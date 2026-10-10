from pathlib import Path
from tempfile import TemporaryDirectory
from decimal import Decimal
import os
import pytest
from unittest.mock import Mock, patch

import pymupdf
from fastapi.testclient import TestClient
from fastapi import HTTPException

from backend.app import storage
from backend.app import auth
from backend.app.connectors.sec import normalized_cik
from backend.app.financial import facts as financial
from backend.app.ingestion import documents
from backend.app import main
from backend.app.retrieval import engine


def test_html_extraction_skips_active_content_and_keeps_headings():
    text = documents.html_text(
        b"<h2>Risk factors</h2><p>Supplier interruptions may delay delivery.</p><script>secret instruction</script>"
    )
    passages = documents.split_passages(text)
    assert passages == [
        ("Supplier interruptions may delay delivery.", None, "Risk factors")
    ]
    assert "secret instruction" not in text


def test_html_table_keeps_rows_and_cell_boundaries():
    text = documents.html_text(
        b"<table><caption>Amounts in USD</caption><tr><th>Year</th><th>Revenue</th></tr><tr><td>2024</td><td>123</td></tr></table>"
    )
    assert "Year | Revenue" in text
    assert "2024 | 123" in text
    assert "Amounts in USD" in text


def test_chunking_preserves_pdf_pages_and_bounds_passage_size():
    passages = documents.split_passages(
        "", [(1, "A" * 3000), (2, "Second page evidence.")]
    )
    assert all(len(body) <= 1400 for body, _, _ in passages)
    assert {page for _, page, _ in passages} == {1, 2}
    assert passages[-1][0] == "Second page evidence."


def test_growth_uses_decimal_and_rejects_incomparable_bases():
    previous = {"value": "90", "unit": "USD", "durationDays": 364, "fiscalYear": 2023}
    current = {"value": "100", "unit": "USD", "durationDays": 371, "fiscalYear": 2024}
    assert financial.annual_growth(current, previous) == str(
        Decimal(10) / Decimal(90) * 100
    )
    assert financial.annual_growth({**current, "value": "0"}, previous) == "-100"
    assert financial.annual_growth(current, {**previous, "value": "0"}) is None
    assert financial.annual_growth(current, {**previous, "unit": "EUR"}) is None
    assert financial.annual_growth(current, {**previous, "durationDays": 350}) is None
    assert financial.annual_growth({**current, "fiscalYear": 2025}, previous) is None


def test_facts_preserve_original_fiscal_year_and_latest_filing():
    points = [
        {
            "form": "10-K",
            "fp": "FY",
            "fy": 2022,
            "start": "2022-01-01",
            "end": "2022-12-31",
            "val": 80,
            "filed": "2023-02-01",
            "accn": "old",
        },
        {
            "form": "10-K",
            "fp": "FY",
            "fy": 2023,
            "start": "2023-01-01",
            "end": "2023-12-31",
            "val": 100,
            "filed": "2024-02-01",
            "accn": "original",
        },
        {
            "form": "10-K/A",
            "fp": "FY",
            "fy": 2023,
            "start": "2023-01-01",
            "end": "2023-12-31",
            "val": 105,
            "filed": "2025-02-01",
            "accn": "amended",
        },
        {
            "form": "10-K",
            "fp": "FY",
            "fy": 2024,
            "start": "2024-02-04",
            "end": "2025-02-01",
            "val": 120,
            "filed": "2025-03-12",
            "accn": "current",
        },
        {
            "form": "10-K",
            "fp": "FY",
            "fy": 2025,
            "start": "2024-02-04",
            "end": "2025-02-01",
            "val": 121,
            "filed": "2026-03-11",
            "accn": "comparative",
        },
        {
            "form": "10-Q",
            "fp": "Q3",
            "fy": 2024,
            "start": "2024-01-01",
            "end": "2024-09-30",
            "val": 90,
            "filed": "2024-11-01",
            "accn": "quarter",
        },
        {
            "form": "10-K",
            "fp": "FY",
            "start": "2020-01-01",
            "end": "2020-12-31",
            "val": 60,
            "filed": "2021-02-01",
            "accn": "missing-fiscal-year",
        },
    ]
    data = {
        "entityName": "Sample Co",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": points}
                }
            }
        },
    }
    with patch.object(financial, "cached_json", return_value=data):
        series = financial.load_fact_series(
            "0000000001", financial.FACT_CONCEPTS["revenue"]
        )
    assert [point["fiscalYear"] for point in series["periods"]] == [2022, 2023, 2024]
    assert series["periods"][1]["value"] == "105"
    assert series["periods"][1]["accession"] == "amended"
    assert series["periods"][2]["end"] == "2025-02-01"
    assert series["periods"][2]["fiscalYear"] == 2024
    assert series["periods"][2]["value"] == "121"


