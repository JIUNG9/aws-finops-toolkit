"""Financial budget management routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException

from finops.db.database import Database
from finops.web.deps import get_db
from finops.web.schemas import BudgetCreate, BudgetOut, BudgetSnapshotOut

router = APIRouter(tags=["budgets"])


@router.get("/budgets", response_model=list[BudgetOut])
async def list_budgets(db: Database = Depends(get_db)):
    return await db.fetchall("SELECT * FROM budgets ORDER BY created_at DESC")


@router.post("/budgets", response_model=BudgetOut, status_code=201)
async def create_budget(body: BudgetCreate, db: Database = Depends(get_db)):
    budget_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    period_days = {"monthly": 30, "quarterly": 90, "annual": 365}.get(body.period_type, 30)
    period_start = now.replace(day=1).isoformat()
    period_end = (now.replace(day=1) + timedelta(days=period_days)).isoformat()

    await db.execute(
        """INSERT INTO budgets
        (id, name, account_id, service_id, period_type, period_start, period_end,
         budget_amount, alert_threshold_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (budget_id, body.name, body.account_id, body.service_id, body.period_type,
         period_start, period_end, body.budget_amount, body.alert_threshold_pct),
    )
    await db.commit()
    return await db.fetchone("SELECT * FROM budgets WHERE id = ?", (budget_id,))


@router.get("/budgets/{budget_id}", response_model=BudgetOut)
async def get_budget(budget_id: str, db: Database = Depends(get_db)):
    row = await db.fetchone("SELECT * FROM budgets WHERE id = ?", (budget_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Budget not found")
    return row


@router.get("/budgets/{budget_id}/snapshots", response_model=list[BudgetSnapshotOut])
async def get_budget_snapshots(budget_id: str, db: Database = Depends(get_db)):
    return await db.fetchall(
        "SELECT * FROM budget_snapshots WHERE budget_id = ? ORDER BY snapshot_date",
        (budget_id,),
    )


@router.get("/budgets/summary")
async def budget_summary(db: Database = Depends(get_db)):
    return await db.fetchall(
        "SELECT * FROM budgets ORDER BY status DESC, actual_amount DESC"
    )
