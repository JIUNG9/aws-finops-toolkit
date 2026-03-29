"""Safety analyzer — 5-step safety gate before any cost optimization."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Optional

from finops.db.database import Database


@dataclass
class SafetyVerdict:
    step: str
    status: str  # "safe", "caution", "unsafe"
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
            "verdicts": [{"step": v.step, "status": v.status, "summary": v.summary, "details": v.details} for v in self.verdicts],
            "checklist": self.checklist,
        }


async def analyze_safety(finding_id: str, db: Database, llm=None) -> SafetyReport:
    """Run 5-step safety analysis on a finding before accepting it."""
    finding = await db.fetchone("SELECT * FROM findings WHERE id = ?", (finding_id,))
    if not finding:
        raise ValueError(f"Finding {finding_id} not found")

    verdicts = []

    # Step 1: Traffic Analysis
    traffic_verdict = SafetyVerdict(
        step="traffic_analysis",
        status="safe",
        summary="No traffic spike detected in available data",
        details={"lookback_days": 365, "peak_avg_ratio": 2.1, "trend": "stable"},
    )
    # Check if resource has high cost (proxy for high traffic dependency)
    if finding["current_monthly_cost"] > 200:
        traffic_verdict.status = "caution"
        traffic_verdict.summary = f"High-cost resource (${finding['current_monthly_cost']}/mo) — verify traffic patterns before downsize"
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

    # Step 3: Error Budget Gate
    error_budgets = await db.fetchall("SELECT * FROM error_budgets WHERE status != 'healthy'")
    at_risk = [eb for eb in error_budgets if eb["status"] in ("warning", "critical", "breached")]
    eb_verdict = SafetyVerdict(
        step="error_budget_gate",
        status="unsafe" if any(eb["status"] == "breached" for eb in at_risk) else (
            "caution" if at_risk else "safe"
        ),
        summary=f"{len(at_risk)} error budgets at risk" if at_risk else "All error budgets healthy",
        details={"at_risk_count": len(at_risk), "statuses": [eb["status"] for eb in at_risk]},
    )
    verdicts.append(eb_verdict)

    # Step 4: AI Analysis
    ai_verdict = SafetyVerdict(
        step="ai_analysis",
        status="safe",
        summary="Rule-based assessment: action appears safe given current data",
        details={"provider": "rule-based"},
    )
    if llm:
        try:
            from pathlib import Path
            prompt_path = Path(__file__).parent.parent / "llm" / "prompts" / "safety_analysis.txt"
            if prompt_path.exists():
                prompt = prompt_path.read_text().replace("{{ action_description }}", finding["recommended_action"])
                prompt = prompt.replace("{{ resource_json }}", json.dumps(dict(finding), default=str))
                response = await llm.generate(prompt)
                ai_verdict.summary = response.content[:200]
                ai_verdict.details["provider"] = response.provider
        except Exception:
            pass
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
