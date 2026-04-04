"""Findings management routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from finops.db.database import Database
from finops.web.deps import get_db
from finops.web.schemas import FindingOut, FindingUpdate

router = APIRouter(tags=["findings"])


@router.get("/findings", response_model=list[FindingOut])
async def list_findings(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    check_name: Optional[str] = None,
    account_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Database = Depends(get_db),
):
    sql = "SELECT * FROM findings WHERE 1=1"
    params: list = []
    if severity:
        sql += " AND severity = ?"
        params.append(severity)
    if status:
        sql += " AND status = ?"
        params.append(status)
    if check_name:
        sql += " AND check_name = ?"
        params.append(check_name)
    if account_id:
        sql += " AND account_id = ?"
        params.append(account_id)
    sql += " ORDER BY estimated_monthly_savings DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return await db.fetchall(sql, tuple(params))


@router.get("/findings/watchlist", response_model=list[FindingOut])
async def get_watchlist(db: Database = Depends(get_db)):
    return await db.fetchall(
        "SELECT * FROM findings WHERE watch_list = 1 ORDER BY estimated_monthly_savings DESC"
    )


@router.get("/findings/{finding_id}", response_model=FindingOut)
async def get_finding(finding_id: str, db: Database = Depends(get_db)):
    row = await db.fetchone("SELECT * FROM findings WHERE id = ?", (finding_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Finding not found")
    return row


@router.patch("/findings/{finding_id}", response_model=FindingOut)
async def update_finding(finding_id: str, body: FindingUpdate, db: Database = Depends(get_db)):
    existing = await db.fetchone("SELECT * FROM findings WHERE id = ?", (finding_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Finding not found")
    updates: list[str] = []
    params: list[object] = []
    if body.status is not None:
        updates.append("status = ?")
        params.append(body.status)
    if body.watch_list is not None:
        updates.append("watch_list = ?")
        params.append(body.watch_list)
    if body.snoozed_until is not None:
        updates.append("snoozed_until = ?")
        params.append(body.snoozed_until)
    if updates:
        params.append(finding_id)
        await db.execute(f"UPDATE findings SET {', '.join(updates)} WHERE id = ?", tuple(params))
        await db.commit()
    return await db.fetchone("SELECT * FROM findings WHERE id = ?", (finding_id,))
