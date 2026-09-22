from pathlib import Path

from rbvecchi.config import Settings
from rbvecchi.db import Database
from rbvecchi.monitor import GarageMonitor
from rbvecchi.shelly import ShellyStatus


class FakeShelly:
    def get_switch_config(self):
        return {"in_mode": "detached", "initial_state": "off", "auto_off": True}

    def pulse_relay(self, seconds: float):
        return {"was_on": False}


class FakeNotifier:
    def __init__(self):
        self.messages = []
        self.enabled = True

    def send(self, message: str) -> None:
        self.messages.append(message)


def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_name="Test",
        shelly_host="http://192.168.1.100",
        shelly_username="admin",
        shelly_password="",
        shelly_input_id=0,
        shelly_switch_id=0,
        input_true_is_open=True,
        shelly_timeout_seconds=4.0,
        poll_interval_seconds=2.0,
        open_alert_seconds=300,
        relay_pulse_seconds=0.7,
        command_cooldown_seconds=3.0,
        require_detached_mode=True,
        telegram_bot_token="token",
        telegram_chat_id="123",
        telegram_notify_closed_after_alert=True,
        web_username="admin",
        web_password="password",
        secret_key="secret",
        database_path=tmp_path / "garage.db",
        timezone="Europe/Rome",
        listen_host="127.0.0.1",
        listen_port=8080,
        log_level="INFO",
    )


def shelly_status(open_state: bool) -> ShellyStatus:
    return ShellyStatus(
        raw_input_state=open_state,
        relay_output=False,
        wifi_rssi=-60,
        uptime_seconds=100,
        temperature_c=None,
        firmware=None,
    )


def test_open_alert_and_close_notification(tmp_path, monkeypatch) -> None:
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    notifier = FakeNotifier()
    monitor = GarageMonitor(cfg, db, FakeShelly(), notifier)

    monkeypatch.setattr("rbvecchi.monitor.time.time", lambda: 1000.0)
    monitor._handle_status(shelly_status(True))
    assert notifier.messages == []

    monkeypatch.setattr("rbvecchi.monitor.time.time", lambda: 1301.0)
    monitor._handle_status(shelly_status(True))
    assert len(notifier.messages) == 1
    assert "ancora aperto" in notifier.messages[0]

    monkeypatch.setattr("rbvecchi.monitor.time.time", lambda: 1360.0)
    monitor._handle_status(shelly_status(False))
    assert len(notifier.messages) == 2
    assert "Garage chiuso" in notifier.messages[1]
