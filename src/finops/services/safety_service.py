"""Safety analyzer — 5-step safety gate before any cost optimization."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from finops.config import SloConfig
from finops.db.database import Database
from finops.services.slo_source import SloSourceError, remaining_budget_status

logger = logging.getLogger(__name__)


@dataclass
class SafetyVerdict:
    step: str
    status: str  # "safe", "caution", "unsafe", "unknown" (no data), "pending"
    summary: str
    details: dict


@dataclass
class SafetyReport:
    id: str
    finding_id: str
    overall: str  # "safe", "caution", "unsafe"
    verdicts: list[SafetyVerdict]
    checklist: list[dict]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "finding_id": self.finding_id,
            "overall": self.overall,
            "verdicts": [
                {"step": v.step, "status": v.status, "summary": v.summary, "details": v.details}
                for v in self.verdicts
            ],
            "checklist": self.checklist,
        }


async def error_budget_verdict(finding, db: Database, slo: SloConfig | None = None) -> SafetyVerdict:
    """Error budget step: look only at the budgets of the services that own the finding's resource.

    A service with a query in `slo.services` is read live from Prometheus and its table rows are
    ignored. If that read fails the step is `caution`, never `safe`.
    """
    service_rows = await db.fetchall(
        "SELECT DISTINCT sr.service_id, s.name AS service_name FROM service_resources sr"
        " LEFT JOIN services s ON s.id = sr.service_id"
        " WHERE sr.resource_id = ? AND sr.account_id = ?",
        (finding["resource_id"], finding["account_id"]),
    )
    service_ids = [r["service_id"] for r in service_rows]
    if not service_ids:
        return SafetyVerdict(
            step="error_budget_gate",
            status="unknown",
            summary="Resource is not mapped to a service; no error budget was checked",
            details={"service_ids": [], "at_risk_count": 0, "statuses": []},
        )

    all_statuses: list[str] = []
    sources: dict[str, str] = {}
    live_errors: dict[str, str] = {}
    for row in service_rows:
        name = row["service_name"]
        if slo and slo.prometheus_url and name in slo.services:
            try:
                status, remaining = await remaining_budget_status(slo, name)
            except SloSourceError as exc:
                logger.warning("Live error budget read failed for service %s: %s", name, exc)
                live_errors[name] = str(exc)
                sources[name] = "prometheus (failed)"
            else:
                all_statuses.append(status)
                sources[name] = f"prometheus (remaining {remaining:.2f})"
            continue
        budgets = await db.fetchall(
            "SELECT status FROM error_budgets WHERE service_id = ?", (row["service_id"],)
        )
        if budgets:
            sources[name or row["service_id"]] = "database"
        all_statuses.extend(b["status"] for b in budgets)

    at_risk = [st for st in all_statuses if st in ("warning", "critical", "breached")]
    if "breached" in at_risk:
        status, summary = "unsafe", f"{len(at_risk)} error budgets at risk for the owning service"
    elif at_risk or live_errors:
        parts = []
        if at_risk:
            parts.append(f"{len(at_risk)} error budgets at risk for the owning service")
        if live_errors:
            parts.append(f"live budget read failed for {', '.join(sorted(live_errors))}")
        status, summary = "caution", "; ".join(parts)
    elif not all_statuses:
        status, summary = "unknown", "The owning service has no error budget"
    else:
        status, summary = "safe", "Error budgets of the owning service are healthy"
    return SafetyVerdict(
        step="error_budget_gate",
        status=status,
        summary=summary,
        details={
            "service_ids": service_ids,
            "at_risk_count": len(at_risk),
            "statuses": at_risk,
            "sources": sources,
            "live_errors": live_errors,
        },
    )


async def analyze_safety(
    finding_id: str, db: Database, llm=None, slo: SloConfig | None = None
) -> SafetyReport:
    """Run 5-step safety analysis on a finding before accepting it."""
    finding = await db.fetchone("SELECT * FROM findings WHERE id = ?", (finding_id,))
    if not finding:
        raise ValueError(f"Finding {finding_id} not found")

    verdicts = []

    # Step 1: Traffic Analysis. No traffic metrics are collected yet, so the only
    # signal is the resource's own monthly cost, used as a rough proxy.
    if finding["current_monthly_cost"] > 200:
        traffic_verdict = SafetyVerdict(
            step="traffic_analysis",
            status="caution",
            summary=(
                f"High-cost resource (${finding['current_monthly_cost']}/mo)"
                " \u2014 verify traffic patterns before downsize"
            ),
            details={"source": "cost_proxy"},
        )
    else:
        traffic_verdict = SafetyVerdict(
            step="traffic_analysis",
            status="unknown",
            summary="No traffic data is collected; traffic was not checked",
            details={"source": "none"},
        )
    verdicts.append(traffic_verdict)

    # Step 2: Dependency Check
    deps = await db.fetchall(
        """SELECT sd.*, s.name as service_name FROM service_resources sr
        JOIN service_dependencies sd ON sr.service_id = sd.service_id
        JOIN services s ON sd.depends_on_id = s.id
        WHERE sr.resource_id = ?""",
        (finding["resource_id"],),
    )
    dep_count = len(deps)
    dep_verdict = SafetyVerdict(
        step="dependency_check",
        status="safe" if dep_count == 0 else ("caution" if dep_count < 3 else "unsafe"),
        summary=f"{dep_count} downstream dependencies found" if dep_count > 0 else "No known dependencies",
        details={"dependency_count": dep_count, "services": [d["service_name"] for d in deps]},
    )
    verdicts.append(dep_verdict)

    # Step 3: Error Budget Gate. Only the budgets of the services that own this resource count.
    verdicts.append(await error_budget_verdict(finding, db, slo))

    # Step 4: AI Analysis. Without an LLM there is no assessment; a failing LLM is reported, not hidden.
    ai_verdict = SafetyVerdict(
        step="ai_analysis",
        status="unknown",
        summary="No LLM configured; no AI assessment was made",
        details={"provider": "none"},
    )
    if llm:
        prompt_path = Path(__file__).parent.parent / "llm" / "prompts" / "safety_analysis.txt"
        try:
            prompt = prompt_path.read_text().replace("{{ action_description }}", finding["recommended_action"])
            prompt = prompt.replace("{{ resource_json }}", json.dumps(dict(finding), default=str))
            response = await llm.generate(prompt)
        except Exception as exc:
            logger.warning("Safety AI analysis failed for finding %s: %s", finding_id, exc)
            ai_verdict.summary = f"AI analysis failed: {type(exc).__name__}"
            ai_verdict.details = {"provider": "error", "error": f"{type(exc).__name__}: {exc}"[:200]}
        else:
            ai_verdict.status = "safe"
            ai_verdict.summary = response.content[:200]
            ai_verdict.details = {"provider": response.provider}
    verdicts.append(ai_verdict)

    # Step 5: User Confirmation (always required)
    confirm_verdict = SafetyVerdict(
        step="user_confirmation",
        status="pending",
        summary="Awaiting user approval",
        details={},
    )
    verdicts.append(confirm_verdict)

    # Overall verdict
    statuses = [v.status for v in verdicts if v.step != "user_confirmation"]
    if "unsafe" in statuses:
        overall = "unsafe"
    elif "caution" in statuses:
        overall = "caution"
    else:
        overall = "safe"

    # Build checklist
    checklist = [
        {"item": "Reviewed traffic patterns", "checked": False},
        {"item": "Checked downstream dependencies", "checked": False},
        {"item": "Verified error budget health", "checked": False},
        {"item": "Read AI risk assessment", "checked": False},
        {"item": "Approved by team lead", "checked": False},
    ]

    report = SafetyReport(
        id=str(uuid.uuid4()),
        finding_id=finding_id,
        overall=overall,
        verdicts=verdicts,
        checklist=checklist,
    )

    # Persist
    await db.execute(
        """INSERT INTO safety_analyses (id, finding_id, traffic_verdict, dependency_verdict,
        error_budget_verdict, ai_verdict, overall_verdict, checklist)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (report.id, finding_id,
         json.dumps(verdicts[0].details), json.dumps(verdicts[1].details),
         json.dumps(verdicts[2].details), json.dumps(verdicts[3].details),
         overall, json.dumps(checklist)),
    )
    await db.commit()

    return report
