# EvidenceGraph portfolio diagrams

These diagrams describe the implementation in this repository as inspected on 2026-10-10. They are designed for a portfolio page, GitHub, and technical interviews. The SVG files are editable vector artwork; `render_diagrams.py` is the diagram-as-code source that regenerates both SVG and PNG exports.

## Files

| Diagram | SVG | PNG |
|---|---|---|
| System architecture | [system-architecture.svg](system-architecture.svg) | [system-architecture.png](system-architecture.png) |
| End-to-end execution flow | [execution-flow.svg](execution-flow.svg) | [execution-flow.png](execution-flow.png) |

Source: [render_diagrams.py](render_diagrams.py)

Regenerate the exports from the repository root with:

```powershell
py -3.11 -m pip install -r requirements-dev.txt
py -3.11 docs/portfolio-diagrams/render_diagrams.py
```

The renderer uses Matplotlib and Pillow from `requirements-dev.txt`; CI regenerates and validates the SVG and PNG exports. These are development-only dependencies.

## 01 — System architecture

### What it shows

The browser interface is static HTML, CSS, and JavaScript served by the FastAPI application. The same application serves the introduction and research workspace and exposes JSON routes under `/api/v1`. In the hosted profile, request middleware applies trusted-host checks, a signed OIDC session, same-origin checks for browser writes, request IDs, and safe response headers. OIDC is an external identity provider; an account must have a verified email that matches the configured allowlist.

Core routes call the ingestion and research modules inside the same Python process. Upload parsing runs in the request. SEC filing sync records a job and schedules FastAPI `BackgroundTasks`; it is not sent to an external queue or worker service. The ingestion code extracts supported text, splits passages, derives stable passage IDs from content, and stores documents and FTS5 rows in SQLite.

Research reads indexed passages through SQLite FTS5 BM25. When the request asks for one of the supported annual financial metrics, the facts module loads SEC Company Facts through the shared SEC connector, applies period and unit checks, and builds source references. The optional OpenAI-compatible provider can draft cited narrative only when configured. It is off by default. The provider receives the question, up to eight retrieved excerpts, and relevant facts; draft output passes schema, citation-ID, and numeric checks before display.

SQLite is the only durable service dependency. It contains source documents, passages and the FTS5 index, SEC response cache, job states, settings, saved research results, and evaluation runs. The hosted container is single-organization, single-replica, and configured for one Uvicorn worker with a persistent volume.

### Communication paths

1. Browser to FastAPI: same-origin HTTP requests and JSON responses; uploaded files use multipart form data.
2. Hosted identity: browser-based OIDC authorization-code flow with PKCE; the callback validates verified identity and allowlist membership. The signed, HttpOnly, Secure, SameSite=Lax session cookie holds identity claims, not provider tokens.
3. SEC: the connector uses fixed `sec.gov` and `data.sec.gov` URLs and a contact email in the SEC User-Agent. Requests have timeouts, per-process pacing, SQLite JSON caching, and up to three attempts for timeouts, connection errors, HTTP 429, and HTTP 5xx. Company submissions are cached for one hour and Company Facts for six hours.
4. Ingestion: uploads are parsed inline; SEC filing sync runs as an in-process background task. Both write document and passage rows to SQLite. FTS5 indexes passage text.
5. Research: the retriever reads up to eight matching passages from FTS5. Facts are fetched from Company Facts when relevant and enabled. The assembled result is saved to SQLite before it is returned to the browser.
6. Optional narrative: when enabled, one HTTPS request sends the question, up to eight passages, and relevant facts to the configured OpenAI-compatible endpoint. This can send source text outside the deployment. The generated prose is not semantically verified.

### Engineering choices and trade-offs

- The current browser application has no frontend build step. The repository documents that the default research path is deterministic and requires neither a paid model nor a vector database.
- SQLite provides local durable storage and FTS5 lexical retrieval in one application dependency. The trade-off is a single shared workspace and one replica; the current design is not horizontally scalable.
- Filing ingestion is asynchronous relative to the HTTP response, but the task still runs in the API process. A process restart marks queued/running jobs failed; a user can retry them. Work is not automatically resumed.
- The retriever is deterministic lexical BM25. It does not use embeddings, semantic retrieval, hybrid search, query decomposition, or reranking.
- The optional LLM is a drafting step, not an agent. The application does not contain LangChain, LangGraph, MCP, tool execution, or model routing.
- The repository documents the implementation and operational trade-offs, but does not record a rationale for every original technology choice. This guide avoids attributing undocumented motivations to the authors.

### Security, reliability, and observability

