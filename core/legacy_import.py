"""Safe, one-time legacy data import from invoice_log and invoice_counter."""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from core.numbering import financial_year
from core.security import record_audit_log


FY_PATTERN = re.compile(r"/(\d{2}-\d{2})/")


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
    ).fetchone()
    return row is not None


def get_unmigrated_legacy_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    """Return unmigrated legacy invoice/counter info without modifying legacy tables."""
    imported = connection.execute("SELECT 1 FROM legacy_imports WHERE id = 1").fetchone()
    if imported is not None:
        return {"pending": False, "invoice_numbers": [], "count": 0}

    logs: list[sqlite3.Row] = []
    counters: list[sqlite3.Row] = []
    if _table_exists(connection, "invoice_log"):
        logs = connection.execute(
            "SELECT invoice_no, created_at, customer_name, grand_total, status FROM invoice_log ORDER BY created_at ASC, invoice_no ASC"
        ).fetchall()
    if _table_exists(connection, "invoice_counter"):
        counters = connection.execute(
            "SELECT financial_year, last_number FROM invoice_counter ORDER BY financial_year ASC"
        ).fetchall()

    if not logs and not counters:
        return {"pending": False, "invoice_numbers": [], "count": 0}

    return {
        "pending": True,
        "invoice_numbers": [row["invoice_no"] for row in logs],
        "count": len(logs),
        "counters": [(row["financial_year"], int(row["last_number"])) for row in counters],
    }


def _parse_fy(invoice_no: str, created_at: str) -> str:
    match = FY_PATTERN.search(invoice_no or "")
    if match:
        return match.group(1)
    try:
        return financial_year(date.fromisoformat(created_at[:10]))
    except ValueError:
        return financial_year()


def _float_to_paise(amount: float | str | Decimal) -> int:
    rupees = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(rupees * 100)


def import_legacy_data_into_company(
    connection: sqlite3.Connection,
    *,
    company_id: int,
    workspace_id: int,
    user_id: int,
    company_prefix: str,
) -> int:
    """Import legacy invoice_log & invoice_counter into the given company atomically."""
    already = connection.execute("SELECT 1 FROM legacy_imports WHERE id = 1").fetchone()
    if already is not None:
        return 0

    summary = get_unmigrated_legacy_summary(connection)
    if not summary["pending"]:
        return 0

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if _table_exists(connection, "invoice_counter"):
        counters = connection.execute(
            "SELECT financial_year, last_number FROM invoice_counter"
        ).fetchall()
        for row in counters:
            connection.execute(
                """
                INSERT INTO number_series(company_id, document_type, financial_year, prefix, last_number)
                VALUES (?, 'invoice', ?, ?, ?)
                ON CONFLICT(company_id, document_type, financial_year)
                DO UPDATE SET last_number = MAX(number_series.last_number, excluded.last_number)
                """,
                (company_id, row["financial_year"], company_prefix, int(row["last_number"])),
            )

    imported_count = 0
    if _table_exists(connection, "invoice_log"):
        logs = connection.execute(
            "SELECT invoice_no, created_at, customer_name, grand_total, status FROM invoice_log"
        ).fetchall()
        for row in logs:
            invoice_no = str(row["invoice_no"])
            created_at = str(row["created_at"])
            invoice_date = created_at[:10] if len(created_at) >= 10 else date.today().isoformat()
            fy = _parse_fy(invoice_no, created_at)
            grand_total_paise = _float_to_paise(row["grand_total"])
            status = str(row["status"])

            # Insert as draft first, then transition to issued/cancelled to respect triggers.
            cursor = connection.execute(
                """
                INSERT INTO invoices(
                    company_id, customer_id, invoice_no, financial_year, invoice_date,
                    doc_status, customer_name, grand_total_paise, legacy, created_at, updated_at
                )
                VALUES (?, NULL, NULL, ?, ?, 'draft', ?, ?, 1, ?, ?)
                """,
                (
                    company_id,
                    fy,
                    invoice_date,
                    str(row["customer_name"]),
                    grand_total_paise,
                    created_at,
                    created_at,
                ),
            )
            invoice_id = cursor.lastrowid
            if status == "cancelled":
                connection.execute(
                    """
                    UPDATE invoices
                    SET doc_status = 'cancelled',
                        invoice_no = ?,
                        cancelled_at = ?,
                        cancel_reason = 'Legacy cancelled invoice',
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (invoice_no, created_at, now_iso, invoice_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE invoices
                    SET doc_status = 'issued',
                        invoice_no = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (invoice_no, now_iso, invoice_id),
                )
            imported_count += 1

    connection.execute(
        "INSERT INTO legacy_imports(id, company_id, imported_count, imported_at) VALUES (1, ?, ?, ?)",
        (company_id, imported_count, now_iso),
    )
    record_audit_log(
        connection,
        workspace_id=workspace_id,
        company_id=company_id,
        user_id=user_id,
        action="legacy_import",
        entity="company",
        entity_id=company_id,
        details={"imported_count": imported_count},
    )
    return imported_count
