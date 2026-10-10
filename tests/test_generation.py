import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from backend.app import generation, main, storage


def configure(monkeypatch):
    monkeypatch.setenv("EVIDENCEGRAPH_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("EVIDENCEGRAPH_LLM_MODEL", "research-model")
    monkeypatch.setenv("EVIDENCEGRAPH_LLM_API_KEY", "secret")
    monkeypatch.setenv("EVIDENCEGRAPH_LLM_MAX_TOKENS", "1200")


def provider_response(answer):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": json.dumps(answer)}}]
    }
    return response


def answer(summary, citation_ids=("passage-1",), findings=None):
    return {
        "summary": summary,
        "summaryCitationIds": list(citation_ids),
        "findings": findings or [],
    }


def test_disabled_generation_never_sends_document_text(monkeypatch):
    for name in (
        "EVIDENCEGRAPH_LLM_BASE_URL",
        "EVIDENCEGRAPH_LLM_MODEL",
        "EVIDENCEGRAPH_LLM_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    post = Mock()
    with patch.object(generation.requests, "post", post):
        result, status = generation.generate_answer(
            "What risk is described?",
            [{"id": "passage-1", "excerpt": "Sensitive source text."}],
            [],
        )
    assert result is None
    assert status == "disabled"
    post.assert_not_called()


def test_generation_requires_complete_configuration_and_https_in_production(
    monkeypatch,
):
    monkeypatch.setenv("EVIDENCEGRAPH_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("EVIDENCEGRAPH_LLM_MODEL", "research-model")
    monkeypatch.delenv("EVIDENCEGRAPH_LLM_API_KEY", raising=False)
    assert generation.configuration_errors()
    configure(monkeypatch)
    with patch.object(generation, "ENVIRONMENT", "production"):
        monkeypatch.setenv("EVIDENCEGRAPH_LLM_BASE_URL", "http://model.example/v1")
        assert generation.configuration_errors()
        monkeypatch.setenv("EVIDENCEGRAPH_LLM_BASE_URL", "https://model.example/v1")
        monkeypatch.setenv("EVIDENCEGRAPH_LLM_MAX_TOKENS", "255")
        assert generation.configuration_errors()


def test_generated_claims_require_known_citations_and_supported_numbers(monkeypatch):
    configure(monkeypatch)
    citations = [
        {
            "id": "passage-1",
            "title": "Annual filing",
            "locator": "FY2024",
            "excerpt": "Supplier concentration increased to 4 suppliers in FY2024.",
        }
    ]
    valid = answer(
        "The disclosure names 4 suppliers for FY2024.",
        findings=[
            {
                "text": "Supplier concentration is discussed.",
                "citationIds": ["passage-1"],
            }
        ],
    )
    response = provider_response(valid)
    with patch.object(generation.requests, "post", return_value=response) as post:
        result, status = generation.generate_answer(
            "What supplier risks are disclosed?", citations, []
        )
    assert status == "complete"
    assert result["summaryCitationIds"] == ["passage-1"]
    assert post.call_args.kwargs["allow_redirects"] is False
    assert post.call_args.kwargs["timeout"] == generation.TIMEOUT
    assert post.call_args.kwargs["json"]["max_tokens"] == 1200

    for invalid in (
        answer("A risk is disclosed.", ("unknown-id",)),
        answer("The source describes 5 suppliers.", ("passage-1",)),
        answer("The source names five suppliers.", ("passage-1",)),
    ):
        with patch.object(
            generation.requests, "post", return_value=provider_response(invalid)
        ):
            result, status = generation.generate_answer(
                "What supplier risks are disclosed?", citations, []
            )
        assert result is None
        assert status == "rejected"


def test_provider_error_falls_back_without_leaking_provider_exception(
    monkeypatch, caplog
):
    configure(monkeypatch)
    citation = [{"id": "passage-1", "excerpt": "A source passage."}]
    with patch.object(
        generation.requests,
        "post",
        side_effect=requests.ConnectionError("secret provider response"),
    ):
        result, status = generation.generate_answer(
            "Explain this passage.", citation, []
        )
    assert result is None
    assert status == "unavailable"
    assert "secret provider response" not in caplog.text


def test_growth_claim_cites_both_verified_fact_inputs(monkeypatch):
    configure(monkeypatch)
    current_id, prior_id = "fact-2024", "fact-2023"
    citations = [
        {
            "id": current_id,
            "title": "Example Co",
            "locator": "FY2024",
            "value": "120",
            "unit": "USD",
        },
        {
            "id": prior_id,
            "title": "Example Co",
            "locator": "FY2023",
            "value": "100",
            "unit": "USD",
        },
    ]
    metrics = [
        {
            "sourceId": current_id,
            "cik": "1",
            "metric": "revenue",
            "fiscalYear": 2024,
            "value": "120",
            "growthPercent": "20",
        },
        {
            "sourceId": prior_id,
            "cik": "1",
            "metric": "revenue",
            "fiscalYear": 2023,
            "value": "100",
            "growthPercent": None,
        },
    ]
    draft = answer("Revenue grew 20% in FY2024.", (current_id,))
    with patch.object(
        generation.requests, "post", return_value=provider_response(draft)
    ):
        result, status = generation.generate_answer(
            "How did revenue grow?", citations, metrics
        )
    assert result is None
    assert status == "rejected"

    draft["summaryCitationIds"] = [current_id, prior_id]
    with patch.object(
        generation.requests, "post", return_value=provider_response(draft)
    ):
        result, status = generation.generate_answer(
            "How did revenue grow?", citations, metrics
        )
    assert status == "complete"
    assert set(result["summaryCitationIds"]) == {current_id, prior_id}


def test_configured_draft_flows_through_research_and_report(monkeypatch):
    configure(monkeypatch)
    with TemporaryDirectory() as temporary:
        data_dir = Path(temporary)
        with (
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "DB_PATH", data_dir / "test.sqlite3"),
        ):
            with TestClient(main.app) as client:
                uploaded = client.post(
                    "/api/v1/documents/upload",
                    files={
                        "file": (
                            "risk.txt",
                            (
                                "Risk factors\n\nSupplier concentration may delay "
                                "product delivery and increase operating costs. "
                                "Management monitors alternative suppliers and "
                                "maintains inventory buffers to reduce disruption."
                            ).encode(),
                            "text/plain",
                        )
                    },
                )
                assert uploaded.status_code == 201, uploaded.text

                def complete_request(_, **kwargs):
                    user_message = json.loads(kwargs["json"]["messages"][1]["content"])
                    citation_id = user_message["passages"][0]["citationId"]
                    return provider_response(
                        answer(
                            "Supplier risks include possible delivery delays.",
                            (citation_id,),
                            [
                                {
                                    "text": "Management monitors alternative suppliers.",
                                    "citationIds": [citation_id],
                                }
                            ],
                        )
                    )

                with patch.object(
                    generation.requests, "post", side_effect=complete_request
                ) as post:
                    result = client.post(
                        "/api/v1/research/query",
                        json={
                            "question": "What supplier risks are described?",
                            "includeFinancials": False,
                        },
                    )
                assert result.status_code == 201, result.text
                body = result.json()
                assert body["generation"]["status"] == "complete"
                assert body["answer"]["summary"].startswith("Supplier risks")
                request_body = json.loads(
                    post.call_args.kwargs["json"]["messages"][1]["content"]
                )
                assert (
                    "sourceUrl"
                    not in post.call_args.kwargs["json"]["messages"][1]["content"]
                )
                assert (
                    "risk.txt"
                    not in post.call_args.kwargs["json"]["messages"][1]["content"]
                )
                assert request_body["passages"]

                report = client.get(f"/api/v1/research/{body['id']}/report").json()[
                    "content"
                ]
                assert "## AI-assisted draft" in report
                assert body["answer"]["summaryCitationIds"][0] in report
