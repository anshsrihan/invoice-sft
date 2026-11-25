"""Authentication, workspace membership, and company-level access control."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from flask_login import UserMixin


class AuthUser(UserMixin):
    """Authenticated user loaded by Flask-Login."""

    def __init__(self, user_id: int, email: str, created_at: str) -> None:
        self.id = str(user_id)
        self.user_id = int(user_id)
        self.email = email
        self.created_at = created_at


def load_user_by_id(connection: sqlite3.Connection, user_id: str | int) -> AuthUser | None:
    try:
        numeric_id = int(user_id)
    except (TypeError, ValueError):
        return None
    row = connection.execute(
        "SELECT id, email, created_at FROM users WHERE id = ?", (numeric_id,)
    ).fetchone()
    if not row:
        return None
    return AuthUser(row["id"], row["email"], row["created_at"])


def is_safe_redirect_url(target: str | None) -> bool:
    """Ensure post-login redirects stay on this site."""
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc and target.startswith("/") and not target.startswith("//")


def get_user_workspace(connection: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT w.id, w.name, w.created_at, m.role
        FROM workspaces w
        JOIN memberships m ON m.workspace_id = w.id
        WHERE m.user_id = ?
        ORDER BY w.id ASC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def list_user_companies(connection: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT c.*
        FROM companies c
        JOIN memberships m ON m.workspace_id = c.workspace_id
        WHERE m.user_id = ?
        ORDER BY c.id ASC
        """,
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def resolve_company_access(
    connection: sqlite3.Connection, user_id: int | None, company_id: int | None
) -> dict[str, Any] | None:
    """Verify user -> workspace membership -> company ownership in one query."""
    if not user_id or not company_id:
        return None
    row = connection.execute(
        """
        SELECT c.*
        FROM companies c
        JOIN workspaces w ON w.id = c.workspace_id
        JOIN memberships m ON m.workspace_id = w.id
        WHERE c.id = ? AND m.user_id = ?
        """,
        (int(company_id), int(user_id)),
    ).fetchone()
    return dict(row) if row else None


def active_company_for_user(
    connection: sqlite3.Connection, user_id: int, session_obj: Any
) -> dict[str, Any] | None:
    """Revalidate the session's active company against workspace membership."""
    session_company_id = session_obj.get("active_company_id")
    if session_company_id is not None:
        company = resolve_company_access(connection, user_id, session_company_id)
        if company:
            return company
        session_obj.pop("active_company_id", None)

    companies = list_user_companies(connection, user_id)
    if companies:
        session_obj["active_company_id"] = companies[0]["id"]
        return companies[0]
    return None


def record_audit_log(
    connection: sqlite3.Connection,
    *,
    workspace_id: int,
    company_id: int | None,
    user_id: int | None,
    action: str,
    entity: str,
    entity_id: str | int,
    details: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO audit_log(workspace_id, company_id, user_id, action, entity, entity_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            workspace_id,
            company_id,
            user_id,
            action,
            entity,
            str(entity_id),
            json.dumps(details or {}, sort_keys=True),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
