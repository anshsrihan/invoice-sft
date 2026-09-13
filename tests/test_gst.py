from decimal import Decimal

import pytest

from core.gst import resolve_tax_split


def test_matching_states_use_equally_split_cgst_and_sgst():
    split = resolve_tax_split("Maharashtra", "Maharashtra", 18, 1000)

    assert split == {
        "type": "intra",
        "cgst": Decimal("90.00"),
        "sgst": Decimal("90.00"),
        "igst": Decimal("0.00"),
    }


def test_different_states_use_igst_only():
    split = resolve_tax_split("Maharashtra", "Karnataka", 5, "120.50")

    assert split["type"] == "inter"
    assert split["cgst"] == Decimal("0.00")
    assert split["sgst"] == Decimal("0.00")
    assert split["igst"] == Decimal("6.03")


def test_states_are_required():
    with pytest.raises(ValueError, match="place of supply"):
        resolve_tax_split("Maharashtra", "", 18, 100)
