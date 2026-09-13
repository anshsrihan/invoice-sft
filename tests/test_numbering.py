from datetime import date

from core.numbering import (
    create_invoice_record,
    financial_year,
    invoice_history,
    mark_cancelled,
    next_invoice_number,
)


def test_financial_year_rolls_over_on_first_april():
    assert financial_year(date(2026, 3, 31)) == "25-26"
    assert financial_year(date(2026, 4, 1)) == "26-27"


def test_numbers_are_sequential_per_financial_year(tmp_path):
    database = tmp_path / "invoices.db"

    assert next_invoice_number(db_path=database, as_of=date(2026, 3, 31)) == "INV/25-26/0001"
    assert next_invoice_number(db_path=database, as_of=date(2026, 3, 31)) == "INV/25-26/0002"
    assert next_invoice_number(db_path=database, as_of=date(2026, 4, 1)) == "INV/26-27/0001"


def test_cancelling_an_invoice_does_not_free_its_number(tmp_path):
    database = tmp_path / "invoices.db"
    first = create_invoice_record("Asha Industries", "118.00", db_path=database, as_of=date(2026, 5, 1))
    mark_cancelled(first, db_path=database)
    second = create_invoice_record("Bina Services", "236.00", db_path=database, as_of=date(2026, 5, 1))

    assert first == "INV/26-27/0001"
    assert second == "INV/26-27/0002"
    assert [row["status"] for row in invoice_history(database)] == ["issued", "cancelled"]
