"""AI recommendation and safety analysis routes."""

from __future__ import annotations

import json
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException

from finops.db.database import Database
from finops.web.deps import get_db
from finops.web.schemas import AIRecommendationOut

router = APIRouter(tags=["ai"])


@router.get("/ai/recommendations", response_model=list[AIRecommendationOut])
async def list_recommendations(status: str = None, db: Database = Depends(get_db)):
    sql = "SELECT * FROM ai_recommendations"
    params = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    return await db.fetchall(sql, tuple(params))


@router.post("/ai/analyze", status_code=201)
async def trigger_analysis(db: Database = Depends(get_db)):
    """Trigger AI analysis on latest scan findings."""
    findings = await db.fetchall(
        """SELECT * FROM findings WHERE status = 'open'
        ORDER BY estimated_monthly_savings DESC LIMIT 20"""
    )
    if not findings:
        return {"message": "No open findings to analyze"}

    # Try to use LLM if configured
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if api_key:
        try:
            from finops.llm.base import get_llm_provider
            provider_name = "claude" if os.environ.get("ANTHROPIC_API_KEY") else "openai"
            llm = get_llm_provider(provider_name, api_key=api_key)
            prompt = f"Analyze these AWS cost findings and provide prioritized recommendations:\n{json.dumps([dict(f) for f in findings[:10]], indent=2)}"
            response = await llm.generate(prompt, system_prompt="You are an SRE cost optimization advisor.")

            rec_id = str(uuid.uuid4())
            await db.execute(
                """INSERT INTO ai_recommendations
                (id, recommendation_type, title, body, severity, llm_provider, llm_model, confidence, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (rec_id, "cost_optimization", "AI Cost Analysis", response.content,
                 "info", response.provider, response.model, 0.85, "pending"),
            )
            await db.commit()
            return {"id": rec_id, "status": "completed", "provider": response.provider}
        except Exception as e:
            pass

    # Fallback: rule-based recommendations
    total_savings = sum(f["estimated_monthly_savings"] for f in findings)
    rec_id = str(uuid.uuid4())
    body = f"## Cost Optimization Summary\n\n"
    body += f"Found **{len(findings)} open findings** with **${total_savings:.0f}/month** in potential savings.\n\n"
    body += "### Top Actions\n"
    for i, f in enumerate(findings[:5], 1):
        body += f"{i}. **{f['check_name']}** — {f['resource_name']}: {f['recommended_action']} (saves ${f['estimated_monthly_savings']:.0f}/mo)\n"

    await db.execute(
        """INSERT INTO ai_recommendations
        (id, recommendation_type, title, body, severity, llm_provider, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (rec_id, "cost_optimization", f"${total_savings:.0f}/mo savings identified",
         body, "info", "rule-based", "pending"),
    )
    await db.commit()
    return {"id": rec_id, "status": "completed", "provider": "rule-based"}


@router.patch("/ai/recommendations/{rec_id}")
async def update_recommendation(rec_id: str, status: str = "accepted", db: Database = Depends(get_db)):
    existing = await db.fetchone("SELECT * FROM ai_recommendations WHERE id = ?", (rec_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    await db.execute("UPDATE ai_recommendations SET status = ? WHERE id = ?", (status, rec_id))
    await db.commit()
    return {"id": rec_id, "status": status}


@router.post("/ai/what-if")
async def what_if_analysis(finding_id: str = "", action: str = "", db: Database = Depends(get_db)):
    """Simulate the impact of accepting a recommendation."""
    finding = await db.fetchone("SELECT * FROM findings WHERE id = ?", (finding_id,)) if finding_id else None

    if not finding:
        return {"error": "Finding not found", "verdict": "unknown"}

    # Check error budget for related service
    error_budgets = await db.fetchall("SELECT * FROM error_budgets")
    budget_ok = all(eb["status"] in ("healthy",) for eb in error_budgets) if error_budgets else True

    savings = finding["estimated_monthly_savings"]
    return {
        "finding": finding["resource_name"],
        "action": finding["recommended_action"],
        "projected_monthly_savings": savings,
        "projected_annual_savings": savings * 12,
        "error_budget_safe": budget_ok,
        "risk_level": "low" if finding["severity"] in ("low", "info") else "medium",
        "recommendation": "Safe to proceed" if budget_ok else "Defer — error budget at risk",
    }
