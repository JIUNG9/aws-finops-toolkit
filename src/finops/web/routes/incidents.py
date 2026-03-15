"""Incident management and user impact routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from finops.db.database import Database
from finops.web.deps import get_db
from finops.web.schemas import IncidentCreate, IncidentOut

router = APIRouter(tags=["incidents"])


@router.get("/incidents", response_model=list[IncidentOut])
async def list_incidents(db: Database = Depends(get_db)):
    return await db.fetchall("SELECT * FROM incidents ORDER BY started_at DESC")


@router.post("/incidents", response_model=IncidentOut, status_code=201)
async def create_incident(body: IncidentCreate, db: Database = Depends(get_db)):
    inc_id = str(uuid.uuid4())
    user_churn = None
    if body.user_impact_before is not None and body.user_impact_after is not None:
        user_churn = body.user_impact_before - body.user_impact_after

    await db.execute(
        """INSERT INTO incidents
        (id, service_id, title, description, severity, started_at, ended_at,
         user_impact_before, user_impact_after, user_churn)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (inc_id, body.service_id, body.title, body.description, body.severity,
         body.started_at, body.ended_at, body.user_impact_before,
         body.user_impact_after, user_churn),
    )
    await db.commit()
    return await db.fetchone("SELECT * FROM incidents WHERE id = ?", (inc_id,))


@router.get("/incidents/{incident_id}", response_model=IncidentOut)
async def get_incident(incident_id: str, db: Database = Depends(get_db)):
    row = await db.fetchone("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Incident not found")
    return row


@router.get("/incidents/{incident_id}/user-impact")
async def get_user_impact(incident_id: str, db: Database = Depends(get_db)):
    inc = await db.fetchone("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {
        "incident_id": incident_id,
        "users_before": inc.get("user_impact_before"),
        "users_after": inc.get("user_impact_after"),
        "user_churn": inc.get("user_churn"),
        "churn_pct": (
            round(inc["user_churn"] / inc["user_impact_before"] * 100, 1)
            if inc.get("user_churn") and inc.get("user_impact_before")
            else None
        ),
    }