- Production startup fails closed when OIDC, HTTPS origin, trusted hosts, session secret, or email allowlist configuration is missing or invalid.
- The hosted profile uses verified OIDC identities and a shared single-organization corpus. It has no per-user roles, workspace memberships, or durable audit history.
- The Docker image runs as non-root with a read-only root filesystem, bounded temporary storage, dropped Linux capabilities, and no-new-privileges. Compose includes persistent storage and a bounded JSON log policy.
- The app returns liveness and readiness probes. Readiness checks SQLite; it does not assert that SEC, OIDC, or the optional model provider is reachable.
- Request logs contain request ID, method, path, status, and duration. The implementation does not provide distributed tracing, application metrics, or centralized error monitoring.
- There is no application-level distributed rate limiter. The deployment documentation calls for rate limits at the cloud ingress.
- The versioned synthetic fixture is a ten-question regression check. Opt-in live SEC tests add seven Target queries plus 13 source-anchored questions over Walmart, Costco, and an issuer-held-out Apple filing. They compare BM25 with simple token overlap and check selected annual XBRL facts, but do not provide human-judged semantic relevance or answer accuracy.

### Important limits

- One shared SQLite workspace per hosted deployment; one replica and one Uvicorn worker only.
- Annual SEC Company Facts are limited to USD 10-K and 10-K/A periods for revenue, net income, and operating cash flow. Custom tags, quarterly comparisons, profit margin, currency conversion, and dimensional facts are not mapped.
- Annual growth is calculated with `Decimal`; it is unavailable if periods are not adjacent, the prior value is non-positive, units differ, or annual durations differ by more than seven days.
- Search is lexical FTS5 BM25, not semantic or hybrid retrieval.
- PDF extraction preserves page numbers but does not OCR image-only scans or recover complex visual tables. Uploads are not malware-scanned.
- Generated narrative receives structural citation and numeric checks only. A person must verify claims against the cited filings and reported facts.
- A cloud-container deployment profile is documented, but this repository does not name or prove a deployment to a particular cloud provider.

## 02 — End-to-end execution flow

### Representative request

The flow follows `POST /api/v1/research/query`, using a question about one or more selected issuers. It assumes source documents may already have been indexed; the small source-preparation lane shows how they arrive in the searchable corpus.

1. **Ask.** The browser submits a question, selected CIKs, and the `includeFinancials` choice.
2. **Gate.** In hosted mode, middleware requires a session and rejects cross-origin browser writes. Pydantic validates the request fields; CIK values are normalized. An unauthenticated API request returns 401, a disallowed identity or cross-origin write returns 403, and invalid input returns 422. These failures stop the request.
3. **Retrieve.** The retriever removes a small stop-word set, keeps at most sixteen unique query terms, joins them with OR, optionally filters by selected CIK, and reads up to eight results ordered by FTS5 BM25 rank.
4. **Decide whether to fetch facts.** The request must include financials and the question must mention a supported metric. The current keyword mapping recognizes cash flow, revenue/sales, and net income/profit; profit margin is explicitly not inferred. Otherwise, the facts path is skipped.
5. **Load and check annual facts.** On an SEC cache miss, Company Facts is fetched through the SEC connector. The normalizer uses mapped US-GAAP tags, USD units, 10-K/10-K/A annual periods, and 300–400 day durations. Annual growth is emitted only when the prior fiscal year is adjacent, the prior value is positive, units match, and durations differ by at most seven days. SEC or unsupported-data errors become `missingInformation`; retrieved text evidence can still be returned.
6. **Assemble evidence.** Passage citations and SEC fact citations are deduplicated by citation ID. Findings, metric periods, missing information, caveats, freshness, and retrieval method are included. If there are no citations, the app returns a deterministic message asking for an indexed filing or uploaded source; it does not call the model.
7. **Optionally draft.** If citations exist and all three model settings are configured, the backend makes one provider request. Pydantic validates the JSON answer. Citation IDs must refer to supplied sources and numeric claims must match cited excerpts or verified facts. If generation is disabled, unavailable, or rejected, the deterministic summary and source evidence remain the result. These checks do not prove semantic accuracy.
8. **Persist and return.** The research question and assembled result are saved in SQLite. JSON returns to the browser for the evidence view. A Markdown report is generated only if the user later chooses export.

### Failure outcomes

| Condition | Implemented outcome |
|---|---|
| Missing hosted session | API request returns 401; processing stops. |
| OIDC identity is unverified/not allowlisted, or a browser write is cross-origin | Request is rejected with 403; no fallback bypasses the check. |
| Invalid query or CIK | Request validation/normalization returns 422. |
| SEC timeout, connection failure, 429, or 5xx | SEC connector retries up to three attempts. A final facts-fetch error is recorded as missing information; a filing-sync error marks its job failed and does not create an empty document. |
| No indexed evidence | Normal research outcome: return the missing-evidence message and suggest adding a filing or upload. |
| Model provider error or structurally rejected output | Generation status is unavailable/rejected; keep the deterministic summary and source evidence. No model retry is implemented. |
| API restarts during a filing job | Startup marks queued/running jobs failed; the user can retry. Jobs do not auto-resume. |

