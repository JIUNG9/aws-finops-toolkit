"""FastAPI application factory for the SRE + FinOps Platform."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from finops.config import load_config
from finops.db.database import Database


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    config = load_config()
    db = Database(config.database.resolved_path)
    await db.connect()
    await db.run_migrations()

    app.state.config = config
    app.state.db = db
    app.state.demo = os.environ.get("FINOPS_DEMO", "0") == "1"

    # Seed demo data if demo mode or empty DB
    if app.state.demo:
        from finops.services.scanner_service import seed_demo_data
        await seed_demo_data(db)

    yield

    await db.disconnect()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="SRE + FinOps Platform",
        description="Cost optimization gated on error budgets, traffic analysis, and dependency safety",
        version="0.2.0",
        lifespan=lifespan,
    )

    # Static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Register routes
    from finops.web.routes import (
        pages, accounts, scans, findings, error_budgets,
        budgets, costs, services, ai, incidents, alerts, import_export,
    )

    app.include_router(pages.router)
    app.include_router(accounts.router, prefix="/api/v1")
    app.include_router(scans.router, prefix="/api/v1")
    app.include_router(findings.router, prefix="/api/v1")
    app.include_router(error_budgets.router, prefix="/api/v1")
    app.include_router(budgets.router, prefix="/api/v1")
    app.include_router(costs.router, prefix="/api/v1")
    app.include_router(services.router, prefix="/api/v1")
    app.include_router(ai.router, prefix="/api/v1")
    app.include_router(incidents.router, prefix="/api/v1")
    app.include_router(alerts.router, prefix="/api/v1")
    app.include_router(import_export.router, prefix="/api/v1")

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "version": "0.2.0"}

    return app
