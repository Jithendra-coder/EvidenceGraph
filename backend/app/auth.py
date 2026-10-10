from __future__ import annotations

import os
from urllib.parse import urljoin, urlsplit

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

ENVIRONMENT = os.getenv("EVIDENCEGRAPH_ENV", "development").lower()
AUTH_MODE = os.getenv(
    "EVIDENCEGRAPH_AUTH_MODE", "oidc" if ENVIRONMENT == "production" else "local"
).lower()
SESSION_SECRET = os.getenv("EVIDENCEGRAPH_SESSION_SECRET", "local-development-only")
SESSION_MAX_AGE = 8 * 60 * 60
PUBLIC_BASE_URL = (
    os.getenv("EVIDENCEGRAPH_PUBLIC_BASE_URL", "http://127.0.0.1:8001")
    .rstrip("/")
    .lower()
)

oauth = OAuth()
if all(
    os.getenv(name)
    for name in (
        "EVIDENCEGRAPH_OIDC_DISCOVERY_URL",
        "EVIDENCEGRAPH_OIDC_CLIENT_ID",
        "EVIDENCEGRAPH_OIDC_CLIENT_SECRET",
    )
):
    oauth.register(
        name="evidencegraph",
        server_metadata_url=os.environ["EVIDENCEGRAPH_OIDC_DISCOVERY_URL"],
        client_id=os.environ["EVIDENCEGRAPH_OIDC_CLIENT_ID"],
        client_secret=os.environ["EVIDENCEGRAPH_OIDC_CLIENT_SECRET"],
        client_kwargs={
            "scope": "openid email profile",
            "code_challenge_method": "S256",
        },
    )


def production_config_errors() -> list[str]:
    if ENVIRONMENT != "production":
        return []
    errors = []
    if AUTH_MODE != "oidc":
        errors.append("EVIDENCEGRAPH_AUTH_MODE must be oidc in production.")
    if (
        len(SESSION_SECRET) < 32
        or SESSION_SECRET == "local-development-only"
        or "replace-with" in SESSION_SECRET.casefold()
    ):
        errors.append(
            "Set a random EVIDENCEGRAPH_SESSION_SECRET of at least 32 characters."
        )
    if not oauth.create_client("evidencegraph") or any(
        "replace-with" in os.getenv(name, "").casefold()
        for name in (
            "EVIDENCEGRAPH_OIDC_DISCOVERY_URL",
            "EVIDENCEGRAPH_OIDC_CLIENT_ID",
            "EVIDENCEGRAPH_OIDC_CLIENT_SECRET",
        )
    ):
        errors.append("Set the OIDC discovery URL, client ID, and client secret.")
    discovery_url = os.getenv("EVIDENCEGRAPH_OIDC_DISCOVERY_URL", "")
    if discovery_url and not discovery_url.startswith("https://"):
        errors.append("The OIDC discovery URL must use HTTPS in production.")
    public_url = urlsplit(PUBLIC_BASE_URL)
    try:
        public_port = public_url.port
    except ValueError:
        public_port = -1
    if (
        public_url.scheme != "https"
        or not public_url.netloc
        or public_url.username
        or public_url.password
        or public_port is not None
        or public_url.path not in {"", "/"}
        or public_url.query
        or public_url.fragment
    ):
        errors.append("EVIDENCEGRAPH_PUBLIC_BASE_URL must use HTTPS in production.")
    hosts = [host.casefold() for host in allowed_hosts()]
    if not hosts or any("*" in host or "/" in host or "://" in host for host in hosts):
        errors.append("Set EVIDENCEGRAPH_ALLOWED_HOSTS to the public hostname(s).")
    elif public_url.hostname and public_url.hostname.casefold() not in hosts:
        errors.append(
            "The public URL hostname must appear in EVIDENCEGRAPH_ALLOWED_HOSTS."
        )
    if not (
        os.getenv("EVIDENCEGRAPH_ALLOWED_EMAILS", "").strip()
        or os.getenv("EVIDENCEGRAPH_ALLOWED_EMAIL_DOMAINS", "").strip()
    ):
        errors.append("Set an explicit email or email-domain allowlist for OIDC users.")
    return errors


def allowed_hosts() -> list[str]:
    configured = os.getenv("EVIDENCEGRAPH_ALLOWED_HOSTS", "")
    if configured.strip():
        return [item.strip().lower() for item in configured.split(",") if item.strip()]
    return ["localhost", "127.0.0.1", "testserver"]


def allowed_identity(email: str, verified: bool) -> bool:
    if not verified:
        return False
    normalized = email.strip().casefold()
    allowed_emails = {
        item.strip().casefold()
        for item in os.getenv("EVIDENCEGRAPH_ALLOWED_EMAILS", "").split(",")
        if item.strip()
    }
    allowed_domains = {
        item.strip().lstrip("@").casefold()
        for item in os.getenv("EVIDENCEGRAPH_ALLOWED_EMAIL_DOMAINS", "").split(",")
        if item.strip()
    }
    domain = normalized.rpartition("@")[2]
    return normalized in allowed_emails or domain in allowed_domains


def identity_from_request(request: Request) -> dict[str, str] | None:
    if AUTH_MODE == "local":
        return {"sub": "local", "email": "local@localhost", "name": "Local researcher"}
    identity = request.session.get("identity")
    return identity if isinstance(identity, dict) else None


async def login(request: Request) -> RedirectResponse:
    client = oauth.create_client("evidencegraph")
    if not client:
        raise HTTPException(503, "OIDC sign-in is not configured.")
    callback = urljoin(PUBLIC_BASE_URL + "/", "auth/callback")
    return await client.authorize_redirect(request, callback)


async def callback(request: Request) -> RedirectResponse:
    client = oauth.create_client("evidencegraph")
    if not client:
        raise HTTPException(503, "OIDC sign-in is not configured.")
    try:
        token = await client.authorize_access_token(request)
        user = token.get("userinfo", {})
        subject = user.get("sub")
        email = user.get("email", "")
        if (
            not isinstance(subject, str)
            or not subject
            or len(subject) > 255
            or not isinstance(email, str)
            or len(email) > 254
            or "@" not in email
            or not allowed_identity(email, user.get("email_verified") is True)
        ):
            raise HTTPException(
                403, "This verified account is not allowed to use EvidenceGraph."
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            401,
            "OIDC sign-in failed. Check the identity-provider configuration and try again.",
        ) from exc
    request.session.clear()
    request.session["identity"] = {
        "sub": subject,
        "email": email.strip().casefold(),
        "name": str(user.get("name") or email)[:160],
    }
    return RedirectResponse("/app", status_code=303)


def logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"signedOut": True}


def signed_out() -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Signed out</title>'
        '<main><h1>You are signed out</h1><a href="/auth/login">Sign in again</a></main></html>'
    )
