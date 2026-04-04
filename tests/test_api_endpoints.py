"""API endpoint smoke tests."""

import asyncio
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def app_with_db():
    """Create a FastAPI app with a temporary database."""
    from finops.app import create_app
    from finops.db.database import Database
    from finops.config import load_config
    from finops.services.scanner_service import seed_demo_data

    app = create_app()
    db_path = Path(tempfile.mktemp(suffix=".db"))
    config = load_config()
    db = Database(db_path)
    await db.connect()
    await db.run_migrations()
    app.state.config = config
    app.state.db = db
    app.state.demo = True
    await seed_demo_data(db)

    yield app

    await db.disconnect()
    db_path.unlink(missing_ok=True)


@pytest_asyncio.fixture
async def client(app_with_db):
    """Create a test client."""
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health(self, client):
        r = await client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestAccountsAPI:
    @pytest.mark.asyncio
    async def test_list_accounts(self, client):
        r = await client.get("/api/v1/accounts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_create_account(self, client):
        r = await client.post("/api/v1/accounts", json={"name": "Test", "provider": "aws"})
        assert r.status_code == 201
        assert r.json()["name"] == "Test"


class TestScansAPI:
    @pytest.mark.asyncio
    async def test_list_scans(self, client):
        r = await client.get("/api/v1/scans")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_trigger_scan(self, client):
        r = await client.post("/api/v1/scans", json={"account_ids": [], "checks": []})
        assert r.status_code == 201


class TestFindingsAPI:
    @pytest.mark.asyncio
    async def test_list_findings(self, client):
        r = await client.get("/api/v1/findings")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 10

    @pytest.mark.asyncio
    async def test_watchlist(self, client):
        r = await client.get("/api/v1/findings/watchlist")
        assert r.status_code == 200


class TestErrorBudgetsAPI:
    @pytest.mark.asyncio
    async def test_list_error_budgets(self, client):
        r = await client.get("/api/v1/error-budgets")
        assert r.status_code == 200
        assert len(r.json()) == 4


class TestCostsAPI:
    @pytest.mark.asyncio
    async def test_cost_overview(self, client):
        r = await client.get("/api/v1/costs/overview")
        assert r.status_code == 200
        assert "total_savings_found" in r.json()


class TestServicesAPI:
    @pytest.mark.asyncio
    async def test_list_services(self, client):
        r = await client.get("/api/v1/services")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_dependency_graph(self, client):
        r = await client.get("/api/v1/services/dependency-graph")
        assert r.status_code == 200
        assert "nodes" in r.json()


class TestAIAPI:
    @pytest.mark.asyncio
    async def test_analyze(self, client):
        r = await client.post("/api/v1/ai/analyze")
        assert r.status_code == 201


class TestPages:
    @pytest.mark.asyncio
    async def test_all_pages_render(self, client):
        pages = ["/", "/scans", "/findings", "/error-budgets", "/budgets",
                 "/costs", "/services", "/recommendations", "/incidents",
                 "/alerts", "/settings", "/import-export", "/onboarding"]
        for page in pages:
            r = await client.get(page)
            assert r.status_code == 200, f"Page {page} returned {r.status_code}"
