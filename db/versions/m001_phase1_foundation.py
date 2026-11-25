"""Phase 1 foundation schema: users, workspaces, companies, invoices, and triggers."""

from __future__ import annotations

import sqlite3

from db.connection import execute_sql_statements


DDL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memberships (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('owner', 'admin', 'member')),
    PRIMARY KEY (user_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    legal_name TEXT NOT NULL,
    gstin TEXT NOT NULL,
    pan TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL,
    state TEXT NOT NULL,
    state_code TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'INR',
    bank_details TEXT NOT NULL DEFAULT '',
    logo_path TEXT NOT NULL DEFAULT '',
    invoice_prefix TEXT NOT NULL,
    terms_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_companies_workspace ON companies(workspace_id);

CREATE TABLE IF NOT EXISTS number_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    document_type TEXT NOT NULL DEFAULT 'invoice',
    financial_year TEXT NOT NULL,
    prefix TEXT NOT NULL,
    last_number INTEGER NOT NULL DEFAULT 0 CHECK(last_number >= 0),
    UNIQUE(company_id, document_type, financial_year)
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    billing_address TEXT NOT NULL DEFAULT '',
    shipping_address TEXT NOT NULL DEFAULT '',
    gstin TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    state_code TEXT NOT NULL DEFAULT '',
    payment_terms TEXT NOT NULL DEFAULT '',
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK(is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, id)
);

