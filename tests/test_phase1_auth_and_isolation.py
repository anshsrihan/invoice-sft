import re
import sqlite3
import pytest

from app import create_app
from db.connection import get_connection


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "CSRF token not found in HTML"
    return match.group(1)


def _register_and_create_company(client, email: str, workspace: str, company: dict[str, str]) -> None:
    reg_page = client.get("/auth/register")
    assert reg_page.status_code == 200
    csrf = _extract_csrf(reg_page.get_data(as_text=True))
    res = client.post(
        "/auth/register",
        data={
            "csrf_token": csrf,
            "workspace_name": workspace,
            "email": email,
            "password": "strongpassword123",
            "confirm_password": "strongpassword123",
        },
        follow_redirects=False,
    )
    assert res.status_code == 302

    comp_page = client.get("/companies/new")
    csrf = _extract_csrf(comp_page.get_data(as_text=True))
    res2 = client.post(
        "/companies/new",
        data={"csrf_token": csrf, **company},
        follow_redirects=False,
    )
    assert res2.status_code == 302


def test_secret_key_fails_loudly_outside_debug_mode(tmp_path):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({"DATABASE_PATH": str(tmp_path / "x.db"), "SECRET_KEY": None, "DEBUG": False})


def test_registration_closes_after_first_user_and_logout_is_post_only(tmp_path):
    app = create_app(
        {
            "DATABASE_PATH": str(tmp_path / "auth.db"),
            "SECRET_KEY": "test-secret",
            "ALLOW_REGISTRATION": False,
        }
    )
    client = app.test_client()

    # Short password rejected
    reg_page = client.get("/auth/register")
    csrf = _extract_csrf(reg_page.get_data(as_text=True))
    bad = client.post(
        "/auth/register",
        data={
            "csrf_token": csrf,
            "workspace_name": "WS",
            "email": "owner@example.com",
            "password": "short",
            "confirm_password": "short",
        },
    )
    assert bad.status_code == 400

    # Valid registration succeeds
    ok = client.post(
        "/auth/register",
        data={
            "csrf_token": csrf,
            "workspace_name": "WS",
            "email": "owner@example.com",
            "password": "strongpassword123",
            "confirm_password": "strongpassword123",
        },
    )
    assert ok.status_code == 302

    # Logout GET is not allowed (405)
    assert client.get("/auth/logout").status_code == 405

    # Logout POST works
    comp_page = client.get("/companies/new")
    csrf2 = _extract_csrf(comp_page.get_data(as_text=True))
    out = client.post("/auth/logout", data={"csrf_token": csrf2})
    assert out.status_code == 302

    # Second registration is blocked (403)
    assert client.get("/auth/register").status_code == 403


def test_login_next_redirect_cannot_leave_site(tmp_path):
    app = create_app(
        {
            "DATABASE_PATH": str(tmp_path / "redir.db"),
            "SECRET_KEY": "test-secret",
            "ALLOW_REGISTRATION": False,
        }
    )
    client = app.test_client()
    _register_and_create_company(
        client,
        "a@example.com",
        "WS A",
        {
            "legal_name": "Alpha Pvt Ltd",
            "address": "Mumbai",
            "state": "Maharashtra",
            "gstin": "27ABCDE1234F1Z5",
            "invoice_prefix": "ALP",
            "currency": "INR",
        },
    )
    csrf = _extract_csrf(client.get("/").get_data(as_text=True))
    client.post("/auth/logout", data={"csrf_token": csrf})

    login_page = client.get("/auth/login?next=https://evil.example/phish")
    csrf_login = _extract_csrf(login_page.get_data(as_text=True))
    res = client.post(
        "/auth/login?next=https://evil.example/phish",
        data={
            "csrf_token": csrf_login,
            "email": "a@example.com",
            "password": "strongpassword123",
            "next": "https://evil.example/phish",
        },
        follow_redirects=False,
    )
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/")


def test_tenant_isolation_and_company_switching(tmp_path):
    db_path = str(tmp_path / "isolation.db")
    app = create_app(
        {
            "DATABASE_PATH": db_path,
            "SECRET_KEY": "test-secret",
            "ALLOW_REGISTRATION": True,
        }
    )

    client_a = app.test_client()
    _register_and_create_company(
        client_a,
        "usera@example.com",
        "WS A",
        {
            "legal_name": "Company A",
            "address": "Pune",
            "state": "Maharashtra",
            "gstin": "27ABCDE1234F1Z5",
            "invoice_prefix": "CMPA",
            "currency": "INR",
        },
    )
    # Create second company in User A's workspace and switch between them
    csrf_a = _extract_csrf(client_a.get("/companies/new").get_data(as_text=True))
    res_a2 = client_a.post(
        "/companies/new",
        data={
            "csrf_token": csrf_a,
            "legal_name": "Company A2",
            "address": "Bengaluru",
            "state": "Karnataka",
            "gstin": "29ABCDE1234F1Z5",
            "invoice_prefix": "CMPA2",
            "currency": "INR",
        },
        follow_redirects=False,
    )
    assert res_a2.status_code == 302
    assert b"Company A2" in client_a.get("/").data

    # Switch back to Company A (id=1)
    csrf_list = _extract_csrf(client_a.get("/companies/").get_data(as_text=True))
    client_a.post("/companies/1/switch", data={"csrf_token": csrf_list})
    assert b"Company A" in client_a.get("/").data

    # Issue an invoice in Company A
    csrf_inv = _extract_csrf(client_a.get("/").get_data(as_text=True))
    pdf_res = client_a.post(
        "/generate",
        data={
            "csrf_token": csrf_inv,
            "buyer_name": "Client A",
            "buyer_address": "Mumbai",
            "buyer_state": "Maharashtra",
            "buyer_gstin": "",
            "place_of_supply": "Maharashtra",
            "invoice_date": "2026-05-10",
            "description": "Service",
            "hsn_sac": "9983",
            "quantity": "1",
            "unit_price": "1000",
            "gst_rate": "18",
        },
    )
    assert pdf_res.status_code == 200
    assert pdf_res.data.startswith(b"%PDF-")

    # User B registers and creates Company B
    client_b = app.test_client()
    _register_and_create_company(
        client_b,
        "userb@example.com",
        "WS B",
        {
            "legal_name": "Company B",
            "address": "Delhi",
            "state": "Delhi",
            "gstin": "07ABCDE1234F1Z5",
            "invoice_prefix": "CMPB",
            "currency": "INR",
        },
    )

    # User B cannot view Company A settings or switch to Company A
    assert client_b.get("/companies/1/settings").status_code == 404
    csrf_b = _extract_csrf(client_b.get("/").get_data(as_text=True))
    assert client_b.post("/companies/1/switch", data={"csrf_token": csrf_b}).status_code == 404

    # User B cannot cancel Company A's invoice
    cancel_res = client_b.post(
        "/invoices/CMPA/26-27/0001/cancel",
        data={"csrf_token": csrf_b},
    )
    assert cancel_res.status_code == 404

    # Composite FK prevents linking Company A's customer to Company B's invoice
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO customers(id, company_id, name, created_at, updated_at) VALUES (10, 1, 'Cust A', '2026-01-01', '2026-01-01')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO invoices(company_id, customer_id, invoice_no, financial_year, invoice_date, doc_status, created_at, updated_at)
                VALUES (3, 10, NULL, '26-27', '2026-05-10', 'draft', '2026-05-10', '2026-05-10')
                """
            )
    finally:
        conn.close()
