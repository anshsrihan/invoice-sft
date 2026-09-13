"""GST tax-type resolution using Decimal arithmetic."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


MONEY_PLACES = Decimal("0.01")


def to_decimal(value: Any) -> Decimal:
    """Convert a form or numeric value to Decimal without binary-float drift."""
    try:
        return Decimal(str(value))
    except Exception as exc:  # Decimal raises several exception types
        raise ValueError(f"'{value}' is not a valid number") from exc


def money(value: Any) -> Decimal:
    """Round monetary values to paise, using conventional invoice half-up rounding."""
    return to_decimal(value).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def resolve_tax_split(
    seller_state: str,
    place_of_supply: str,
    rate_pct: float | Decimal | str,
    taxable_value: float | Decimal | str,
) -> dict[str, Any]:
    """Return the applicable per-line GST split.

    A matching seller state and place of supply creates an intra-state supply,
    so CGST and SGST are separately rounded.  A different state creates an
    inter-state supply and applies IGST at the full rate.
    """
    if not seller_state or not place_of_supply:
        raise ValueError("Seller state and place of supply are required")

    rate = to_decimal(rate_pct)
    taxable = money(taxable_value)
    if rate < 0:
        raise ValueError("GST rate cannot be negative")
    if taxable < 0:
        raise ValueError("Taxable value cannot be negative")

    if seller_state.strip().casefold() == place_of_supply.strip().casefold():
        cgst = money(taxable * rate / Decimal("200"))
        sgst = money(taxable * rate / Decimal("200"))
        return {"type": "intra", "cgst": cgst, "sgst": sgst, "igst": Decimal("0.00")}

    igst = money(taxable * rate / Decimal("100"))
    return {"type": "inter", "cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": igst}
