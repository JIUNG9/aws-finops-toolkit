"""Scan management routes."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from finops.db.database import Database
from finops.web.deps import get_db
from finops.web.schemas import ScanTrigger, ScanOut

router = APIRouter(tags=["scans"])


@router.get("/scans", response_model=list[ScanOut])
async def list_scans(limit: int = 50, db: Database = Depends(get_db)):
    rows = await db.fetchall(
        "SELECT * FROM scans ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    return rows


@router.post("/scans", response_model=ScanOut, status_code=201)
async def trigger_scan(body: ScanTrigger, db: Database = Depends(get_db)):
    scan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    account_id = body.account_ids[0] if body.account_ids else None
    await db.execute(
        "INSERT INTO scans (id, account_id, status, started_at, checks_run) VALUES (?, ?, ?, ?, ?)",
        (scan_id, account_id, "running", now, json.dumps(body.checks)),
    )
    await db.commit()
    # TODO: Dispatch async scan via delegate manager
    row = await db.fetchone("SELECT * FROM scans WHERE id = ?", (scan_id,))
    return row


@router.get("/scans/latest", response_model=ScanOut)
async def get_latest_scan(db: Database = Depends(get_db)):
    row = await db.fetchone("SELECT * FROM scans ORDER BY created_at DESC LIMIT 1")
    if not row:
        raise HTTPException(status_code=404, detail="No scans found")
    return row


@router.get("/scans/{scan_id}", response_model=ScanOut)
async def get_scan(scan_id: str, db: Database = Depends(get_db)):
    row = await db.fetchone("SELECT * FROM scans WHERE id = ?", (scan_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Scan not found")
    return row


@router.get("/scans/{scan_id}/findings")
async def get_scan_findings(
    scan_id: str,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Database = Depends(get_db),
):
    sql = "SELECT * FROM findings WHERE scan_id = ?"
    params: list = [scan_id]
    if severity:
        sql += " AND severity = ?"
        params.append(severity)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY estimated_monthly_savings DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = await db.fetchall(sql, tuple(params))
    return rows
