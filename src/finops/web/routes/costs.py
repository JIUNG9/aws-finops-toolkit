"""Cost tracking routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from finops.db.database import Database
from finops.web.deps import get_db

router = APIRouter(tags=["costs"])


async def _scan_totals(db: Database, scan_id: str):
    return await db.fetchone(
        """SELECT
            COALESCE(SUM(current_monthly_cost), 0) as total_current_cost,
            COALESCE(SUM(estimated_monthly_savings), 0) as total_savings_found,
            COUNT(*) as total_findings
        FROM findings
        WHERE scan_id = ?""",
        (scan_id,),
    )


@router.get("/costs/overview")
async def cost_overview(db: Database = Depends(get_db)):
    """Totals from the latest scan's findings, compared with the scan before it.

    The delta fields are null when there is no earlier scan, and delta_pct is
    also null when the earlier scan's cost is 0, so a missing baseline is never
    reported as a change.
    """
    scans = await db.fetchall("SELECT id FROM scans ORDER BY created_at DESC, rowid DESC LIMIT 2")
    current = await _scan_totals(db, scans[0]["id"]) if scans else None
    previous = await _scan_totals(db, scans[1]["id"]) if len(scans) > 1 else None

    current_cost = current["total_current_cost"] if current else 0
    previous_cost = previous["total_current_cost"] if previous else None
    delta = None
    delta_pct = None
    if previous_cost is not None:
        delta = current_cost - previous_cost
        if previous_cost:
            delta_pct = round(delta / previous_cost * 100, 1)
    return {
        "current_period_cost": current_cost,
        "previous_period_cost": previous_cost,
        "delta": delta,
        "delta_pct": delta_pct,
        "total_savings_found": current["total_savings_found"] if current else 0,
        "total_findings": current["total_findings"] if current else 0,
    }


@router.get("/costs/by-account")
async def cost_by_account(db: Database = Depends(get_db)):
    rows = await db.fetchall(
        """SELECT
            f.account_id,
            ca.name as account_name,
            SUM(f.current_monthly_cost) as cost,
            SUM(f.estimated_monthly_savings) as savings
        FROM findings f
        LEFT JOIN cloud_accounts ca ON f.account_id = ca.id
        WHERE f.scan_id = (SELECT id FROM scans ORDER BY created_at DESC LIMIT 1)
        GROUP BY f.account_id"""
    )
    return rows


@router.get("/costs/trend")
async def cost_trend(days: int = 90, db: Database = Depends(get_db)):
    rows = await db.fetchall(
        """SELECT snapshot_date, SUM(total_cost) as cost
        FROM cost_snapshots
        WHERE snapshot_date >= date('now', ? || ' days')
        GROUP BY snapshot_date
        ORDER BY snapshot_date""",
        (f"-{days}",),
    )
    return rows


@router.get("/costs/comparison")
async def cost_comparison(db: Database = Depends(get_db)):
    # Compare latest two scans
    scans = await db.fetchall(
        "SELECT id, created_at FROM scans WHERE status = 'completed' ORDER BY created_at DESC LIMIT 2"
    )
    if len(scans) < 2:
        return {"before": {}, "after": {}, "delta": {}}

    after_findings = await db.fetchall(
        "SELECT check_name, SUM(estimated_monthly_savings) as savings"
        " FROM findings WHERE scan_id = ? GROUP BY check_name",
        (scans[0]["id"],),
    )
    before_findings = await db.fetchall(
        "SELECT check_name, SUM(estimated_monthly_savings) as savings"
        " FROM findings WHERE scan_id = ? GROUP BY check_name",
        (scans[1]["id"],),
    )
    return {"before": before_findings, "after": after_findings}
