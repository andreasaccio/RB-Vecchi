import logging
import sqlite3
import time
from dataclasses import replace

import pytest
import requests

from rbvecchi import notifier as notifier_module
from rbvecchi.db import Database
from rbvecchi.web import create_app
from test_monitor import settings

TOKEN = "123456:SEGRETO-DEL-BOT"


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeTelegram:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, json, timeout):
        self.calls.append({"url": url, "json": json})
        result = self.responses.pop(0) if self.responses else FakeResponse(200, {"ok": True})
        if isinstance(result, Exception):
            raise result
        return result


def make_client(tmp_path, monkeypatch, telegram, **overrides):
    cfg = replace(settings(tmp_path), telegram_bot_token=TOKEN, **overrides)
    monkeypatch.setattr(notifier_module.requests, "post", telegram)
    app = create_app(cfg, start_monitor=False)
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": "password"})
    with client.session_transaction() as sess:
        csrf = sess["csrf_token"]
    return app, client, csrf


def post_test(client, csrf):
    return client.post("/api/telegram/test", headers={"X-CSRF-Token": csrf})


def set_online(app, garage_open: bool, since_seconds_ago: int) -> None:
    monitor = app.extensions["garage_monitor"]
    monitor._snapshot.online = True
    monitor._snapshot.garage_open = garage_open
    monitor._snapshot.state_since = time.time() - since_seconds_ago
    monitor._snapshot.last_success = time.time()


def test_requires_login_and_csrf(tmp_path, monkeypatch) -> None:
    telegram = FakeTelegram()
    app, client, csrf = make_client(tmp_path, monkeypatch, telegram)

    assert client.post("/api/telegram/test").status_code == 403
    assert post_test(client, "sbagliato").status_code == 403

    anonymous = app.test_client()
    assert anonymous.post("/api/telegram/test", headers={"X-CSRF-Token": csrf}).status_code == 401
    assert telegram.calls == []


def test_message_contains_state_when_online(tmp_path, monkeypatch) -> None:
    telegram = FakeTelegram()
    app, client, csrf = make_client(tmp_path, monkeypatch, telegram)
    set_online(app, garage_open=False, since_seconds_ago=125)

    response = post_test(client, csrf)

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    text = telegram.calls[0]["json"]["text"]
    assert text.startswith("🧪 Test RB-Vecchi — ")
    assert "Basculante: chiuso da 2 min 5 s." in text


def test_works_when_shelly_offline(tmp_path, monkeypatch) -> None:
    Database(tmp_path / "garage.db").reconcile(True, time.time() - 600)
    telegram = FakeTelegram()
    _, client, csrf = make_client(tmp_path, monkeypatch, telegram)

    response = post_test(client, csrf)

    assert response.status_code == 200
    text = telegram.calls[0]["json"]["text"]
    assert "stato non disponibile, Shelly non raggiungibile" in text
    assert "Ultimo stato registrato: aperto." in text


@pytest.mark.parametrize(
    ("status_code", "description", "hint"),
    [
        (401, "Unauthorized", "TELEGRAM_BOT_TOKEN"),
        (400, "Bad Request: chat not found", "TELEGRAM_CHAT_ID"),
        (403, "Forbidden: bot was kicked from the group chat", "rimosso dal gruppo"),
    ],
)
def test_propagates_telegram_description(tmp_path, monkeypatch, status_code, description, hint) -> None:
    telegram = FakeTelegram(
        FakeResponse(status_code, {"ok": False, "error_code": status_code, "description": description})
    )
    _, client, csrf = make_client(tmp_path, monkeypatch, telegram)

    response = post_test(client, csrf)

    payload = response.get_json()
    assert response.status_code == 502
    assert payload["telegram_error_code"] == status_code
    assert payload["telegram_description"] == description
    assert f"Telegram {status_code}: {description}" in payload["error"]
    assert hint in payload["error"]


def test_network_error_does_not_leak_token(tmp_path, monkeypatch, caplog) -> None:
    telegram = FakeTelegram(
        requests.ConnectionError(f"Max retries exceeded with url: /bot{TOKEN}/sendMessage")
    )
    _, client, csrf = make_client(tmp_path, monkeypatch, telegram)

    with caplog.at_level(logging.DEBUG):
        response = post_test(client, csrf)

    assert response.status_code == 504
    assert "non raggiungibile" in response.get_json()["error"]
    assert TOKEN not in response.get_data(as_text=True)
    assert TOKEN not in caplog.text


def test_not_configured(tmp_path, monkeypatch) -> None:
    telegram = FakeTelegram()
    app, client, csrf = make_client(tmp_path, monkeypatch, telegram, telegram_chat_id="")

    response = post_test(client, csrf)
    page = client.get("/").get_data(as_text=True)

    assert response.status_code == 409
    assert telegram.calls == []
    assert 'id="telegramTestButton" class="secondary-button" type="button" disabled' in page
    assert "Telegram non configurato" in page


def test_cooldown_after_success(tmp_path, monkeypatch) -> None:
    telegram = FakeTelegram()
    _, client, csrf = make_client(tmp_path, monkeypatch, telegram)

    assert post_test(client, csrf).status_code == 200
    second = post_test(client, csrf)

    assert second.status_code == 429
    assert second.get_json()["retry_after"] > 0
    assert len(telegram.calls) == 1


def test_cooldown_reset_after_failure_but_not_after_rate_limit(tmp_path, monkeypatch) -> None:
    telegram = FakeTelegram(
        FakeResponse(400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}),
        FakeResponse(429, {"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 5"}),
    )
    _, client, csrf = make_client(tmp_path, monkeypatch, telegram)

    assert post_test(client, csrf).status_code == 502
    assert post_test(client, csrf).status_code == 502
    assert post_test(client, csrf).status_code == 429
    assert len(telegram.calls) == 2


def test_not_recorded_in_database(tmp_path, monkeypatch) -> None:
    telegram = FakeTelegram(
        FakeResponse(400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}),
    )
    _, client, csrf = make_client(tmp_path, monkeypatch, telegram)

    post_test(client, csrf)
    post_test(client, csrf)

    with sqlite3.connect(tmp_path / "garage.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