def test_cik_normalization_rejects_non_identifier_characters():
    assert normalized_cik("CIK 123") == "0000000123"
    with pytest.raises(HTTPException) as error:
        normalized_cik("not-a-cik-123")
    assert error.value.status_code == 422


def test_revenue_prefers_total_revenues_when_company_reports_it():
    point = {
        "form": "10-K",
        "fp": "FY",
        "fy": 2026,
        "start": "2025-02-01",
        "end": "2026-01-31",
        "filed": "2026-03-13",
        "accn": "0000104169-26-000055",
    }
    facts = {
        "entityName": "Walmart Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [{**point, "val": 706_413_000_000}]}
                },
                "Revenues": {"units": {"USD": [{**point, "val": 713_163_000_000}]}},
            }
        },
    }
    with patch.object(financial, "cached_json", return_value=facts):
        series = financial.load_fact_series(
            "0000104169", financial.FACT_CONCEPTS["revenue"]
        )
    assert series["periods"][0]["value"] == "713163000000"
    assert series["periods"][0]["concept"] == "us-gaap:Revenues"


def test_revenue_falls_back_per_period_when_total_tag_is_not_reported():
    facts = {
        "entityName": "Sample Co",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2022,
                                "start": "2021-01-01",
                                "end": "2021-12-31",
                                "val": 100,
                                "filed": "2022-02-01",
                                "accn": "older-revenue",
                            }
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-K",
                                "fp": "FY",
                                "fy": 2023,
                                "start": "2022-01-01",
                                "end": "2022-12-31",
                                "val": 120,
                                "filed": "2023-02-01",
                                "accn": "newer-revenue",
                            }
                        ]
                    }
                },
            }
        },
    }
    with patch.object(financial, "cached_json", return_value=facts):
        series = financial.load_fact_series(
            "0000000001", financial.FACT_CONCEPTS["revenue"]
        )
    assert [point["value"] for point in series["periods"]] == ["100", "120"]
    assert [point["concept"] for point in series["periods"]] == [
        "us-gaap:Revenues",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    ]
    assert series["concept"] == series["periods"][-1]["concept"]


def test_company_filings_use_report_dates_and_accessions_without_fy():
    submissions = {
        "name": "Target Corporation",
        "filings": {
            "recent": {
                "form": ["10-K"],
                "reportDate": ["2026-01-31"],
                "filingDate": ["2026-03-11"],
                "accessionNumber": ["0000027419-26-000016"],
                "primaryDocument": ["tgt-20260131.htm"],
            }
        },
    }
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
            patch.object(main, "cached_json", return_value=submissions),
            TestClient(main.app) as client,
        ):
            response = client.get("/api/v1/companies/27419")
    assert response.status_code == 200
    assert response.json()["filings"] == [
        {
            "form": "10-K",
            "reportDate": "2026-01-31",
            "filingDate": "2026-03-11",
            "accession": "0000027419-26-000016",
        }
    ]


def test_company_search_reads_tickers_from_sec_website_file_endpoint():
    payload = {"0": {"cik_str": 27419, "ticker": "TGT", "title": "Target Corp"}}
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
            patch.object(main, "cached_json", return_value=payload) as cached_json,
            TestClient(main.app) as client,
        ):
            response = client.get("/api/v1/companies/search", params={"q": "Target"})
    assert response.status_code == 200
    assert response.json()["items"] == [
        {"cik": "0000027419", "name": "Target Corp", "ticker": "TGT"}
    ]
    assert cached_json.call_args.args[:2] == (
        "company_tickers",
        "https://www.sec.gov/files/company_tickers.json",
    )


