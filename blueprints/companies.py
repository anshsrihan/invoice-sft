"""Companies blueprint: onboarding, switching, and company settings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from config import GST_STATES, SELLER_DEFAULTS, STATE_TO_CODE
from core.legacy_import import get_unmigrated_legacy_summary, import_legacy_data_into_company
from core.security import (
    get_user_workspace,
    is_safe_redirect_url,
    list_user_companies,
    record_audit_log,
    resolve_company_access,
)
from core.validators import normalize_gstin, validate_company_payload
from db.connection import db_session, get_connection


companies_bp = Blueprint("companies", __name__, url_prefix="/companies")


def _company_form_payload(form: Any) -> dict[str, str]:
    return {
        "legal_name": form.get("legal_name", "").strip(),
        "gstin": normalize_gstin(form.get("gstin", "")),
        "pan": normalize_gstin(form.get("pan", "")),
        "address": form.get("address", "").strip(),
        "state": form.get("state", "").strip(),
        "phone": form.get("phone", "").strip(),
        "email": form.get("email", "").strip(),
        "currency": (form.get("currency", "INR").strip() or "INR").upper(),
        "bank_details": form.get("bank_details", "").strip(),
        "invoice_prefix": form.get("invoice_prefix", "").strip().upper(),
        "terms_text": form.get("terms_text", "").strip(),
    }


def _default_company_form() -> dict[str, str]:
    return {
        "legal_name": SELLER_DEFAULTS.get("name", ""),
        "gstin": SELLER_DEFAULTS.get("gstin", ""),
        "pan": "",
        "address": SELLER_DEFAULTS.get("address", ""),
        "state": SELLER_DEFAULTS.get("state", ""),
        "phone": SELLER_DEFAULTS.get("phone", ""),
        "email": SELLER_DEFAULTS.get("email", ""),
        "currency": "INR",
        "bank_details": "",
        "invoice_prefix": "",
        "terms_text": "",
    }


@companies_bp.get("/")
@login_required
def list_companies():
    conn = get_connection(current_app.config["DATABASE_PATH"])
    try:
        companies = list_user_companies(conn, current_user.user_id)
    finally:
        conn.close()
    return render_template("companies/list.html", companies=companies)


@companies_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_company():
    db_path = current_app.config["DATABASE_PATH"]
    conn = get_connection(db_path)
    try:
        legacy_summary = get_unmigrated_legacy_summary(conn)
        existing_companies = list_user_companies(conn, current_user.user_id)
    finally:
        conn.close()

    errors: dict[str, str] = {}
    form_data = _default_company_form() if not existing_companies else {
        "legal_name": "",
        "gstin": "",
        "pan": "",
        "address": "",
        "state": "",
        "phone": "",
        "email": "",
        "currency": "INR",
        "bank_details": "",
        "invoice_prefix": "",
        "terms_text": "",
    }

    if request.method == "POST":
        form_data = _company_form_payload(request.form)
        errors = validate_company_payload(form_data)
        if not errors:
            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with db_session(db_path, immediate=True) as tx:
                workspace = get_user_workspace(tx, current_user.user_id)
                if not workspace:
                    abort(403)
                cursor = tx.execute(
                    """
                    INSERT INTO companies(
                        workspace_id, legal_name, gstin, pan, address, state, state_code,
                        phone, email, currency, bank_details, logo_path, invoice_prefix, terms_text, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)
                    """,
                    (
                        workspace["id"],
                        form_data["legal_name"],
                        form_data["gstin"],
                        form_data["pan"],
                        form_data["address"],
                        form_data["state"],
                        STATE_TO_CODE[form_data["state"]],
                        form_data["phone"],
                        form_data["email"],
                        form_data["currency"],
                        form_data["bank_details"],
                        form_data["invoice_prefix"],
                        form_data["terms_text"],
                        now_iso,
                    ),
                )
                company_id = int(cursor.lastrowid)
                import_legacy_data_into_company(
                    tx,
                    company_id=company_id,
                    workspace_id=int(workspace["id"]),
                    user_id=current_user.user_id,
                    company_prefix=form_data["invoice_prefix"],
                )
                record_audit_log(
                    tx,
                    workspace_id=int(workspace["id"]),
                    company_id=company_id,
                    user_id=current_user.user_id,
                    action="company_created",
                    entity="company",
                    entity_id=company_id,
                    details={"legal_name": form_data["legal_name"]},
                )
            session["active_company_id"] = company_id
            return redirect(url_for("invoices.index"))

    return render_template(
        "companies/setup.html",
        form=form_data,
        errors=errors,
        states=GST_STATES,
        legacy_summary=legacy_summary,
        is_edit=False,
    ), (400 if errors else 200)


@companies_bp.post("/<int:company_id>/switch")
@login_required
def switch_company(company_id: int):
    conn = get_connection(current_app.config["DATABASE_PATH"])
    try:
        company = resolve_company_access(conn, current_user.user_id, company_id)
    finally:
        conn.close()
    if not company:
        abort(404)

    session["active_company_id"] = company["id"]
    next_url = request.form.get("next", "")
    if is_safe_redirect_url(next_url):
        return redirect(next_url)
    return redirect(url_for("invoices.index"))


@companies_bp.route("/<int:company_id>/settings", methods=["GET", "POST"])
@login_required
def company_settings(company_id: int):
    db_path = current_app.config["DATABASE_PATH"]
    conn = get_connection(db_path)
    try:
        company = resolve_company_access(conn, current_user.user_id, company_id)
    finally:
        conn.close()
    if not company:
        abort(404)

    errors: dict[str, str] = {}
    form_data = dict(company)
    saved = False

    if request.method == "POST":
        form_data = _company_form_payload(request.form)
        errors = validate_company_payload(form_data)
        if not errors:
            with db_session(db_path, immediate=True) as tx:
                verified = resolve_company_access(tx, current_user.user_id, company_id)
                if not verified:
                    abort(404)
                tx.execute(
                    """
                    UPDATE companies
                    SET legal_name = ?, gstin = ?, pan = ?, address = ?, state = ?, state_code = ?,
                        phone = ?, email = ?, currency = ?, bank_details = ?, invoice_prefix = ?, terms_text = ?
                    WHERE id = ?
                    """,
                    (
                        form_data["legal_name"],
                        form_data["gstin"],
                        form_data["pan"],
                        form_data["address"],
                        form_data["state"],
                        STATE_TO_CODE[form_data["state"]],
                        form_data["phone"],
                        form_data["email"],
                        form_data["currency"],
                        form_data["bank_details"],
                        form_data["invoice_prefix"],
                        form_data["terms_text"],
                        company_id,
                    ),
                )
                record_audit_log(
                    tx,
                    workspace_id=int(verified["workspace_id"]),
                    company_id=company_id,
                    user_id=current_user.user_id,
                    action="company_updated",
                    entity="company",
                    entity_id=company_id,
                )
            saved = True

    return render_template(
        "companies/setup.html",
        form=form_data,
        errors=errors,
        states=GST_STATES,
        legacy_summary={"pending": False, "invoice_numbers": [], "count": 0},
        is_edit=True,
        company_id=company_id,
        saved=saved,
    ), (400 if errors else 200)
