"""Alert service — Slack webhook notifications."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from finops.db.database import Database

logger = logging.getLogger(__name__)


async def create_alert(db: Database, name: str, alert_type: str,
                       channel: str = "slack", config: dict = None) -> dict:
    """Create an alert configuration."""
    alert_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO alerts (id, name, alert_type, channel, config) VALUES (?, ?, ?, ?, ?)",
        (alert_id, name, alert_type, channel, json.dumps(config or {})),
    )
    await db.commit()
    return {"id": alert_id, "name": name, "alert_type": alert_type, "channel": channel}


async def check_budget_alerts(db: Database) -> list[dict]:
    """Check all budgets and fire alerts if thresholds are breached."""
    alerts = await db.fetchall("SELECT * FROM alerts WHERE alert_type = 'budget' AND enabled = 1")
    budgets = await db.fetchall("SELECT * FROM budgets")
    triggered = []

    for budget in budgets:
        if budget["budget_amount"] <= 0:
            continue
        usage_pct = budget["actual_amount"] / budget["budget_amount"] * 100
        if usage_pct >= budget["alert_threshold_pct"]:
            for alert in alerts:
                config = json.loads(alert.get("config", "{}"))
                webhook_url = config.get("webhook_url", "")
                if webhook_url:
                    message = {
                        "text": (
                            f"Budget Alert: {budget['name']} is at {usage_pct:.0f}%"
                            f" (${budget['actual_amount']:.0f}/${budget['budget_amount']:.0f})"
                        )
                    }
                    triggered.append({"alert_id": alert["id"], "budget": budget["name"], "usage_pct": usage_pct})
                    await _send_slack(webhook_url, message)
                    await db.execute(
                        "UPDATE alerts SET last_triggered = ? WHERE id = ?",
                        (datetime.now(timezone.utc).isoformat(), alert["id"]),
                    )

    if triggered:
        await db.commit()
    return triggered


async def check_error_budget_alerts(db: Database) -> list[dict]:
    """Check error budgets and fire alerts if burn rate is high."""
    alerts = await db.fetchall("SELECT * FROM alerts WHERE alert_type = 'error_budget' AND enabled = 1")
    budgets = await db.fetchall(
        "SELECT eb.*, s.name as service_name FROM error_budgets eb LEFT JOIN services s ON eb.service_id = s.id"
    )
    triggered = []

    for eb in budgets:
        if eb["budget_total_minutes"] <= 0:
            continue
        remaining_pct = 100 * (1 - eb["budget_consumed_minutes"] / eb["budget_total_minutes"])
        if remaining_pct < 30:
            for alert in alerts:
                config = json.loads(alert.get("config", "{}"))
                webhook_url = config.get("webhook_url", "")
                if webhook_url:
                    message = {
                        "text": (
                            f"Error Budget Alert: {eb.get('service_name', 'Unknown')}"
                            f" at {remaining_pct:.0f}% remaining ({eb['status']})"
                        )
                    }
                    triggered.append({
                        "alert_id": alert["id"],
                        "service": eb.get("service_name"),
                        "remaining_pct": remaining_pct,
                    })
                    await _send_slack(webhook_url, message)

    return triggered


async def _send_slack(webhook_url: str, message: dict) -> bool:
    """Send a message to Slack via webhook."""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=message, timeout=10)
            return response.status_code == 200
    except Exception as e:
        logger.error(f"Slack notification failed: {e}")
        return False