def test_init_db_adds_report_date_without_replacing_existing_documents():
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
        ):
            with storage.connect() as db:
                db.execute(
                    """CREATE TABLE documents (
                        id TEXT PRIMARY KEY, source_key TEXT NOT NULL UNIQUE,
                        checksum TEXT NOT NULL, title TEXT NOT NULL,
                        source_type TEXT NOT NULL, source_url TEXT,
                        company_cik TEXT, company_name TEXT, form TEXT,
                        filing_date TEXT, fiscal_year INTEGER, accession TEXT,
                        filename TEXT, page_count INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL
                    )"""
                )
                db.execute(
                    """CREATE TABLE passages (
                        id TEXT PRIMARY KEY, doc_id TEXT NOT NULL,
                        ordinal INTEGER NOT NULL, heading TEXT, page INTEGER,
                        text TEXT NOT NULL, UNIQUE(doc_id, ordinal)
                    )"""
                )
                db.execute(
                    """CREATE VIRTUAL TABLE passages_fts USING fts5(
                        passage_id UNINDEXED, doc_id UNINDEXED,
                        company_cik UNINDEXED, heading UNINDEXED, text,
                        tokenize='unicode61'
                    )"""
                )
                db.execute(
                    "INSERT INTO documents(id,source_key,checksum,title,source_type,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        "doc-1",
                        "upload:one",
                        "hash",
                        "Saved document",
                        "upload",
                        "2026-01-01",
                    ),
                )
                db.execute(
                    "INSERT INTO passages(id,doc_id,ordinal,text) VALUES(?,?,?,?)",
                    ("passage-1", "doc-1", 0, "Stores fulfilling merchandise sales."),
                )
                db.execute(
                    "INSERT INTO passages_fts(passage_id,doc_id,company_cik,heading,text) VALUES(?,?,?,?,?)",
                    (
                        "passage-1",
                        "doc-1",
                        "0000027419",
                        "",
                        "Stores fulfilling merchandise sales.",
                    ),
                )
            storage.init_db()
            with storage.connect() as db:
                columns = {
                    row["name"] for row in db.execute("PRAGMA table_info(documents)")
                }
                saved = db.execute(
                    "SELECT title,report_date FROM documents WHERE id='doc-1'"
                ).fetchone()
                porter_hit = db.execute(
                    "SELECT passage_id FROM passages_fts WHERE passages_fts MATCH 'fulfillment'"
                ).fetchone()
    assert "report_date" in columns
    assert saved["title"] == "Saved document"
    assert saved["report_date"] is None
    assert porter_hit["passage_id"] == "passage-1"


def test_filing_sync_selects_exact_sec_accession_without_fy():
    accession = "0000027419-26-000016"
    submissions = {
        "name": "Target Corporation",
        "filings": {
            "recent": {
                "form": ["10-K", "10-K"],
                "reportDate": ["2026-01-31", "2025-02-01"],
                "filingDate": ["2026-03-11", "2025-03-12"],
                "accessionNumber": [accession, "0000027419-25-000018"],
                "primaryDocument": ["tgt-20260131.htm", "tgt-20250201.htm"],
            }
        },
    }
    response = Mock()
    response.iter_content.return_value = [
        b"<html><h1>Risk factors</h1><p>"
        + b"Inventory shrink can affect costs. " * 12
        + b"</p></html>"
    ]
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
        ):
            storage.init_db()
            timestamp = storage.now_iso()
            with storage.connect() as db:
                db.execute(
                    "INSERT INTO jobs VALUES(?,?,?,?,?,?)",
                    (
                        "accession-sync",
                        "sec_filing",
                        "queued",
                        "Queued.",
                        timestamp,
                        timestamp,
                    ),
                )
            with (
                patch.object(documents, "cached_json", return_value=submissions),
                patch.object(documents, "sec_get", return_value=response) as sec_get,
            ):
                documents.ingest_filing(
                    "accession-sync", "0000027419", "10-K", accession
                )
            with storage.connect() as db:
                document = db.execute(
                    "SELECT title,report_date,fiscal_year,accession FROM documents WHERE source_key=?",
                    (f"sec:{accession}",),
                ).fetchone()
                job = db.execute(
                    "SELECT status FROM jobs WHERE id='accession-sync'"
                ).fetchone()
            assert job["status"] == "complete"
            assert document["title"].endswith("period ended 2026-01-31")
            assert document["report_date"] == "2026-01-31"
            assert document["fiscal_year"] is None
            assert document["accession"] == accession
            assert "tgt-20260131.htm" in sec_get.call_args.args[0]
            with TestClient(main.app) as client:
                research = client.post(
                    "/api/v1/research/query",
                    json={
                        "question": "What inventory shrink risk is described?",
                        "companies": ["27419"],
                        "includeFinancials": False,
                    },
                )
            assert research.status_code == 201
            assert research.json()["findings"]
            assert any(
                citation["reportDate"] == "2026-01-31"
                and "period ended 2026-01-31" in citation["locator"]
                for citation in research.json()["citations"]
            )


