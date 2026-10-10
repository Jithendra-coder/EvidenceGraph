from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

import requests
from fastapi import HTTPException

from ..storage import connect, get_contact

MAX_SEC_DOCUMENT = 25 * 1024 * 1024
SEC_BASE = "https://data.sec.gov"
ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"
_sec_lock = threading.Lock()
_last_sec_request = 0.0


def sec_headers() -> dict[str, str]:
    contact = get_contact()
    if not contact:
        raise HTTPException(
            503, "Add a contact email in Settings to enable SEC access."
        )
    return {
        "User-Agent": f"EvidenceGraph/1.0 (contact: {contact})",
        "Accept-Encoding": "gzip, deflate",
    }


def sec_get(url: str, *, stream: bool = False) -> requests.Response:
    global _last_sec_request
    headers = sec_headers()
    for attempt in range(3):
        with _sec_lock:
            delay = 0.12 - (time.monotonic() - _last_sec_request)
            if delay > 0:
                time.sleep(delay)
            _last_sec_request = time.monotonic()
        try:
            response = requests.get(
                url, headers=headers, timeout=(5, 30), stream=stream
            )
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt < 2:
                    response.close()
                    time.sleep(0.5 * (2**attempt))
                    continue
            response.raise_for_status()
            return response
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt == 2:
                raise HTTPException(
                    502, "SEC could not be reached after three attempts."
                ) from exc
            time.sleep(0.5 * (2**attempt))
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 502
            raise HTTPException(
                502, f"SEC returned HTTP {status}; no document was indexed."
            ) from exc
    raise HTTPException(502, "SEC request failed; no document was indexed.")


def cached_json(key: str, url: str, ttl: int) -> dict[str, Any]:
    with connect() as db:
        row = db.execute(
            "SELECT value, fetched FROM cache WHERE key=?", (key,)
        ).fetchone()
        if row and time.time() - row["fetched"] < ttl:
            return json.loads(row["value"])
    response = sec_get(url)
    try:
        if len(response.content) > MAX_SEC_DOCUMENT:
            raise HTTPException(502, "SEC response exceeded the configured size limit.")
        data = response.json()
    except ValueError as exc:
        raise HTTPException(502, "SEC returned invalid JSON.") from exc
    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO cache(key,value,fetched) VALUES(?,?,?)",
            (key, json.dumps(data, separators=(",", ":")), time.time()),
        )
    return data


def normalized_cik(value: str) -> str:
    match = re.fullmatch(r"(?:CIK\s*)?([0-9]{1,10})", value.strip(), re.IGNORECASE)
    if not match:
        raise HTTPException(422, "CIK must contain between 1 and 10 digits.")
    return match.group(1).zfill(10)


def filing_value(recent: dict[str, Any], column: str, index: int) -> Any:
    values = recent.get(column, [])
    return values[index] if index < len(values) else None
