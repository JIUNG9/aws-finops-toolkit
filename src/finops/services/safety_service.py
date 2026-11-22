"""Safety analyzer — 5-step safety gate before any cost optimization."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from finops.db.database import Database

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


async def analyze_safety(finding_id: str, db: Database, llm=None) -> SafetyReport:
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
    service_rows = await db.fetchall(
        "SELECT DISTINCT service_id FROM service_resources WHERE resource_id = ? AND account_id = ?",
        (finding["resource_id"], finding["account_id"]),
    )
    service_ids = [r["service_id"] for r in service_rows]
    if not service_ids:
        eb_verdict = SafetyVerdict(
            step="error_budget_gate",
            status="unknown",
            summary="Resource is not mapped to a service; no error budget was checked",
            details={"service_ids": [], "at_risk_count": 0, "statuses": []},
        )
    else:
        marks = ",".join("?" for _ in service_ids)
        error_budgets = await db.fetchall(
            f"SELECT * FROM error_budgets WHERE service_id IN ({marks})", tuple(service_ids)
        )
        at_risk = [eb for eb in error_budgets if eb["status"] in ("warning", "critical", "breached")]
        if not error_budgets:
            eb_status, eb_summary = "unknown", "The owning service has no error budget"
        elif any(eb["status"] == "breached" for eb in at_risk):
            eb_status, eb_summary = "unsafe", f"{len(at_risk)} error budgets at risk for the owning service"
        elif at_risk:
            eb_status, eb_summary = "caution", f"{len(at_risk)} error budgets at risk for the owning service"
        else:
            eb_status, eb_summary = "safe", "Error budgets of the owning service are healthy"
        eb_verdict = SafetyVerdict(
            step="error_budget_gate",
            status=eb_status,
            summary=eb_summary,
            details={
                "service_ids": service_ids,
                "at_risk_count": len(at_risk),
                "statuses": [eb["status"] for eb in at_risk],
            },
        )
    verdicts.append(eb_verdict)

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
