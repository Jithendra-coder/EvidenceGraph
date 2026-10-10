# EvidenceGraph

EvidenceGraph is a source-grounded financial research workspace for SEC filings, annual XBRL facts, and uploaded documents. It supports a local development profile and a fail-closed, OIDC-protected single-organization container profile.

## What works in this release

- Search public issuers by name, ticker, or CIK using SEC EDGAR.
- Sync an exact recent 10-K or 10-Q filing by its SEC accession number (including amendments) into a persistent local SQLite index.
- Upload PDF, HTML, and UTF-8 text files; retain page numbers for PDFs and stable document hashes for duplicate detection.
- Search indexed passages with SQLite FTS5 and open each excerpt in the evidence viewer.
- Retrieve annual SEC Company Facts for revenue, net income, and operating cash flow.
- Calculate annual growth using `Decimal`, reporting-period duration checks, and source fact references.
- Save research sessions and export them to Markdown.
- Run a versioned synthetic retrieval benchmark that reports Recall@5, MRR, nDCG@5, latency, and misses.
- Run opt-in live SEC evaluations: a Target smoke test and a three-issuer revenue/retrieval evaluation with a Walmart/Costco development split and an Apple issuer holdout; both use temporary storage.
- Use a responsive, keyboard-friendly browser interface. No paid model, vector database, or frontend build step is required.

The default research path is deterministic. An optional OpenAI-compatible model can draft cited narrative when an operator configures all three provider settings; it receives the question, retrieved excerpts, and relevant XBRL facts. Drafts must pass citation-ID and numeric checks, but those checks do not verify semantic accuracy. Search uses SQLite FTS5 BM25 with Porter stemming. The hosted profile provides OIDC sign-in, an email allowlist, request tracing, health probes, and a hardened container, but the data model remains one shared workspace per deployment.

## Run locally

Requires Python 3.11 or newer. On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