## Interview notes

### 30-second explanation

EvidenceGraph is a source-grounded financial research workspace. A researcher can index SEC filings or upload supported documents, search passages with SQLite FTS5 BM25, and compare three annual SEC XBRL metrics with the reported periods and citations visible. Results and research sessions are stored in SQLite and can be exported as Markdown. The default answer path is deterministic; an optional model can draft cited narrative, but the app checks citation IDs and numbers rather than semantic correctness. The hosted profile uses OIDC and is deliberately limited to one organization, one application replica, and one SQLite workspace.

### 2-minute explanation

The browser is a static HTML/CSS/JavaScript application served by FastAPI. In hosted mode, the application validates the host, requires a signed OIDC session, checks the verified identity against an allowlist, and rejects cross-origin browser writes. Query schemas and CIKs are validated before research runs.

Document ingestion has two paths. Upload parsing happens in the request. SEC filing sync stores a job and schedules FastAPI BackgroundTasks in the API process. Extracted passages retain source locators and stable IDs, then enter SQLite and its FTS5 index. There is no external queue or worker.

For a query, the retriever builds an OR expression from normalized terms and returns at most eight lexical BM25 passages, optionally filtered by issuer. If the request and keyword mapping call for revenue, net income, or operating cash flow, the facts module loads cached SEC Company Facts, filters annual USD 10-K/10-K/A periods, and calculates growth only after adjacency, unit, value, and duration checks. The result includes source IDs, periods, citations, caveats, and any missing information.

The optional OpenAI-compatible call is disabled by default. If enabled, it receives the question, up to eight excerpts, and relevant facts. A Pydantic response schema plus citation-ID and numeric checks reject structurally unsupported drafts. Those checks cannot establish that prose is semantically correct, so source review remains necessary. Whether a draft is available or not, the app stores the assembled research result in SQLite and returns it to the browser; Markdown export is a separate user action.

Operationally, the production container uses one Uvicorn worker and one replica with persistent SQLite. The project has request-ID logs and liveness/readiness probes, but not distributed tracing, centralized metrics, a durable worker queue, or distributed rate limiting. Those boundaries matter before increasing scale or enabling multiple organizations.

### Five likely interview questions

1. **Why use FTS5 instead of a vector database?**<br>
   The implemented retriever is lexical BM25 over SQLite FTS5. The repository documents no vector database or embedding pipeline. The trade-off is a simpler deterministic search path that may miss semantically related wording; the project does not claim semantic recall.

2. **How do you prevent an LLM from inventing financial numbers or citations?**<br>
   The draft must use supplied citation IDs, and numeric values must appear in cited excerpts or verified facts. The response is parsed through a strict Pydantic schema. These checks are structural and do not prove semantic support, so every claim still needs source review.

3. **What happens when SEC is unavailable?**<br>
   The connector retries transient timeouts, connection errors, 429s, and 5xx responses up to three attempts. A facts-fetch error is added to `missingInformation` while the query can continue with retrieved passages. A filing ingestion error marks its persisted job failed; failed downloads do not create empty indexed documents.

4. **Can the hosted app be scaled horizontally or serve multiple organizations?**<br>
   No. All allowlisted users share one SQLite corpus, and ingestion jobs execute in one API process. The documented boundary is one organization, one replica, and one Uvicorn worker. The architecture guide calls for PostgreSQL, tenant-scoped authorization, and a durable queue before scaling.

5. **What does the evaluation prove?**<br>
   The versioned synthetic ten-question fixture measures lexical retrieval metrics such as Recall@5, MRR, nDCG@5, latency, and misses. The opt-in live SEC evaluations add a small, source-anchored retrieval set and selected revenue fact checks. They do not evaluate answer truth or establish general financial research quality.

## Validation summary

Source reviewed: `README.md`, `docs/architecture.md`, `docs/security.md`, `.env.example`, `Dockerfile`, `docker-compose.yml`, `backend/app/main.py`, `auth.py`, `connectors/sec.py`, `ingestion/documents.py`, `retrieval/engine.py`, `financial/facts.py`, `generation.py`, `schemas.py`, `storage.py`, and `frontend/app.js`.

The SVG and PNG exports are generated from the same `render_diagrams.py` source. The renderer parses each SVG as XML, checks that editable text is present, and verifies each PNG opens at 2,400 pixels or wider. The exports are 3,080 × 2,032 and 3,360 × 1,848 pixels. Both diagrams were visually inspected after rendering. The current readiness pass also ran the full offline suite (31 passed, two opt-in live tests skipped), then ran both live SEC tests (two passed) against temporary SQLite stores. The live tests cover Target plus the Walmart/Costco development and Apple issuer-holdout set; they do not judge generated-answer correctness.
