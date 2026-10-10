from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import (
    AUTH_MODE,
    ENVIRONMENT,
    PUBLIC_BASE_URL,
    SESSION_MAX_AGE,
    SESSION_SECRET,
    allowed_hosts,
    callback as oidc_callback,
    identity_from_request,
    login as oidc_login,
    logout as oidc_logout,
    production_config_errors,
    signed_out,
)
from .connectors.sec import SEC_BASE, cached_json, filing_value, normalized_cik
from .financial.facts import FACT_CONCEPTS, annual_growth, citation_for_fact, get_fact
from . import generation
from .ingestion.documents import (
    MAX_UPLOAD,
    extract_upload,
    ingest_filing,
    store_document,
)
from .retrieval.engine import retrieve, run_baseline_evaluation
from .schemas import CompareRequest, ResearchRequest, SecContact, SyncRequest
from .storage import FRONTEND, connect, get_contact, init_db, now_iso

logger = logging.getLogger("evidencegraph")
logger.setLevel(
    getattr(logging, os.getenv("EVIDENCEGRAPH_LOG_LEVEL", "INFO").upper(), logging.INFO)
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    config_errors = production_config_errors() + generation.configuration_errors()
    if config_errors:
        raise RuntimeError(
            "Invalid production configuration: " + " ".join(config_errors)
        )
    init_db()
    yield


app = FastAPI(
    title="EvidenceGraph",
    version="1.0.0",
    description="Single-organization, source-grounded financial research.",
    lifespan=lifespan,
    docs_url=None if ENVIRONMENT == "production" else "/docs",
    redoc_url=None if ENVIRONMENT == "production" else "/redoc",
    openapi_url=None if ENVIRONMENT == "production" else "/openapi.json",
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    started = time.perf_counter()
    incoming_id = request.headers.get("X-Request-ID", "")
    request.state.request_id = (
        incoming_id
        if re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", incoming_id)
        else str(uuid.uuid4())
    )
    origin = request.headers.get("origin")
    expected_origin = (
        f"{request.url.scheme}://{request.url.netloc}"
        if ENVIRONMENT != "production"
        else PUBLIC_BASE_URL
    )
    public_paths = {
        "/",
        "/auth/login",
        "/auth/callback",
        "/auth/signed-out",
        "/api/v1/health/live",
        "/api/v1/health/ready",
    }
    if (
        AUTH_MODE == "oidc"
        and request.url.path not in public_paths
        and not request.url.path.startswith("/assets/")
        and not identity_from_request(request)
    ):
        if request.url.path.startswith("/api/"):
            response = JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "authentication_required",
                        "message": "Sign in to access this workspace.",
                        "requestId": request.state.request_id,
                    }
                },
            )
        else:
            response = RedirectResponse("/auth/login", status_code=303)
        return add_response_headers(response, request.state.request_id)
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and origin
        and origin.rstrip("/") != expected_origin
    ):
        return add_response_headers(
            JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "cross_origin_request",
                        "message": "Cross-origin changes are not allowed.",
                        "requestId": request.state.request_id,
                    }
                },
            ),
            request.state.request_id,
        )
    if request.url.path.endswith("/documents/upload"):
        try:
            if (
                int(request.headers.get("content-length", "0"))
                > MAX_UPLOAD + 1024 * 1024
            ):
                return add_response_headers(
                    JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "upload_too_large",
                                "message": "The upload exceeds the 15 MB size limit.",
                                "requestId": request.state.request_id,
                            }
                        },
                    ),
                    request.state.request_id,
                )
        except ValueError:
            pass
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "Unhandled request error request_id=%s", request.state.request_id
        )
        response = JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "The request could not be completed.",
                    "requestId": request.state.request_id,
                }
            },
        )
    add_response_headers(response, request.state.request_id)
    logger.info(
        "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
        request.state.request_id,
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    return response


def add_response_headers(response, request_id: str):
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    )
    if response.headers.get("content-type", "").startswith("application/json"):
        response.headers["Cache-Control"] = "no-store"
    if ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


