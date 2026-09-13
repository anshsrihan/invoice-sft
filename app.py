"""Local Flask entry point for GST invoice generation."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from itertools import zip_longest
from pathlib import Path
from typing import Any

from flask import Flask, redirect, render_template, request, send_file, url_for

from config import DATABASE_PATH, GST_RATES, GST_STATES, SELLER_DEFAULTS, STATE_TO_CODE
from core.calculator import invoice_totals
from core.numbering import create_invoice_record, initialize_database, invoice_history, mark_cancelled
from core.validators import normalize_gstin, validate_invoice_payload
from pdf.render import render_invoice_pdf


FORM_FIELDS = (
    "seller_name",
    "seller_address",
    "seller_state",
    "seller_gstin",
    "seller_phone",
    "seller_email",
    "buyer_name",
    "buyer_address",
    "buyer_state",
    "buyer_gstin",
    "place_of_supply",
    "invoice_date",
)
LINE_FIELDS = ("description", "hsn_sac", "quantity", "unit_price", "gst_rate")


def empty_form() -> dict[str, Any]:
    """Return one blank item row along with editable seller defaults."""
    return {
        "seller_name": SELLER_DEFAULTS["name"],
        "seller_address": SELLER_DEFAULTS["address"],
        "seller_state": SELLER_DEFAULTS["state"],
        "seller_gstin": SELLER_DEFAULTS["gstin"],
        "seller_phone": SELLER_DEFAULTS["phone"],
        "seller_email": SELLER_DEFAULTS["email"],
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


def form_payload(form: Any) -> dict[str, Any]:
    """Turn repeated row fields in Flask's form data into a calculation payload."""
    payload: dict[str, Any] = {field: form.get(field, "").strip() for field in FORM_FIELDS}
    columns = [form.getlist(field) for field in LINE_FIELDS]
    payload["items"] = [
        dict(zip(LINE_FIELDS, values))
        for values in zip_longest(*columns, fillvalue="")
    ]
    payload["seller_gstin"] = normalize_gstin(payload["seller_gstin"])
    payload["buyer_gstin"] = normalize_gstin(payload["buyer_gstin"])
    return payload


def presentation_form(payload: dict[str, Any]) -> dict[str, Any]:
    """Adapt a server payload to the form template without exposing an ``items`` method."""
    fields = {field: payload.get(field, "") for field in FORM_FIELDS}
    fields["line_items"] = payload.get("items", []) or empty_form()["line_items"]
    return fields


def invoice_context(payload: dict[str, Any], totals: dict[str, Any], invoice_no: str) -> dict[str, Any]:
    """Build the PDF context only after values have passed server validation."""
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


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(DATABASE_PATH=DATABASE_PATH, INVOICE_PREFIX="INV")
    if test_config:
        app.config.update(test_config)
    initialize_database(app.config["DATABASE_PATH"])

    def render_form(
        form_data: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
        status: int = 200,
    ):
        return (
            render_template(
                "index.html",
                form=form_data or empty_form(),
                errors=errors or {},
                states=GST_STATES,
                gst_rates=GST_RATES,
            ),
            status,
        )

    @app.get("/")
    def index():
        return render_form()

    @app.post("/generate")
    def generate():
        payload = form_payload(request.form)
        errors = validate_invoice_payload(payload)
        form_data = presentation_form(payload)
        if errors:
            return render_form(form_data, errors, 400)

        try:
            totals = invoice_totals(
                payload["items"], payload["seller_state"], payload["place_of_supply"]
            )
            invoice_no = create_invoice_record(
                payload["buyer_name"],
                totals["grand_total"],
                prefix=app.config["INVOICE_PREFIX"],
                db_path=app.config["DATABASE_PATH"],
            )
            pdf_bytes = render_invoice_pdf(invoice_context(payload, totals, invoice_no))
        except Exception as exc:
            # Once a number is allocated it can never be reused.  If the PDF
            # renderer fails, retain the number as a cancelled record instead.
            if "invoice_no" in locals():
                mark_cancelled(invoice_no, app.config["DATABASE_PATH"])
            return render_form(
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

    @app.get("/history")
    def history():
        return render_template("history.html", invoices=invoice_history(app.config["DATABASE_PATH"]))

    @app.post("/invoices/<path:invoice_no>/cancel")
    def cancel(invoice_no: str):
        try:
            mark_cancelled(invoice_no, app.config["DATABASE_PATH"])
        except ValueError:
            return "Invoice not found", 404
        return redirect(url_for("history", cancelled=invoice_no))

    return app


app = create_app()


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(host="127.0.0.1", port=port, debug=True)
