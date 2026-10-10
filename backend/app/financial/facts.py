from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException

from ..connectors.sec import ARCHIVE_BASE, SEC_BASE, cached_json

FACT_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
}


def load_fact_series(cik: str, tag_names: tuple[str, ...]) -> dict[str, Any]:
    data = cached_json(
        f"facts:{cik}", f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik}.json", 6 * 3600
    )
    facts = data.get("facts", {}).get("us-gaap", {})
    by_period: dict[tuple[str, str], dict[str, Any]] = {}
    # Prefer total revenue per period without letting its older history hide newer facts.
    for priority, tag in enumerate(tag_names):
        item = facts.get(tag)
        if not item:
            continue
        for point in item.get("units", {}).get("USD", []):
            if point.get("form") not in {"10-K", "10-K/A"} or point.get("fp") != "FY":
                continue
            try:
                start = datetime.strptime(point["start"], "%Y-%m-%d").date()
                end = datetime.strptime(point["end"], "%Y-%m-%d").date()
                duration = (end - start).days
                fiscal_year = int(point["fy"])
                value = Decimal(str(point["val"]))
            except (KeyError, TypeError, ValueError, InvalidOperation):
                continue
            if not 300 <= duration <= 400:
                continue
            candidate = {
                "fiscalYear": fiscal_year,
                "start": str(start),
                "end": str(end),
                "durationDays": duration,
                "value": str(value),
                "unit": "USD",
                "filed": point.get("filed"),
                "form": point.get("form"),
                "accession": point.get("accn"),
                "concept": f"us-gaap:{tag}",
            }
            key = (str(start), str(end))
            period = by_period.get(key)
            if period is None:
                period = {
                    "fiscalYear": fiscal_year,
                    "yearFiled": point.get("filed"),
                    "candidate": candidate,
                    "priority": priority,
                }
                by_period[key] = period
                continue
            if (
                period["yearFiled"] is None
                or (point.get("filed") or "") < period["yearFiled"]
            ):
                period["fiscalYear"] = fiscal_year
                period["yearFiled"] = point.get("filed") or ""
            current = period["candidate"]
            same_concept = priority == period["priority"]
            newer_fact = (candidate["filed"] or "") > (current["filed"] or "")
            closer_duration = (candidate["filed"] or "") == (
                current["filed"] or ""
            ) and abs(duration - 365) < abs(current["durationDays"] - 365)
            if priority < period["priority"] or (
                same_concept and (newer_fact or closer_duration)
            ):
                period["candidate"] = candidate
                period["priority"] = priority
    by_year: dict[int, dict[str, Any]] = {}
    for period in by_period.values():
        candidate = period["candidate"]
        fiscal_year = period["fiscalYear"]
        candidate["fiscalYear"] = fiscal_year
        current = by_year.get(fiscal_year)
        if (
            current is None
            or (candidate["filed"] or "") > (current["filed"] or "")
            or (
                (candidate["filed"] or "") == (current["filed"] or "")
                and abs(candidate["durationDays"] - 365)
                < abs(current["durationDays"] - 365)
            )
        ):
            by_year[fiscal_year] = candidate
    periods = sorted(by_year.values(), key=lambda p: (p["end"], p["filed"] or ""))
    latest_concept = periods[-1]["concept"] if periods else None
    return {
        "cik": cik,
        "companyName": data.get("entityName", "Unknown company"),
        "concept": latest_concept,
        "periods": periods,
    }


def get_fact(cik: str, metric: str) -> dict[str, Any]:
    if metric not in FACT_CONCEPTS:
        raise HTTPException(422, "Unsupported financial metric.")
    return load_fact_series(cik, FACT_CONCEPTS[metric])


def annual_growth(current: dict[str, Any], previous: dict[str, Any]) -> str | None:
    base = Decimal(previous["value"])
    if (
        current["fiscalYear"] - previous["fiscalYear"] != 1
        or base <= 0
        or current["unit"] != previous["unit"]
        or abs(current["durationDays"] - previous["durationDays"]) > 7
    ):
        return None
    return str((Decimal(current["value"]) - base) / base * 100)


def citation_for_fact(cik: str, point: dict[str, Any], title: str) -> dict[str, Any]:
    accession = point.get("accession") or ""
    source = (
        f"{ARCHIVE_BASE}/{int(cik)}/{accession.replace('-', '')}/"
        if accession
        else f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik}.json"
    )
    return {
        "id": f"{cik}:{point['concept']}:{point['fiscalYear']}",
        "title": title,
        "sourceUrl": source,
        "sourceType": "SEC XBRL",
        "form": point.get("form") or "10-K",
        "fiscalYear": point["fiscalYear"],
        "locator": f"{point['concept']} · FY{point['fiscalYear']} · filed {point.get('filed') or 'unknown'}",
        "accession": accession or None,
        "value": point["value"],
        "unit": point["unit"],
        "periodStart": point["start"],
        "periodEnd": point["end"],
    }
