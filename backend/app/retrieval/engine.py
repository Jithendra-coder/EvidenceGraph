from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from typing import Any

from ..storage import ROOT, connect, now_iso

STOP_WORDS = {
    "the",
    "and",
    "for",
    "from",
    "that",
    "with",
    "what",
    "when",
    "where",
    "were",
    "was",
    "are",
    "how",
    "does",
    "did",
    "their",
    "they",
    "them",
    "about",
    "into",
    "over",
    "under",
    "year",
    "years",
    "company",
    "companies",
    "across",
    "compare",
    "compared",
    "explain",
    "please",
}


def retrieve(question: str, ciks: list[str], limit: int = 8) -> list[dict[str, Any]]:
    terms = [
        word
        for word in re.findall(r"[\w]{2,}", question.casefold())
        if word not in STOP_WORDS
    ]
    terms = list(dict.fromkeys(terms))[:16]
    if not terms:
        return []
    match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
    with connect() as db:
        sql = """SELECT p.passage_id,p.doc_id,p.text,p.heading,d.title,d.source_type,d.source_url,
                 d.company_cik,d.company_name,d.form,d.filing_date,d.report_date,d.fiscal_year,d.accession,
                 rank AS score
                 FROM passages_fts p JOIN documents d ON d.id=p.doc_id
                 WHERE passages_fts MATCH ?"""
        args: list[Any] = [match]
        if ciks:
            sql += " AND d.company_cik IN (" + ",".join("?" for _ in ciks) + ")"
            args.extend(ciks)
        sql += " ORDER BY score LIMIT ?"
        args.append(limit)
        rows = db.execute(sql, args).fetchall()
    return [dict(row) for row in rows]


def run_baseline_evaluation() -> dict[str, Any]:
    dataset_path = ROOT / "datasets" / "baseline.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE VIRTUAL TABLE baseline USING fts5(id UNINDEXED, text, tokenize='porter unicode61')"
    )
    db.executemany(
        "INSERT INTO baseline(id,text) VALUES(?,?)",
        [(item["id"], item["text"]) for item in dataset["passages"]],
    )
    reciprocal_ranks, recalls, ndcgs, failures = [], [], [], []
    started = time.perf_counter()
    for case in dataset["questions"]:
        terms = [
            word
            for word in re.findall(r"[\w]{2,}", case["question"].casefold())
            if word not in STOP_WORDS
        ]
        terms = list(dict.fromkeys(terms))[:16]
        match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        hits = (
            [
                row[0]
                for row in db.execute(
                    "SELECT id FROM baseline WHERE baseline MATCH ? ORDER BY rank LIMIT 5",
                    (match,),
                )
            ]
            if match
            else []
        )
        relevant = set(case["relevant"])
        ranks = [index + 1 for index, item in enumerate(hits) if item in relevant]
        reciprocal_ranks.append(1 / min(ranks) if ranks else 0)
        recalls.append(len(set(hits) & relevant) / len(relevant))
        dcg = sum(
            1 / math.log2(index + 2)
            for index, item in enumerate(hits)
            if item in relevant
        )
        ideal = sum(1 / math.log2(index + 2) for index in range(min(len(relevant), 5)))
        ndcgs.append(dcg / ideal if ideal else 0)
        if not ranks:
            failures.append(
                {
                    "question": case["question"],
                    "relevant": sorted(relevant),
                    "retrieved": hits,
                }
            )
    duration = round((time.perf_counter() - started) * 1000, 2)
    result = {
        "datasetVersion": dataset["version"],
        "datasetNote": dataset["note"],
        "questionCount": len(dataset["questions"]),
        "passageCount": len(dataset["passages"]),
        "recallAt5": round(sum(recalls) / len(recalls), 4),
        "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4),
        "ndcgAt5": round(sum(ndcgs) / len(ndcgs), 4),
        "latencyMs": duration,
        "retrieval": {
            "method": "SQLite FTS5 BM25",
            "topK": 5,
            "datasetSha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        },
        "failures": failures,
        "completedAt": now_iso(),
    }
    db.close()
    run_id = str(uuid.uuid4())
    with connect() as store:
        store.execute(
            "INSERT INTO evaluation_runs VALUES(?,?,?)",
            (run_id, json.dumps(result), result["completedAt"]),
        )
    return {"id": run_id, **result}
