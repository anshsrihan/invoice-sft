"""Server-side input validation for GST invoices."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from config import GST_RATES, STATE_TO_CODE
from core.gst import to_decimal


GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
HSN_SAC_RE = re.compile(r"^[0-9]{4,8}$")


def normalize_gstin(value: str) -> str:
    return (value or "").strip().upper()


def is_valid_gstin(value: str) -> bool:
    """Check GSTIN shape; this deliberately does not call a government registry."""
    return bool(GSTIN_RE.fullmatch(normalize_gstin(value)))


def is_valid_hsn_sac(value: str) -> bool:
    """GST invoices accept a numeric HSN/SAC code; category lookup is out of scope."""
    return bool(HSN_SAC_RE.fullmatch((value or "").strip()))


def gstin_matches_state(gstin: str, state: str) -> bool:
    """Validate the GSTIN's first two state-code digits against the selected state."""
    gstin = normalize_gstin(gstin)
    return bool(gstin and state in STATE_TO_CODE and gstin[:2] == STATE_TO_CODE[state])


def validate_invoice_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Return field errors.  Values are still calculated only after this passes."""
    errors: dict[str, str] = {}
    required = {
        "seller_name": "Supplier legal name",
        "seller_address": "Supplier address",
        "seller_state": "Supplier state",
        "seller_gstin": "Supplier GSTIN",
        "buyer_name": "Recipient name",
        "buyer_address": "Recipient address",
        "buyer_state": "Recipient state",
        "place_of_supply": "Place of supply",
        "invoice_date": "Invoice date",
    }
    for key, label in required.items():
        if not str(payload.get(key, "")).strip():
            errors[key] = f"{label} is required."

    for field in ("seller_state", "buyer_state", "place_of_supply"):
        if payload.get(field) and payload[field] not in STATE_TO_CODE:
            errors[field] = "Choose a valid Indian state or Union Territory."

    seller_gstin = normalize_gstin(str(payload.get("seller_gstin", "")))
    if seller_gstin and not is_valid_gstin(seller_gstin):
        errors["seller_gstin"] = "Enter a valid 15-character GSTIN."
    elif seller_gstin and payload.get("seller_state") and not gstin_matches_state(seller_gstin, payload["seller_state"]):
        errors["seller_gstin"] = "GSTIN state code does not match the supplier state."

    buyer_gstin = normalize_gstin(str(payload.get("buyer_gstin", "")))
    if buyer_gstin and not is_valid_gstin(buyer_gstin):
        errors["buyer_gstin"] = "Enter a valid 15-character GSTIN."
    elif buyer_gstin and payload.get("buyer_state") and not gstin_matches_state(buyer_gstin, payload["buyer_state"]):
        errors["buyer_gstin"] = "GSTIN state code does not match the recipient state."

    try:
        date.fromisoformat(str(payload.get("invoice_date", "")))
    except ValueError:
        errors["invoice_date"] = "Enter a valid invoice date."

    items = payload.get("items", [])
    if not items:
        errors["items"] = "Add at least one line item."
        return errors

    allowed_rates = {to_decimal(rate) for rate in GST_RATES}
    for position, item in enumerate(items, start=1):
        prefix = f"Line {position}: "
        if not str(item.get("description", "")).strip():
            errors[f"item_{position}_description"] = prefix + "description is required."
        if not is_valid_hsn_sac(str(item.get("hsn_sac", ""))):
            errors[f"item_{position}_hsn_sac"] = prefix + "HSN/SAC must be 4–8 digits."
        try:
            if to_decimal(item.get("quantity", "")) <= 0:
                raise ValueError
        except ValueError:
            errors[f"item_{position}_quantity"] = prefix + "quantity must be greater than zero."
        try:
            if to_decimal(item.get("unit_price", "")) < 0:
                raise ValueError
        except ValueError:
            errors[f"item_{position}_unit_price"] = prefix + "unit price must be zero or more."
        try:
            if to_decimal(item.get("gst_rate", "")) not in allowed_rates:
                raise ValueError
        except ValueError:
            errors[f"item_{position}_gst_rate"] = prefix + "choose a supported GST rate."
    return errors