# SessionMiddleware wraps the request-ID middleware so OIDC state stays in a signed,
# HttpOnly cookie. The cookie contains identity claims only, never provider tokens.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=SESSION_MAX_AGE,
    same_site="lax",
    https_only=ENVIRONMENT == "production",
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"http_{exc.status_code}",
                "message": exc.detail,
                "requestId": getattr(request.state, "request_id", None),
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request fields are invalid.",
                "requestId": getattr(request.state, "request_id", None),
            }
        },
    )


app.mount("/assets", StaticFiles(directory=FRONTEND), name="assets")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND / "landing.html")


@app.get("/app", include_in_schema=False)
def workspace() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@app.get("/auth/login", include_in_schema=False)
async def auth_login(request: Request):
    if AUTH_MODE == "local":
        return RedirectResponse("/app", status_code=303)
    return await oidc_login(request)


@app.get("/auth/callback", include_in_schema=False)
async def auth_callback(request: Request):
    return await oidc_callback(request)


@app.post("/auth/logout", include_in_schema=False)
def auth_logout(request: Request):
    return oidc_logout(request)


@app.get("/auth/signed-out", include_in_schema=False)
def auth_signed_out():
    return signed_out()


@app.get("/api/v1/auth/session")
def auth_session(request: Request) -> dict[str, Any]:
    return {
        "authenticated": True,
        "mode": AUTH_MODE,
        "user": identity_from_request(request),
    }


@app.get("/api/v1/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/health/ready")
def readiness() -> dict[str, str]:
    try:
        with connect() as db:
            db.execute("SELECT 1").fetchone()
    except Exception as exc:
        logger.exception("Readiness check failed")
        raise HTTPException(503, "The data store is unavailable.") from exc
    return {"status": "ready"}


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    with connect() as db:
        docs = db.execute("SELECT count(*) FROM documents").fetchone()[0]
        passages = db.execute("SELECT count(*) FROM passages").fetchone()[0]
    return {
        "status": "ok",
        "mode": AUTH_MODE,
        "secConfigured": bool(get_contact()),
        "indexedDocuments": docs,
        "indexedPassages": passages,
        "timestamp": now_iso(),
    }


@app.get("/api/v1/settings")
def settings() -> dict[str, Any]:
    contact = get_contact()
    masked = (
        (contact[:2] + "•••" + contact[contact.find("@") :])
        if contact and "@" in contact
        else None
    )
    return {
        "secConfigured": bool(contact),
        "contact": masked,
        "generationEnabled": generation.enabled(),
        "generationModel": generation.model_name() if generation.enabled() else None,
        "generationMaxTokens": generation.max_tokens()
        if generation.enabled()
        else None,
    }


@app.put("/api/v1/settings/sec-contact")
def save_sec_contact(payload: SecContact) -> dict[str, Any]:
    email = payload.email.strip()
    if any(not 33 <= ord(char) <= 126 for char in email) or not re.fullmatch(
        r"[^\s@<>]+@[^\s@<>]+\.[A-Za-z]{2,}", email
    ):
        raise HTTPException(422, "Enter a valid contact email for the SEC User-Agent.")
    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES('sec_contact',?)",
            (email,),
        )
    return {"secConfigured": True, "message": "SEC contact saved on this device."}


@app.get("/api/v1/companies/search")
def search_companies(q: str = "") -> dict[str, Any]:
    query = q.strip().casefold()
    if len(query) > 100:
        raise HTTPException(422, "Company search is limited to 100 characters.")
    if len(query) < 1:
        return {"items": []}
    data = cached_json(
        "company_tickers", "https://www.sec.gov/files/company_tickers.json", 24 * 3600
    )
    matches = []
    for row in data.values():
        name, symbol = str(row.get("title", "")), str(row.get("ticker", ""))
        cik = str(row.get("cik_str", "")).zfill(10)
        if (
            query in name.casefold()
            or query in symbol.casefold()
            or query == cik.lstrip("0")
        ):
            matches.append({"cik": cik, "name": name, "ticker": symbol})
            if len(matches) == 12:
                break
    return {"items": matches}


@app.get("/api/v1/companies/{cik}/facts")
def company_facts(cik: str, metric: str = "revenue") -> dict[str, Any]:
    return get_fact(normalized_cik(cik), metric)


