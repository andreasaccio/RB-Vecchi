from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import secrets
import threading
import time
from datetime import date, datetime, time as dt_time, timedelta
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    Response,
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
from .notifier import TelegramError, TelegramNotifier
from . import bolletta, raccolta
from .shelly import PresaRicarica, ShellyClient, ShellyError

LOGGER = logging.getLogger(__name__)

TELEGRAM_TEST_COOLDOWN_SECONDS = 30.0
CARICA_COOLDOWN_SECONDS = 30.0
BOLLETTA_COOLDOWN_SECONDS = 30.0
PREZZO_MASSIMO = 5.0

TELEGRAM_ERROR_HINTS = {
    401: "Token del bot non valido: controllare TELEGRAM_BOT_TOKEN.",
    403: "Il bot non può scrivere nella chat: è stato rimosso dal gruppo o bloccato.",
    429: "Troppi messaggi inviati: riprovare più tardi.",
}


def impronta_static(cartella: Path) -> str:
    """Impronta dei file di static/. Le pagine la mettono come ?v= negli URL di
    CSS e JS: dopo un aggiornamento l'URL cambia e il telefono scarica i file
    nuovi anche se il service worker ha ancora in cache quelli vecchi."""
    h = hashlib.sha256()
    for f in sorted(cartella.iterdir()):
        if f.is_file():
            h.update(f.name.encode() + b"\0" + f.read_bytes())
    return h.hexdigest()[:10]


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
    app.jinja_env.globals["asset_v"] = impronta_static(Path(app.static_folder))

    database = Database(settings.database_path)
    shelly = ShellyClient(
        settings.shelly_host,
        settings.shelly_username,
        settings.shelly_password,
        input_id=settings.shelly_input_id,
        switch_id=settings.shelly_switch_id,
        timeout=settings.shelly_timeout_seconds,
    )
    presa = PresaRicarica(settings.carica_shelly_host, timeout=settings.shelly_timeout_seconds)
    notifier = TelegramNotifier(
        settings.telegram_bot_token,
        settings.telegram_chat_id,
    )
    monitor = GarageMonitor(settings, database, shelly, notifier)
    bollette = bolletta.InvioBollette(
        database,
        notifier,
        lambda: raccolta.leggi_consumi(settings.raccolta_dir / raccolta.CONSUMI_CARICA),
        settings.timezone,
        settings.app_name,
    )
    if start_monitor:
        monitor.start()
        bollette.start()

    app.extensions["settings"] = settings
    app.extensions["database"] = database
    app.extensions["garage_monitor"] = monitor
    app.extensions["bollette"] = bollette

    def authenticated() -> bool:
        return not settings.web_auth_enabled or session.get("authenticated") is True

    def ensure_csrf() -> str:
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    def require_csrf() -> None:
        supplied = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not supplied or not expected or not hmac.compare_digest(supplied, expected):
            abort(403)

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
        return render_template("index.html", app_name=settings.app_name, csrf_token=ensure_csrf())

    @app.get("/dettagli")
    @login_required
    def dettagli():
        # Pagina "Impianto": oltre ai dettagli in sola lettura ospita il test Telegram.
        return render_template(
            "dettagli.html",
            app_name=settings.app_name,
            csrf_token=ensure_csrf(),
            alert_minutes=max(1, settings.open_alert_seconds // 60),
            shelly_address=settings.shelly_host.replace("http://", "").replace("https://", ""),
            telegram_enabled=settings.telegram_enabled,
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

    def leggi_raccolta(lettore, nome_file: str, chiave: str):
        # Endpoint separati da /api/status: leggono solo i file della raccolta dati.
        try:
            dati = lettore(settings.raccolta_dir / nome_file)
        except Exception:
            LOGGER.exception("Lettura di %s fallita", nome_file)
            dati = {"stato": "non_disponibile", "motivo": "errore interno di lettura",
                    "eta_s": None}
        return jsonify({"ok": True, chiave: dati})

    @app.get("/api/powerline")
    @login_required
    def api_powerline():
        return leggi_raccolta(raccolta.leggi_riepilogo, raccolta.STATO_RETE, "powerline")

    @app.get("/api/carica")
    @login_required
    def api_carica():
        return leggi_raccolta(raccolta.leggi_carica, raccolta.CARICA, "carica")

    @app.get("/api/sistema")
    @login_required
    def api_sistema():
        return leggi_raccolta(raccolta.leggi_sistema, raccolta.SISTEMA, "sistema")

    @app.get("/api/carica/registro")
    @login_required
    def api_carica_registro():
        try:
            registro = raccolta.leggi_registro_carica(settings.raccolta_dir / raccolta.REGISTRO_CARICA)
        except Exception:
            LOGGER.exception("Lettura del registro della ricarica fallita")
            registro = {"stato": "non_disponibile", "motivo": "errore interno di lettura",
                        "eta_s": None, "sessioni": []}
        return jsonify({"ok": True, "registro": registro,
                        "comandi": database.list_commands("CARICA_ON", limit=20)})

    carica_lock = threading.Lock()
    ultima_carica_ora = -CARICA_COOLDOWN_SECONDS

    @app.post("/api/carica/avvia")
    @login_required
    def api_carica_avvia():
        # Unica scrittura di RB-Vecchi verso lo Shelly della ricarica: chiude il
        # relè. Lo riapre lo script ricarica-notturna sullo Shelly.
        nonlocal ultima_carica_ora
        require_csrf()
        now = time.monotonic()
        with carica_lock:
            remaining = CARICA_COOLDOWN_SECONDS - (now - ultima_carica_ora)
            if remaining > 0:
                return jsonify({"ok": False,
                                "error": f"Attendere {math.ceil(remaining)} s prima di riprovare",
                                "retry_after": math.ceil(remaining)}), 429
            ultima_carica_ora = now
        try:
            era_accesa = presa.accendi()
        except ShellyError as exc:
            with carica_lock:
                ultima_carica_ora = -CARICA_COOLDOWN_SECONDS
            database.log_command(time.time(), False, str(exc), "CARICA_ON")
            LOGGER.warning("Carica ora non riuscita: %s", exc)
            return jsonify({"ok": False, "error": str(exc)}), 503
        detail = "presa già accesa" if era_accesa else "presa accesa"
        database.log_command(time.time(), True, detail, "CARICA_ON")
        LOGGER.info("Carica ora dalla dashboard: %s", detail)
        message = ("La presa era già accesa" if era_accesa else
                   "Presa accesa: se l'auto ha bisogno di carica parte subito, "
                   "altrimenti lo Shelly la rispegne entro 5 minuti")
        return jsonify({"ok": True, "message": message, "era_accesa": era_accesa})

    # ------------------------------------------------------------ consumi e bollette

    tz = ZoneInfo(settings.timezone)

    @app.get("/ricarica")
    @login_required
    def ricarica():
        return render_template("ricarica.html", app_name=settings.app_name,
                               csrf_token=ensure_csrf())

    def scheda_bolletta(periodo: bolletta.Periodo, b: dict | None, riga: dict | None,
                        stato: str) -> dict:
        return {
            "periodo": periodo.id, "titolo": periodo.titolo, "stato": stato,
            "kWh": b["kWh"] if b else None, "euro": b["euro"] if b else None,
            "parziale": b["parziale"] if b else None,
            "emessa": b["emessa"] if b and riga else None,
            "inviata_ts": riga["inviata_ts"] if riga else None,
            "tentativi": riga["tentativi"] if riga else 0,
            "ultimo_esito": riga["ultimo_esito"] if riga else None,
        }

    @app.get("/api/ricarica")
    @login_required
    def api_ricarica():
        adesso = time.time()
        oggi = datetime.fromtimestamp(adesso, tz).date()
        try:
            consumi = raccolta.leggi_consumi(settings.raccolta_dir / raccolta.CONSUMI_CARICA)
        except Exception:
            LOGGER.exception("Lettura dei consumi della ricarica fallita")
            consumi = {"stato": "non_disponibile", "motivo": "errore interno di lettura",
                       "eta_s": None, "giorni": [], "sessioni": [], "profilo": None,
                       "contatore": None}
        tariffe = database.list_tariffe()

        giorni, mesi = [], {}
        for giorno, wh, _, _ in consumi["giorni"]:
            kwh = wh / 1000
            euro = kwh * bolletta.prezzo_del_giorno(tariffe, giorno)
            giorni.append({"giorno": giorno, "kWh": round(kwh, 3), "euro": round(euro, 4)})
            m = mesi.setdefault(giorno[:7], {"mese": giorno[:7], "kWh": 0.0, "euro": 0.0})
            m["kWh"] += kwh
            m["euro"] += euro
        for s in consumi["sessioni"]:
            giorno = datetime.fromtimestamp(s["inizio"], tz).date().isoformat()
            s["euro"] = round((s["energia_Wh"] or 0) / 1000
                              * bolletta.prezzo_del_giorno(tariffe, giorno), 4)

        corrente = bolletta.Periodo.da_data(oggi)
        schede = []
        anteprima = (bolletta.calcola(consumi, tariffe, corrente, adesso, tz)
                     if consumi["stato"] == "ok" else None)
        schede.append(scheda_bolletta(corrente, anteprima, None, "in_corso"))
        emesse = {r["periodo"]: r for r in database.list_bollette()}
        precedente = corrente.precedente()
        if precedente.id not in emesse:
            b = (bolletta.calcola(consumi, tariffe, precedente, adesso, tz)
                 if consumi["stato"] == "ok" else None)
            if b and b["giorni"]:
                schede.append(scheda_bolletta(precedente, b, None, "da_emettere"))
        for periodo_id, riga in emesse.items():
            b = json.loads(riga["dati"])
            stato = "inviata" if riga["inviata_ts"] else "non_inviata"
            schede.append(scheda_bolletta(bolletta.Periodo.da_id(periodo_id), b, riga, stato))

        oggi_txt = oggi.isoformat()
        riepilogo = {
            "oggi": next(({"kWh": g["kWh"], "euro": g["euro"]} for g in giorni
                          if g["giorno"] == oggi_txt), {"kWh": 0.0, "euro": 0.0}),
            "mese": {k: round(v, 3) for k, v in mesi.get(oggi_txt[:7], {"kWh": 0.0, "euro": 0.0}).items()
                     if k != "mese"},
            "bimestre": {"periodo": corrente.id, "titolo": corrente.titolo,
                         "kWh": anteprima["kWh"] if anteprima else None,
                         "euro": anteprima["euro"] if anteprima else None},
        }
        return jsonify({
            "ok": True,
            "consumi": {k: consumi.get(k) for k in ("stato", "motivo", "eta_s", "sessioni",
                                                     "profilo", "contatore")},
            "giorni": giorni,
            "mesi": [{"mese": m["mese"], "kWh": round(m["kWh"], 3), "euro": round(m["euro"], 2)}
                     for m in sorted(mesi.values(), key=lambda m: m["mese"])],
            "riepilogo": riepilogo,
            "tariffe": tariffe,
            "prezzo_attuale": bolletta.prezzo_del_giorno(tariffe, oggi_txt),
            "prezzo_predefinito": bolletta.PREZZO_PREDEFINITO,
            "prezzo_dal_minimo": corrente.dal.isoformat(),
            "bollette": schede,
        })

    @app.post("/api/ricarica/prezzo")
    @login_required
    def api_ricarica_prezzo():
        require_csrf()
        dati = request.get_json(silent=True) or {}
        oggi = datetime.now(tz).date()
        minimo = bolletta.Periodo.da_data(oggi).dal
        try:
            prezzo = float(str(dati.get("eur_kwh", "")).replace(",", "."))
            dal = date.fromisoformat(str(dati.get("dal") or oggi.isoformat()))
        except ValueError:
            return jsonify({"ok": False, "error": "Prezzo o data non validi"}), 400
        if not (0 < prezzo <= PREZZO_MASSIMO) or math.isnan(prezzo):
            return jsonify({"ok": False,
                            "error": f"Il prezzo deve essere fra 0 e {PREZZO_MASSIMO:.0f} €/kWh"}), 400
        if dal < minimo:
            return jsonify({"ok": False, "error": "Il prezzo può valere al più presto dall'inizio "
                            f"del bimestre in corso ({minimo:%d/%m/%Y})"}), 400
        if dal > oggi + timedelta(days=366):
            return jsonify({"ok": False, "error": "Data troppo lontana"}), 400
        database.set_tariffa(dal.isoformat(), round(prezzo, 4), time.time())
        LOGGER.info("Prezzo della ricarica: %.4f €/kWh dal %s", prezzo, dal)
        return jsonify({"ok": True, "message": f"Prezzo {prezzo:.3f} €/kWh dal {dal:%d/%m/%Y}"
                        .replace(".", ",", 1), "tariffe": database.list_tariffe()})

    def periodo_o_404(periodo_id: str) -> bolletta.Periodo:
        try:
            return bolletta.Periodo.da_id(periodo_id)
        except ValueError:
            abort(404)

    @app.get("/ricarica/bolletta/<periodo_id>.pdf")
    @login_required
    def ricarica_bolletta_pdf(periodo_id: str):
        periodo = periodo_o_404(periodo_id)
        b = bollette.fotografia(periodo)
        anteprima = b is None
        if b is None:
            b = bollette.anteprima(periodo, time.time())
        if b is None or not b["giorni"]:
            return jsonify({"ok": False, "error": "Nessun dato per il periodo"}), 409
        risposta = Response(bollette.pdf(b, anteprima), mimetype="application/pdf")
        risposta.headers["Content-Disposition"] = (
            f'inline; filename="{bolletta.nome_file(b)}"')
        return risposta

    bolletta_lock = threading.Lock()
    ultimo_invio_bolletta = -BOLLETTA_COOLDOWN_SECONDS

    @app.post("/api/ricarica/bolletta/<periodo_id>/invia")
    @login_required
    def api_ricarica_bolletta_invia(periodo_id: str):
        nonlocal ultimo_invio_bolletta
        require_csrf()
        periodo = periodo_o_404(periodo_id)
        adesso = time.time()
        if periodo.fine_ts(tz) > adesso:
            return jsonify({"ok": False, "error": "Il bimestre non è ancora finito"}), 409
        if not notifier.enabled:
            return jsonify({"ok": False, "error": "Telegram non configurato"}), 409
        with bolletta_lock:
            restante = BOLLETTA_COOLDOWN_SECONDS - (time.monotonic() - ultimo_invio_bolletta)
            if restante > 0:
                return jsonify({"ok": False, "error": f"Attendere {math.ceil(restante)} s"}), 429
            ultimo_invio_bolletta = time.monotonic()
        b = bollette.emetti(periodo, adesso)
        if b is None:
            return jsonify({"ok": False, "error": "Nessun dato per il periodo"}), 409
        ok, esito = bollette.invia(b, adesso)
        if not ok:
            return jsonify({"ok": False, "error": esito}), 502
        return jsonify({"ok": True, "message": f"Bolletta {periodo.titolo} inviata su Telegram"})

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
        require_csrf()
        try:
            monitor.pulse()
        except Exception as exc:
            LOGGER.warning("Comando garage rifiutato o fallito: %s", exc)
            return jsonify({"ok": False, "error": str(exc)}), 503
        return jsonify({"ok": True, "message": "Impulso inviato al basculante"})

    telegram_test_lock = threading.Lock()
    last_telegram_test_at = -TELEGRAM_TEST_COOLDOWN_SECONDS

    def telegram_test_message() -> str:
        # Usa solo lo snapshot in memoria: il test non interroga lo Shelly.
        tz = ZoneInfo(settings.timezone)
        now = datetime.now(tz)
        status = monitor.snapshot()
        lines = [f"🧪 Test RB-Vecchi — {now:%d/%m/%Y %H:%M:%S}"]
        state = {True: "aperto", False: "chiuso"}.get(status["garage_open"])
        if status["online"] and state:
            if status["state_duration_seconds"] is not None:
                duration = GarageMonitor._format_duration(status["state_duration_seconds"])
                lines.append(f"Basculante: {state} da {duration}.")
            else:
                lines.append(f"Basculante: {state}.")
        else:
            lines.append("Basculante: stato non disponibile, Shelly non raggiungibile.")
            if status["last_success"] is not None and state:
                last = datetime.fromtimestamp(status["last_success"], tz)
                ago = GarageMonitor._format_duration(status["stale_seconds"] or 0)
                lines.append(
                    f"Ultima lettura valida: {state}, alle {last:%H:%M del %d/%m} ({ago} fa)."
                )
            elif state:
                lines.append(f"Ultimo stato registrato: {state}.")
        lines.append("Messaggio di prova inviato dalla dashboard.")
        return "\n".join(lines)

    @app.post("/api/telegram/test")
    @login_required
    def api_telegram_test():
        nonlocal last_telegram_test_at
        require_csrf()
        if not notifier.enabled:
            return (
                jsonify({"ok": False, "error": "Telegram non configurato: token o chat ID mancanti"}),
                409,
            )
        now = time.monotonic()
        with telegram_test_lock:
            remaining = TELEGRAM_TEST_COOLDOWN_SECONDS - (now - last_telegram_test_at)
            if remaining > 0:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": f"Attendere {math.ceil(remaining)} s prima di un nuovo test",
                            "retry_after": math.ceil(remaining),
                        }
                    ),
                    429,
                )
            last_telegram_test_at = now

        try:
            notifier.send(telegram_test_message())
        except TelegramError as exc:
            if exc.error_code != 429:
                with telegram_test_lock:
                    last_telegram_test_at = -TELEGRAM_TEST_COOLDOWN_SECONDS
            LOGGER.warning("Test Telegram fallito: %s", exc)
            hint = TELEGRAM_ERROR_HINTS.get(exc.error_code)
            if exc.error_code == 400 and "chat not found" in exc.description.lower():
                hint = "Chat inesistente o bot mai avviato in quella chat: controllare TELEGRAM_CHAT_ID."
            error = f"{exc} — {hint}" if hint else str(exc)
            status_code = 502 if exc.error_code is not None else 504
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": error,
                        "telegram_error_code": exc.error_code,
                        "telegram_description": exc.description,
                    }
                ),
                status_code,
            )
        LOGGER.info("Test Telegram inviato dalla dashboard")
        return jsonify({"ok": True, "message": "Messaggio di prova consegnato a Telegram"})

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
