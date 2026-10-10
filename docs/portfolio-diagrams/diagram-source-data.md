# EvidenceGraph — diagram source data

Verified project facts and presentation requirements used to prepare the system architecture and end-to-end execution flow. This file is the content brief, not a diagram. It is intended to be reusable when the visual assets are recreated or revised.

- **Project name:** EvidenceGraph
- **Project category:** Source-grounded financial research workspace
- **Brief verified against repository and live SEC evaluations:** 2026-10-10
- **Scope:** Documentation and technical visualization only

## 1. Project summary

EvidenceGraph helps a researcher search indexed company filings and uploaded documents, inspect source-linked passages, and compare a limited set of annual SEC financial facts. Research results are stored and returned with their citations and caveats. A configured language model can optionally draft cited narrative; the normal research path works without a model.

### Problem addressed

Financial research requires readers to find relevant evidence across filings and documents and to connect reported facts back to their source. EvidenceGraph combines lexical document retrieval with selected annual SEC XBRL facts and presents source references alongside the result.

### Intended user

A researcher using the browser workspace. In the hosted profile, access is limited to identities that pass the configured OIDC and verified-email allowlist checks. Authorized users share one organization-wide workspace and corpus.

### Inputs

- A natural-language research question.
- Zero or more selected company CIKs.
- A choice to include financial facts.
- Previously indexed SEC filing passages.
- Uploaded PDF, HTML, or UTF-8 text documents, up to 15 MB per upload.

### Outputs

- Up to eight matching passages from the indexed corpus, with source citations.
- Supported annual SEC facts and period comparisons, when requested and available.
- Missing-information notes and caveats.
- A deterministic research result, with an optional model-drafted narrative when configured.
- A saved research session and JSON response; a Markdown report can be generated when the user selects export.

## 2. Verified technology and component inventory

| Area | Implemented component | Responsibility |
|---|---|---|
| Browser UI | Vanilla HTML, CSS, and JavaScript | Introduction page and research workspace; sends same-origin requests to the application. |
| Web application and API | Python, FastAPI, Pydantic | Serves the UI, exposes JSON routes under `/api/v1`, validates request/response data, and provides health endpoints. |
| Identity | External OIDC provider | Hosted browser authorization-code flow with PKCE; the application validates identity and verified-email allowlist membership. |
| Request security | FastAPI middleware and signed session cookie | Trusted-host checks, authenticated session checks, same-origin checks for browser writes, request IDs, and safe response headers. Hosted session cookie is HttpOnly, Secure, SameSite=Lax, and lasts eight hours. |
| Document ingestion | In-process Python modules | Parses supported upload text inline; splits text into passages, derives stable IDs, and records source locators. SEC filing synchronization selects the exact Submissions API accession, records report period end separately from filing date, and runs through FastAPI `BackgroundTasks` in the API process. |
| Search | SQLite FTS5 with BM25 ranking and Porter stemming | Lexical search over indexed passage text. Query terms are normalized, combined with OR, optionally filtered by issuer, and limited to eight results. Existing indexes rebuild from stored passages on startup after the tokenizer migration. |
| Financial data | SEC Company Facts API and application fact-normalization code | Reads mapped US-GAAP annual facts for revenue, net income, and operating cash flow; applies period, unit, duration, and SEC fiscal-year checks. |
| Durable state | SQLite in WAL mode on a persistent volume | Stores documents, passages, FTS5 index, SEC response cache, jobs, settings, saved research results, and evaluation runs. It is the only durable service dependency. |
| Optional AI | Configured OpenAI-compatible API | Produces one optional narrative draft from the question, retrieved excerpts, and relevant facts. Disabled unless the required settings are present. |
| Runtime packaging | Docker / Docker Compose | Hosted container profile runs one Uvicorn worker and one replica with persistent SQLite storage and container hardening. No particular cloud provider is established by the repository. |

### External boundaries