@app.get("/api/v1/companies/{cik}")
def company_detail(cik: str) -> dict[str, Any]:
    cik = normalized_cik(cik)
    data = cached_json(
        f"submissions:{cik}", f"{SEC_BASE}/submissions/CIK{cik}.json", 3600
    )
    recent = data.get("filings", {}).get("recent", {})
    count = len(recent.get("form", []))
    filings = []
    for index in range(count):
        form = filing_value(recent, "form", index)
        if form not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
            continue
        filings.append(
            {
                "form": form,
                "reportDate": filing_value(recent, "reportDate", index),
                "filingDate": filing_value(recent, "filingDate", index),
                "accession": filing_value(recent, "accessionNumber", index),
            }
        )
        if len(filings) == 12:
            break
    return {
        "cik": cik,
        "name": data.get("name"),
        "sic": data.get("sic"),
        "sicDescription": data.get("sicDescription"),
        "fiscalYearEnd": data.get("fiscalYearEnd"),
        "filings": filings,
    }


@app.post("/api/v1/documents/sync", status_code=202)
def sync_document(payload: SyncRequest, background: BackgroundTasks) -> dict[str, str]:
    cik = normalized_cik(payload.cik)
    if payload.form not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
        raise HTTPException(422, "Only 10-K and 10-Q filings are supported.")
    job_id, timestamp = str(uuid.uuid4()), now_iso()
    with connect() as db:
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?)",
            (
                job_id,
                "sec_filing",
                "queued",
                "Queued for SEC retrieval.",
                timestamp,
                timestamp,
            ),
        )
    background.add_task(ingest_filing, job_id, cik, payload.form, payload.accession)
    return {"jobId": job_id, "status": "queued"}


@app.get("/api/v1/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found.")
    return dict(row)


@app.post("/api/v1/documents/upload", status_code=201)
async def upload_document(file: UploadFile = File(...)) -> dict[str, Any]:
    name = Path(file.filename or "document").name[:180]
    content = await file.read(MAX_UPLOAD + 1)
    if not content:
        raise HTTPException(422, "The uploaded file is empty.")
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "The upload exceeds the 15 MB size limit.")
    text, pages = extract_upload(name, content)
    if len(text.strip()) < 80:
        raise HTTPException(
            422, "No readable text was extracted. Scanned PDFs need OCR before upload."
        )
    checksum = hashlib.sha256(content).hexdigest()
    doc_id, created = store_document(
        source_key=f"upload:{checksum}",
        checksum=checksum,
        title=name,
        source_type="upload",
        filename=name,
        text=text,
        page_texts=pages,
        source_url=None,
    )
    with connect() as db:
        count = db.execute(
            "SELECT count(*) FROM passages WHERE doc_id=?", (doc_id,)
        ).fetchone()[0]
    return {"id": doc_id, "created": created, "passageCount": count}


