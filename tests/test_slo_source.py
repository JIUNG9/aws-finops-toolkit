"""Live error budget from Prometheus: the reader and its use in the safety gate."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from finops.config import SloConfig
from finops.services.slo_source import SloSourceError, remaining_budget_status, status_from_remaining

from tests.test_safety_gate import accept, add_finding, add_service
from tests.test_safety_gate import env as _env

env = _env  # reuse the fixture from the safety gate tests


def serve(payload, code=200):
    """Start a stub Prometheus that answers every query with `payload`; returns (server, url, queries)."""
    queries: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            queries.append(self.path)
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}", queries


def vector(*values):
    return {"status": "success", "data": {"resultType": "vector",
            "result": [{"metric": {}, "value": [1700000000, str(v)]} for v in values]}}


@pytest.fixture
def prom():
    servers = []

    def start(payload, code=200):
        server, url, queries = serve(payload, code)
        servers.append(server)
        return url, queries

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def slo_for(url, service="checkout"):
    return SloConfig(prometheus_url=url, services={service: 'slo_budget_remaining{service="checkout"}'})


@pytest.mark.parametrize("remaining,expected", [
    (1.0, "healthy"), (0.51, "healthy"), (0.5, "warning"), (0.21, "warning"),
    (0.2, "critical"), (0.01, "critical"), (0.0, "breached"), (-0.3, "breached"),
])
def test_status_thresholds_match_error_budget_events(remaining, expected):
    assert status_from_remaining(remaining) == expected


@pytest.mark.asyncio
async def test_reads_the_configured_query(prom):
    url, queries = prom(vector(0.35))
    status, remaining = await remaining_budget_status(slo_for(url), "checkout")
    assert (status, remaining) == ("warning", 0.35)
    assert "slo_budget_remaining" in queries[0] and queries[0].startswith("/api/v1/query?query=")


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,code,fragment", [
    (vector(), 200, "0 series"),
    (vector(0.4, 0.9), 200, "2 series"),
    (vector("NaN"), 200, "NaN"),
    ({"status": "error", "error": "bad query"}, 200, "status 'error'"),
    ({}, 500, "HTTPError"),
])
async def test_unusable_answers_raise(prom, payload, code, fragment):
    url, _ = prom(payload, code)
    with pytest.raises(SloSourceError, match=fragment):
        await remaining_budget_status(slo_for(url), "checkout")


@pytest.mark.asyncio
async def test_unreachable_prometheus_raises():
    with pytest.raises(SloSourceError, match="query failed"):
        await remaining_budget_status(slo_for("http://127.0.0.1:9"), "checkout")


@pytest.mark.asyncio
async def test_non_http_scheme_is_refused():
    with pytest.raises(SloSourceError, match="http"):
        await remaining_budget_status(slo_for("file:///etc/passwd"), "checkout")


@pytest.mark.asyncio
async def test_live_breach_blocks_even_when_table_says_healthy(env, prom):
    from finops.services.safety_service import analyze_safety

    _, db = env
    await add_service(db, "checkout", "nat-1", "healthy")
    await add_finding(db, "f1", "nat-1")
    url, _ = prom(vector(0))
    report = await analyze_safety("f1", db, slo=slo_for(url))
    step = next(v for v in report.verdicts if v.step == "error_budget_gate")
    assert step.status == "unsafe"
    assert report.overall == "unsafe"
    assert step.details["sources"]["checkout"].startswith("prometheus")


@pytest.mark.asyncio
async def test_live_healthy_overrides_stale_table_breach(env, prom):
    from finops.services.safety_service import analyze_safety

    _, db = env
    await add_service(db, "checkout", "nat-1", "breached")
    await add_finding(db, "f1", "nat-1")
    url, _ = prom(vector(0.9))
    report = await analyze_safety("f1", db, slo=slo_for(url))
    assert next(v for v in report.verdicts if v.step == "error_budget_gate").status == "safe"


@pytest.mark.asyncio
async def test_failed_live_read_is_caution_not_safe(env):
    from finops.services.safety_service import analyze_safety

    _, db = env
    await add_service(db, "checkout", "nat-1", "healthy")
    await add_finding(db, "f1", "nat-1")
    report = await analyze_safety("f1", db, slo=slo_for("http://127.0.0.1:9"))
    step = next(v for v in report.verdicts if v.step == "error_budget_gate")
    assert step.status == "caution"
    assert "checkout" in step.details["live_errors"]
    assert "live budget read failed" in step.summary


@pytest.mark.asyncio
async def test_service_without_a_query_keeps_using_the_table(env, prom):
    from finops.services.safety_service import analyze_safety

    _, db = env
    await add_service(db, "billing", "nat-1", "warning")
    await add_finding(db, "f1", "nat-1")
    url, queries = prom(vector(0))
    report = await analyze_safety("f1", db, slo=slo_for(url))  # query exists only for "checkout"
    step = next(v for v in report.verdicts if v.step == "error_budget_gate")
    assert step.status == "caution"
    assert queries == []
    assert step.details["sources"] == {"billing": "database"}


@pytest.mark.asyncio
async def test_accept_route_uses_the_configured_live_source(env, prom):
    app, db = env
    await add_service(db, "checkout", "nat-1", "healthy")
    await add_finding(db, "f1", "nat-1")
    url, _ = prom(vector(0))
    app.state.config.slo = slo_for(url)
    r = await accept(app, "f1")
    assert r.status_code == 409
    assert (await db.fetchone("SELECT status FROM findings WHERE id = 'f1'"))["status"] == "open"


def test_load_config_parses_slo_section(tmp_path):
    from finops.config import load_config

    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "slo:\n  prometheus_url: http://prometheus.monitoring.svc:9090\n  timeout_seconds: 2\n"
        "  services:\n    checkout: 'budget_remaining{service=\"checkout\"}'\n"
    )
    slo = load_config(cfg).slo
    assert slo.prometheus_url == "http://prometheus.monitoring.svc:9090"
    assert slo.timeout_seconds == 2.0
    assert slo.services == {"checkout": 'budget_remaining{service="checkout"}'}
    assert load_config(tmp_path / "missing.yaml").slo.prometheus_url == ""