- **OIDC provider:** external identity system used for hosted sign-in.
- **SEC EDGAR:** fixed `sec.gov` and `data.sec.gov` endpoints for submissions, filing data, and Company Facts.
- **Optional model provider:** an OpenAI-compatible HTTPS endpoint. Research source text and relevant facts are sent to it when narrative drafting is enabled.

No other external service, database, queue, model orchestration framework, or vector service is represented.

## 3. System architecture content

Use these components and relationships when explaining the architecture:

1. **Researcher / browser → FastAPI application:** The browser loads the UI and sends same-origin HTTP requests. JSON endpoints live under `/api/v1`; uploads use multipart form data.
2. **Browser ↔ OIDC provider → FastAPI trust middleware:** Hosted sign-in uses authorization code with PKCE. The callback checks verified identity and allowlist membership; the app then uses a signed session cookie. Do not draw the OIDC provider as the application database or as a model provider.
3. **FastAPI application → trust and request middleware → core routes:** Hosted requests pass host, session, and browser-write origin checks. Request IDs and safe headers are applied by the application middleware.
4. **Core routes → ingestion modules:** Upload extraction and passage indexing happen inline. SEC filing synchronization persists a job for the selected SEC accession and schedules an in-process FastAPI background task. The filing's report period end and filing date are separate metadata; a fiscal year is not guessed from a date.
5. **Core routes → research modules → SQLite FTS5:** Research modules query indexed passages. SQLite supplies durable application records and the lexical search index.
6. **Research modules ↔ SEC EDGAR:** Relevant Company Facts and filing data are fetched through the SEC connector; the connector also uses local SQLite caching. Requests have timeouts, process-local pacing, and bounded retries for transient failures.
7. **Research modules → optional model provider:** Only when citations exist and model settings are configured. One HTTPS call sends the question, up to eight excerpts, and relevant facts. The provider is optional and off by default.
8. **Research modules → SQLite → browser:** The assembled result is saved before the JSON response is returned. Markdown export is a later user action.
9. **Application → operational signals:** Request logs include request ID, method, path, status, and duration. Liveness and readiness endpoints exist; readiness checks SQLite.

### Boundaries and runtime shape

- One shared organization workspace, one application replica, and one Uvicorn worker are the documented hosted profile.
- SEC filing tasks run in the API process; they are not sent to a separate queue or worker service.
- SQLite and its persistent volume are the only durable application storage.
- Model access is optional and can send indexed source text outside the deployment.
- The repository does not establish a named cloud provider or production deployment URL.

## 4. End-to-end execution flow data

Representative operation: a researcher submits `POST /api/v1/research/query` with a question, selected CIKs, and the `includeFinancials` setting. Source documents may have been indexed before this request.

### Primary successful path

1. **Ask:** The browser submits the question, selected company CIKs, and financial-facts choice.
2. **Gate:** Hosted middleware checks the session and same-origin policy. Pydantic validates request fields and CIKs are normalized.
3. **Retrieve:** The retriever removes a small stop-word set, keeps at most 16 unique terms, joins them with OR, applies a selected-issuer filter when present, and returns up to eight FTS5 BM25 passages. SQLite's Porter tokenizer matches common English word forms; retrieval remains lexical.
4. **Decide whether to load facts:** Facts are considered only when `includeFinancials` is enabled and the question matches a supported metric keyword. Current mapping recognizes cash flow, revenue/sales, and net income/profit. Profit margin is not inferred.
5. **Load annual facts:** On a cache miss, the SEC Company Facts API is queried. The code maps supported US-GAAP tags to USD annual 10-K/10-K/A facts and accepts 300–400 day durations. The fiscal-year label comes from SEC `fy` on the earliest filing for the exact period so a later comparative filing cannot relabel it; facts with no `fy` are skipped. Growth is emitted only when fiscal years are adjacent, the prior amount is positive, units match, and durations differ by no more than seven days.
6. **Assemble evidence:** Passage and fact citations are deduplicated by citation ID. The result includes findings, periods, missing information, caveats, freshness, and retrieval method.
7. **Optional draft:** If evidence citations exist and the model endpoint, API key, and model settings are configured, one provider request is made. Pydantic checks the response schema; citation IDs must be supplied IDs and numeric claims must match cited excerpts or verified facts.
8. **Persist and return:** The result is saved in SQLite and returned as JSON to the browser. A Markdown export is generated only if the user chooses export.

