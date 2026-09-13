"""Authoritative invoice calculations performed by the server."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.gst import money, resolve_tax_split, to_decimal


ZERO = Decimal("0.00")


def line_total(qty: float | Decimal | str, unit_price: float | Decimal | str, rate_pct: float | Decimal | str) -> dict[str, Decimal]:
    """Calculate a single line before choosing its GST tax type.

    Each monetary amount is rounded at the line level.  ``invoice_totals``
    then derives the authoritative CGST/SGST/IGST split for the line.
    """
    quantity = to_decimal(qty)
    price = to_decimal(unit_price)
    rate = to_decimal(rate_pct)
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")
    if price < 0:
        raise ValueError("Unit price cannot be negative")
    if rate < 0:
        raise ValueError("GST rate cannot be negative")

    taxable_value = money(quantity * price)
    tax = money(taxable_value * rate / Decimal("100"))
    return {
        "quantity": quantity,
        "unit_price": money(price),
        "rate_pct": rate,
        "taxable_value": taxable_value,
        "tax": tax,
        "total": money(taxable_value + tax),
    }


def invoice_totals(
    line_items: list[dict[str, Any]], seller_state: str, place_of_supply: str
) -> dict[str, Any]:
    """Return rounded item rows and invoice-level GST totals.

    Tax is calculated and rounded per line, then added.  This avoids a
    sum-then-round difference between the printed lines and invoice total.
    """
    if not line_items:
        raise ValueError("At least one line item is required")

    rows: list[dict[str, Any]] = []
    taxable_total = cgst_total = sgst_total = igst_total = ZERO

    for item in line_items:
        base = line_total(item["quantity"], item["unit_price"], item["gst_rate"])
        split = resolve_tax_split(
            seller_state, place_of_supply, base["rate_pct"], base["taxable_value"]
        )
        # Components are separately rounded for an intra-state line.  Use
        # their sum for the printed GST and line total.
        line_tax = money(split["cgst"] + split["sgst"] + split["igst"])
        row = {
            "description": str(item["description"]).strip(),
            "hsn_sac": str(item["hsn_sac"]).strip(),
            **base,
            **split,
            "tax": line_tax,
            "total": money(base["taxable_value"] + line_tax),
        }
        rows.append(row)
        taxable_total += row["taxable_value"]
        cgst_total += row["cgst"]
        sgst_total += row["sgst"]
        igst_total += row["igst"]

    tax_total = money(cgst_total + sgst_total + igst_total)
    return {
        "tax_type": "intra" if seller_state.strip().casefold() == place_of_supply.strip().casefold() else "inter",
        "items": rows,
        "taxable_total": money(taxable_total),
        "cgst_total": money(cgst_total),
        "sgst_total": money(sgst_total),
        "igst_total": money(igst_total),
        "tax_total": tax_total,
        "grand_total": money(taxable_total + tax_total),
    }