def test_sync_api_enqueues_the_selected_accession():
    accession = "0000027419-26-000016"
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
            patch.object(main, "ingest_filing") as ingest,
            TestClient(main.app) as client,
        ):
            response = client.post(
                "/api/v1/documents/sync",
                json={
                    "cik": "27419",
                    "form": "10-K",
                    "accession": accession,
                },
            )
    assert response.status_code == 202
    ingest.assert_called_once_with(
        response.json()["jobId"], "0000027419", "10-K", accession
    )


def test_upload_reingestion_search_and_cross_origin_write():
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
        ):
            with TestClient(main.app) as client:
                body = (
                    "Risk factors\n\nSupplier concentration may delay product delivery and increase costs. "
                    "The filing describes alternate suppliers, inventory buffers, and ongoing monitoring. "
                    "Management reviews delivery risks every quarter."
                ).encode()
                first = client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("filing.txt", body, "text/plain")},
                )
                assert first.status_code == 201, first.text
                assert first.json()["created"] is True
                duplicate = client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("copy.txt", body, "text/plain")},
                )
                assert duplicate.status_code == 201
                assert duplicate.json()["created"] is False
                result = client.post(
                    "/api/v1/research/query",
                    json={
                        "question": "What supplier concentration risks are described?",
                        "includeFinancials": False,
                    },
                )
                assert result.status_code == 201, result.text
                assert result.json()["findings"]
                assert result.json()["citations"][0]["docId"] == first.json()["id"]
                cited_id = result.json()["findings"][0]["citationId"]
                evidence = client.get(
                    f"/api/v1/documents/{first.json()['id']}/evidence/{cited_id}"
                )
                assert evidence.status_code == 200
                assert evidence.json()["focusPassageId"] == cited_id
                report = client.get(f"/api/v1/research/{result.json()['id']}/report")
                assert report.status_code == 200
                assert "# EvidenceGraph research report" in report.json()["content"]
                margin = client.post(
                    "/api/v1/research/query",
                    json={"question": "What is profit margin growth?"},
                )
                assert margin.status_code == 201
                assert margin.json()["metrics"] == []
                assert "not available" in margin.json()["missingInformation"][0]
                invalid_pdf = client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("report.pdf", b"not a PDF", "application/pdf")},
                )
                assert invalid_pdf.status_code == 415
                blocked = client.post(
                    "/api/v1/documents/upload",
                    headers={"Origin": "https://attacker.example"},
                    files={"file": ("again.txt", body, "text/plain")},
                )
                assert blocked.status_code == 403
                missing_route = client.get("/api/v1/unknown")
                assert missing_route.status_code == 404
                assert missing_route.json()["error"]["code"] == "http_404"
                assert missing_route.headers["x-request-id"]
                assert client.get("/api/v1/documents").json()["total"] == 1
                malformed_contact = client.put(
                    "/api/v1/settings/sec-contact", json={"email": "a@example.com\x00"}
                )
                assert malformed_contact.status_code == 422


def test_pdf_upload_preserves_page_reference():
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
        ):
            with TestClient(main.app) as client:
                pdf = pymupdf.open()
                page = pdf.new_page()
                page.insert_text((72, 72), "Quarterly risk disclosure. " * 12)
                content = pdf.tobytes()
                pdf.close()
                response = client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("risk.pdf", content, "application/pdf")},
                )
                assert response.status_code == 201, response.text
                document = client.get(
                    f"/api/v1/documents/{response.json()['id']}"
                ).json()
                assert document["document"]["page_count"] == 1
                assert document["passages"][0]["page"] == 1


def test_failed_sec_fetch_fails_job_without_empty_document():
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
        ):
            storage.init_db()
            job_id = "sec-failure-case"
            timestamp = storage.now_iso()
            with storage.connect() as db:
                db.execute(
                    "INSERT INTO jobs VALUES(?,?,?,?,?,?)",
                    (job_id, "sec_filing", "queued", "Queued.", timestamp, timestamp),
                )
            with patch.object(
                documents,
                "cached_json",
                side_effect=HTTPException(502, "SEC is unavailable."),
            ):
                documents.ingest_filing(
                    job_id, "0000000001", "10-K", "0000000001-24-000001"
                )
            with storage.connect() as db:
                job = db.execute(
                    "SELECT status,detail FROM jobs WHERE id=?", (job_id,)
                ).fetchone()
                document_count = db.execute(
                    "SELECT count(*) FROM documents"
                ).fetchone()[0]
            assert job["status"] == "failed"
            assert "SEC is unavailable" in job["detail"]
            assert document_count == 0


