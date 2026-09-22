#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from rbvecchi.config import load_settings
from rbvecchi.notifier import TelegramNotifier
from rbvecchi.shelly import ShellyClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnostica RB-Vecchi")
    parser.add_argument("--env", default="/etc/rb-vecchi.env")
    parser.add_argument(
        "--telegram-test",
        action="store_true",
        help="Invia un messaggio di prova al chat ID configurato",
    )
    args = parser.parse_args()

    settings = load_settings(args.env)
    client = ShellyClient(
        settings.shelly_host,
        settings.shelly_username,
        settings.shelly_password,
        settings.shelly_input_id,
        settings.shelly_switch_id,
        settings.shelly_timeout_seconds,
    )

    print(f"Shelly: {settings.shelly_host}")
    try:
        status = client.get_status()
        config = client.get_switch_config()
    except Exception as exc:
        print(f"ERRORE Shelly: {exc}", file=sys.stderr)
        return 2

    garage_open = (
        status.raw_input_state
        if settings.input_true_is_open
        else not status.raw_input_state
    )
    print("Connessione Shelly: OK")
    print(f"Input raw: {status.raw_input_state}")
    print(f"Stato interpretato: {'APERTO' if garage_open else 'CHIUSO'}")
    print(f"Input mode relè: {config.get('in_mode', 'n/d')}")
    print(f"Initial state: {config.get('initial_state', 'n/d')}")
    print(f"Auto off: {config.get('auto_off', 'n/d')}")
    print(f"Relè attivo: {status.relay_output}")
    print(f"Wi-Fi: {status.wifi_rssi if status.wifi_rssi is not None else 'n/d'} dBm")

    if settings.require_detached_mode and config.get("in_mode") != "detached":
        print("ATTENZIONE: il comando web sarà bloccato finché in_mode non sarà detached.")

    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    print(f"Telegram configurato: {'sì' if notifier.enabled else 'no'}")
    if args.telegram_test:
        if not notifier.enabled:
            print("ERRORE: token o chat ID Telegram mancanti", file=sys.stderr)
            return 3
        try:
            notifier.send("✅ Test RB-Vecchi: notifiche Telegram operative.")
            print("Messaggio Telegram di prova inviato.")
        except Exception as exc:
            print(f"ERRORE Telegram: {exc}", file=sys.stderr)
            return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
