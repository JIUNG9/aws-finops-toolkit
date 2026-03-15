"""Service catalog and dependency graph routes."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException

from finops.db.database import Database
from finops.web.deps import get_db
from finops.web.schemas import ServiceCreate, ServiceOut, DependencyCreate, DependencyGraph, DependencyGraphNode, DependencyGraphLink

router = APIRouter(tags=["services"])


@router.get("/services", response_model=list[ServiceOut])
async def list_services(db: Database = Depends(get_db)):
    return await db.fetchall("SELECT * FROM services ORDER BY priority, name")


@router.get("/services/dependency-graph", response_model=DependencyGraph)
async def get_dependency_graph(db: Database = Depends(get_db)):
    services = await db.fetchall("SELECT * FROM services")
    deps = await db.fetchall("SELECT * FROM service_dependencies")

    priority_groups = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    nodes = [DependencyGraphNode(
        id=s["id"], name=s["name"], priority=s["priority"],
        group=priority_groups.get(s["priority"], 2),
    ) for s in services]

    links = [DependencyGraphLink(
        source=d["service_id"], target=d["depends_on_id"], type=d["dependency_type"],
    ) for d in deps]

    return DependencyGraph(nodes=nodes, links=links)


@router.post("/services", response_model=ServiceOut, status_code=201)
async def create_service(body: ServiceCreate, db: Database = Depends(get_db)):
    svc_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO services (id, name, priority, stateless, owner_team) VALUES (?, ?, ?, ?, ?)",
        (svc_id, body.name, body.priority, int(body.stateless), body.owner_team),
    )
    await db.commit()
    return await db.fetchone("SELECT * FROM services WHERE id = ?", (svc_id,))


@router.get("/services/{service_id}", response_model=ServiceOut)
async def get_service(service_id: str, db: Database = Depends(get_db)):
    row = await db.fetchone("SELECT * FROM services WHERE id = ?", (service_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Service not found")
    return row


@router.delete("/services/{service_id}", status_code=204)
async def delete_service(service_id: str, db: Database = Depends(get_db)):
    await db.execute("DELETE FROM services WHERE id = ?", (service_id,))
    await db.commit()


@router.post("/services/{service_id}/dependencies", status_code=201)
async def add_dependency(service_id: str, body: DependencyCreate, db: Database = Depends(get_db)):
    dep_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO service_dependencies (id, service_id, depends_on_id, dependency_type) VALUES (?, ?, ?, ?)",
        (dep_id, service_id, body.depends_on_id, body.dependency_type),
    )
    await db.commit()
    return {"id": dep_id}
