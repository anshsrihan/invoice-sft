import re
import sqlite3
import pytest

from app import create_app
from core.numbering import create_invoice_record, initialize_database, mark_cancelled
from db.connection import get_connection


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "CSRF token not found in HTML"
    return match.group(1)


def test_legacy_import_preserves_data_and_continues_sequence(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    initialize_database(db_path)
    from datetime import date

    inv1 = create_invoice_record("DRDO", "118000.00", prefix="INV", db_path=db_path, as_of=date(2026, 9, 13))
    inv2 = create_invoice_record("Cancelled Client", "500.00", prefix="INV", db_path=db_path, as_of=date(2026, 9, 14))
    mark_cancelled(inv2, db_path=db_path)
    assert inv1 == "INV/26-27/0001"
    assert inv2 == "INV/26-27/0002"

    app = create_app(
        {
            "DATABASE_PATH": db_path,
            "SECRET_KEY": "test-secret",
            "ALLOW_REGISTRATION": False,
        }
    )
    client = app.test_client()

    csrf = _extract_csrf(client.get("/auth/register").get_data(as_text=True))
    client.post(
        "/auth/register",
        data={
            "csrf_token": csrf,
            "workspace_name": "Main",
            "email": "owner@example.com",
            "password": "strongpassword123",
            "confirm_password": "strongpassword123",
        },
    )

    setup_html = client.get("/companies/new").get_data(as_text=True)
    assert "INV/26-27/0001" in setup_html
    csrf_comp = _extract_csrf(setup_html)
    res = client.post(
        "/companies/new",
        data={
            "csrf_token": csrf_comp,
            "legal_name": "My Real Business",
            "address": "Mumbai",
            "state": "Maharashtra",
            "gstin": "27ABCDE1234F1Z5",
            "invoice_prefix": "INV",
            "currency": "INR",
        },
        follow_redirects=False,
    )
    assert res.status_code == 302

    # History page shows both imported invoices
    hist = client.get("/history").get_data(as_text=True)
    assert "INV/26-27/0001" in hist
    assert "INV/26-27/0002" in hist
    assert "cancelled" in hist

    # Generate new invoice -> must get INV/26-27/0003 (or 0002 if only 1 legacy row existed),
    # and must ignore any forged seller_* POST values!
    csrf_inv = _extract_csrf(client.get("/").get_data(as_text=True))
    pdf_res = client.post(
        "/generate",
        data={
            "csrf_token": csrf_inv,
            "seller_name": "FORGED SELLER",
            "seller_gstin": "29ZZZZZ9999Z1Z5",
            "seller_state": "Karnataka",
            "buyer_name": "New Buyer",
            "buyer_address": "Pune",
            "buyer_state": "Maharashtra",
            "buyer_gstin": "",
            "place_of_supply": "Maharashtra",
            "invoice_date": "2026-09-20",
            "description": "Consulting",
            "hsn_sac": "9983",
            "quantity": "1",
            "unit_price": "1000",
            "gst_rate": "18",
        },
    )
    assert pdf_res.status_code == 200
    assert "INV-26-27-0003.pdf" in pdf_res.headers.get("Content-Disposition", "")
    assert pdf_res.data.startswith(b"%PDF-")

    # Verify no dual writes to legacy tables and immutability triggers work
    conn = get_connection(db_path)
    try:
        legacy_count = conn.execute("SELECT COUNT(*) FROM invoice_log").fetchone()[0]
        legacy_counter = conn.execute("SELECT last_number FROM invoice_counter WHERE financial_year='26-27'").fetchone()[0]
        assert legacy_count == 2
        assert legacy_counter == 2

        imported_row = conn.execute(
            "SELECT grand_total_paise, doc_status, legacy FROM invoices WHERE invoice_no = 'INV/26-27/0001'"
        ).fetchone()
        assert imported_row["grand_total_paise"] == 11800000
        assert imported_row["doc_status"] == "issued"
        assert imported_row["legacy"] == 1

        new_row = conn.execute(
            "SELECT id, seller_snapshot, grand_total_paise FROM invoices WHERE invoice_no = 'INV/26-27/0003'"
        ).fetchone()
        assert "My Real Business" in new_row["seller_snapshot"]
        assert "FORGED SELLER" not in new_row["seller_snapshot"]
        assert new_row["grand_total_paise"] == 118000

        # Immutability triggers block deleting or mutating issued invoice or its items
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM invoices WHERE id = ?", (new_row["id"],))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE invoices SET grand_total_paise = 0 WHERE id = ?", (new_row["id"],))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (new_row["id"],))
    finally:
        conn.close()


def test_single_legacy_invoice_continues_at_0002(tmp_path):
    db_path = str(tmp_path / "single_legacy.db")
    initialize_database(db_path)
    from datetime import date

    inv1 = create_invoice_record("DRDO", "118000.00", prefix="INV", db_path=db_path, as_of=date(2026, 9, 13))
    assert inv1 == "INV/26-27/0001"

    app = create_app(
        {
            "DATABASE_PATH": db_path,
            "SECRET_KEY": "test-secret",
            "ALLOW_REGISTRATION": False,
        }
    )
    client = app.test_client()
    csrf = _extract_csrf(client.get("/auth/register").get_data(as_text=True))
    client.post(
        "/auth/register",
        data={
            "csrf_token": csrf,
            "workspace_name": "Main",
            "email": "owner@example.com",
            "password": "strongpassword123",
            "confirm_password": "strongpassword123",
        },
    )
    csrf_comp = _extract_csrf(client.get("/companies/new").get_data(as_text=True))
    client.post(
        "/companies/new",
        data={
            "csrf_token": csrf_comp,
            "legal_name": "Real Co",
            "address": "Mumbai",
            "state": "Maharashtra",
            "gstin": "27ABCDE1234F1Z5",
            "invoice_prefix": "INV",
            "currency": "INR",
        },
    )
    csrf_inv = _extract_csrf(client.get("/").get_data(as_text=True))
    pdf_res = client.post(
        "/generate",
        data={
            "csrf_token": csrf_inv,
            "buyer_name": "Buyer 2",
            "buyer_address": "Pune",
            "buyer_state": "Maharashtra",
            "buyer_gstin": "",
            "place_of_supply": "Maharashtra",
            "invoice_date": "2026-09-20",
            "description": "Consulting",
            "hsn_sac": "9983",
            "quantity": "1",
            "unit_price": "100",
            "gst_rate": "18",
        },
    )
    assert pdf_res.status_code == 200
    assert "INV-26-27-0002.pdf" in pdf_res.headers.get("Content-Disposition", "")
