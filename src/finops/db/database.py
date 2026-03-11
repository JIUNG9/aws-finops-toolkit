"""SQLite database connection manager using aiosqlite."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import aiosqlite


class Database:
    """Async SQLite database wrapper."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

    async def disconnect(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        return await self.conn.execute(sql, params)

    async def executemany(self, sql: str, params_list: list[tuple]) -> aiosqlite.Cursor:
        return await self.conn.executemany(sql, params_list)

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        cursor = await self.conn.execute(sql, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def commit(self) -> None:
        await self.conn.commit()

    async def run_migrations(self) -> None:
        migrations_dir = Path(__file__).parent.parent.parent.parent / "migrations"
        if not migrations_dir.exists():
            migrations_dir = Path(__file__).parent.parent.parent / "migrations"

        for sql_file in sorted(migrations_dir.glob("*.sql")):
            sql = sql_file.read_text()
            await self.conn.executescript(sql)
        await self.commit()
