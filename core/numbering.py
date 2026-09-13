"""SQLite-backed, financial-year-aware invoice numbering."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from config import DATABASE_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_counter (
    financial_year TEXT PRIMARY KEY,
    last_number INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS invoice_log (
    invoice_no TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    grand_total REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'issued' CHECK(status IN ('issued', 'cancelled'))
);
"""


def financial_year(on_date: date | None = None) -> str:
    """Return India's Apr–Mar financial-year label, e.g. ``25-26``."""
    current = on_date or date.today()
    start_year = current.year if current.month >= 4 else current.year - 1
    return f"{start_year % 100:02d}-{(start_year + 1) % 100:02d}"


def _validate_prefix(prefix: str) -> str:
    cleaned = (prefix or "").strip().upper()
    if not cleaned or not cleaned.replace("-", "").isalnum() or len(cleaned) > 5:
        raise ValueError("Invoice prefix must be 1–5 letters, digits, or hyphens")
    return cleaned


@contextmanager
def _connection(db_path: str | Path = DATABASE_PATH) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(SCHEMA)
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(db_path: str | Path = DATABASE_PATH) -> None:
    """Create the local state tables if this is the first run."""
    with _connection(db_path):
        pass


def _allocate_number(
    connection: sqlite3.Connection, prefix: str, on_date: date | None
) -> str:
    fy = financial_year(on_date)
    # IMMEDIATE serializes concurrent local requests before reading the counter.
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute(
        "SELECT last_number FROM invoice_counter WHERE financial_year = ?", (fy,)
    ).fetchone()
    next_number = (int(row["last_number"]) if row else 0) + 1
    connection.execute(
        "INSERT INTO invoice_counter(financial_year, last_number) VALUES(?, ?) "
        "ON CONFLICT(financial_year) DO UPDATE SET last_number = excluded.last_number",
        (fy, next_number),
    )
    return f"{prefix}/{fy}/{next_number:04d}"


def next_invoice_number(
    prefix: str = "INV", db_path: str | Path = DATABASE_PATH, as_of: date | None = None
) -> str:
    """Persist and return the next sequential number for the current FY.

    Use ``create_invoice_record`` in the Flask request path so the allocation
    and invoice-history record commit together.
    """
    with _connection(db_path) as connection:
        return _allocate_number(connection, _validate_prefix(prefix), as_of)


def create_invoice_record(
    customer_name: str,
    grand_total: Decimal | float | str,
    *,
    prefix: str = "INV",
    db_path: str | Path = DATABASE_PATH,
    as_of: date | None = None,
) -> str:
    """Allocate and log an issued invoice in the same SQLite transaction."""
    if not str(customer_name).strip():
        raise ValueError("Customer name is required")
    amount = Decimal(str(grand_total)).quantize(Decimal("0.01"))
    if amount < 0:
        raise ValueError("Grand total cannot be negative")

    with _connection(db_path) as connection:
        invoice_no = _allocate_number(connection, _validate_prefix(prefix), as_of)
        connection.execute(
            "INSERT INTO invoice_log(invoice_no, created_at, customer_name, grand_total, status) "
            "VALUES (?, ?, ?, ?, 'issued')",
            (
                invoice_no,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                str(customer_name).strip(),
                float(amount),
            ),
        )
        return invoice_no


def mark_cancelled(invoice_no: str, db_path: str | Path = DATABASE_PATH) -> None:
    """Mark an invoice cancelled while retaining its permanently used number."""
    with _connection(db_path) as connection:
        cursor = connection.execute(
            "UPDATE invoice_log SET status = 'cancelled' WHERE invoice_no = ?", (invoice_no,)
        )
        if cursor.rowcount != 1:
            raise ValueError("Invoice number was not found")


def invoice_history(db_path: str | Path = DATABASE_PATH) -> list[dict[str, object]]:
    """Return local issued/cancelled history, newest record first."""
    with _connection(db_path) as connection:
        rows = connection.execute(
            "SELECT invoice_no, created_at, customer_name, grand_total, status "
            "FROM invoice_log ORDER BY created_at DESC, invoice_no DESC"
        ).fetchall()
    return [dict(row) for row in rows]
