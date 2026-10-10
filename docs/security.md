# Security and deployment boundary

## Hosted profile

The Docker image starts in production mode and fails startup unless OIDC, an HTTPS public URL, allowed hostnames, a 32-character session secret, and an explicit email allowlist are configured. OIDC discovery must use HTTPS. Configure the identity provider callback as `https://YOUR_HOST/auth/callback`. The application accepts only verified email claims in the configured exact-email or exact-domain allowlist.

The browser session uses an authorization-code OIDC flow with PKCE and Starlette's signed, HttpOnly, Secure, SameSite=Lax cookie with an eight-hour lifetime. It stores only the subject, verified email, and display name; access and ID tokens are not retained. The cookie is signed rather than encrypted, so no secrets or private document content belong in it. API routes require a session. Only the OIDC flow, static assets, and minimal liveness/readiness endpoints are public. Production OpenAPI routes are disabled. Set `EVIDENCEGRAPH_ALLOWED_HOSTS` to hostnames only, without a scheme or path.

This is a dedicated, single-organization deployment. Every allowlisted account can access the same data. There is no per-user or per-workspace authorization, role model, invitation flow, or durable audit log. Do not mix organizations or customer data in one deployment. Use one replica: documents, reports, jobs, settings, and SEC cache live in SQLite on the mounted persistent volume.

Terminate TLS at the cloud ingress, route to container port 8000, and mount a persistent volume at `/app/data`. Configure the cloud volume's encryption-at-rest and backup policies. Keep at least one tested restore point. Apply request and upload rate limits at the ingress; app-level distributed rate limiting is not configured. Use platform secrets for OIDC/session settings rather than image build arguments or checked-in files.

The container runs as a non-root user, uses a read-only root filesystem with a bounded temporary filesystem, drops Linux capabilities, limits retained JSON logs, and exposes liveness and readiness probes. Readiness checks the SQLite store only; SEC, identity-provider, and optional model-provider availability are separate dependencies. Request logs include request ID, method, path, status, and duration, never the request body or authorization header. Unhandled exceptions return a generic response and are logged server-side.

## Local profile

The direct Python run command defaults to unauthenticated local development. It binds to loopback in the documented command. Do not expose that profile to a shared network. The local SQLite file, uploaded source text, settings, and cached SEC responses are not encrypted by the application; rely on the local OS account and disk protections.

## Input and source handling

Uploads are bounded to 15 MiB and support PDF, HTML, and UTF-8 text. PDF signature and file extension are checked, encrypted PDFs and oversized files/pages are rejected, and the parser does not extract embedded files. HTML scripts and style blocks are discarded. Browser output escapes extracted source passages. Image-only PDFs are rejected as unreadable; no OCR or malware scanning is provided.

SEC requests use fixed `sec.gov` and `data.sec.gov` endpoints. Filing accession and document path segments are validated before downloads, and failed downloads never create empty indexed documents. SEC contact email is stored in the application database and sent in the public-data User-Agent.

Optional answer generation is disabled unless an operator sets the model base URL, model name, and API key together. Production provider URLs must use HTTPS. When enabled, the provider receives the question, up to eight retrieved excerpts, and relevant verified facts. Do not enable it for sensitive uploads unless the provider is approved to process them. Redirects are rejected, credentials are sent only in the authorization header, and request bodies and provider responses are not logged. Citation and numeric checks do not prove that generated prose is semantically supported; users must inspect cited source material. Provider cost and availability are external dependencies.

Write requests from a browser origin other than the application origin are rejected. Production sessions use SameSite=Lax cookies. Avoid adding cross-origin API access without an explicit CSRF and CORS design.

## Before scaling or handling multiple tenants

Use PostgreSQL with migrations, tenant/workspace IDs and authorization filters on every query and retrieval index; move ingestion to a durable external queue with retry and idempotency; add centralized rate limits, audit trails, retention/deletion controls, malware scanning, and security/integration testing. Do not add application replicas while SQLite remains the data store.
