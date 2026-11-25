"""Invoices blueprint: company-scoped invoice generation, history, and cancellation."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from itertools import zip_longest
from typing import Any

from flask import Blueprint, current_app, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required

from config import GST_RATES, GST_STATES, STATE_TO_CODE
from core.calculator import invoice_totals
from core.numbering import cancel_company_invoice, issue_company_invoice, list_company_invoices
from core.security import active_company_for_user, record_audit_log, resolve_company_access
from core.validators import (
    normalize_gstin,
    validate_buyer_and_items_payload,
    validate_company_for_issuance,
)
from db.connection import db_session, get_connection
from pdf.render import render_invoice_pdf


invoices_bp = Blueprint("invoices", __name__)

BUYER_FIELDS = (
    "buyer_name",
    "buyer_address",
    "buyer_state",
    "buyer_gstin",
    "place_of_supply",
    "invoice_date",
)
LINE_FIELDS = ("description", "hsn_sac", "quantity", "unit_price", "gst_rate")


def _seller_fields_from_company(company: dict[str, Any]) -> dict[str, str]:
    return {
        "seller_name": str(company.get("legal_name", "")),
        "seller_address": str(company.get("address", "")),
        "seller_state": str(company.get("state", "")),
        "seller_gstin": str(company.get("gstin", "")),
        "seller_phone": str(company.get("phone", "")),
        "seller_email": str(company.get("email", "")),
    }


def _empty_invoice_form(company: dict[str, Any]) -> dict[str, Any]:
    return {
        **_seller_fields_from_company(company),
        "buyer_name": "",
        "buyer_address": "",
        "buyer_state": "",
        "buyer_gstin": "",
        "place_of_supply": "",
        "invoice_date": date.today().isoformat(),
        "line_items": [
            {"description": "", "hsn_sac": "", "quantity": "1", "unit_price": "", "gst_rate": "18"}
        ],
    }


def _buyer_payload(form: Any, company: dict[str, Any]) -> dict[str, Any]:
    """Extract recipient/line fields from form; seller fields always come from active company."""
    payload: dict[str, Any] = _seller_fields_from_company(company)
    for field in BUYER_FIELDS:
        payload[field] = form.get(field, "").strip()
    columns = [form.getlist(field) for field in LINE_FIELDS]
    payload["items"] = [
        dict(zip(LINE_FIELDS, values))
        for values in zip_longest(*columns, fillvalue="")
    ]
    payload["buyer_gstin"] = normalize_gstin(payload["buyer_gstin"])
    return payload


def _presentation_form(payload: dict[str, Any], company: dict[str, Any]) -> dict[str, Any]:
    fields = _seller_fields_from_company(company)
    for field in BUYER_FIELDS:
        fields[field] = payload.get(field, "")
    fields["line_items"] = payload.get("items", []) or _empty_invoice_form(company)["line_items"]
    return fields


def _invoice_context(payload: dict[str, Any], totals: dict[str, Any], invoice_no: str) -> dict[str, Any]:
    return {
        "invoice_no": invoice_no,
        "invoice_date": date.fromisoformat(payload["invoice_date"]).strftime("%d %b %Y"),
        "seller": {
            "name": payload["seller_name"],
            "address": payload["seller_address"],
            "state": payload["seller_state"],
            "state_code": STATE_TO_CODE[payload["seller_state"]],
            "gstin": payload["seller_gstin"],
            "phone": payload["seller_phone"],
            "email": payload["seller_email"],
        },
        "buyer": {
            "name": payload["buyer_name"],
            "address": payload["buyer_address"],
            "state": payload["buyer_state"],
            "state_code": STATE_TO_CODE[payload["buyer_state"]],
            "gstin": payload["buyer_gstin"],
        },
        "place_of_supply": payload["place_of_supply"],
        "place_of_supply_code": STATE_TO_CODE[payload["place_of_supply"]],
        "totals": totals,
    }


def _render_invoice_form(
    company: dict[str, Any],
    form_data: dict[str, Any] | None = None,
    errors: dict[str, str] | None = None,
    status: int = 200,
):
    return (
        render_template(
            "index.html",
            form=form_data or _empty_invoice_form(company),
            errors=errors or {},
            states=GST_STATES,
            gst_rates=GST_RATES,
            company=company,
        ),
        status,
    )


def _get_active_company(db_path: str) -> dict[str, Any] | None:
    conn = get_connection(db_path)
    try:
        return active_company_for_user(conn, current_user.user_id, session)
    finally:
        conn.close()


@invoices_bp.get("/")
@login_required
def index():
    company = _get_active_company(current_app.config["DATABASE_PATH"])
    if not company:
        return redirect(url_for("companies.new_company"))
    return _render_invoice_form(company)


@invoices_bp.post("/generate")
@login_required
def generate():
    db_path = current_app.config["DATABASE_PATH"]
    company = _get_active_company(db_path)
    if not company:
        return redirect(url_for("companies.new_company"))

    payload = _buyer_payload(request.form, company)
    form_data = _presentation_form(payload, company)

    company_errors = validate_company_for_issuance(company)
    if company_errors:
        return _render_invoice_form(company, form_data, company_errors, 400)

    errors = validate_buyer_and_items_payload(payload)
    if errors:
        return _render_invoice_form(company, form_data, errors, 400)

    invoice_no: str | None = None
    try:
        totals = invoice_totals(
            payload["items"], company["state"], payload["place_of_supply"]
        )
        seller_snapshot = {
            "legal_name": company["legal_name"],
            "address": company["address"],
            "state": company["state"],
            "state_code": company["state_code"],
            "gstin": company["gstin"],
            "pan": company.get("pan", ""),
            "phone": company.get("phone", ""),
            "email": company.get("email", ""),
        }
        buyer_snapshot = {
            "name": payload["buyer_name"],
            "address": payload["buyer_address"],
            "state": payload["buyer_state"],
            "state_code": STATE_TO_CODE[payload["buyer_state"]],
            "gstin": payload["buyer_gstin"],
        }
        with db_session(db_path, immediate=True) as tx:
            verified_company = resolve_company_access(tx, current_user.user_id, company["id"])
            if not verified_company:
                return redirect(url_for("companies.new_company"))
            invoice_id, invoice_no = issue_company_invoice(
                tx,
                company=verified_company,
                payload=payload,
                totals=totals,
                seller_snapshot=seller_snapshot,
                buyer_snapshot=buyer_snapshot,
            )
            record_audit_log(
                tx,
                workspace_id=int(verified_company["workspace_id"]),
                company_id=int(verified_company["id"]),
                user_id=current_user.user_id,
                action="invoice_issued",
                entity="invoice",
                entity_id=invoice_id,
                details={"invoice_no": invoice_no},
            )
        pdf_bytes = render_invoice_pdf(_invoice_context(payload, totals, invoice_no))
    except Exception as exc:
        if invoice_no is not None:
            with db_session(db_path, immediate=True) as tx:
                cancel_company_invoice(
                    tx,
                    company_id=int(company["id"]),
                    invoice_no=invoice_no,
                    reason="PDF generation failed",
                )
        return _render_invoice_form(
            company,
            form_data,
            {"form": f"Invoice could not be generated: {exc}"},
            500,
        )

    filename = invoice_no.replace("/", "-") + ".pdf"
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )


@invoices_bp.get("/history")
@login_required
def history():
    db_path = current_app.config["DATABASE_PATH"]
    company = _get_active_company(db_path)
    if not company:
        return redirect(url_for("companies.new_company"))

    conn = get_connection(db_path)
    try:
        invoices = list_company_invoices(conn, int(company["id"]))
    finally:
        conn.close()
    return render_template("history.html", invoices=invoices)


@invoices_bp.post("/invoices/<path:invoice_no>/cancel")
@login_required
def cancel(invoice_no: str):
    db_path = current_app.config["DATABASE_PATH"]
    company = _get_active_company(db_path)
    if not company:
        return redirect(url_for("companies.new_company"))

    reason = request.form.get("reason", "").strip() or "Cancelled by user"
    try:
        with db_session(db_path, immediate=True) as tx:
            verified_company = resolve_company_access(tx, current_user.user_id, company["id"])
            if not verified_company:
                return "Invoice not found", 404
            cancel_company_invoice(
                tx,
                company_id=int(verified_company["id"]),
                invoice_no=invoice_no,
                reason=reason,
            )
            record_audit_log(
                tx,
                workspace_id=int(verified_company["workspace_id"]),
                company_id=int(verified_company["id"]),
                user_id=current_user.user_id,
                action="invoice_cancelled",
                entity="invoice",
                entity_id=invoice_no,
                details={"reason": reason},
            )
    except ValueError:
        return "Invoice not found", 404
    return redirect(url_for("invoices.history", cancelled=invoice_no))
