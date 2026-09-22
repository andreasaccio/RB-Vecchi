from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on", "si", "sì"}


def _as_int(name: str, default: int, minimum: int | None = None) -> int:
    value = int(os.getenv(name, str(default)))
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} deve essere >= {minimum}")
    return value


def _as_float(name: str, default: float, minimum: float | None = None) -> float:
    value = float(os.getenv(name, str(default)))
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} deve essere >= {minimum}")
    return value


@dataclass(frozen=True)
class Settings:
    app_name: str
    shelly_host: str
    shelly_username: str
    shelly_password: str
    shelly_input_id: int
    shelly_switch_id: int
    input_true_is_open: bool
    shelly_timeout_seconds: float
    poll_interval_seconds: float
    open_alert_seconds: int
    relay_pulse_seconds: float
    command_cooldown_seconds: float
    require_detached_mode: bool
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_notify_closed_after_alert: bool
    web_username: str
    web_password: str
    secret_key: str
    database_path: Path
    timezone: str
    listen_host: str
    listen_port: int
    log_level: str

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def web_auth_enabled(self) -> bool:
        return bool(self.web_username and self.web_password)


def load_settings(env_file: str | None = None) -> Settings:
    if env_file:
        load_dotenv(env_file)
    else:
        load_dotenv()

    secret_key = os.getenv("SECRET_KEY", "").strip() or secrets.token_urlsafe(48)
    host = os.getenv("SHELLY_HOST", "192.168.1.100").strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"

    return Settings(
        app_name=os.getenv("APP_NAME", "RB-Vecchi · Casa").strip(),
        shelly_host=host,
        shelly_username=os.getenv("SHELLY_USERNAME", "admin").strip(),
        shelly_password=os.getenv("SHELLY_PASSWORD", ""),
        shelly_input_id=_as_int("SHELLY_INPUT_ID", 0, 0),
        shelly_switch_id=_as_int("SHELLY_SWITCH_ID", 0, 0),
        input_true_is_open=_as_bool("INPUT_TRUE_IS_OPEN", True),
        shelly_timeout_seconds=_as_float("SHELLY_TIMEOUT_SECONDS", 4.0, 0.5),
        poll_interval_seconds=_as_float("POLL_INTERVAL_SECONDS", 2.0, 0.5),
        open_alert_seconds=_as_int("GARAGE_OPEN_ALERT_SECONDS", 300, 10),
        relay_pulse_seconds=_as_float("RELAY_PULSE_SECONDS", 0.7, 0.1),
        command_cooldown_seconds=_as_float("COMMAND_COOLDOWN_SECONDS", 3.0, 0.5),
        require_detached_mode=_as_bool("REQUIRE_DETACHED_MODE", True),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        telegram_notify_closed_after_alert=_as_bool(
            "TELEGRAM_NOTIFY_CLOSED_AFTER_ALERT", True
        ),
        web_username=os.getenv("WEB_USERNAME", "admin").strip(),
        web_password=os.getenv("WEB_PASSWORD", "").strip(),
        secret_key=secret_key,
        database_path=Path(
            os.getenv("DATABASE_PATH", "/var/lib/rb-vecchi/garage.db")
        ).expanduser(),
        timezone=os.getenv("TIMEZONE", "Europe/Rome").strip(),
        listen_host=os.getenv("LISTEN_HOST", "0.0.0.0").strip(),
        listen_port=_as_int("LISTEN_PORT", 8080, 1),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper().strip(),
    )
