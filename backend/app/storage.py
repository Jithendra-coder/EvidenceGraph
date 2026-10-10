from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
DATA_DIR = (
    Path(os.environ.get("EVIDENCEGRAPH_DATA_DIR", ROOT / "data")).expanduser().resolve()
)
DB_PATH = DATA_DIR / "evidencegraph.sqlite3"


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30, factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 30000")
    db.execute("PRAGMA synchronous = FULL")
    return db


def init_db() -> None:
    with connect() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, fetched REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, source_key TEXT NOT NULL UNIQUE, checksum TEXT NOT NULL,
            title TEXT NOT NULL, source_type TEXT NOT NULL, source_url TEXT,
            company_cik TEXT, company_name TEXT, form TEXT, filing_date TEXT,
            report_date TEXT, fiscal_year INTEGER, accession TEXT, filename TEXT,
            page_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS documents_company ON documents(company_cik, filing_date);
        CREATE TABLE IF NOT EXISTS passages (
            id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL, heading TEXT, page INTEGER, text TEXT NOT NULL,
            UNIQUE(doc_id, ordinal)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
            passage_id UNINDEXED, doc_id UNINDEXED, company_cik UNINDEXED,
            heading UNINDEXED, text, tokenize='porter unicode61'
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
            detail TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research (
            id TEXT PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evaluation_runs (
            id TEXT PRIMARY KEY, result TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        document_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(documents)")
        }
        if "report_date" not in document_columns:
            db.execute("ALTER TABLE documents ADD COLUMN report_date TEXT")
        fts_table = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='passages_fts'"
        ).fetchone()
        if (
            fts_table
            and "tokenize='porter unicode61'" not in fts_table["sql"].casefold()
        ):
            db.execute("DROP TABLE passages_fts")
            db.execute(
                """CREATE VIRTUAL TABLE passages_fts USING fts5(
                    passage_id UNINDEXED, doc_id UNINDEXED, company_cik UNINDEXED,
                    heading UNINDEXED, text, tokenize='porter unicode61'
                )"""
            )
            db.execute(
                """INSERT INTO passages_fts(passage_id,doc_id,company_cik,heading,text)
                   SELECT p.id,p.doc_id,COALESCE(d.company_cik,''),COALESCE(p.heading,''),p.text
                   FROM passages p JOIN documents d ON d.id=p.doc_id"""
            )
        db.execute(
            "UPDATE jobs SET status='failed',detail=?,updated_at=? WHERE status IN ('queued','running')",
            ("Application restarted before this job finished. Retry it.", now_iso()),
        )
    if os.name != "nt":
        os.chmod(DATA_DIR, 0o700)
        os.chmod(DB_PATH, 0o600)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_contact() -> str | None:
    with connect() as db:
        row = db.execute(
            "SELECT value FROM settings WHERE key='sec_contact'"
        ).fetchone()
        return row["value"] if row else None


def update_job(job_id: str, status: str, detail: str) -> None:
    with connect() as db:
        db.execute(
            "UPDATE jobs SET status=?,detail=?,updated_at=? WHERE id=?",
            (status, detail[:500], now_iso(), job_id),
        )
