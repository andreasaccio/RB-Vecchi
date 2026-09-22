from __future__ import annotations

import hmac
import logging
import secrets
import time
from datetime import datetime, time as dt_time
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .config import Settings, load_settings
from .db import Database
from .monitor import GarageMonitor
from .notifier import TelegramNotifier
from .shelly import ShellyClient

LOGGER = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, start_monitor: bool = True) -> Flask:
    settings = settings or load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=86400 * 30,
        MAX_CONTENT_LENGTH=16 * 1024,
    )

    database = Database(settings.database_path)
    shelly = ShellyClient(
        settings.shelly_host,
        settings.shelly_username,
        settings.shelly_password,
        input_id=settings.shelly_input_id,
        switch_id=settings.shelly_switch_id,
        timeout=settings.shelly_timeout_seconds,
    )
    notifier = TelegramNotifier(
        settings.telegram_bot_token,
        settings.telegram_chat_id,
    )
    monitor = GarageMonitor(settings, database, shelly, notifier)
    if start_monitor:
        monitor.start()

    app.extensions["settings"] = settings
    app.extensions["database"] = database
    app.extensions["garage_monitor"] = monitor

    def authenticated() -> bool:
        return not settings.web_auth_enabled or session.get("authenticated") is True

    def ensure_csrf() -> str:
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not authenticated():
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "Sessione scaduta"}), 401
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)

        return wrapped

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/login")
    def login():
        if authenticated():
            return redirect(url_for("index"))
        return render_template("login.html", app_name=settings.app_name, error=None)

    @app.post("/login")
    def login_post():
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        valid_user = hmac.compare_digest(username, settings.web_username)
        valid_password = hmac.compare_digest(password, settings.web_password)
        if not (valid_user and valid_password):
            time.sleep(0.5)
            return (
                render_template(
                    "login.html",
                    app_name=settings.app_name,
                    error="Credenziali non valide",
                ),
                401,
            )
        session.clear()
        session.permanent = True
        session["authenticated"] = True
        ensure_csrf()
        return redirect(url_for("index"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def index():
        return render_template(
            "index.html",
            app_name=settings.app_name,
            csrf_token=ensure_csrf(),
            alert_minutes=max(1, settings.open_alert_seconds // 60),
            shelly_address=settings.shelly_host.replace("http://", "").replace("https://", ""),
        )

    @app.get("/api/dashboard")
    @login_required
    def api_dashboard():
        now = datetime.now(ZoneInfo(settings.timezone))
        start_of_day = datetime.combine(now.date(), dt_time.min, tzinfo=now.tzinfo)
        snapshot = monitor.snapshot()
        events = database.list_events(limit=50)
        stats = database.stats_between(start_of_day.timestamp(), now.timestamp())
        return jsonify(
            {
                "ok": True,
                "server_time": now.isoformat(),
                "status": snapshot,
                "stats": stats,
                "events": events,
                "timezone": settings.timezone,
            }
        )

    @app.get("/api/status")
    @login_required
    def api_status():
        return jsonify({"ok": True, "status": monitor.snapshot()})

    @app.get("/api/events")
    @login_required
    def api_events():
        try:
            limit = int(request.args.get("limit", 50))
        except ValueError:
            limit = 50
        return jsonify({"ok": True, "events": database.list_events(limit)})

    @app.post("/api/garage/pulse")
    @login_required
    def api_pulse():
        supplied = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not supplied or not expected or not hmac.compare_digest(supplied, expected):
            abort(403)
        try:
            monitor.pulse()
        except Exception as exc:
            LOGGER.warning("Comando garage rifiutato o fallito: %s", exc)
            return jsonify({"ok": False, "error": str(exc)}), 503
        return jsonify({"ok": True, "message": "Impulso inviato al basculante"})

    @app.get("/healthz")
    def healthz():
        snapshot = monitor.snapshot()
        status_code = 200 if snapshot["online"] else 503
        return jsonify({"ok": snapshot["online"], "shelly_online": snapshot["online"]}), status_code

    @app.get("/manifest.webmanifest")
    def manifest():
        return app.send_static_file("manifest.webmanifest")

    @app.get("/service-worker.js")
    def service_worker():
        response = app.send_static_file("service-worker.js")
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    return app
