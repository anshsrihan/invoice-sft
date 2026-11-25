"""Versioned, atomic SQLite migration runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
import sqlite3

from config import DATABASE_PATH
from db.connection import get_connection, transaction
from db.versions import MIGRATIONS


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    upgrade: Callable[[sqlite3.Connection], None]


SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def apply_migrations(
    db_path: str | Path = DATABASE_PATH,
    migrations: Iterable[Migration] | None = None,
) -> list[int]:
    """Apply pending migrations atomically; return newly applied version numbers."""
    ordered = sorted(
        migrations if migrations is not None else [Migration(*item) for item in MIGRATIONS],
        key=lambda m: m.version,
    )
    applied_now: list[int] = []
    connection = get_connection(db_path)
    try:
        connection.execute(SCHEMA_MIGRATIONS_SQL)
        rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
        existing = {int(row["version"]) for row in rows}

        for migration in ordered:
            if migration.version in existing:
                continue
            with transaction(connection, immediate=True):
                migration.upgrade(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                    (migration.version, migration.name, _utc_now_iso()),
                )
            applied_now.append(migration.version)
            existing.add(migration.version)
        return applied_now
    finally:
        connection.close()