### Decision and branch data

| Decision | Condition | Implemented outcome |
|---|---|---|
| Hosted access | Valid session and allowed identity | Continue request. |
| Hosted access | Missing session | Return 401 and stop. |
| Hosted access | Unverified or non-allowlisted identity; cross-origin browser write | Return 403 and stop. |
| Input validation | Invalid query fields or CIK | Return 422 or reject during CIK normalization; do not continue research. |
| Annual facts | Financials enabled and supported keyword detected | Fetch/use cached SEC facts and apply the annual-period checks. |
| Annual facts | Financials disabled or no supported keyword | Skip fact retrieval and continue with passage evidence. |
| Evidence availability | At least one passage or fact citation exists | Assemble evidence; optional narrative may run if configured. |
| Evidence availability | No citations | Return a deterministic missing-evidence message and suggest indexing or uploading a source; skip the model call. |
| Model availability | Configured provider succeeds and output passes structural checks | Include draft with evidence. Semantic correctness is not proven by these checks. |
| Model availability | Disabled, unavailable, or rejected | Keep the deterministic summary and evidence; no model retry is implemented. |

### Source preparation path (separate from a query)

- **Upload:** PDF, HTML, or UTF-8 text is parsed inline in the request, split into passages, and written to SQLite/FTS5. PDF extraction can retain page numbers.
- **SEC filing synchronization:** The browser sends the selected accession. The app matches that accession and form in SEC submissions, records the SEC report date and filing date, then schedules in-process `BackgroundTasks`; filing text is extracted and passages are stored in the same corpus. This path is asynchronous relative to the HTTP response, but it is not a durable external queue.

## 5. Failure handling and recovery facts

| Failure or limitation | Actual behavior |
|---|---|
| Missing hosted session | API returns 401; request stops. |
| Denied identity or cross-origin write | API returns 403; access is not bypassed by a fallback. |
| Invalid request | Schema validation returns 422 or CIK normalization rejects it. |
| SEC timeout, connection failure, HTTP 429, or HTTP 5xx | SEC connector retries up to three attempts. Submissions cache for one hour and Company Facts for six hours. |
| Final Company Facts fetch failure | Record missing information and continue with any retrieved passage evidence. |
| SEC filing sync failure | Persisted job is marked failed; the failed download does not create an empty document. User can retry. |
| No indexed evidence | Return the deterministic missing-evidence research outcome; this is a normal result, not an infrastructure failure. |
| Model request error or rejected draft | Keep deterministic summary and evidence. There is no model retry. |
| API process restarts during a filing task | Queued/running tasks are marked failed at startup; user can retry. There is no automatic resume. |

## 6. Security, reliability, and observability facts

- Hosted startup fails closed when required OIDC, HTTPS origin, trusted-host, session-secret, or verified-email allowlist configuration is absent or invalid.
- Hosted sessions use a signed, HttpOnly, Secure, SameSite=Lax cookie with an eight-hour lifetime.
- All allowlisted users share the same corpus. There are no per-user roles, workspace memberships, or durable audit history.
- Docker uses a non-root user, read-only root filesystem, dropped Linux capabilities, `no-new-privileges`, bounded temporary storage, and bounded JSON logs.
- Health endpoints provide liveness and readiness. Readiness checks SQLite, not external SEC/OIDC/model availability.
- Request logs include request ID, method, path, status, and duration. Distributed tracing, application metrics, and centralized error monitoring are not implemented.
- There is no distributed application rate limiter; deployment documentation assigns ingress rate limiting to the hosting layer.

## 7. Important scope limits — do not imply these capabilities

