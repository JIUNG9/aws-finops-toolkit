"""FastAPI dependencies — shared across all routes."""

from __future__ import annotations

from fastapi import Request

from finops.config import FinOpsConfig
from finops.db.database import Database


def get_db(request: Request) -> Database:
    return request.app.state.db  # type: ignore[no-any-return]


def get_config(request: Request) -> FinOpsConfig:
    return request.app.state.config  # type: ignore[no-any-return]


def is_demo(request: Request) -> bool:
    return getattr(request.app.state, "demo", False)
