"""Cloud account management routes."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException

from finops.db.database import Database
from finops.web.deps import get_db
from finops.web.schemas import AccountCreate, AccountUpdate, AccountOut

router = APIRouter(tags=["accounts"])


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(db: Database = Depends(get_db)):
    rows = await db.fetchall("SELECT * FROM cloud_accounts ORDER BY created_at DESC")
    for row in rows:
        row["config"] = json.loads(row.get("config", "{}"))
    return rows


@router.post("/accounts", response_model=AccountOut, status_code=201)
async def create_account(body: AccountCreate, db: Database = Depends(get_db)):
    account_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO cloud_accounts (id, provider, name, config) VALUES (?, ?, ?, ?)",
        (account_id, body.provider, body.name, json.dumps(body.config)),
    )
    await db.commit()
    row = await db.fetchone("SELECT * FROM cloud_accounts WHERE id = ?", (account_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    row["config"] = json.loads(row["config"])
    return row


@router.get("/accounts/{account_id}", response_model=AccountOut)
async def get_account(account_id: str, db: Database = Depends(get_db)):
    row = await db.fetchone("SELECT * FROM cloud_accounts WHERE id = ?", (account_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    row["config"] = json.loads(row["config"])
    return row


@router.put("/accounts/{account_id}", response_model=AccountOut)
async def update_account(account_id: str, body: AccountUpdate, db: Database = Depends(get_db)):
    existing = await db.fetchone("SELECT * FROM cloud_accounts WHERE id = ?", (account_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found")
    updates = []
    params = []
    if body.name is not None:
        updates.append("name = ?")
        params.append(body.name)
    if body.config is not None:
        updates.append("config = ?")
        params.append(json.dumps(body.config))
    if body.status is not None:
        updates.append("status = ?")
        params.append(body.status)
    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(account_id)
        await db.execute(f"UPDATE cloud_accounts SET {', '.join(updates)} WHERE id = ?", tuple(params))
        await db.commit()
    row = await db.fetchone("SELECT * FROM cloud_accounts WHERE id = ?", (account_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    row["config"] = json.loads(row["config"])
    return row


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(account_id: str, db: Database = Depends(get_db)):
    existing = await db.fetchone("SELECT * FROM cloud_accounts WHERE id = ?", (account_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found")
    await db.execute("DELETE FROM cloud_accounts WHERE id = ?", (account_id,))
    await db.commit()
