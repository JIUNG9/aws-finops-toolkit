"""Pydantic schemas — shared contract between API routes and frontend templates."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


# ── Cloud Accounts ──────────────────────────────────────

class AccountCreate(BaseModel):
    provider: str = "aws"
    name: str
    config: dict = {}


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None
    status: Optional[str] = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    provider: str
    name: str
    config: dict
    status: str
    last_synced: Optional[str]
    created_at: str


# ── Scans ───────────────────────────────────────────────

class ScanTrigger(BaseModel):
    account_ids: list[str] = []
    checks: list[str] = []


class ScanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    account_id: Optional[str]
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    total_findings: int
    total_monthly_savings: float
    checks_run: str
    created_at: str


# ── Findings ────────────────────────────────────────────

class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    scan_id: str
    account_id: str
    check_name: str
    resource_type: str
    resource_id: str
    resource_name: str
    severity: str
    current_monthly_cost: float
    estimated_monthly_savings: float
    recommended_action: str
    details: str
    status: str
    watch_list: int
    created_at: str


class FindingUpdate(BaseModel):
    status: Optional[str] = None
    watch_list: Optional[int] = None
    snoozed_until: Optional[str] = None


# ── Services ────────────────────────────────────────────

class ServiceCreate(BaseModel):
    name: str
    priority: str = "P2"
    stateless: bool = False
    owner_team: str = ""


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    priority: str
    stateless: int
    owner_team: str
    created_at: str


class DependencyCreate(BaseModel):
    depends_on_id: str
    dependency_type: str = "runtime"


class DependencyGraphNode(BaseModel):
    id: str
    name: str
    priority: str
    group: int = 0


class DependencyGraphLink(BaseModel):
    source: str
    target: str
    type: str = "runtime"


class DependencyGraph(BaseModel):
    nodes: list[DependencyGraphNode]
    links: list[DependencyGraphLink]


# ── Error Budgets ───────────────────────────────────────

class ErrorBudgetCreate(BaseModel):
    service_id: str
    period_type: str = "monthly"
    slo_target_pct: float = 99.9
    p99_latency_target_ms: Optional[float] = None


class ErrorBudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    service_id: str
    period_type: str
    period_start: str
    period_end: str
    slo_target_pct: float
    budget_total_minutes: float
    budget_consumed_minutes: float
    status: str
    created_at: str

    @property
    def remaining_pct(self) -> float:
        if self.budget_total_minutes == 0:
            return 0.0
        return max(0.0, 100.0 * (1 - self.budget_consumed_minutes / self.budget_total_minutes))


class ErrorBudgetEventCreate(BaseModel):
    event_type: str
    started_at: str
    ended_at: Optional[str] = None
    duration_minutes: float = 0.0
    description: str = ""
    source: str = "manual"


# ── Financial Budgets ───────────────────────────────────

class BudgetCreate(BaseModel):
    name: str
    account_id: Optional[str] = None
    service_id: Optional[str] = None
    period_type: str = "monthly"
    budget_amount: float
    alert_threshold_pct: float = 80.0


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    account_id: Optional[str]
    service_id: Optional[str]
    period_type: str
    period_start: str
    period_end: str
    budget_amount: float
    actual_amount: float
    forecasted_amount: Optional[float]
    status: str
    created_at: str


class BudgetSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    snapshot_date: str
    actual_amount: float
    forecasted_amount: Optional[float]


# ── Cost Tracking ───────────────────────────────────────

class CostOverview(BaseModel):
    current_period_cost: float
    previous_period_cost: float
    delta: float
    delta_pct: float
    total_savings_found: float


class CostByAccount(BaseModel):
    account_id: str
    account_name: str
    cost: float


class CostTrendPoint(BaseModel):
    date: str
    cost: float


# ── AI Recommendations ──────────────────────────────────

class AIRecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    recommendation_type: str
    title: str
    body: str
    severity: str
    llm_provider: Optional[str]
    confidence: Optional[float]
    status: str
    created_at: str


# ── Incidents ───────────────────────────────────────────

class IncidentCreate(BaseModel):
    service_id: Optional[str] = None
    title: str
    description: str = ""
    severity: str = "medium"
    started_at: str
    ended_at: Optional[str] = None
    user_impact_before: Optional[int] = None
    user_impact_after: Optional[int] = None


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    service_id: Optional[str]
    title: str
    severity: str
    started_at: str
    ended_at: Optional[str]
    user_impact_before: Optional[int]
    user_impact_after: Optional[int]
    user_churn: Optional[int]
    cost_impact: Optional[float]
    created_at: str