def test_internal_ingestion_errors_are_logged_but_not_shown_to_users():
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
        ):
            storage.init_db()
            timestamp = storage.now_iso()
            with storage.connect() as db:
                db.execute(
                    "INSERT INTO jobs VALUES(?,?,?,?,?,?)",
                    (
                        "internal-failure",
                        "sec_filing",
                        "queued",
                        "Queued.",
                        timestamp,
                        timestamp,
                    ),
                )
            with patch.object(
                documents,
                "cached_json",
                side_effect=RuntimeError("private filesystem path /srv/secret/data"),
            ):
                documents.ingest_filing(
                    "internal-failure",
                    "0000000001",
                    "10-K",
                    "0000000001-24-000001",
                )
            with storage.connect() as db:
                detail = db.execute(
                    "SELECT detail FROM jobs WHERE id='internal-failure'"
                ).fetchone()["detail"]
            assert "private filesystem path" not in detail
            assert (
                detail
                == "The filing could not be processed. Review the service log and retry."
            )


def test_startup_marks_incomplete_jobs_as_retryable_failures():
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
        ):
            storage.init_db()
            timestamp = storage.now_iso()
            with storage.connect() as db:
                db.executemany(
                    "INSERT INTO jobs VALUES(?,?,?,?,?,?)",
                    [
                        (
                            "queued-job",
                            "sec_filing",
                            "queued",
                            "Queued.",
                            timestamp,
                            timestamp,
                        ),
                        (
                            "running-job",
                            "sec_filing",
                            "running",
                            "Working.",
                            timestamp,
                            timestamp,
                        ),
                        (
                            "done-job",
                            "sec_filing",
                            "complete",
                            "Done.",
                            timestamp,
                            timestamp,
                        ),
                    ],
                )
            with TestClient(main.app):
                pass
            with storage.connect() as db:
                statuses = {
                    row["id"]: (row["status"], row["detail"])
                    for row in db.execute("SELECT id,status,detail FROM jobs")
                }
            assert statuses["queued-job"][0] == "failed"
            assert statuses["running-job"][0] == "failed"
            assert "Retry it" in statuses["running-job"][1]
            assert statuses["done-job"] == ("complete", "Done.")


def test_production_oidc_allowlist_requires_verified_email():
    with patch.dict(
        os.environ,
        {
            "EVIDENCEGRAPH_ALLOWED_EMAILS": "analyst@example.com",
            "EVIDENCEGRAPH_ALLOWED_EMAIL_DOMAINS": "research.example.org",
        },
        clear=True,
    ):
        assert auth.allowed_identity("Analyst@Example.com", True)
        assert auth.allowed_identity("person@research.example.org", True)
        assert not auth.allowed_identity("analyst@example.com", False)
        assert not auth.allowed_identity("person@sub.research.example.org", True)
        assert not auth.allowed_identity("other@example.com", True)


def test_production_configuration_fails_closed_without_identity_and_https():
    with (
        patch.object(auth, "ENVIRONMENT", "production"),
        patch.object(auth, "AUTH_MODE", "local"),
        patch.object(auth, "SESSION_SECRET", "short"),
        patch.object(auth, "PUBLIC_BASE_URL", "http://example.test"),
        patch.object(auth.oauth, "create_client", return_value=None),
        patch.dict(os.environ, {}, clear=True),
    ):
        errors = auth.production_config_errors()
    assert any("AUTH_MODE" in error for error in errors)
    assert any("SESSION_SECRET" in error for error in errors)
    assert any("HTTPS" in error for error in errors)
    assert any("email" in error for error in errors)
    with (
        patch.object(auth, "ENVIRONMENT", "production"),
        patch.object(
            auth,
            "SESSION_SECRET",
            "replace-with-a-random-secret-at-least-32-characters",
        ),
    ):
        assert any(
            "SESSION_SECRET" in error for error in auth.production_config_errors()
        )


