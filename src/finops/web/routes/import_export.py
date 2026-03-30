"""Import and export routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import JSONResponse

from finops.db.database import Database
from finops.web.deps import get_db

router = APIRouter(tags=["import-export"])


@router.get("/export/scans")
async def export_scans(db: Database = Depends(get_db)):
    scans = await db.fetchall("SELECT * FROM scans ORDER BY created_at DESC")
    return JSONResponse(content=scans, headers={"Content-Disposition": "attachment; filename=scans.json"})


@router.get("/export/findings")
async def export_findings(db: Database = Depends(get_db)):
    findings = await db.fetchall("SELECT * FROM findings ORDER BY estimated_monthly_savings DESC")
    return JSONResponse(content=findings, headers={"Content-Disposition": "attachment; filename=findings.json"})


@router.get("/export/error-budgets")
async def export_error_budgets(db: Database = Depends(get_db)):
    budgets = await db.fetchall("SELECT * FROM error_budgets")
    return JSONResponse(content=budgets, headers={"Content-Disposition": "attachment; filename=error-budgets.json"})


@router.get("/export/budgets")
async def export_budgets(db: Database = Depends(get_db)):
    budgets = await db.fetchall("SELECT * FROM budgets")
    return JSONResponse(content=budgets, headers={"Content-Disposition": "attachment; filename=budgets.json"})


@router.post("/import")
async def import_data(file: UploadFile = File(...), db: Database = Depends(get_db)):
    content = await file.read()
    data = json.loads(content)

    imported = {"scans": 0, "findings": 0, "error_budgets": 0, "budgets": 0}

    if isinstance(data, list) and data:
        sample = data[0]
        if "check_name" in sample:
            for row in data:
                await db.execute(
                    """INSERT OR IGNORE INTO findings (id, scan_id, account_id, check_name,
                    resource_type, resource_id, resource_name, severity,
                    current_monthly_cost, estimated_monthly_savings, recommended_action, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (row["id"], row.get("scan_id", ""), row.get("account_id", ""),
                     row["check_name"], row.get("resource_type", ""), row.get("resource_id", ""),
                     row.get("resource_name", ""), row.get("severity", "medium"),
                     row.get("current_monthly_cost", 0), row.get("estimated_monthly_savings", 0),
                     row.get("recommended_action", ""), row.get("status", "open")),
                )
                imported["findings"] += 1
        elif "slo_target_pct" in sample:
            for row in data:
                await db.execute(
                    """INSERT OR IGNORE INTO error_budgets (id, service_id, period_type,
                    period_start, period_end, slo_target_pct, budget_total_minutes,
                    budget_consumed_minutes, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (row["id"], row.get("service_id", ""), row.get("period_type", "monthly"),
                     row.get("period_start", ""), row.get("period_end", ""),
                     row.get("slo_target_pct", 99.9), row.get("budget_total_minutes", 0),
                     row.get("budget_consumed_minutes", 0), row.get("status", "healthy")),
                )
                imported["error_budgets"] += 1

    await db.commit()
    return {"imported": imported}
