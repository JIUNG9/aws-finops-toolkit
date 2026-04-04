"""Delegate manager — background scan workers."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from finops.db.database import Database

logger = logging.getLogger(__name__)


class DelegateManager:
    """Manages background data collection workers."""

    def __init__(self, db: Database, max_concurrent: int = 3):
        self.db = db
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.running: dict[str, asyncio.Task] = {}

    async def run_scan(self, account_id: str, scan_id: str, checks: Optional[list[str]] = None) -> None:
        """Run a scan as a background task."""
        task = asyncio.create_task(self._execute_scan(account_id, scan_id, checks))
        self.running[scan_id] = task

    async def _execute_scan(self, account_id: str, scan_id: str, checks: Optional[list[str]] = None) -> None:
        """Execute a scan with semaphore-limited concurrency."""
        async with self.semaphore:
            try:
                now = datetime.now(timezone.utc).isoformat()
                await self.db.execute(
                    "UPDATE scans SET status = 'running', started_at = ? WHERE id = ?",
                    (now, scan_id),
                )
                await self.db.commit()

                # Get account config
                account = await self.db.fetchone(
                    "SELECT * FROM cloud_accounts WHERE id = ?", (account_id,)
                )
                if not account:
                    raise ValueError(f"Account {account_id} not found")

                # TODO: Run actual checks via provider
                # For now, generate demo findings
                findings_count = 0
                total_savings = 0.0

                # Mark scan complete
                completed = datetime.now(timezone.utc).isoformat()
                await self.db.execute(
                    """UPDATE scans SET status = 'completed', completed_at = ?,
                    total_findings = ?, total_monthly_savings = ? WHERE id = ?""",
                    (completed, findings_count, total_savings, scan_id),
                )
                await self.db.commit()
                logger.info(f"Scan {scan_id} completed: {findings_count} findings, ${total_savings}/mo savings")

            except Exception as e:
                logger.error(f"Scan {scan_id} failed: {e}")
                await self.db.execute(
                    "UPDATE scans SET status = 'failed', error_message = ? WHERE id = ?",
                    (str(e), scan_id),
                )
                await self.db.commit()
            finally:
                self.running.pop(scan_id, None)

    def get_status(self, scan_id: str) -> str:
        if scan_id in self.running:
            return "running"
        return "unknown"
