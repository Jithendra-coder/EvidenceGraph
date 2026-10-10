from __future__ import annotations

import hashlib
import logging
import re
import uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import pymupdf
from fastapi import HTTPException

from ..connectors.sec import (
    ARCHIVE_BASE,
    MAX_SEC_DOCUMENT,
    SEC_BASE,
    cached_json,
    filing_value,
    sec_get,
)
from ..storage import connect, now_iso, update_job

logger = logging.getLogger("evidencegraph")
MAX_UPLOAD = 15 * 1024 * 1024


class TextExtractor(HTMLParser):
    BLOCKS = {"p", "div", "br", "li", "section", "article", "header", "footer"}
    HEADINGS = {"h1", "h2", "h3", "h4"}
    CELLS = {"td", "th"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0
        self.heading_capture: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1
        if tag in self.HEADINGS:
            self.heading_capture = []
        elif tag == "tr" and not self.hidden:
            self.parts.append("\n")
        elif tag in self.BLOCKS and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1
        if tag in self.HEADINGS and self.heading_capture is not None:
            heading = " ".join("".join(self.heading_capture).split())
            if heading:
                self.parts.append(f"\n## {heading[:180]}\n")
            self.heading_capture = None
        elif tag == "tr" and not self.hidden:
            self.parts.append("\n")
        elif tag in self.CELLS and not self.hidden:
            self.parts.append(" | ")
        elif tag in self.BLOCKS and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.hidden:
            return
        if self.heading_capture is not None:
            self.heading_capture.append(data)
        else:
            clean = " ".join(data.split())
            if clean:
                self.parts.append(clean + " ")

    def text(self) -> str:
        text = re.sub(r"[ \t]*\|[ \t]*", " | ", "".join(self.parts))
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n +", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def html_text(content: bytes) -> str:
    parser = TextExtractor()
    parser.feed(content.decode("utf-8", errors="replace"))
    parser.close()
    return parser.text()


def _pack_paragraphs(
    paragraphs: list[str], page: int | None, heading: str | None
) -> list[tuple[str, int | None, str | None]]:
    out: list[str] = []
    current = ""
    for paragraph in paragraphs:
        while len(paragraph) > 1400:
            if current:
                out.append(current)
                current = ""
            out.append(paragraph[:1400])
            paragraph = paragraph[1400:]
        if current and len(current) + len(paragraph) > 1400:
            out.append(current)
            current = ""
        current = f"{current}\n{paragraph}".strip()
    if current:
        out.append(current)
    return [(part, page, heading) for part in out]


def split_passages(
    text: str, page_texts: list[tuple[int | None, str]] | None = None
) -> list[tuple[str, int | None, str | None]]:
    chunks: list[tuple[str, int | None, str | None]] = []
    for page, block in page_texts or [(None, text)]:
        heading = None
        current: list[str] = []
        for raw in re.split(r"\n+", block):
            line = " ".join(raw.split())
            if not line:
                continue
            if line.startswith("## "):
                if current:
                    chunks.extend(_pack_paragraphs(current, page, heading))
                    current = []
                heading = line[3:183]
            else:
                current.append(line)
        if current:
            chunks.extend(_pack_paragraphs(current, page, heading))
    return chunks


def store_document(
    *,
    source_key: str,
    checksum: str,
    title: str,
    source_type: str,
    text: str,
    source_url: str | None,
    company_cik: str | None = None,
    company_name: str | None = None,
    form: str | None = None,
    filing_date: str | None = None,
    report_date: str | None = None,
    fiscal_year: int | None = None,
    accession: str | None = None,
    filename: str | None = None,
    page_texts: list[tuple[int | None, str]] | None = None,
) -> tuple[str, bool]:
    with connect() as db:
        existing = db.execute(
            "SELECT id FROM documents WHERE source_key=?", (source_key,)
        ).fetchone()
        if existing:
            return existing["id"], False
        doc_id = str(uuid.uuid4())
        passages = split_passages(text, page_texts)
        if not passages:
            raise HTTPException(
                422, "No readable text could be extracted from this document."
            )
        inserted = db.execute(
            """INSERT OR IGNORE INTO documents(id,source_key,checksum,title,source_type,source_url,
                   company_cik,company_name,form,filing_date,report_date,fiscal_year,accession,filename,page_count,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                doc_id,
                source_key,
                checksum,
                title[:240],
                source_type,
                source_url,
                company_cik,
                company_name,
                form,
                filing_date,
                report_date,
                fiscal_year,
                accession,
                filename,
                len(page_texts or []),
                now_iso(),
            ),
        )
        if inserted.rowcount != 1:
            existing = db.execute(
                "SELECT id FROM documents WHERE source_key=?", (source_key,)
            ).fetchone()
            if existing:
                return existing["id"], False
            raise HTTPException(
                409, "This document could not be indexed due to a concurrent update."
            )
        for ordinal, (body, page, heading) in enumerate(passages):
            passage_id = hashlib.sha256(
                f"{checksum}:{ordinal}:{body}".encode()
            ).hexdigest()
            db.execute(
                "INSERT INTO passages(id,doc_id,ordinal,heading,page,text) VALUES(?,?,?,?,?,?)",
                (passage_id, doc_id, ordinal, heading, page, body),
            )
            db.execute(
                "INSERT INTO passages_fts(passage_id,doc_id,company_cik,heading,text) VALUES(?,?,?,?,?)",
                (passage_id, doc_id, company_cik or "", heading or "", body),
            )
    return doc_id, True


def ingest_filing(job_id: str, cik: str, form: str, accession: str) -> None:
    try:
        if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
            raise ValueError("SEC accession number is invalid.")
        update_job(
            job_id, "running", "Finding the requested filing in SEC submissions."
        )
        submissions = cached_json(
            f"submissions:{cik}", f"{SEC_BASE}/submissions/CIK{cik}.json", 3600
        )
        recent = submissions.get("filings", {}).get("recent", {})
        count = len(recent.get("form", []))
        matches = []
        for idx in range(count):
            if (
                filing_value(recent, "form", idx) != form
                or filing_value(recent, "accessionNumber", idx) != accession
            ):
                continue
            matches.append(
                {
                    key: filing_value(recent, key, idx)
                    for key in (
                        "form",
                        "reportDate",
                        "filingDate",
                        "accessionNumber",
                        "primaryDocument",
                    )
                }
            )
        if not matches:
            raise ValueError(
                f"No {form} filing with accession {accession} was found in recent SEC submissions."
            )
        filing = matches[0]
        accession, primary = (
            filing.get("accessionNumber") or "",
            filing.get("primaryDocument") or "",
        )
        if (
            not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,180}", primary)
            or ".." in primary
        ):
            raise ValueError(
                "SEC returned an invalid filing path; the document was not downloaded."
            )
        archive_url = (
            f"{ARCHIVE_BASE}/{int(cik)}/{accession.replace('-', '')}/{quote(primary)}"
        )
        with connect() as db:
            prior = db.execute(
                "SELECT id FROM documents WHERE source_key=?", (f"sec:{accession}",)
            ).fetchone()
        if prior:
            update_job(job_id, "complete", f"Filing is already indexed ({accession}).")
            return
        update_job(job_id, "running", "Downloading and extracting the SEC filing.")
        response = sec_get(archive_url, stream=True)
        chunks, total = [], 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_SEC_DOCUMENT:
                response.close()
                raise ValueError("SEC filing exceeds the 25 MB ingestion limit.")
            chunks.append(chunk)
        body = b"".join(chunks)
        text = html_text(body)
        if len(text.strip()) < 200:
            raise ValueError(
                "SEC filing had too little extractable text; it was not indexed."
            )
        company = submissions.get("name", "Unknown company")
        report_date = filing.get("reportDate")
        store_document(
            source_key=f"sec:{accession}",
            checksum=hashlib.sha256(body).hexdigest(),
            title=f"{company} · {form} · period ended {report_date or 'unknown'}",
            source_type="sec_filing",
            source_url=archive_url,
            text=text,
            company_cik=cik,
            company_name=company,
            form=form,
            filing_date=filing.get("filingDate"),
            report_date=report_date,
            fiscal_year=None,
            accession=accession,
            filename=primary,
        )
        with connect() as db:
            passages = db.execute(
                "SELECT count(*) FROM passages WHERE doc_id=(SELECT id FROM documents WHERE source_key=?)",
                (f"sec:{accession}",),
            ).fetchone()[0]
        update_job(job_id, "complete", f"{passages} passages indexed.")
    except HTTPException as exc:
        update_job(job_id, "failed", str(exc.detail))
    except Exception:
        logger.exception("Filing ingestion failed for job %s", job_id)
        update_job(
            job_id,
            "failed",
            "The filing could not be processed. Review the service log and retry.",
        )


def extract_upload(
    filename: str, content: bytes
) -> tuple[str, list[tuple[int | None, str]]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(
                415, "The file extension and contents do not match a PDF."
            )
        try:
            with pymupdf.open(stream=content, filetype="pdf") as doc:
                if doc.needs_pass:
                    raise HTTPException(422, "Encrypted PDFs are not supported.")
                if doc.page_count > 1000:
                    raise HTTPException(413, "The PDF exceeds the 1,000 page limit.")
                pages, extracted_size = [], 0
                for index, page in enumerate(doc):
                    text = page.get_text("text")
                    extracted_size += len(text)
                    if extracted_size > 20 * 1024 * 1024:
                        raise HTTPException(
                            413, "Extracted PDF text exceeds the 20 MB limit."
                        )
                    pages.append((index + 1, text))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                422, "The PDF is corrupt, encrypted, or cannot be parsed."
            ) from exc
        return "\n".join(text for _, text in pages), pages
    if suffix in {".html", ".htm"}:
        text = html_text(content)
        return text, [(None, text)]
    if suffix == ".txt":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(415, "Text files must use UTF-8 encoding.") from exc
        return text, [(None, text)]
    raise HTTPException(415, "Upload a PDF, HTML, or UTF-8 text file.")
