"""SQLite-backed, financial-year-aware invoice numbering."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

from config import DATABASE_PATH, MAX_INVOICE_NO_LENGTH


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
    """LEGACY: retained for existing tests; remove in Phase 2."""
    with _connection(db_path) as connection:
        rows = connection.execute(
            "SELECT invoice_no, created_at, customer_name, grand_total, status "
            "FROM invoice_log ORDER BY created_at DESC, invoice_no DESC"
        ).fetchall()
    return [dict(row) for row in rows]


# --- Phase 1: Company-scoped numbering and invoice persistence ---


def to_paise(value: Decimal | float | str) -> int:
    """Convert a monetary amount in rupees to integer paise using half-up rounding."""
    rupees = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(rupees * 100)


def allocate_company_invoice_number(
    connection: sqlite3.Connection,
    *,
    company_id: int,
    prefix: str,
    on_date: date | None = None,
    document_type: str = "invoice",
) -> tuple[str, str]:
    """Allocate the next sequential number for a company and FY inside an active transaction."""
    cleaned_prefix = _validate_prefix(prefix)
    fy = financial_year(on_date)
    row = connection.execute(
        """
        SELECT last_number FROM number_series
        WHERE company_id = ? AND document_type = ? AND financial_year = ?
        """,
        (company_id, document_type, fy),
    ).fetchone()
    next_number = (int(row["last_number"]) if row else 0) + 1
    invoice_no = f"{cleaned_prefix}/{fy}/{next_number:04d}"
    if len(invoice_no) > MAX_INVOICE_NO_LENGTH:
        raise ValueError(f"Generated invoice number '{invoice_no}' exceeds {MAX_INVOICE_NO_LENGTH} characters")

    connection.execute(
        """
        INSERT INTO number_series(company_id, document_type, financial_year, prefix, last_number)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(company_id, document_type, financial_year)
        DO UPDATE SET last_number = excluded.last_number, prefix = excluded.prefix
        """,
        (company_id, document_type, fy, cleaned_prefix, next_number),
    )
    return invoice_no, fy


def issue_company_invoice(
    connection: sqlite3.Connection,
    *,
    company: dict[str, Any],
    payload: dict[str, Any],
    totals: dict[str, Any],
    seller_snapshot: dict[str, Any],
    buyer_snapshot: dict[str, Any],
) -> tuple[int, str]:
    """Insert draft -> insert items -> update to issued in one atomic transaction."""
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inv_date = date.fromisoformat(payload["invoice_date"])
    invoice_no, fy = allocate_company_invoice_number(
        connection,
        company_id=int(company["id"]),
        prefix=str(company["invoice_prefix"]),
        on_date=inv_date,
    )

    # 1. Insert as draft with invoice_no = NULL to satisfy immutability triggers.
    cursor = connection.execute(
        """
        INSERT INTO invoices(
            company_id, customer_id, invoice_no, financial_year, invoice_date,
            doc_status, customer_name, place_of_supply, legacy, created_at, updated_at
        )
        VALUES (?, NULL, NULL, ?, ?, 'draft', ?, ?, 0, ?, ?)
        """,
        (
            int(company["id"]),
            fy,
            payload["invoice_date"],
            payload["buyer_name"],
            payload["place_of_supply"],
            now_iso,
            now_iso,
        ),
    )
    invoice_id = int(cursor.lastrowid)

    # 2. Insert line items while invoice is still 'draft'.
    for index, item in enumerate(totals["items"], start=1):
        connection.execute(
            """
            INSERT INTO invoice_items(
                invoice_id, line_order, description, hsn_sac, quantity, unit,
                unit_price, discount_paise, taxable_value_paise, gst_rate,
                cgst_paise, sgst_paise, igst_paise, cess_paise, total_paise
            )
            VALUES (?, ?, ?, ?, ?, '', ?, 0, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                invoice_id,
                index,
                item["description"],
                item["hsn_sac"],
                str(item["quantity"]),
                str(item["unit_price"]),
                to_paise(item["taxable_value"]),
                str(item["rate_pct"]),
                to_paise(item["cgst"]),
                to_paise(item["sgst"]),
                to_paise(item["igst"]),
                to_paise(item["total"]),
            ),
        )

    # 3. Transition to 'issued' with allocated number, snapshots, and paise totals.
    connection.execute(
        """
        UPDATE invoices
        SET doc_status = 'issued',
            invoice_no = ?,
            seller_snapshot = ?,
            buyer_snapshot = ?,
            taxable_total_paise = ?,
            cgst_total_paise = ?,
            sgst_total_paise = ?,
            igst_total_paise = ?,
            grand_total_paise = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            invoice_no,
            json.dumps(seller_snapshot, sort_keys=True),
            json.dumps(buyer_snapshot, sort_keys=True),
            to_paise(totals["taxable_total"]),
            to_paise(totals["cgst_total"]),
            to_paise(totals["sgst_total"]),
            to_paise(totals["igst_total"]),
            to_paise(totals["grand_total"]),
            now_iso,
            invoice_id,
        ),
    )
    return invoice_id, invoice_no


def list_company_invoices(connection: sqlite3.Connection, company_id: int) -> list[dict[str, Any]]:
    """Return issued/cancelled invoices for a single company, newest first."""
    rows = connection.execute(
        """
        SELECT id, invoice_no, invoice_date, created_at, customer_name,
               grand_total_paise, doc_status AS status, legacy, cancel_reason
        FROM invoices
        WHERE company_id = ? AND doc_status != 'draft'
        ORDER BY created_at DESC, id DESC
        """,
        (int(company_id),),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["grand_total"] = Decimal(item["grand_total_paise"]) / Decimal("100")
        result.append(item)
    return result


def cancel_company_invoice(
    connection: sqlite3.Connection,
    *,
    company_id: int,
    invoice_no: str,
    reason: str = "Cancelled by user",
) -> None:
    """Cancel an issued invoice belonging to company_id without freeing its number."""
    cleaned_reason = (reason or "").strip() or "Cancelled by user"
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row = connection.execute(
        "SELECT id, doc_status FROM invoices WHERE company_id = ? AND invoice_no = ?",
        (int(company_id), invoice_no),
    ).fetchone()
    if not row:
        raise ValueError("Invoice number was not found")
    if row["doc_status"] != "issued":
        raise ValueError("Only issued invoices can be cancelled")

    connection.execute(
        """
        UPDATE invoices
        SET doc_status = 'cancelled',
            cancelled_at = ?,
            cancel_reason = ?,
            updated_at = ?
        WHERE id = ? AND company_id = ?
        """,
        (now_iso, cleaned_reason, now_iso, int(row["id"]), int(company_id)),
    )
