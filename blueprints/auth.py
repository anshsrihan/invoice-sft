"""Authentication blueprint: registration, login, and POST-only logout."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from config import MIN_PASSWORD_LENGTH
from core.security import AuthUser, is_safe_redirect_url, list_user_companies, record_audit_log
from db.connection import db_session, get_connection


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _registration_open(db_path: str) -> bool:
    if current_app.config.get("ALLOW_REGISTRATION"):
        return True
    conn = get_connection(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()["cnt"]
        return int(count) == 0
    finally:
        conn.close()


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    db_path = current_app.config["DATABASE_PATH"]
    if not _registration_open(db_path):
        abort(403, description="Registration is closed.")

    if current_user.is_authenticated:
        return redirect(url_for("invoices.index"))

    errors: dict[str, str] = {}
    form_data = {"email": "", "workspace_name": ""}

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        workspace_name = request.form.get("workspace_name", "").strip()
        form_data = {"email": email, "workspace_name": workspace_name}

        if not email or "@" not in email:
            errors["email"] = "Enter a valid email address."
        if len(password) < MIN_PASSWORD_LENGTH:
            errors["password"] = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        elif password != confirm:
            errors["confirm_password"] = "Passwords do not match."
        if not workspace_name:
            errors["workspace_name"] = "Workspace name is required."

        if not errors:
            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with db_session(db_path, immediate=True) as conn:
                if not current_app.config.get("ALLOW_REGISTRATION"):
                    count = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()["cnt"]
                    if int(count) > 0:
                        abort(403, description="Registration is closed.")

                existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
                if existing:
                    errors["email"] = "An account with this email already exists."
                else:
                    user_cur = conn.execute(
                        "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
                        (email, generate_password_hash(password), now_iso),
                    )
                    user_id = int(user_cur.lastrowid)
                    ws_cur = conn.execute(
                        "INSERT INTO workspaces(name, created_at) VALUES (?, ?)",
                        (workspace_name, now_iso),
                    )
                    workspace_id = int(ws_cur.lastrowid)
                    conn.execute(
                        "INSERT INTO memberships(user_id, workspace_id, role) VALUES (?, ?, 'owner')",
                        (user_id, workspace_id),
                    )
                    record_audit_log(
                        conn,
                        workspace_id=workspace_id,
                        company_id=None,
                        user_id=user_id,
                        action="user_registered",
                        entity="user",
                        entity_id=user_id,
                        details={"email": email},
                    )
                    login_user(AuthUser(user_id, email, now_iso))
                    return redirect(url_for("companies.new_company"))

    return render_template("auth/register.html", errors=errors, form=form_data), (400 if errors else 200)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    db_path = current_app.config["DATABASE_PATH"]
    if current_user.is_authenticated:
        return redirect(url_for("invoices.index"))

    conn = get_connection(db_path)
    try:
        user_count = int(conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()["cnt"])
    finally:
        conn.close()
    if user_count == 0:
        return redirect(url_for("auth.register"))

    errors: dict[str, str] = {}
    email = ""
    next_url = request.args.get("next") or request.form.get("next") or ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT id, email, password_hash, created_at FROM users WHERE email = ?",
                (email,),
            ).fetchone()
            if not row or not check_password_hash(row["password_hash"], password):
                errors["form"] = "Invalid email or password."
            else:
                user = AuthUser(row["id"], row["email"], row["created_at"])
                login_user(user)
                companies = list_user_companies(conn, user.user_id)
                if not companies:
                    return redirect(url_for("companies.new_company"))
                session["active_company_id"] = companies[0]["id"]
                if is_safe_redirect_url(next_url):
                    return redirect(next_url)
                return redirect(url_for("invoices.index"))
        finally:
            conn.close()

    return render_template(
        "auth/login.html",
        errors=errors,
        email=email,
        next_url=next_url if is_safe_redirect_url(next_url) else "",
        registration_open=_registration_open(db_path),
    ), (401 if errors else 200)


@auth_bp.post("/logout")
@login_required
def logout():
    session.pop("active_company_id", None)
    logout_user()
    return redirect(url_for("auth.login"))
