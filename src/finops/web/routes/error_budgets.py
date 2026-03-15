"""Error budget management routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException

from finops.db.database import Database
from finops.web.deps import get_db
from finops.web.schemas import ErrorBudgetCreate, ErrorBudgetOut, ErrorBudgetEventCreate

router = APIRouter(tags=["error-budgets"])


def _calculate_budget_minutes(slo_pct: float, period_type: str) -> float:
    """Calculate total allowed downtime minutes from SLO target."""
    days = {"monthly": 30, "quarterly": 90, "rolling_30d": 30}.get(period_type, 30)
    total_minutes = days * 24 * 60
    return total_minutes * (1 - slo_pct / 100)


@router.get("/error-budgets", response_model=list[ErrorBudgetOut])
async def list_error_budgets(db: Database = Depends(get_db)):
    return await db.fetchall("SELECT * FROM error_budgets ORDER BY created_at DESC")


@router.post("/error-budgets", response_model=ErrorBudgetOut, status_code=201)
async def create_error_budget(body: ErrorBudgetCreate, db: Database = Depends(get_db)):
    budget_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    period_days = {"monthly": 30, "quarterly": 90, "rolling_30d": 30}.get(body.period_type, 30)
    period_start = now.replace(day=1).isoformat()
    period_end = (now.replace(day=1) + timedelta(days=period_days)).isoformat()
    budget_minutes = _calculate_budget_minutes(body.slo_target_pct, body.period_type)

    await db.execute(
        """INSERT INTO error_budgets
        (id, service_id, period_type, period_start, period_end, slo_target_pct,
         budget_total_minutes, p99_latency_target_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (budget_id, body.service_id, body.period_type, period_start, period_end,
         body.slo_target_pct, budget_minutes, body.p99_latency_target_ms),
    )
    await db.commit()
    return await db.fetchone("SELECT * FROM error_budgets WHERE id = ?", (budget_id,))


@router.get("/error-budgets/summary")
async def error_budget_summary(db: Database = Depends(get_db)):
    budgets = await db.fetchall(
        """SELECT eb.*, s.name as service_name FROM error_budgets eb
        LEFT JOIN services s ON eb.service_id = s.id
        ORDER BY eb.status DESC, eb.budget_consumed_minutes DESC"""
    )
    return budgets


@router.get("/error-budgets/{budget_id}", response_model=ErrorBudgetOut)
async def get_error_budget(budget_id: str, db: Database = Depends(get_db)):
    row = await db.fetchone("SELECT * FROM error_budgets WHERE id = ?", (budget_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Error budget not found")
    return row


@router.post("/error-budgets/{budget_id}/events", status_code=201)
async def record_event(budget_id: str, body: ErrorBudgetEventCreate, db: Database = Depends(get_db)):
    budget = await db.fetchone("SELECT * FROM error_budgets WHERE id = ?", (budget_id,))
    if not budget:
        raise HTTPException(status_code=404, detail="Error budget not found")

    event_id = str(uuid.uuid4())
    await db.execute(
        """INSERT INTO error_budget_events
        (id, error_budget_id, event_type, started_at, ended_at, duration_minutes, description, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, budget_id, body.event_type, body.started_at, body.ended_at,
         body.duration_minutes, body.description, body.source),
    )

    # Update consumed minutes
    new_consumed = budget["budget_consumed_minutes"] + body.duration_minutes
    total = budget["budget_total_minutes"]
    remaining_pct = max(0, 100 * (1 - new_consumed / total)) if total > 0 else 0

    if remaining_pct <= 0:
        new_status = "breached"
    elif remaining_pct <= 20:
        new_status = "critical"
    elif remaining_pct <= 50:
        new_status = "warning"
    else:
        new_status = "healthy"

    await db.execute(
        """UPDATE error_budgets SET budget_consumed_minutes = ?, status = ?,
        last_updated = datetime('now') WHERE id = ?""",
        (new_consumed, new_status, budget_id),
    )
    await db.commit()
    return {"id": event_id, "budget_status": new_status, "remaining_pct": round(remaining_pct, 1)}
