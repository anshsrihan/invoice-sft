"""SQLite connection helpers with foreign keys, WAL mode, and explicit transactions."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from config import DATABASE_PATH


def get_connection(db_path: str | Path = DATABASE_PATH) -> sqlite3.Connection:
    """Open a SQLite connection configured for strict integrity and concurrency."""
    connection = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA busy_timeout = 5000;")
    return connection


@contextmanager
def transaction(
    connection: sqlite3.Connection, *, immediate: bool = False
) -> Iterator[sqlite3.Connection]:
    """Run statements inside an explicit SQLite transaction."""
    if connection.in_transaction:
        yield connection
        return

    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield connection
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


@contextmanager
def db_session(
    db_path: str | Path = DATABASE_PATH, *, immediate: bool = False
) -> Iterator[sqlite3.Connection]:
    """Open a configured SQLite connection, run an atomic transaction, and close it."""
    connection = get_connection(db_path)
    try:
        with transaction(connection, immediate=immediate):
            yield connection
    finally:
        connection.close()


def execute_sql_statements(connection: sqlite3.Connection, sql: str) -> None:
    """Execute multi-statement DDL inside an active transaction without implicit commits."""
    buffer: list[str] = []
    for line in sql.splitlines(keepends=True):
        buffer.append(line)
        chunk = "".join(buffer)
        if sqlite3.complete_statement(chunk):
            statement = chunk.strip()
            if statement:
                connection.execute(statement)
            buffer.clear()
    leftover = "".join(buffer).strip()
    if leftover:
        connection.execute(leftover)
