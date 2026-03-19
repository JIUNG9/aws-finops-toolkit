"""Scanner service — orchestrates async scans."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from finops.db.database import Database


DEMO_FINDINGS = [
    {"check_name": "ec2_rightsizing", "resource_type": "EC2 Instance", "resource_id": "i-0abc123def456",
     "resource_name": "api-server-prod-1", "severity": "high", "current_monthly_cost": 156.0,
     "estimated_monthly_savings": 78.0, "recommended_action": "Downsize from m5.xlarge to m5.large — avg CPU 12% over 14 days"},
    {"check_name": "ec2_rightsizing", "resource_type": "EC2 Instance", "resource_id": "i-0def456abc789",
     "resource_name": "worker-staging-2", "severity": "medium", "current_monthly_cost": 73.0,
     "estimated_monthly_savings": 36.5, "recommended_action": "Downsize from t3.large to t3.medium — avg CPU 8%"},
    {"check_name": "nat_gateway", "resource_type": "NAT Gateway", "resource_id": "nat-0abc123",
     "resource_name": "nat-dev-us-east-1a", "severity": "high", "current_monthly_cost": 32.0,
     "estimated_monthly_savings": 27.0, "recommended_action": "Replace with NAT Instance — dev env, 0 bytes processed last 14 days"},
    {"check_name": "unused_resources", "resource_type": "EBS Volume", "resource_id": "vol-0abc123",
     "resource_name": "unattached-vol-old-api", "severity": "low", "current_monthly_cost": 12.0,
     "estimated_monthly_savings": 12.0, "recommended_action": "Delete unattached EBS volume — no attachment in 45 days"},
    {"check_name": "unused_resources", "resource_type": "Elastic IP", "resource_id": "eipalloc-0abc123",
     "resource_name": "old-bastion-eip", "severity": "low", "current_monthly_cost": 3.6,
     "estimated_monthly_savings": 3.6, "recommended_action": "Release unused EIP — not attached to any instance"},
    {"check_name": "rds_rightsizing", "resource_type": "RDS Instance", "resource_id": "prod-orders-db",
     "resource_name": "prod-orders-db", "severity": "high", "current_monthly_cost": 420.0,
     "estimated_monthly_savings": 140.0, "recommended_action": "Downsize from db.r6g.xlarge to db.r6g.large — avg CPU 15%, memory 40%"},
    {"check_name": "cloudwatch_waste", "resource_type": "Log Group", "resource_id": "/aws/lambda/old-function",
     "resource_name": "/aws/lambda/old-function", "severity": "medium", "current_monthly_cost": 25.0,
     "estimated_monthly_savings": 25.0, "recommended_action": "Delete orphan log group — Lambda function deleted 90+ days ago"},
    {"check_name": "s3_lifecycle", "resource_type": "S3 Bucket", "resource_id": "company-data-lake",
     "resource_name": "company-data-lake", "severity": "medium", "current_monthly_cost": 180.0,
     "estimated_monthly_savings": 54.0, "recommended_action": "Add lifecycle policy — transition to IA after 30 days, Glacier after 90"},
    {"check_name": "vpc_waste", "resource_type": "VPC", "resource_id": "vpc-old-staging",
     "resource_name": "old-staging-vpc", "severity": "high", "current_monthly_cost": 64.0,
     "estimated_monthly_savings": 64.0, "recommended_action": "Delete abandoned VPC — no running instances, NAT GW still billing"},
    {"check_name": "reserved_instances", "resource_type": "RI Recommendation", "resource_id": "ri-suggestion-1",
     "resource_name": "m5.large x 4 (1yr No Upfront)", "severity": "info", "current_monthly_cost": 584.0,
     "estimated_monthly_savings": 175.0, "recommended_action": "Purchase 4x m5.large RIs — stable on-demand usage for 6+ months"},
]


async def create_demo_scan(db: Database) -> str:
    """Create a demo scan with realistic findings."""
    scan_id = str(uuid.uuid4())
    account_id = "demo-account"
    now = datetime.now(timezone.utc).isoformat()

    # Ensure demo account exists
    existing = await db.fetchone("SELECT id FROM cloud_accounts WHERE id = ?", (account_id,))
    if not existing:
        await db.execute(
            "INSERT INTO cloud_accounts (id, provider, name, config) VALUES (?, ?, ?, ?)",
            (account_id, "aws", "Demo Account", '{"profile": "demo"}'),
        )

    total_savings = sum(f["estimated_monthly_savings"] for f in DEMO_FINDINGS)
    await db.execute(
        """INSERT INTO scans (id, account_id, status, started_at, completed_at,
        total_findings, total_monthly_savings, checks_run)
        VALUES (?, ?, 'completed', ?, ?, ?, ?, ?)""",
        (scan_id, account_id, now, now, len(DEMO_FINDINGS), total_savings,
         json.dumps(["ec2_rightsizing", "nat_gateway", "unused_resources", "rds_rightsizing",
                      "cloudwatch_waste", "s3_lifecycle", "vpc_waste", "reserved_instances"])),
    )

    for f in DEMO_FINDINGS:
        finding_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO findings (id, scan_id, account_id, check_name, resource_type,
            resource_id, resource_name, severity, current_monthly_cost,
            estimated_monthly_savings, recommended_action)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (finding_id, scan_id, account_id, f["check_name"], f["resource_type"],
             f["resource_id"], f["resource_name"], f["severity"], f["current_monthly_cost"],
             f["estimated_monthly_savings"], f["recommended_action"]),
        )

    await db.commit()
    return scan_id


async def create_demo_error_budgets(db: Database) -> None:
    """Create demo error budgets for services."""
    services = [
        ("gateway", "P0", 99.95, 21.6, 3.2),
        ("orders-api", "P0", 99.9, 43.2, 8.5),
        ("user-service", "P1", 99.9, 43.2, 1.0),
        ("admin-panel", "P2", 99.5, 216.0, 0.0),
    ]
    for name, priority, slo, total_min, consumed_min in services:
        svc_id = str(uuid.uuid4())
        await db.execute(
            "INSERT OR IGNORE INTO services (id, name, priority) VALUES (?, ?, ?)",
            (svc_id, name, priority),
        )
        remaining_pct = max(0, 100 * (1 - consumed_min / total_min)) if total_min > 0 else 100
        status = "healthy" if remaining_pct > 50 else ("warning" if remaining_pct > 20 else "critical")
        eb_id = str(uuid.uuid4())
        await db.execute(
            """INSERT INTO error_budgets (id, service_id, period_type, period_start, period_end,
            slo_target_pct, budget_total_minutes, budget_consumed_minutes, status)
            VALUES (?, ?, 'monthly', '2026-04-01', '2026-05-01', ?, ?, ?, ?)""",
            (eb_id, svc_id, slo, total_min, consumed_min, status),
        )
    await db.commit()


async def create_demo_budgets(db: Database) -> None:
    """Create demo financial budgets."""
    budgets_data = [
        ("Production AWS", 15000, 11200),
        ("Staging AWS", 3000, 2800),
        ("Dev AWS", 2000, 1100),
    ]
    for name, amount, actual in budgets_data:
        b_id = str(uuid.uuid4())
        usage_pct = actual / amount * 100
        status = "on_track" if usage_pct < 80 else ("warning" if usage_pct < 100 else "over_budget")
        await db.execute(
            """INSERT INTO budgets (id, name, period_type, period_start, period_end,
            budget_amount, actual_amount, forecasted_amount, status)
            VALUES (?, ?, 'monthly', '2026-04-01', '2026-05-01', ?, ?, ?, ?)""",
            (b_id, name, amount, actual, actual * 1.1, status),
        )
    await db.commit()


async def seed_demo_data(db: Database) -> None:
    """Seed all demo data."""
    # Check if demo data already exists
    existing = await db.fetchone("SELECT COUNT(*) as cnt FROM scans")
    if existing and existing["cnt"] > 0:
        return
    await create_demo_scan(db)
    await create_demo_error_budgets(db)
    await create_demo_budgets(db)
