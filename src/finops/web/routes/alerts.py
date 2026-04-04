"""Alert configuration routes."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends

from finops.db.database import Database
from finops.web.deps import get_db

router = APIRouter(tags=["alerts"])


@router.get("/alerts")
async def list_alerts(db: Database = Depends(get_db)):
    rows = await db.fetchall("SELECT * FROM alerts ORDER BY created_at DESC")
    for row in rows:
        row["config"] = json.loads(row.get("config", "{}"))
    return rows


@router.post("/alerts", status_code=201)
async def create_alert(
    name: str = "",
    alert_type: str = "budget",
    channel: str = "slack",
    webhook_url: str = "",
    db: Database = Depends(get_db),
):
    alert_id = str(uuid.uuid4())
    config = {"webhook_url": webhook_url}
    await db.execute(
        "INSERT INTO alerts (id, name, alert_type, channel, config) VALUES (?, ?, ?, ?, ?)",
        (alert_id, name, alert_type, channel, json.dumps(config)),
    )
    await db.commit()
    return {"id": alert_id, "name": name, "alert_type": alert_type}


@router.delete("/alerts/{alert_id}", status_code=204)
async def delete_alert(alert_id: str, db: Database = Depends(get_db)):
    await db.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    await db.commit()