@app.get("/api/v1/documents")
def list_documents(q: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
    if not 1 <= limit <= 200 or offset < 0:
        raise HTTPException(422, "Use a limit from 1 to 200 and a non-negative offset.")
    with connect() as db:
        rows = db.execute(
            """SELECT d.*,count(p.id) AS passage_count FROM documents d
            LEFT JOIN passages p ON p.doc_id=d.id WHERE d.title LIKE ? OR d.company_name LIKE ?
            GROUP BY d.id ORDER BY d.created_at DESC LIMIT ? OFFSET ?""",
            (f"%{q[:100]}%", f"%{q[:100]}%", limit, offset),
        ).fetchall()
        total = db.execute(
            "SELECT count(*) FROM documents WHERE title LIKE ? OR company_name LIKE ?",
            (f"%{q[:100]}%", f"%{q[:100]}%"),
        ).fetchone()[0]
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/v1/documents/{doc_id}/status")
def document_status(doc_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute(
            "SELECT d.id,d.source_type,d.created_at,count(p.id) AS passages FROM documents d LEFT JOIN passages p ON p.doc_id=d.id WHERE d.id=? GROUP BY d.id",
            (doc_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Document not found.")
    return {
        "id": row["id"],
        "status": "indexed",
        "passageCount": row["passages"],
        "createdAt": row["created_at"],
    }


@app.get("/api/v1/documents/{doc_id}")
def document_detail(doc_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        passages = db.execute(
            "SELECT id,ordinal,heading,page,text FROM passages WHERE doc_id=? ORDER BY ordinal LIMIT 200",
            (doc_id,),
        ).fetchall()
    return {"document": dict(row), "passages": [dict(item) for item in passages]}


@app.get("/api/v1/documents/{doc_id}/evidence/{passage_id}")
def document_evidence(doc_id: str, passage_id: str) -> dict[str, Any]:
    with connect() as db:
        document = db.execute(
            "SELECT * FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        passage = db.execute(
            "SELECT ordinal FROM passages WHERE id=? AND doc_id=?", (passage_id, doc_id)
        ).fetchone()
        if not document or not passage:
            raise HTTPException(
                404, "The cited passage does not exist in this source document."
            )
        ordinal = passage["ordinal"]
        excerpts = db.execute(
            "SELECT id,ordinal,heading,page,text FROM passages WHERE doc_id=? AND ordinal BETWEEN ? AND ? ORDER BY ordinal",
            (doc_id, max(0, ordinal - 2), ordinal + 2),
        ).fetchall()
    return {
        "document": dict(document),
        "passages": [dict(item) for item in excerpts],
        "focusPassageId": passage_id,
    }


@app.get("/api/v1/research/recent")
def recent_research() -> dict[str, Any]:
    with connect() as db:
        rows = db.execute(
            "SELECT id,question,created_at FROM research ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/v1/evaluations/run", status_code=201)
def evaluation_run() -> dict[str, Any]:
    return run_baseline_evaluation()


@app.get("/api/v1/evaluations")
def evaluation_history() -> dict[str, Any]:
    with connect() as db:
        rows = db.execute(
            "SELECT id,result,created_at FROM evaluation_runs ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "createdAt": row["created_at"],
                **json.loads(row["result"]),
            }
            for row in rows
        ]
    }


@app.post("/api/v1/research/query", status_code=201)
def research_query(payload: ResearchRequest) -> dict[str, Any]:
    question = payload.question.strip()
    ciks = list(dict.fromkeys(normalized_cik(item) for item in payload.companies))
    passages = retrieve(question, ciks)
    lower = question.casefold()
    if "operating cash flow" in lower or "cash flow" in lower:
        metric_key = "operating_cash_flow"
    elif "revenue" in lower or "sales" in lower:
        metric_key = "revenue"
    elif ("net income" in lower or "profit" in lower) and "margin" not in lower:
        metric_key = "net_income"
    else:
        metric_key = None
    citations: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    missing: list[str] = []
    if payload.includeFinancials and metric_key:
        for cik in ciks:
            try:
                series = get_fact(cik, metric_key)
            except HTTPException as exc:
                missing.append(f"{cik}: {exc.detail}")
                continue
            periods = series["periods"][-3:]
            if not periods:
                missing.append(
                    f"{series['companyName']}: no comparable annual {metric_key.replace('_', ' ')} facts were found."
                )
                continue
            for index, point in enumerate(periods):
                citation = citation_for_fact(cik, point, series["companyName"])
                citations.append(citation)
                previous = periods[index - 1] if index else None
                growth = None
                if previous:
                    growth = annual_growth(point, previous)
                metrics.append(
                    {
                        "company": series["companyName"],
                        "cik": cik,
                        "metric": metric_key,
                        "fiscalYear": point["fiscalYear"],
                        "value": point["value"],
                        "unit": point["unit"],
                        "growthPercent": growth,
                        "growthUnavailableReason": (
                            "No earlier annual period is available."
                            if not previous
                            else "The prior value must be positive, with matching units and annual durations."
                            if growth is None
                            else None
                        ),
                        "sourceId": citation["id"],
                        "concept": point["concept"],
                        "periodStart": point["start"],
                        "periodEnd": point["end"],
                        "durationDays": point["durationDays"],
                    }
                )
    elif (
        payload.includeFinancials
        and "margin" in lower
        and ("profit" in lower or "net income" in lower)
    ):
        missing.append(
            "Profit margin is not available in this release; no percentage was inferred from a single financial fact."
        )
    for passage in passages:
        citations.append(
            {
                "id": passage["passage_id"],
                "title": passage["title"],
                "sourceUrl": passage["source_url"],
                "sourceType": passage["source_type"],
                "locator": " · ".join(
                    filter(
                        None,
                        [
                            passage["heading"],
                            (
                                f"{passage['form']} · period ended {passage['report_date']}"
                                if passage["form"] and passage["report_date"]
                                else passage["form"]
                            ),
                            passage["filing_date"],
                        ],
                    )
                ),
                "docId": passage["doc_id"],
                "excerpt": passage["text"],
                "company": passage["company_name"],
                "cik": passage["company_cik"],
                "form": passage["form"],
                "filingDate": passage["filing_date"],
                "reportDate": passage["report_date"],
                "fiscalYear": passage["fiscal_year"],
            }
        )
    citations = list({item["id"]: item for item in citations}.values())
    if not citations:
        summary = "I don’t have indexed evidence for this question yet. Add a company and sync a filing, or upload a source document, then try again."
    else:
        parts = []
        if metrics:
            parts.append(
                f"Found {len(metrics)} annual {metric_key.replace('_', ' ')} figures from SEC XBRL."
            )
        if passages:
            parts.append(
                f"Retrieved {len(passages)} relevant passages from indexed source documents."
            )
        if missing:
            parts.append(
                "Some requested company data was unavailable; see the caveats below."
            )
        summary = (
            " ".join(parts)
            or f"Retrieved {len(passages)} source passage(s). Review the cited evidence before drawing a conclusion."
        )
    answer, generation_status = generation.generate_answer(question, citations, metrics)
    dates = [p["filing_date"] for p in passages if p.get("filing_date")]
    result = {
        "question": question,
        "summary": summary,
        "answer": answer,
        "generation": {
            "status": generation_status,
            "model": generation.model_name() if generation.enabled() else None,
            "maxTokens": generation.max_tokens() if generation.enabled() else None,
        },
        "findings": [
            {
                "text": p["text"],
                "citationId": p["passage_id"],
                "company": p["company_name"],
                "section": p["heading"],
            }
            for p in passages
        ],
        "metrics": metrics,
        "citations": citations,
        "missingInformation": missing,
        "caveats": (
            [
                (
                    "The AI draft passed citation-ID and numeric checks, but those checks do not establish semantic accuracy. Verify every claim against its original source."
                    if generation_status == "complete"
                    else "No AI draft was available; the displayed summary and evidence were assembled deterministically."
                ),
                "Annual XBRL facts are matched by unit and fiscal duration; direct cross-company comparisons may use different fiscal calendars.",
            ]
            if citations
            else []
        ),
        "freshness": {
            "latestFilingDate": max(dates) if dates else None,
            "retrievedAt": now_iso(),
        },
        "retrieval": {"method": "SQLite FTS5 lexical search", "candidateLimit": 8},
    }
    research_id = str(uuid.uuid4())
    with connect() as db:
        db.execute(
            "INSERT INTO research VALUES(?,?,?,?)",
            (research_id, question, json.dumps(result), now_iso()),
        )
    result["id"] = research_id
    return result


@app.get("/api/v1/research/{research_id}/evidence")
def research_evidence(research_id: str) -> dict[str, Any]:
    result = research_get(research_id)
    return {
        "id": research_id,
        "citations": result["citations"],
        "findings": result["findings"],
    }


@app.get("/api/v1/research/{research_id}")
def research_get(research_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute(
            "SELECT answer FROM research WHERE id=?", (research_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Research session not found.")
    result = json.loads(row["answer"])
    result["id"] = research_id
    return result


@app.post("/api/v1/research/compare")
def compare(payload: CompareRequest) -> dict[str, Any]:
    if payload.metric not in FACT_CONCEPTS:
        raise HTTPException(422, "Choose revenue, net income, or operating cash flow.")
    results = []
    for raw_cik in dict.fromkeys(payload.companies):
        cik = normalized_cik(raw_cik)
        series = get_fact(cik, payload.metric)
        periods = series["periods"][-payload.periods :]
        output = []
        for idx, point in enumerate(periods):
            prior = periods[idx - 1] if idx else None
            growth = None
            if prior:
                growth = annual_growth(point, prior)
            output.append(
                {
                    **point,
                    "growthPercent": growth,
                    "citation": citation_for_fact(cik, point, series["companyName"]),
                }
            )
        results.append(
            {
                "cik": cik,
                "company": series["companyName"],
                "concept": series["concept"],
                "periods": output,
            }
        )
    warnings = []
    latest = [company["periods"][-1] for company in results if company["periods"]]
    if len(latest) > 1:
        ends = [datetime.strptime(item["end"], "%Y-%m-%d").date() for item in latest]
        if (max(ends) - min(ends)).days > 45:
            warnings.append(
                "Latest fiscal year ends are more than 45 days apart; treat direct period comparisons with care."
            )
    return {
        "metric": payload.metric,
        "companies": results,
        "warnings": warnings,
        "formula": "(current period value − previous period value) ÷ previous period value × 100",
        "generatedAt": now_iso(),
    }


@app.get("/api/v1/reports/{research_id}")
@app.get("/api/v1/research/{research_id}/report")
def report(research_id: str) -> JSONResponse:
    with connect() as db:
        row = db.execute(
            "SELECT answer FROM research WHERE id=?", (research_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Research session not found.")
    data = json.loads(row["answer"])
    retrieval = data.get("retrieval") or {}
    lines = [
        "# EvidenceGraph research report",
        "",
        f"**Question:** {data['question']}",
        "",
        f"**Generated:** {data['freshness']['retrievedAt']}",
        "",
        "## Reproducibility",
        "",
        f"- Retrieval: {retrieval.get('method', 'unknown')} (candidate limit {retrieval.get('candidateLimit', 'unknown')})",
        f"- Answer generation: {data.get('generation', {}).get('status', 'not recorded')}",
    ]
    if data.get("generation", {}).get("model"):
        lines.append(
            f"- Model: {data['generation']['model']} (maximum {data['generation']['maxTokens']} output tokens)"
        )
    lines += [
        "",
        "## Summary",
        "",
        data["summary"],
        "",
    ]
    if data.get("answer"):
        lines += [
            "## AI-assisted draft",
            "",
            data["answer"]["summary"],
            "",
        ]
        for finding in data["answer"]["findings"]:
            ids = ", ".join(finding["citationIds"])
            lines.append(f"- {finding['text']} [Sources: {ids}]")
        if data["answer"]["findings"]:
            lines.append("")
        lines.append(
            "Verify each draft statement against the cited original source before relying on it."
        )
        lines.append("")
    if data["metrics"]:
        lines += [
            "## Financial facts",
            "",
            "| Company | Fiscal year | Value (USD) | Growth | Source |",
            "|---|---:|---:|---:|---|",
        ]
        for metric in data["metrics"]:
            growth = (
                f"{Decimal(metric['growthPercent']):.2f}%"
                if metric["growthPercent"] is not None
                else "—"
            )
            citation = next(
                (
                    item
                    for item in data["citations"]
                    if item["id"] == metric["sourceId"]
                ),
                {},
            )
            lines.append(
                f"| {metric['company']} | FY{metric['fiscalYear']} | {Decimal(metric['value']):,.0f} | {growth} | [{metric['concept']}]({citation.get('sourceUrl', '')}) [{metric['sourceId']}] |"
            )
        lines.append("")
    if data["findings"]:
        lines += ["## Evidence", ""]
        lines.extend(
            f"- **{finding.get('company') or 'Source'}**{(' · ' + finding['section']) if finding.get('section') else ''}: {finding['text']} [{finding.get('citationId', '')}]"
            for finding in data["findings"]
        )
        lines.append("")
    if data["caveats"] or data["missingInformation"]:
        lines += ["## Caveats and missing information", ""]
        lines.extend(
            f"- {item}" for item in data["caveats"] + data["missingInformation"]
        )
    return JSONResponse(
        {"filename": f"evidencegraph-{research_id[:8]}.md", "content": "\n".join(lines)}
    )
