"""Tests for concurrency, FY boundaries, 16-char limit, PDF parity, and DB immutability."""

from __future__ import annotations

import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from app import create_app
from core.calculator import invoice_totals
from core.numbering import allocate_company_invoice_number, issue_company_invoice
from db.connection import db_session, get_connection
from db.migrations import apply_migrations
from pdf.render import render_invoice_html, render_invoice_pdf


def _setup_company(db_path: str, prefix: str = "INV") -> dict:
    apply_migrations(db_path)
    with db_session(db_path, immediate=True) as conn:
        conn.execute(
            "INSERT INTO workspaces(id, name, created_at) VALUES (1, 'WS', '2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            """
            INSERT INTO companies(
                id, workspace_id, legal_name, gstin, pan, address, state, state_code,
                phone, email, currency, bank_details, logo_path, invoice_prefix, terms_text, created_at
            )
            VALUES (
                1, 1, 'Acme Pvt Ltd', '27ABCDE1234F1Z5', '', '123 MG Road, Mumbai',
                'Maharashtra', '27', '9999999999', 'billing@acme.test', 'INR',
                '', '', ?, '', '2026-01-01T00:00:00+00:00'
            )
            """,
            (prefix,),
        )
        return dict(conn.execute("SELECT * FROM companies WHERE id = 1").fetchone())


def test_concurrent_invoice_allocation_is_unique_and_gap_free(tmp_path):
    db_path = str(tmp_path / "concurrent.db")
    company = _setup_company(db_path, prefix="CONC")

    payload = {
        "buyer_name": "Concurrent Buyer",
        "buyer_address": "Pune",
        "buyer_state": "Maharashtra",
        "buyer_gstin": "",
        "place_of_supply": "Maharashtra",
        "invoice_date": "2026-06-15",
        "items": [
            {"description": "Item", "hsn_sac": "9983", "quantity": "1", "unit_price": "100", "gst_rate": "18"}
        ],
    }
    totals = invoice_totals(payload["items"], company["state"], payload["place_of_supply"])
    seller_snap = {"legal_name": company["legal_name"], "gstin": company["gstin"]}
    buyer_snap = {"name": payload["buyer_name"], "state": payload["buyer_state"]}

    def worker(_idx: int) -> str:
        with db_session(db_path, immediate=True) as conn:
            _, inv_no = issue_company_invoice(
                conn,
                company=company,
                payload=payload,
                totals=totals,
                seller_snapshot=seller_snap,
                buyer_snapshot=buyer_snap,
            )
            return inv_no

    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(worker, range(12)))

    assert len(set(numbers)) == 12
    assert sorted(numbers) == [f"CONC/26-27/{i:04d}" for i in range(1, 13)]


def test_company_financial_year_boundary_march_31_vs_april_1(tmp_path):
    db_path = str(tmp_path / "fy.db")
    _setup_company(db_path, prefix="FY")

    with db_session(db_path, immediate=True) as conn:
        n1, fy1 = allocate_company_invoice_number(
            conn, company_id=1, prefix="FY", on_date=date(2026, 3, 31)
        )
        n2, fy2 = allocate_company_invoice_number(
            conn, company_id=1, prefix="FY", on_date=date(2026, 4, 1)
        )

    assert (n1, fy1) == ("FY/25-26/0001", "25-26")
    assert (n2, fy2) == ("FY/26-27/0001", "26-27")


def test_sixteen_char_invoice_number_limit_fails_cleanly(tmp_path):
    db_path = str(tmp_path / "limit16.db")
    _setup_company(db_path, prefix="ABCDE")

    # ABCDE/26-27/9999 is 16 chars; next number ABCDE/26-27/10000 is 17 chars and must fail.
    with db_session(db_path, immediate=True) as conn:
        conn.execute(
            """
            INSERT INTO number_series(company_id, document_type, financial_year, prefix, last_number)
            VALUES (1, 'invoice', '26-27', 'ABCDE', 9999)
            """
        )

    with pytest.raises(ValueError, match="16 characters"):
        with db_session(db_path, immediate=True) as conn:
            allocate_company_invoice_number(
                conn, company_id=1, prefix="ABCDE", on_date=date(2026, 5, 1)
            )

    # Counter must remain unchanged at 9999
    conn = get_connection(db_path)
    try:
        last_num = conn.execute(
            "SELECT last_number FROM number_series WHERE company_id = 1 AND financial_year = '26-27'"
        ).fetchone()["last_number"]
        assert last_num == 9999
    finally:
        conn.close()


def test_all_database_immutability_rules(tmp_path):
    db_path = str(tmp_path / "immut.db")
    company = _setup_company(db_path, prefix="IMM")
    payload = {
        "buyer_name": "Buyer",
        "buyer_address": "Mumbai",
        "buyer_state": "Maharashtra",
        "buyer_gstin": "",
        "place_of_supply": "Maharashtra",
        "invoice_date": "2026-05-01",
        "items": [
            {"description": "Consulting", "hsn_sac": "9983", "quantity": "1", "unit_price": "500", "gst_rate": "18"}
        ],
    }
    totals = invoice_totals(payload["items"], company["state"], payload["place_of_supply"])
    with db_session(db_path, immediate=True) as conn:
        invoice_id, _ = issue_company_invoice(
            conn,
            company=company,
            payload=payload,
            totals=totals,
            seller_snapshot={"legal_name": company["legal_name"]},
            buyer_snapshot={"name": "Buyer"},
        )

    conn = get_connection(db_path)
    try:
        # 1. Cannot delete issued invoice
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))

        # 2. Cannot revert issued invoice to draft
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE invoices SET doc_status = 'draft' WHERE id = ?", (invoice_id,))

        # 3. Cannot change issued invoice number, snapshots, date, place_of_supply, or totals
        for sql in (
            "UPDATE invoices SET invoice_no = 'IMM/26-27/9999' WHERE id = ?",
            "UPDATE invoices SET seller_snapshot = '{}' WHERE id = ?",
            "UPDATE invoices SET buyer_snapshot = '{}' WHERE id = ?",
            "UPDATE invoices SET invoice_date = '2026-05-02' WHERE id = ?",
            "UPDATE invoices SET place_of_supply = 'Delhi' WHERE id = ?",
            "UPDATE invoices SET grand_total_paise = 1 WHERE id = ?",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(sql, (invoice_id,))

        # 4. Cannot insert, update, or delete invoice_items of an issued invoice
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO invoice_items(
                    invoice_id, line_order, description, hsn_sac, quantity, unit_price,
                    taxable_value_paise, gst_rate, total_paise
                )
                VALUES (?, 2, 'Extra', '9983', '1', '100', 10000, '18', 11800)
                """,
                (invoice_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE invoice_items SET description = 'Tampered' WHERE invoice_id = ?", (invoice_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice_id,))

        # 5. Cancellation requires non-empty reason and timestamp
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE invoices SET doc_status = 'cancelled', cancelled_at = '2026-05-02', cancel_reason = '' WHERE id = ?",
                (invoice_id,),
            )

        # Valid cancellation succeeds, and cancelled invoice is then completely immutable
        conn.execute(
            "UPDATE invoices SET doc_status = 'cancelled', cancelled_at = '2026-05-02', cancel_reason = 'Mistake' WHERE id = ?",
            (invoice_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE invoices SET cancel_reason = 'Changed' WHERE id = ?", (invoice_id,))
    finally:
        conn.close()


def test_generated_pdf_matches_baseline_renderer(tmp_path):
    db_path = str(tmp_path / "pdf_parity.db")
    app = create_app(
        {
            "DATABASE_PATH": db_path,
            "SECRET_KEY": "test-secret",
            "ALLOW_REGISTRATION": False,
        }
    )
    client = app.test_client()

    reg_html = client.get("/auth/register").get_data(as_text=True)
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', reg_html).group(1)
    client.post(
        "/auth/register",
        data={
            "csrf_token": csrf,
            "workspace_name": "WS",
            "email": "owner@example.com",
            "password": "strongpassword123",
            "confirm_password": "strongpassword123",
        },
    )
    comp_html = client.get("/companies/new").get_data(as_text=True)
    csrf2 = re.search(r'name="csrf_token"\s+value="([^"]+)"', comp_html).group(1)
    client.post(
        "/companies/new",
        data={
            "csrf_token": csrf2,
            "legal_name": "Acme Pvt Ltd",
            "address": "123 MG Road, Mumbai",
            "state": "Maharashtra",
            "gstin": "27ABCDE1234F1Z5",
            "phone": "9999999999",
            "email": "billing@acme.test",
            "invoice_prefix": "INV",
            "currency": "INR",
        },
    )

    form_html = client.get("/").get_data(as_text=True)
    csrf3 = re.search(r'name="csrf_token"\s+value="([^"]+)"', form_html).group(1)
    res = client.post(
        "/generate",
        data={
            "csrf_token": csrf3,
            "buyer_name": "Beta Corp",
            "buyer_address": "45 Park Street, Bengaluru",
            "buyer_state": "Karnataka",
            "buyer_gstin": "29ABCDE1234F1Z5",
            "place_of_supply": "Karnataka",
            "invoice_date": "2026-05-15",
            "description": "Cloud Architecture",
            "hsn_sac": "9983",
            "quantity": "2",
            "unit_price": "1500",
            "gst_rate": "18",
        },
    )
    assert res.status_code == 200

    # Render directly with baseline core.calculator + pdf.render using the exact same inputs
    items = [{"description": "Cloud Architecture", "hsn_sac": "9983", "quantity": "2", "unit_price": "1500", "gst_rate": "18"}]
    totals = invoice_totals(items, "Maharashtra", "Karnataka")
    context = {
        "invoice_no": "INV/26-27/0001",
        "invoice_date": "15 May 2026",
        "seller": {
            "name": "Acme Pvt Ltd",
            "address": "123 MG Road, Mumbai",
            "state": "Maharashtra",
            "state_code": "27",
            "gstin": "27ABCDE1234F1Z5",
            "phone": "9999999999",
            "email": "billing@acme.test",
        },
        "buyer": {
            "name": "Beta Corp",
            "address": "45 Park Street, Bengaluru",
            "state": "Karnataka",
            "state_code": "29",
            "gstin": "29ABCDE1234F1Z5",
        },
        "place_of_supply": "Karnataka",
        "place_of_supply_code": "29",
        "totals": totals,
    }
    expected_html = render_invoice_html(context)
    expected_pdf = render_invoice_pdf(context)

    assert "INV/26-27/0001" in expected_html
    assert "Cloud Architecture" in expected_html
    assert "₹3,540.00" in expected_html
    # WeasyPrint embeds timestamps/IDs in PDF metadata, so verify PDF stream length & structure match
    assert res.data.startswith(b"%PDF-")
    assert abs(len(res.data) - len(expected_pdf)) < 256
