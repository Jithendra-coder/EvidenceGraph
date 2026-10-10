"""Opt-in SEC integration smoke test; stores all application data in pytest's temp dir."""

from __future__ import annotations

import os
import json
import math
import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.app import auth, main, storage
from backend.app.retrieval import engine

pytestmark = pytest.mark.skipif(
    os.getenv("EVIDENCEGRAPH_RUN_LIVE_SEC") != "1",
    reason="Set EVIDENCEGRAPH_RUN_LIVE_SEC=1 to call the public SEC APIs.",
)


def metrics_at_5(rankings, relevant_sets):
    recall, reciprocal_rank, ndcg = [], [], []
    for ranking, relevant in zip(rankings, relevant_sets, strict=True):
        top = ranking[:5]
        ranks = [index + 1 for index, item in enumerate(top) if item in relevant]
        recall.append(len(set(top) & relevant) / len(relevant))
        reciprocal_rank.append(1 / min(ranks) if ranks else 0)
        dcg = sum(
            1 / math.log2(index + 2)
            for index, item in enumerate(top)
            if item in relevant
        )
        ideal = sum(1 / math.log2(index + 2) for index in range(min(len(relevant), 5)))
        ndcg.append(dcg / ideal if ideal else 0)
    return {
        "recallAt5": round(sum(recall) / len(recall), 4),
        "mrr": round(sum(reciprocal_rank) / len(reciprocal_rank), 4),
        "ndcgAt5": round(sum(ndcg) / len(ndcg), 4),
    }


def test_target_filing_ingestion_research_and_xbrl_facts(monkeypatch, tmp_path):
    dataset_path = storage.ROOT / "datasets" / "target-2026-10k-retrieval.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    source = dataset["source"]
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "live-sec.sqlite3")
    monkeypatch.setattr(auth, "AUTH_MODE", "local")
    monkeypatch.setattr(main, "AUTH_MODE", "local")

    with TestClient(main.app) as client:
        contact = client.put(
            "/api/v1/settings/sec-contact",
            json={"email": "demo@example.com"},
        )
        assert contact.status_code == 200, contact.text

        company = client.get("/api/v1/companies/0000027419")
        assert company.status_code == 200, company.text
        filing = next(
            item
            for item in company.json()["filings"]
            if item["accession"] == source["accession"]
        )
        assert filing["reportDate"] == source["reportDate"]

        sync = client.post(
            "/api/v1/documents/sync",
            json={
                "cik": source["cik"],
                "form": filing["form"],
                "accession": filing["accession"],
            },
        )
        assert sync.status_code == 202, sync.text
        job = client.get(f"/api/v1/jobs/{sync.json()['jobId']}")
        assert job.status_code == 200, job.text
        assert job.json()["status"] == "complete", job.json()

        research = client.post(
            "/api/v1/research/query",
            json={
                "question": "What inventory shrink risks does Target disclose in its annual filing?",
                "companies": [source["cik"]],
                "includeFinancials": False,
            },
        )
        assert research.status_code == 201, research.text
        result = research.json()
        assert result["findings"]
        assert any("shrink" in item["text"].casefold() for item in result["findings"])
        assert any(
            item["reportDate"] == source["reportDate"] for item in result["citations"]
        )

        facts = client.post(
            "/api/v1/research/query",
            json={
                "question": "What was Target annual revenue for the latest years?",
                "companies": ["0000027419"],
                "includeFinancials": True,
            },
        )
        assert facts.status_code == 201, facts.text
        metrics = facts.json()["metrics"]
        current = next(item for item in metrics if item["fiscalYear"] == 2025)
        assert current["value"] == "104780000000"
        assert current["periodEnd"] == "2026-01-31"
        assert current["growthPercent"].startswith("-1.6759")

        with storage.connect() as db:
            passages = [
                dict(row)
                for row in db.execute(
                    """SELECT p.id,p.ordinal,p.text FROM passages p
                       JOIN documents d ON d.id=p.doc_id WHERE d.accession=?
                       ORDER BY p.ordinal""",
                    (source["accession"],),
                )
            ]
        bm25_rankings, baseline_rankings, relevant_sets = [], [], []
        for case in dataset["questions"]:
            relevant = {
                passage["id"]
                for passage in passages
                if any(
                    anchor.casefold() in passage["text"].casefold()
                    for anchor in case["relevantAnchors"]
                )
            }
            assert relevant, f"No source passage matched {case['question']!r}"
            terms = list(
                dict.fromkeys(
                    word
                    for word in re.findall(r"[\w]{2,}", case["question"].casefold())
                    if word not in engine.STOP_WORDS
                )
            )[:16]
            bm25_rankings.append(
                [
                    item["passage_id"]
                    for item in engine.retrieve(case["question"], [source["cik"]], 5)
                ]
            )
            simple = sorted(
                passages,
                key=lambda passage: (
                    -sum(term in passage["text"].casefold() for term in terms),
                    passage["ordinal"],
                ),
            )
            baseline_rankings.append(
                [
                    passage["id"]
                    for passage in simple
                    if any(term in passage["text"].casefold() for term in terms)
                ][:5]
            )
            relevant_sets.append(relevant)

        bm25 = metrics_at_5(bm25_rankings, relevant_sets)
        simple = metrics_at_5(baseline_rankings, relevant_sets)
        assert bm25["recallAt5"] > simple["recallAt5"]
        assert bm25["mrr"] > simple["mrr"]
        assert bm25["ndcgAt5"] > simple["ndcgAt5"]
        assert bm25["recallAt5"] >= 0.85
        assert bm25["mrr"] >= 0.75
        assert bm25["ndcgAt5"] >= 0.77
        print(
            json.dumps(
                {
                    "datasetVersion": dataset["version"],
                    "sourceAccession": source["accession"],
                    "questionCount": len(dataset["questions"]),
                    "bm25": bm25,
                    "simpleBaseline": simple,
                    "bm25Misses": [
                        case["question"]
                        for case, ranking, relevant in zip(
                            dataset["questions"],
                            bm25_rankings,
                            relevant_sets,
                            strict=True,
                        )
                        if not set(ranking[:5]) & relevant
                    ],
                },
                ensure_ascii=False,
            )
        )


