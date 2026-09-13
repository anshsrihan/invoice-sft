from decimal import Decimal

from core.calculator import invoice_totals, line_total


def test_line_total_calculates_taxable_tax_and_total():
    total = line_total("2.5", "100", "18")

    assert total["taxable_value"] == Decimal("250.00")
    assert total["tax"] == Decimal("45.00")
    assert total["total"] == Decimal("295.00")


def test_invoice_sums_rounded_tax_per_line_not_after_aggregation():
    invoice = invoice_totals(
        [
            {"description": "Small item A", "hsn_sac": "1234", "quantity": "1", "unit_price": "0.10", "gst_rate": "5"},
            {"description": "Small item B", "hsn_sac": "1234", "quantity": "1", "unit_price": "0.10", "gst_rate": "5"},
        ],
        "Maharashtra",
        "Karnataka",
    )

    # Each 0.005 tax rounds up to a paisa.  Summing first would incorrectly
    # produce only one paisa and disagree with the printed rows.
    assert [item["igst"] for item in invoice["items"]] == [Decimal("0.01"), Decimal("0.01")]
    assert invoice["taxable_total"] == Decimal("0.20")
    assert invoice["igst_total"] == Decimal("0.02")
    assert invoice["grand_total"] == Decimal("0.22")


def test_intra_state_invoice_has_cgst_and_sgst_per_line():
    invoice = invoice_totals(
        [{"description": "Consulting", "hsn_sac": "9983", "quantity": "2", "unit_price": "1250", "gst_rate": "18"}],
        "Maharashtra",
        "Maharashtra",
    )

    assert invoice["tax_type"] == "intra"
    assert invoice["cgst_total"] == Decimal("225.00")
    assert invoice["sgst_total"] == Decimal("225.00")
    assert invoice["igst_total"] == Decimal("0.00")
    assert invoice["grand_total"] == Decimal("2950.00")
