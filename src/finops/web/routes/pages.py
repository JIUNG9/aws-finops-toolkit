"""HTMX page routes — server-rendered HTML pages."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from finops.db.database import Database
from finops.web.deps import get_db

router = APIRouter(tags=["pages"])

templates_dir = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Database = Depends(get_db)):
    cost = await db.fetchone(
        """SELECT COALESCE(SUM(estimated_monthly_savings), 0) as savings,
        COUNT(*) as findings FROM findings
        WHERE scan_id = (SELECT id FROM scans ORDER BY created_at DESC LIMIT 1)"""
    ) or {"savings": 0, "findings": 0}

    budgets = await db.fetchall(
        "SELECT eb.*, s.name as service_name FROM error_budgets eb LEFT JOIN services s ON eb.service_id = s.id"
    )
    scans = await db.fetchall("SELECT * FROM scans ORDER BY created_at DESC LIMIT 5")
    top_findings = await db.fetchall(
        "SELECT * FROM findings ORDER BY estimated_monthly_savings DESC LIMIT 10"
    )

    return templates.TemplateResponse(request, "pages/dashboard.html", {
        "cost": cost, "error_budgets": budgets, "scans": scans, "top_findings": top_findings,
    })


@router.get("/scans", response_class=HTMLResponse)
async def scans_page(request: Request, db: Database = Depends(get_db)):
    scans = await db.fetchall("SELECT * FROM scans ORDER BY created_at DESC LIMIT 50")
    accounts = await db.fetchall("SELECT * FROM cloud_accounts WHERE status = 'active'")
    return templates.TemplateResponse(request, "pages/scans.html", {"scans": scans, "accounts": accounts})


@router.get("/findings", response_class=HTMLResponse)
async def findings_page(request: Request, db: Database = Depends(get_db)):
    findings = await db.fetchall("SELECT * FROM findings ORDER BY estimated_monthly_savings DESC LIMIT 100")
    return templates.TemplateResponse(request, "pages/findings.html", {"findings": findings})


@router.get("/error-budgets", response_class=HTMLResponse)
async def error_budgets_page(request: Request, db: Database = Depends(get_db)):
    budgets = await db.fetchall(
        """SELECT eb.*, s.name as service_name FROM error_budgets eb
        LEFT JOIN services s ON eb.service_id = s.id ORDER BY eb.status DESC"""
    )
    return templates.TemplateResponse(request, "pages/error_budgets.html", {"error_budgets": budgets})


@router.get("/budgets", response_class=HTMLResponse)
async def budgets_page(request: Request, db: Database = Depends(get_db)):
    budgets = await db.fetchall("SELECT * FROM budgets ORDER BY status DESC")
    return templates.TemplateResponse(request, "pages/budgets.html", {"budgets": budgets})


@router.get("/costs", response_class=HTMLResponse)
async def costs_page(request: Request, db: Database = Depends(get_db)):
    return templates.TemplateResponse(request, "pages/costs.html", {})


@router.get("/services", response_class=HTMLResponse)
async def services_page(request: Request, db: Database = Depends(get_db)):
    services = await db.fetchall("SELECT * FROM services ORDER BY priority, name")
    return templates.TemplateResponse(request, "pages/services.html", {"services": services})


@router.get("/recommendations", response_class=HTMLResponse)
async def recommendations_page(request: Request, db: Database = Depends(get_db)):
    recommendations = await db.fetchall("SELECT * FROM ai_recommendations ORDER BY created_at DESC")
    return templates.TemplateResponse(request, "pages/recommendations.html", {"recommendations": recommendations})


@router.get("/incidents", response_class=HTMLResponse)
async def incidents_page(request: Request, db: Database = Depends(get_db)):
    incidents = await db.fetchall("SELECT * FROM incidents ORDER BY started_at DESC")
    return templates.TemplateResponse(request, "pages/incidents.html", {"incidents": incidents})


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Database = Depends(get_db)):
    accounts = await db.fetchall("SELECT * FROM cloud_accounts ORDER BY created_at DESC")
    return templates.TemplateResponse(request, "pages/settings.html", {"accounts": accounts})
