"""Local Flask entry point for the multi-business GST invoice platform."""

from __future__ import annotations

import os
from typing import Any

from flask import Flask, session
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect

from blueprints.auth import auth_bp
from blueprints.companies import companies_bp
from blueprints.invoices import invoices_bp
from config import ALLOW_REGISTRATION, DATABASE_PATH, SECRET_KEY, SESSION_COOKIE_SECURE
from core.security import active_company_for_user, list_user_companies, load_user_by_id
from db.connection import get_connection
from db.migrations import apply_migrations


csrf = CSRFProtect()
login_manager = LoginManager()
login_manager.login_view = "auth.login"


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    debug_env = os.getenv("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes"}
    app.config.from_mapping(
        DATABASE_PATH=DATABASE_PATH,
        SECRET_KEY=SECRET_KEY,
        ALLOW_REGISTRATION=ALLOW_REGISTRATION,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
        WTF_CSRF_ENABLED=True,
    )
    if test_config:
        app.config.update(test_config)

    is_debug = bool(app.debug or app.config.get("DEBUG") or debug_env)
    if not app.config.get("SECRET_KEY"):
        if is_debug:
            app.config["SECRET_KEY"] = "dev-debug-only-secret-key"
        else:
            raise RuntimeError(
                "SECRET_KEY is not configured. Set INVOICE_SECRET_KEY or FLASK_SECRET_KEY before running."
            )

    apply_migrations(app.config["DATABASE_PATH"])

    csrf.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        conn = get_connection(app.config["DATABASE_PATH"])
        try:
            return load_user_by_id(conn, user_id)
        finally:
            conn.close()

    @app.context_processor
    def inject_company_context():
        if not current_user.is_authenticated:
            return {"active_company": None, "user_companies": []}
        conn = get_connection(app.config["DATABASE_PATH"])
        try:
            companies = list_user_companies(conn, current_user.user_id)
            active = active_company_for_user(conn, current_user.user_id, session)
            return {"active_company": active, "user_companies": companies}
        finally:
            conn.close()

    app.register_blueprint(auth_bp)
    app.register_blueprint(companies_bp)
    app.register_blueprint(invoices_bp)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    debug_mode = os.environ.get("FLASK_DEBUG", "1").strip().lower() in {"1", "true", "yes"}
    app = create_app({"DEBUG": debug_mode})
    app.run(host="127.0.0.1", port=port, debug=debug_mode)
