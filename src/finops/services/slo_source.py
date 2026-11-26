"""Live error budget reading from Prometheus (instant query, stdlib only)."""

from __future__ import annotations

import asyncio
import json
import math
import urllib.error
import urllib.parse
import urllib.request

from finops.config import SloConfig


class SloSourceError(Exception):
    """The live source did not give a usable reading."""


def status_from_remaining(remaining: float) -> str:
    """Map the remaining budget ratio to the status names the error_budgets table uses."""
    if remaining <= 0:
        return "breached"
    if remaining <= 0.2:
        return "critical"
    if remaining <= 0.5:
        return "warning"
    return "healthy"


def _query(base_url: str, promql: str, timeout: float) -> float:
    if urllib.parse.urlparse(base_url).scheme not in ("http", "https"):
        raise SloSourceError("slo.prometheus_url must start with http:// or https://")
    url = f"{base_url.rstrip('/')}/api/v1/query?{urllib.parse.urlencode({'query': promql})}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (scheme checked above)
            body = json.load(resp)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise SloSourceError(f"query failed: {type(exc).__name__}: {exc}"[:200]) from exc
    if body.get("status") != "success":
        raise SloSourceError(f"Prometheus returned status {body.get('status')!r}")
    result = body.get("data", {}).get("result", [])
    if len(result) != 1:
        raise SloSourceError(f"query returned {len(result)} series; it must return exactly 1")
    try:
        value = float(result[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SloSourceError("sample has no numeric value") from exc
    if math.isnan(value):
        raise SloSourceError("sample value is NaN")
    return value


async def remaining_budget_status(slo: SloConfig, service_name: str) -> tuple[str, float]:
    """Return (status, remaining ratio) for a service. Raises SloSourceError on any failure."""
    promql = slo.services[service_name]
    remaining = await asyncio.to_thread(_query, slo.prometheus_url, promql, slo.timeout_seconds)
    return status_from_remaining(remaining), remaining
