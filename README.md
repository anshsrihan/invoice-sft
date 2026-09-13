# Invoice Generator v2

A private, local-only GST tax-invoice generator. Fill in the browser form, review live GST totals, and download a print-ready PDF. Nothing is sent to a cloud service: invoice numbering and history stay in `invoice_state.db` beside the app.

## Run it

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Open [http://localhost:5000](http://localhost:5000). The app listens only on `127.0.0.1`.

On macOS, WeasyPrint also needs its native Pango/GObject renderer once. Install it with `brew install weasyprint`; the app automatically checks Homebrew’s standard library paths when generating a PDF. Linux and Windows have their own platform prerequisites in the [WeasyPrint installation guide](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).

## Use it safely

- Add your own supplier defaults with `INVOICE_SELLER_NAME`, `INVOICE_SELLER_ADDRESS`, `INVOICE_SELLER_STATE`, `INVOICE_SELLER_GSTIN`, `INVOICE_SELLER_PHONE`, and `INVOICE_SELLER_EMAIL`, or simply enter them in the editable form.
- Use the recipient's state as the place of supply unless your transaction calls for a different place of supply. The app derives CGST+SGST for intra-state supplies and IGST for inter-state supplies.
- Invoice numbers are assigned only after server-side validation, at PDF generation time. An allocated number is logged atomically; cancelled invoices remain in the sequence and can never be reused.
- The History page is an invoice register and supports cancelling an issued number. It does not store a duplicate of the generated PDF, so save the browser download in your normal records location.

## Project map

- `core/` — Decimal-based GST split, line totals, validators, and SQLite numbering.
- `pdf/` — Jinja HTML invoice and WeasyPrint conversion.
- `templates/` and `static/` — the local Flask form and live calculator.
- `tests/` — GST, rounding, and financial-year numbering regression tests.
- `legacy/` — the untouched Tkinter/Word implementation retained only as reference.

## Scope

This creates a GST tax-invoice PDF; it does not submit an IRP e-invoice or generate an IRN. It is deliberately a single-user local tool and does not cover composition-scheme Bills of Supply.