def test_multi_issuer_retrieval_and_revenue_facts(monkeypatch, tmp_path):
    dataset_path = storage.ROOT / "datasets" / "issuer-research-evaluation.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "issuer-evaluation.sqlite3")
    monkeypatch.setattr(auth, "AUTH_MODE", "local")
    monkeypatch.setattr(main, "AUTH_MODE", "local")

    with TestClient(main.app) as client:
        contact = client.put(
            "/api/v1/settings/sec-contact",
            json={"email": "demo@example.com"},
        )
        assert contact.status_code == 200, contact.text

        for source in dataset["sources"]:
            company = client.get(f"/api/v1/companies/{source['cik']}")
            assert company.status_code == 200, company.text
            filing = next(
                item
                for item in company.json()["filings"]
                if item["accession"] == source["accession"]
            )
            assert filing["form"] == source["form"]
            assert filing["reportDate"] == source["reportDate"]
            sync = client.post(
                "/api/v1/documents/sync",
                json={
                    "cik": source["cik"],
                    "form": filing["form"],
                    "accession": filing["accession"],
                },
            )
            assert sync.status_code == 202, sync.text
            job = client.get(f"/api/v1/jobs/{sync.json()['jobId']}")
            assert job.status_code == 200, job.text
            assert job.json()["status"] == "complete", job.json()

        compared = client.post(
            "/api/v1/research/compare",
            json={
                "companies": [source["cik"] for source in dataset["sources"]],
                "metric": "revenue",
                "periods": 2,
            },
        )
        assert compared.status_code == 200, compared.text
        comparison = {item["cik"]: item for item in compared.json()["companies"]}
        for source in dataset["sources"]:
            company = comparison[source["cik"]]
            current, previous = company["periods"][-1], company["periods"][-2]
            assert current["fiscalYear"] == source["revenue"]["fiscalYear"]
            assert current["value"] == source["revenue"]["value"]
            assert current["end"] == source["revenue"]["periodEnd"]
            assert previous["fiscalYear"] == source["revenue"]["priorFiscalYear"]
            assert previous["value"] == source["revenue"]["priorValue"]
            assert previous["end"] == source["revenue"]["priorPeriodEnd"]
            assert current["citation"]["accession"] == current["accession"]
            assert current["citation"]["sourceUrl"] == (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{int(source['cik'])}/{current['accession'].replace('-', '')}/"
            )
            expected_growth = (
                (Decimal(current["value"]) - Decimal(previous["value"]))
                / Decimal(previous["value"])
                * 100
            )
            assert Decimal(current["growthPercent"]) == expected_growth
        assert any("more than 45 days" in item for item in compared.json()["warnings"])

        with storage.connect() as db:
            passages_by_cik = {}
            for source in dataset["sources"]:
                passages_by_cik[source["cik"]] = [
                    dict(row)
                    for row in db.execute(
                        """SELECT p.id,p.ordinal,p.text FROM passages p
                           JOIN documents d ON d.id=p.doc_id WHERE d.accession=?
                           ORDER BY p.ordinal""",
                        (source["accession"],),
                    )
                ]

        report = {}
        for split in ("development", "holdout"):
            bm25_rankings, baseline_rankings, relevant_sets, misses = [], [], [], []
            cases = [item for item in dataset["questions"] if item["split"] == split]
            for case in cases:
                passages = passages_by_cik[case["cik"]]
                relevant = {
                    passage["id"]
                    for passage in passages
                    if any(
                        anchor.casefold() in passage["text"].casefold()
                        for anchor in case["relevantAnchors"]
                    )
                }
                assert relevant, f"No source passage matched {case['question']!r}"
                result = client.post(
                    "/api/v1/research/query",
                    json={
                        "question": case["question"],
                        "companies": [case["cik"]],
                        "includeFinancials": False,
                    },
                )
                assert result.status_code == 201, result.text
                bm25 = [item["citationId"] for item in result.json()["findings"][:5]]
                terms = list(
                    dict.fromkeys(
                        word
                        for word in re.findall(r"[\w]{2,}", case["question"].casefold())
                        if word not in engine.STOP_WORDS
                    )
                )[:16]
                simple = sorted(
                    passages,
                    key=lambda passage: (
                        -sum(term in passage["text"].casefold() for term in terms),
                        passage["ordinal"],
                    ),
                )
                baseline = [
                    passage["id"]
                    for passage in simple
                    if any(term in passage["text"].casefold() for term in terms)
                ][:5]
                bm25_rankings.append(bm25)
                baseline_rankings.append(baseline)
                relevant_sets.append(relevant)
                if not set(bm25) & relevant:
                    misses.append(case["question"])
            report[split] = {
                "questionCount": len(cases),
                "bm25": metrics_at_5(bm25_rankings, relevant_sets),
                "simpleBaseline": metrics_at_5(baseline_rankings, relevant_sets),
                "bm25Misses": misses,
            }

        print(
            json.dumps(
                {
                    "datasetVersion": dataset["version"],
                    "developmentIssuers": [
                        item["company"]
                        for item in dataset["sources"]
                        if item["split"] == "development"
                    ],
                    "holdoutIssuers": [
                        item["company"]
                        for item in dataset["sources"]
                        if item["split"] == "holdout"
                    ],
                    "retrieval": report,
                    "revenueFacts": {
                        source["company"]: {
                            "fiscalYear": comparison[source["cik"]]["periods"][-1][
                                "fiscalYear"
                            ],
                            "value": comparison[source["cik"]]["periods"][-1]["value"],
                            "concept": comparison[source["cik"]]["concept"],
                        }
                        for source in dataset["sources"]
                    },
                },
                ensure_ascii=False,
            )
        )