def test_production_configuration_accepts_a_complete_single_host_setup():
    with (
        patch.object(auth, "ENVIRONMENT", "production"),
        patch.object(auth, "AUTH_MODE", "oidc"),
        patch.object(
            auth, "SESSION_SECRET", "a-random-secret-longer-than-thirty-two-characters"
        ),
        patch.object(auth, "PUBLIC_BASE_URL", "https://research.example.test"),
        patch.object(auth.oauth, "create_client", return_value=object()),
        patch.dict(
            os.environ,
            {
                "EVIDENCEGRAPH_ALLOWED_HOSTS": "research.example.test",
                "EVIDENCEGRAPH_OIDC_DISCOVERY_URL": "https://identity.example.test/.well-known/openid-configuration",
                "EVIDENCEGRAPH_OIDC_CLIENT_ID": "evidencegraph",
                "EVIDENCEGRAPH_OIDC_CLIENT_SECRET": "configured-secret",
                "EVIDENCEGRAPH_ALLOWED_EMAIL_DOMAINS": "example.test",
            },
            clear=True,
        ),
    ):
        assert auth.production_config_errors() == []


def test_oidc_mode_denies_anonymous_api_requests_but_exposes_safe_probes():
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
            patch.object(auth, "AUTH_MODE", "oidc"),
            patch.object(main, "AUTH_MODE", "oidc"),
        ):
            with TestClient(main.app) as client:
                private = client.get("/api/v1/documents")
                assert private.status_code == 401
                assert private.json()["error"]["code"] == "authentication_required"
                assert private.headers["cache-control"] == "no-store"
                assert private.headers["x-content-type-options"] == "nosniff"
                assert client.get("/", follow_redirects=False).status_code == 200
                assert client.get("/app", follow_redirects=False).status_code == 303
                assert client.get("/api/v1/health/live").json() == {"status": "ok"}
                assert client.get("/api/v1/health/ready").json() == {"status": "ready"}


def test_production_origin_check_uses_the_configured_https_origin():
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
            patch.object(main, "ENVIRONMENT", "production"),
            patch.object(main, "PUBLIC_BASE_URL", "https://research.example.test"),
        ):
            with TestClient(main.app) as client:
                accepted = client.put(
                    "/api/v1/settings/sec-contact",
                    headers={"Origin": "https://research.example.test"},
                    json={"email": "analyst@example.com"},
                )
                assert accepted.status_code == 200
                assert (
                    accepted.headers["strict-transport-security"] == "max-age=31536000"
                )
                rejected = client.put(
                    "/api/v1/settings/sec-contact",
                    headers={"Origin": "https://attacker.example"},
                    json={"email": "attacker@example.com"},
                )
                assert rejected.status_code == 403


def test_oidc_callback_creates_a_limited_session_and_logout_clears_it():
    class IdentityProvider:
        async def authorize_access_token(self, _request):
            return {
                "userinfo": {
                    "sub": "user-123",
                    "email": "analyst@example.com",
                    "email_verified": True,
                    "name": "Financial Analyst",
                },
                "access_token": "must-not-be-stored",
            }

    with (
        patch.object(auth, "AUTH_MODE", "oidc"),
        patch.object(main, "AUTH_MODE", "oidc"),
        patch.object(auth.oauth, "create_client", return_value=IdentityProvider()),
        patch.dict(os.environ, {"EVIDENCEGRAPH_ALLOWED_EMAILS": "analyst@example.com"}),
    ):
        with TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with (
                patch.object(storage, "DATA_DIR", data_dir),
                patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
                TestClient(main.app) as client,
            ):
                callback = client.get("/auth/callback", follow_redirects=False)
                assert callback.status_code == 303
                session = client.get("/api/v1/auth/session")
                assert session.status_code == 200
                assert session.json()["user"]["email"] == "analyst@example.com"
                assert "must-not-be-stored" not in client.cookies.get("session", "")
                assert client.get("/api/v1/documents").status_code == 200
                assert client.post("/auth/logout").json() == {"signedOut": True}
                assert client.get("/api/v1/documents").status_code == 401
                signed_out = client.get("/auth/signed-out")
                assert signed_out.status_code == 200
                assert "You are signed out" in signed_out.text


def test_synthetic_retrieval_benchmark_is_reproducible_and_recorded():
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
        ):
            main.init_db()
            first = engine.run_baseline_evaluation()
            second = engine.run_baseline_evaluation()
            assert first["datasetVersion"] == "synthetic-baseline-1.0"
            assert (
                first["retrieval"]["datasetSha256"]
                == second["retrieval"]["datasetSha256"]
            )
            assert first["questionCount"] == 10
            assert first["recallAt5"] >= 0.7
            assert main.evaluation_history()["items"]
