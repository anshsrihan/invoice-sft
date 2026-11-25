import sqlite3
import pytest

from db.connection import get_connection
from db.migrations import Migration, apply_migrations


def test_migrations_apply_from_scratch_and_are_idempotent(tmp_path):
    db_path = tmp_path / "app.db"

    first = apply_migrations(db_path)
    second = apply_migrations(db_path)

    assert first == [1]
    assert second == []

    conn = get_connection(db_path)
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {
            "schema_migrations",
            "users",
            "workspaces",
            "memberships",
            "companies",
            "number_series",
            "customers",
            "products",
            "invoices",
            "invoice_items",
            "payments",
            "audit_log",
            "legacy_imports",
        }.issubset(tables)
    finally:
        conn.close()


def test_failing_migration_leaves_no_partial_tables(tmp_path):
    db_path = tmp_path / "failing.db"

    def broken_upgrade(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE partial_table (id INTEGER PRIMARY KEY)")
        raise RuntimeError("boom during migration")

    with pytest.raises(RuntimeError, match="boom during migration"):
        apply_migrations(db_path, migrations=[Migration(99, "broken", broken_upgrade)])

    conn = get_connection(db_path)
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "partial_table" not in tables
        rows = conn.execute("SELECT version FROM schema_migrations WHERE version = 99").fetchall()
        assert rows == []
    finally:
        conn.close()


def test_foreign_keys_and_membership_roles_enforced(tmp_path):
    db_path = tmp_path / "constraints.db"
    apply_migrations(db_path)

    conn = get_connection(db_path)
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

        # Foreign key violation: membership referencing missing user/workspace
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO memberships(user_id, workspace_id, role) VALUES (999, 999, 'owner')"
            )

        # Invalid role rejected by CHECK constraint
        conn.execute(
            "INSERT INTO users(id, email, password_hash, created_at) VALUES (1, 'a@b.com', 'h', '2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO workspaces(id, name, created_at) VALUES (1, 'WS', '2026-01-01T00:00:00+00:00')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO memberships(user_id, workspace_id, role) VALUES (1, 1, 'superadmin')"
            )
    finally:
        conn.close()