CREATE INDEX IF NOT EXISTS idx_customers_company ON customers(company_id);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    hsn_sac TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    unit_price TEXT NOT NULL DEFAULT '0.00',
    gst_rate TEXT NOT NULL DEFAULT '0',
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK(is_archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_company ON products(company_id);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    customer_id INTEGER,
    invoice_no TEXT,
    financial_year TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    due_date TEXT,
    doc_status TEXT NOT NULL DEFAULT 'draft' CHECK(doc_status IN ('draft', 'issued', 'cancelled')),
    seller_snapshot TEXT,
    buyer_snapshot TEXT,
    customer_name TEXT NOT NULL DEFAULT '',
    place_of_supply TEXT NOT NULL DEFAULT '',
    taxable_total_paise INTEGER NOT NULL DEFAULT 0 CHECK(taxable_total_paise >= 0),
    cgst_total_paise INTEGER NOT NULL DEFAULT 0 CHECK(cgst_total_paise >= 0),
    sgst_total_paise INTEGER NOT NULL DEFAULT 0 CHECK(sgst_total_paise >= 0),
    igst_total_paise INTEGER NOT NULL DEFAULT 0 CHECK(igst_total_paise >= 0),
    cess_total_paise INTEGER NOT NULL DEFAULT 0 CHECK(cess_total_paise >= 0),
    grand_total_paise INTEGER NOT NULL DEFAULT 0 CHECK(grand_total_paise >= 0),
    pdf_path TEXT,
    pdf_sha256 TEXT,
    template_version TEXT,
    cancelled_at TEXT,
    cancel_reason TEXT,
    legacy INTEGER NOT NULL DEFAULT 0 CHECK(legacy IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (company_id, customer_id) REFERENCES customers(company_id, id) ON DELETE RESTRICT,
    UNIQUE(company_id, invoice_no),
    CHECK(doc_status != 'draft' OR invoice_no IS NULL),
    CHECK(doc_status = 'draft' OR (invoice_no IS NOT NULL AND length(invoice_no) BETWEEN 1 AND 16)),
    CHECK(doc_status != 'issued' OR legacy = 1 OR (seller_snapshot IS NOT NULL AND buyer_snapshot IS NOT NULL)),
    CHECK(doc_status != 'cancelled' OR (cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL AND length(trim(cancel_reason)) > 0))
);

CREATE INDEX IF NOT EXISTS idx_invoices_company_created ON invoices(company_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_invoices_company_fy ON invoices(company_id, financial_year);

CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    line_order INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL,
    hsn_sac TEXT NOT NULL,
    quantity TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT '',
    unit_price TEXT NOT NULL,
    discount_paise INTEGER NOT NULL DEFAULT 0 CHECK(discount_paise >= 0),
    taxable_value_paise INTEGER NOT NULL CHECK(taxable_value_paise >= 0),
    gst_rate TEXT NOT NULL,
    cgst_paise INTEGER NOT NULL DEFAULT 0 CHECK(cgst_paise >= 0),
    sgst_paise INTEGER NOT NULL DEFAULT 0 CHECK(sgst_paise >= 0),
    igst_paise INTEGER NOT NULL DEFAULT 0 CHECK(igst_paise >= 0),
    cess_paise INTEGER NOT NULL DEFAULT 0 CHECK(cess_paise >= 0),
    total_paise INTEGER NOT NULL CHECK(total_paise >= 0)
);

CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE RESTRICT,
    amount_paise INTEGER NOT NULL CHECK(amount_paise > 0),
    paid_on TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT '',
    reference TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    company_id INTEGER REFERENCES companies(id) ON DELETE RESTRICT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_workspace ON audit_log(workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS legacy_imports (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    imported_count INTEGER NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_invoices_no_delete
BEFORE DELETE ON invoices
WHEN OLD.doc_status != 'draft'
BEGIN
    SELECT RAISE(ABORT, 'Issued or cancelled invoices cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS trg_invoices_no_revert_or_mutate
BEFORE UPDATE ON invoices
BEGIN
    SELECT RAISE(ABORT, 'Issued or cancelled invoices cannot revert to draft')
    WHERE OLD.doc_status != 'draft' AND NEW.doc_status = 'draft';

    SELECT RAISE(ABORT, 'Cancelled invoices are immutable')
    WHERE OLD.doc_status = 'cancelled';

    SELECT RAISE(ABORT, 'Issued invoice core fields are immutable')
    WHERE OLD.doc_status = 'issued' AND (
        NEW.company_id IS NOT OLD.company_id
        OR NEW.customer_id IS NOT OLD.customer_id
        OR NEW.invoice_no IS NOT OLD.invoice_no
        OR NEW.financial_year IS NOT OLD.financial_year
        OR NEW.invoice_date IS NOT OLD.invoice_date
        OR NEW.seller_snapshot IS NOT OLD.seller_snapshot
        OR NEW.buyer_snapshot IS NOT OLD.buyer_snapshot
        OR NEW.place_of_supply IS NOT OLD.place_of_supply
        OR NEW.taxable_total_paise IS NOT OLD.taxable_total_paise
        OR NEW.cgst_total_paise IS NOT OLD.cgst_total_paise
        OR NEW.sgst_total_paise IS NOT OLD.sgst_total_paise
        OR NEW.igst_total_paise IS NOT OLD.igst_total_paise
        OR NEW.cess_total_paise IS NOT OLD.cess_total_paise
        OR NEW.grand_total_paise IS NOT OLD.grand_total_paise
        OR NEW.legacy IS NOT OLD.legacy
    );

    SELECT RAISE(ABORT, 'Issued invoice PDF metadata cannot be overwritten')
    WHERE OLD.doc_status = 'issued' AND (
        (OLD.pdf_path IS NOT NULL AND NEW.pdf_path IS NOT OLD.pdf_path)
        OR (OLD.pdf_sha256 IS NOT NULL AND NEW.pdf_sha256 IS NOT OLD.pdf_sha256)
        OR (OLD.template_version IS NOT NULL AND NEW.template_version IS NOT OLD.template_version)
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_invoice_items_insert_only_draft
BEFORE INSERT ON invoice_items
WHEN (SELECT doc_status FROM invoices WHERE id = NEW.invoice_id) != 'draft'
BEGIN
    SELECT RAISE(ABORT, 'Cannot insert items into a non-draft invoice');
END;

CREATE TRIGGER IF NOT EXISTS trg_invoice_items_update_only_draft
BEFORE UPDATE ON invoice_items
WHEN (SELECT doc_status FROM invoices WHERE id = OLD.invoice_id) != 'draft'
BEGIN
    SELECT RAISE(ABORT, 'Cannot modify items of a non-draft invoice');
END;

CREATE TRIGGER IF NOT EXISTS trg_invoice_items_delete_only_draft
BEFORE DELETE ON invoice_items
WHEN (SELECT doc_status FROM invoices WHERE id = OLD.invoice_id) != 'draft'
BEGIN
    SELECT RAISE(ABORT, 'Cannot delete items from a non-draft invoice');
END;
"""


def upgrade(connection: sqlite3.Connection) -> None:
    """Create Phase 1 tables, indexes, and immutability triggers."""
    execute_sql_statements(connection, DDL)