Open [http://127.0.0.1:8001](http://127.0.0.1:8001) for the EvidenceGraph introduction. Select **Get started** to open the research workspace at [http://127.0.0.1:8001/app](http://127.0.0.1:8001/app). The FastAPI OpenAPI reference is available at [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).

On first use, open **Settings** and add a contact email. The SEC requires a descriptive User-Agent for automated requests. EvidenceGraph stores that email in its local SQLite settings table and sends it with public EDGAR requests. SEC data calls are paced, cached, retried for transient failures, and surfaced as errors when they fail.

The SQLite database defaults to `./data/evidencegraph.sqlite3`. Set `EVIDENCEGRAPH_DATA_DIR` to use another directory. Uploaded content and search text stay in the configured data store; SEC requests go only to fixed public SEC URLs.

Model generation is disabled by default. To enable it, configure `EVIDENCEGRAPH_LLM_BASE_URL`, `EVIDENCEGRAPH_LLM_MODEL`, and `EVIDENCEGRAPH_LLM_API_KEY`; production endpoints must use HTTPS. `EVIDENCEGRAPH_LLM_MAX_TOKENS` sets the response cap (256–2048; default 1200). Set the provider API base URL without `/chat/completions`; EvidenceGraph appends that path. The configured provider receives the research question and up to eight retrieved passages plus relevant structured facts. This may send uploaded or SEC filing text outside the deployment and may incur provider charges. The Settings page reports the configured model and disclosure. Leave all three values blank to keep all research local and deterministic.

## Cloud container deployment

The production container requires an OIDC identity provider, HTTPS public URL, host allowlist, and an exact email or email-domain allowlist. Create an OIDC client with this callback URL: `https://YOUR_HOST/auth/callback`. Copy the example configuration, generate a session key, then replace every example value with the deployment's actual values:

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up --build -d
docker compose logs -f evidencegraph
```

Set the generated value as `EVIDENCEGRAPH_SESSION_SECRET` in `.env`. Configure `EVIDENCEGRAPH_PUBLIC_BASE_URL`, `EVIDENCEGRAPH_ALLOWED_HOSTS`, the OIDC discovery URL/client credentials, and `EVIDENCEGRAPH_ALLOWED_EMAILS` or `EVIDENCEGRAPH_ALLOWED_EMAIL_DOMAINS` before starting. Never commit `.env`. Compose binds to loopback for use behind a TLS reverse proxy; a cloud container platform should route HTTPS to container port `8000` (or its injected `PORT`), mount persistent storage at `/app/data`, and set the same environment variables as platform secrets. Use `/api/v1/health/live` for liveness and `/api/v1/health/ready` for readiness.

Keep exactly one application replica with the current SQLite data layer. Back up the persistent volume and test a restore before relying on it. All allowlisted accounts can access the same deployment data. Do not deploy multiple organizations to the same instance.

## Verify the project

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m py_compile backend/app/main.py
node --check frontend/app.js
```

For the live SEC smoke test in PowerShell, set `$env:EVIDENCEGRAPH_RUN_LIVE_SEC = "1"` and run `py -3.11 -m pytest -q -s tests/test_live_sec.py`. It makes public SEC requests and keeps application data in a temporary test directory. Clear the setting afterward with `Remove-Item Env:EVIDENCEGRAPH_RUN_LIVE_SEC`.

The standard retrieval benchmark is a synthetic regression fixture. The live SEC tests compare BM25 with a simple token-overlap baseline on seven Target questions and 13 issuer-anchored Walmart, Costco, and Apple questions. The second test also checks recent annual revenue against SEC XBRL and exercises the three-company comparison endpoint. Walmart's reported total revenue is selected from `us-gaap:Revenues` when present, instead of net sales alone. These tests measure retrieval and fact mapping; anchor-label retrieval is not full semantic relevance or answer-accuracy review. See the [evaluation dataset](datasets/issuer-research-evaluation.json) for the questions and protocol.

## API map

All endpoints use the `/api/v1` prefix. `POST /documents/sync` accepts the selected filing's `cik`, `form`, and SEC `accession`, returns a job ID, and should be followed by polling `/jobs/{job_id}` for completion or an explicit failure. Filing cards show the SEC report period end separately from its filing date; financial fiscal-year labels come from SEC XBRL facts.

| Area | Endpoints |
|---|---|
| Identity and health | `GET /auth/login`, `POST /auth/logout`, `GET /api/v1/auth/session`, `GET /api/v1/health/live`, `GET /api/v1/health/ready` |
| Health and setup | `GET /api/v1/health`, `GET /api/v1/settings`, `PUT /api/v1/settings/sec-contact` |
| Companies | `GET /companies/search`, `GET /companies/{cik}`, `GET /companies/{cik}/facts` |
| Documents | `POST /documents/upload`, `POST /documents/sync`, `GET /documents`, `GET /documents/{id}`, `GET /documents/{id}/status` |
| Research | `POST /research/query`, `POST /research/compare`, `GET /research/{id}`, `GET /research/{id}/evidence`, `GET /research/{id}/report` |
| Evaluation | `POST /evaluations/run`, `GET /evaluations` |

## Current product limits

- The hosted profile is single-tenant and single-replica. All allowlisted OIDC users share one workspace; there are no per-user roles, workspace memberships, or audit event history.
- Ingestion jobs are persisted in SQLite, but execute in the API process. Startup marks interrupted jobs failed and they can be retried; long jobs do not resume automatically.
- The hosted profile uses SQLite on persistent storage, not PostgreSQL. It is not suitable for horizontal scaling; move to PostgreSQL and a durable worker queue before adding replicas.
- SEC company facts support annual 10-K and 10-K/A periods in USD. Custom taxonomy concepts, quarterly comparisons, profit margin, currency conversion, and dimensional facts are not mapped.
- PDF text extraction preserves page numbers but does not OCR image-only scans or recover complex visual tables.
- Search is lexical FTS5 BM25 with Porter stemming. It does not use semantic embeddings, Qdrant hybrid search, query decomposition, or reranking; stemming can broaden matches, so citations still need review.
- The fixtures contain 10 synthetic regression questions and a small live SEC set (7 Target questions plus 13 issuer-anchored questions). The live retrieval set is a diagnostic with one issuer holdout, not a statistically representative or human-judged answer-quality benchmark.
- There is no semantic validation of generated prose, financial advice, PDF export, OCR, malware scanning, or application-level distributed request rate limiting. Configure equivalent rate limits at the cloud ingress before opening access beyond a small allowlisted group.

See [the architecture](docs/architecture.md), [security and deployment notes](docs/security.md), [portfolio diagrams and interview notes](docs/portfolio-diagrams/README.md), and the [demo storyboard](docs/demo-script.md) for implementation details.
