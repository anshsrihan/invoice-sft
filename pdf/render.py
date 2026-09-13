"""Render completed invoices to print-ready HTML and PDF bytes."""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _configure_macos_library_path() -> None:
    """Help pip-installed WeasyPrint find Homebrew's Pango/GObject libraries."""
    if sys.platform != "darwin":
        return
    brew_library_paths = [path for path in ("/opt/homebrew/lib", "/usr/local/lib") if Path(path).is_dir()]
    if not brew_library_paths:
        return
    existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    entries = brew_library_paths + ([existing] if existing else [])
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(entries)


def format_money(value: Decimal | float | str) -> str:
    """Display a currency amount with a rupee symbol and two decimal places."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    return f"₹{amount:,.2f}"


def format_number(value: Decimal | float | str) -> str:
    amount = Decimal(str(value))
    return f"{amount.normalize():f}" if amount % 1 else f"{amount:.0f}"


def _environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "xml"])
    )
    environment.filters["money"] = format_money
    environment.filters["number"] = format_number
    return environment


def render_invoice_html(invoice: dict[str, Any]) -> str:
    """Render the audit-friendly invoice template for previewing or PDF export."""
    return _environment().get_template("invoice.html").render(invoice=invoice)


def render_invoice_pdf(invoice: dict[str, Any]) -> bytes:
    """Convert an invoice to PDF without relying on Word or LibreOffice."""
    _configure_macos_library_path()
    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise RuntimeError(
            "WeasyPrint is not installed. Run 'pip install -r requirements.txt' before generating PDFs."
        ) from exc

    return HTML(string=render_invoice_html(invoice), base_url=str(TEMPLATE_DIR)).write_pdf()
