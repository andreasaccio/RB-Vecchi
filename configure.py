#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import secrets
import shlex
import string
from pathlib import Path


def load_existing(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        try:
            parsed = shlex.split(value, posix=True)
            values[key] = parsed[0] if parsed else ""
        except ValueError:
            values[key] = value.strip('"\'')
    return values


def ask(label: str, default: str = "", secret: bool = False) -> str:
    if secret:
        suffix = " [già configurata]" if default else ""
    else:
        suffix = f" [{default}]" if default else ""
    prompt = f"{label}{suffix}: "
    value = getpass.getpass(prompt) if secret else input(prompt)
    return value.strip() or default


def ask_bool(label: str, default: bool) -> bool:
    marker = "S/n" if default else "s/N"
    while True:
        value = input(f"{label} [{marker}]: ").strip().lower()
        if not value:
            return default
        if value in {"s", "si", "sì", "y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Rispondere s oppure n.")


def generate_password(length: int = 18) -> str:
    alphabet = string.ascii_letters + string.digits + "-_!@"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def env_line(key: str, value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, (int, float)):
        rendered = str(value)
    else:
        rendered = json.dumps(value, ensure_ascii=False)
    return f"{key}={rendered}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Configura RB-Vecchi")
    parser.add_argument("--output", default="/etc/rb-vecchi.env")
    args = parser.parse_args()

    output = Path(args.output)
    existing = load_existing(output)

    print("\nConfigurazione RB-Vecchi")
    print("Premere Invio per accettare il valore proposto.\n")

    app_name = ask("Nome visualizzato", existing.get("APP_NAME", "RB-Vecchi · Casa"))
    shelly_host = ask("Indirizzo Shelly", existing.get("SHELLY_HOST", "192.168.1.100"))
    shelly_username = ask("Utente Shelly", existing.get("SHELLY_USERNAME", "admin"))
    shelly_password = ask(
        "Password Shelly (vuota se non configurata)",
        existing.get("SHELLY_PASSWORD", ""),
        secret=True,
    )

    current_mapping = existing.get("INPUT_TRUE_IS_OPEN", "true").lower() == "true"
    input_true_is_open = ask_bool(
        "Lo stato logico TRUE dell'input indica garage APERTO?",
        current_mapping,
    )

    alert_minutes = int(
        ask(
            "Minuti prima dell'avviso Telegram",
            str(max(1, int(existing.get("GARAGE_OPEN_ALERT_SECONDS", "300")) // 60)),
        )
    )
    pulse_seconds = float(
        ask("Durata impulso relè in secondi", existing.get("RELAY_PULSE_SECONDS", "0.7"))
    )

    print("\nTelegram può essere lasciato vuoto e configurato in seguito.")
    telegram_token = ask(
        "Token del bot Telegram",
        existing.get("TELEGRAM_BOT_TOKEN", ""),
        secret=True,
    )
    telegram_chat_id = ask("Chat ID Telegram", existing.get("TELEGRAM_CHAT_ID", ""))

    print("\nCredenziali della pagina web.")
    web_username = ask("Utente web", existing.get("WEB_USERNAME", "admin"))
    web_password = ask(
        "Password web (vuota per generarne una)",
        existing.get("WEB_PASSWORD", ""),
        secret=True,
    )
    generated_password = False
    if not web_password:
        web_password = generate_password()
        generated_password = True

    listen_port = int(ask("Porta web", existing.get("LISTEN_PORT", "8080")))
    secret_key = existing.get("SECRET_KEY", "") or secrets.token_urlsafe(48)

    values: list[tuple[str, str | int | float | bool]] = [
        ("APP_NAME", app_name),
        ("SHELLY_HOST", shelly_host),
        ("SHELLY_USERNAME", shelly_username),
        ("SHELLY_PASSWORD", shelly_password),
        ("SHELLY_INPUT_ID", 0),
        ("SHELLY_SWITCH_ID", 0),
        ("INPUT_TRUE_IS_OPEN", input_true_is_open),
        ("SHELLY_TIMEOUT_SECONDS", 4.0),
        ("POLL_INTERVAL_SECONDS", 2.0),
        ("GARAGE_OPEN_ALERT_SECONDS", alert_minutes * 60),
        ("RELAY_PULSE_SECONDS", pulse_seconds),
        ("COMMAND_COOLDOWN_SECONDS", 3.0),
        ("REQUIRE_DETACHED_MODE", True),
        ("TELEGRAM_BOT_TOKEN", telegram_token),
        ("TELEGRAM_CHAT_ID", telegram_chat_id),
        ("TELEGRAM_NOTIFY_CLOSED_AFTER_ALERT", True),
        ("WEB_USERNAME", web_username),
        ("WEB_PASSWORD", web_password),
        ("SECRET_KEY", secret_key),
        ("DATABASE_PATH", "/var/lib/rb-vecchi/garage.db"),
        ("TIMEZONE", "Europe/Rome"),
        ("LISTEN_HOST", "0.0.0.0"),
        ("LISTEN_PORT", listen_port),
        ("LOG_LEVEL", "INFO"),
    ]

    output.parent.mkdir(parents=True, exist_ok=True)
    content = "# Generato da configure.py\n" + "\n".join(env_line(k, v) for k, v in values) + "\n"
    output.write_text(content, encoding="utf-8")

    print(f"\nConfigurazione salvata in {output}")
    print(f"Utente web: {web_username}")
    if generated_password:
        print(f"Password web generata: {web_password}")
        print("Conservarla in un luogo sicuro.")


if __name__ == "__main__":
    main()
