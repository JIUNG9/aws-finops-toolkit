"""Safety gate: runs when a finding is accepted, and scopes the error budget to the owning service."""

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

ACCOUNT = "123456789012"


@pytest_asyncio.fixture
async def env():
    from finops.app import create_app
    from finops.config import load_config
    from finops.db.database import Database

    app = create_app()
    db_path = Path(tempfile.mktemp(suffix=".db"))
    db = Database(db_path)
    await db.connect()
    await db.run_migrations()
    app.state.config = load_config()
    app.state.db = db
    app.state.demo = False
    await db.execute("INSERT INTO cloud_accounts (id, name) VALUES (?, 'acme-corp')", (ACCOUNT,))
    await db.execute("INSERT INTO scans (id, account_id) VALUES ('scan-1', ?)", (ACCOUNT,))
    await db.commit()
    yield app, db
    await db.disconnect()
    db_path.unlink(missing_ok=True)
    for ext in ("-wal", "-shm"):
        Path(str(db_path) + ext).unlink(missing_ok=True)


async def add_finding(db, fid, resource_id, cost=50.0):
    await db.execute(
        """INSERT INTO findings (id, scan_id, account_id, check_name, resource_type, resource_id,
        current_monthly_cost, estimated_monthly_savings, recommended_action)
        VALUES (?, 'scan-1', ?, 'nat_gateway', 'nat', ?, ?, 10, 'delete it')""",
        (fid, ACCOUNT, resource_id, cost),
    )
    await db.commit()


async def add_service(db, name, resource_id=None, budget_status=None):
    sid = f"svc-{name}"
    await db.execute("INSERT INTO services (id, name) VALUES (?, ?)", (sid, name))
    if resource_id:
        await db.execute(
            "INSERT INTO service_resources (id, service_id, account_id, resource_id, resource_type)"
            " VALUES (?, ?, ?, ?, 'nat')",
            (f"sr-{name}", sid, ACCOUNT, resource_id),
        )
    if budget_status:
        await db.execute(
            """INSERT INTO error_budgets (id, service_id, period_start, period_end,
            budget_total_minutes, status) VALUES (?, ?, '2026-11-01', '2026-12-01', 43.2, ?)""",
            (f"eb-{name}", sid, budget_status),
        )
    await db.commit()


async def accept(app, fid):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.patch(f"/api/v1/findings/{fid}", json={"status": "accepted"})


async def verdict(db, fid):
    from finops.services.safety_service import analyze_safety

    report = await analyze_safety(fid, db)
    return report, {v.step: v for v in report.verdicts}


@pytest.mark.asyncio
async def test_other_services_breached_budget_does_not_block(env):
    app, db = env
    await add_service(db, "checkout", "nat-1", "healthy")
    await add_service(db, "billing", "nat-2", "breached")
    await add_finding(db, "f1", "nat-1")
    r = await accept(app, "f1")
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    row = await db.fetchone("SELECT overall_verdict FROM safety_analyses WHERE finding_id = 'f1'")
    assert row["overall_verdict"] == "safe"


@pytest.mark.asyncio
async def test_own_breached_budget_blocks_accept(env):
    app, db = env
    await add_service(db, "checkout", "nat-1", "breached")
    await add_finding(db, "f1", "nat-1")
    r = await accept(app, "f1")
    assert r.status_code == 409
    assert r.json()["detail"]["safety"]["overall"] == "unsafe"
    row = await db.fetchone("SELECT status FROM findings WHERE id = 'f1'")
    assert row["status"] == "open"


@pytest.mark.asyncio
async def test_own_warning_budget_is_caution_and_allowed(env):
    app, db = env
    await add_service(db, "checkout", "nat-1", "warning")
    await add_finding(db, "f1", "nat-1")
    r = await accept(app, "f1")
    assert r.status_code == 200
    row = await db.fetchone("SELECT overall_verdict FROM safety_analyses WHERE finding_id = 'f1'")
    assert row["overall_verdict"] == "caution"


@pytest.mark.asyncio
async def test_unmapped_resource_is_unknown_not_safe(env):
    _, db = env
    await add_service(db, "billing", "nat-2", "breached")
    await add_finding(db, "f1", "nat-9")
    report, steps = await verdict(db, "f1")
    assert steps["error_budget_gate"].status == "unknown"
    assert steps["traffic_analysis"].status == "unknown"
    assert steps["ai_analysis"].status == "unknown"
    assert "peak_avg_ratio" not in steps["traffic_analysis"].details
    assert report.overall == "safe"


@pytest.mark.asyncio
async def test_reaccepting_does_not_rerun_gate(env):
    app, db = env
    await add_service(db, "checkout", "nat-1", "healthy")
    await add_finding(db, "f1", "nat-1")
    await db.execute("UPDATE findings SET status = 'accepted' WHERE id = 'f1'")
    await db.commit()
    await db.execute("UPDATE error_budgets SET status = 'breached'")
    await db.commit()
    r = await accept(app, "f1")
    assert r.status_code == 200
    rows = await db.fetchall("SELECT id FROM safety_analyses")
    assert rows == []


@pytest.mark.asyncio
async def test_llm_error_is_reported_not_swallowed(env):
    from finops.services.safety_service import analyze_safety

    _, db = env
    await add_finding(db, "f1", "nat-1")

    class BrokenLLM:
        async def generate(self, prompt):
            raise RuntimeError("rate limited")

    report = await analyze_safety("f1", db, llm=BrokenLLM())
    ai = next(v for v in report.verdicts if v.step == "ai_analysis")
    assert ai.status == "unknown"
    assert "RuntimeError" in ai.summary
    assert "rate limited" in ai.details["error"]