- No vector database, embeddings, semantic retrieval, hybrid retrieval, query decomposition, or reranking.
- No LangChain, LangGraph, MCP, autonomous agent, tool execution, or model routing.
- No external durable job queue or separate worker; filing sync runs in the API process.
- No horizontally scaled multi-replica SQLite architecture or multi-tenant isolation.
- SEC facts are limited to revenue, net income, and operating cash flow from mapped US-GAAP annual USD 10-K/10-K/A periods. Custom tags, quarterly comparisons, profit margin, currency conversion, and dimensional facts are not mapped.
- PDF text extraction does not OCR image-only scans or reliably recover complex visual tables. Uploads are not malware-scanned.
- Generated narrative has schema, citation-ID, and numeric checks only. These checks do not establish semantic accuracy; a human must inspect cited sources.
- The standard synthetic ten-question fixture measures retrieval behavior. The opt-in live set adds seven Target queries plus 13 issuer-anchored Walmart, Costco, and Apple queries, with Apple held out by issuer. These are retrieval diagnostics with source-checked anchors, not human-judged answer-accuracy evidence.
- Annual revenue prefers `us-gaap:Revenues` when that concept is reported, so issuers that separately report net sales and other revenue are represented by total revenue; other mapped revenue concepts remain fallbacks.
- No named cloud provider deployment is proven by the repository.

## 8. Diagram requirements

### Diagram 01 — System Architecture

- **Title:** `01 — System Architecture`
- **Subtitle:** `How the system is designed, connected, and engineered.`
- Show the user/browser, FastAPI application, request/security middleware, core routes, ingestion and research modules, SQLite, SEC EDGAR, OIDC, optional model provider, and implemented operational signals.
- Separate application-owned components from external providers and storage.
- Label connections only with supported relationships such as HTTP/JSON, OIDC, SEC request, optional HTTPS provider call, SQLite, and in-process async filing task.
- Make the one-organization, one-replica, one-worker deployment boundary clear.

### Diagram 02 — End-to-End Execution Flow

- **Title:** `02 — End-to-End Execution Flow`
- **Subtitle:** `A research query, from validated input to a source-linked result.`
- Follow the actual `POST /api/v1/research/query` path from browser input through access/input checks, FTS5 retrieval, conditional annual facts, evidence assembly, optional draft, persistence, and response.
- Keep source preparation as a distinct pre-query path.
- Show no citations as a normal missing-evidence outcome that skips the model.
- Show authentication, input, SEC, model, and interrupted-job outcomes according to the implemented behavior above.
- Distinguish the in-process background filing path and optional provider call in the legend; do not draw the model as required for normal research.

### Shared visual and export requirements

- Minimal, precise, technical, enterprise-style visual language; white background, generous whitespace, clear hierarchy, restrained semantic color, readable typography, consistent borders and connectors.
- Suggested palette: white `#FFFFFF`, slate `#0F172A`, gray `#64748B`, soft blue `#EFF6FF` / blue `#2563EB`, soft teal `#F0FDFA`, soft green `#F0FDF4`, soft amber `#FFFBEB`, soft red `#FEF2F2`, boundary gray `#E2E8F0`.
- Use rounded rectangles for processes, diamonds for decisions, cylinders for SQLite, and directional arrows for verified communication paths. Avoid invented logos or technology icons.
- Keep architecture focused on system organization and execution flow focused on runtime behavior.
- Desired deliverables when rendering is requested: separate editable sources plus SVG and high-resolution PNG exports, approximately 2,400 px or wider, with no clipped labels or overlaps.

## 9. Source files used for verification

Project documentation and implementation inspected for the diagram data include:

- `README.md`, `docs/architecture.md`, and `docs/security.md`
- `.env.example`, `Dockerfile`, and `docker-compose.yml`
- `backend/app/main.py`, `backend/app/auth.py`, `backend/app/connectors/sec.py`
- `backend/app/ingestion/documents.py`, `backend/app/retrieval/engine.py`
- `backend/app/financial/facts.py`, `backend/app/generation.py`
- `backend/app/schemas.py`, `backend/app/storage.py`, and `frontend/app.js`

This brief records implemented behavior and repository-documented deployment boundaries. It does not claim that undocumented technology choices have a particular design rationale or that a cloud deployment has been performed.
