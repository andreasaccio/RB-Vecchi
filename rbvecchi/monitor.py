from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Settings
from .db import Database, Transition
from .notifier import TelegramNotifier
from .shelly import ShellyClient, ShellyError, ShellyStatus

LOGGER = logging.getLogger(__name__)


@dataclass
class RuntimeSnapshot:
    online: bool = False
    garage_open: bool | None = None
    raw_input_state: bool | None = None
    state_since: float | None = None
    alert_sent: bool = False
    last_success: float | None = None
    last_error: str | None = None
    relay_output: bool | None = None
    wifi_rssi: int | None = None
    uptime_seconds: int | None = None
    temperature_c: float | None = None
    firmware: str | None = None
    switch_in_mode: str | None = None
    switch_auto_off: bool | None = None
    switch_initial_state: str | None = None
    safety_warning: str | None = None


class GarageMonitor:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        shelly: ShellyClient,
        notifier: TelegramNotifier,
    ) -> None:
        self.settings = settings
        self.database = database
        self.shelly = shelly
        self.notifier = notifier
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        persisted = database.get_current_state()
        self._snapshot = RuntimeSnapshot(
            garage_open=persisted["garage_open"],
            state_since=persisted["state_since"],
            alert_sent=persisted["alert_sent"],
        )
        self._last_alert_attempt = 0.0
        self._last_command_at = 0.0
        self._last_config_check = -300.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="garage-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def snapshot(self) -> dict:
        with self._lock:
            data = asdict(self._snapshot)
        now = time.time()
        state_since = data.get("state_since")
        data["state_duration_seconds"] = (
            max(0, int(now - state_since)) if state_since is not None else None
        )
        data["stale_seconds"] = (
            max(0, int(now - data["last_success"]))
            if data.get("last_success") is not None
            else None
        )
        data["telegram_enabled"] = self.settings.telegram_enabled
        data["alert_after_seconds"] = self.settings.open_alert_seconds
        detached_ok = data.get("switch_in_mode") == "detached"
        data["command_allowed"] = bool(
            data.get("online")
            and (detached_ok or not self.settings.require_detached_mode)
        )
        return data

    def pulse(self) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_command_at < self.settings.command_cooldown_seconds:
                raise RuntimeError("Attendere qualche secondo prima di inviare un altro comando")
            if not self._snapshot.online:
                raise RuntimeError("Shelly non raggiungibile: comando non inviato")
            if (
                self.settings.require_detached_mode
                and self._snapshot.switch_in_mode != "detached"
            ):
                raise RuntimeError(
                    "Comando bloccato: impostare il relè Shelly in modalità Detached"
                )
            self._last_command_at = now

        event_time = time.time()
        try:
            self.shelly.pulse_relay(self.settings.relay_pulse_seconds)
            self.database.log_command(event_time, True, "Impulso inviato")
        except Exception as exc:
            self.database.log_command(event_time, False, str(exc))
            with self._lock:
                self._last_command_at = 0.0
            raise

    def _run(self) -> None:
        LOGGER.info("Monitor garage avviato")
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                status = self.shelly.get_status()
                self._handle_status(status)
            except ShellyError as exc:
                LOGGER.warning("%s", exc)
                with self._lock:
                    self._snapshot.online = False
                    self._snapshot.last_error = str(exc)
            except Exception:
                LOGGER.exception("Errore inatteso nel monitor garage")
                with self._lock:
                    self._snapshot.online = False
                    self._snapshot.last_error = "Errore interno nel monitor"

            elapsed = time.monotonic() - started
            wait = max(0.1, self.settings.poll_interval_seconds - elapsed)
            self._stop.wait(wait)

    def _handle_status(self, status: ShellyStatus) -> None:
        now = time.time()
        garage_open = (
            status.raw_input_state
            if self.settings.input_true_is_open
            else not status.raw_input_state
        )
        self._refresh_switch_config_if_needed()
        transition = self.database.reconcile(garage_open, now)
        persisted = self.database.get_current_state()

        with self._lock:
            self._snapshot.online = True
            self._snapshot.garage_open = garage_open
            self._snapshot.raw_input_state = status.raw_input_state
            self._snapshot.state_since = persisted["state_since"]
            self._snapshot.alert_sent = persisted["alert_sent"]
            self._snapshot.last_success = now
            self._snapshot.last_error = None
            self._snapshot.relay_output = status.relay_output
            self._snapshot.wifi_rssi = status.wifi_rssi
            self._snapshot.uptime_seconds = status.uptime_seconds
            self._snapshot.temperature_c = status.temperature_c
            self._snapshot.firmware = status.firmware

        if transition:
            self._handle_transition(transition)

        self._maybe_send_open_alert(now)

    def _refresh_switch_config_if_needed(self) -> None:
        monotonic_now = time.monotonic()
        if monotonic_now - self._last_config_check < 300:
            return
        self._last_config_check = monotonic_now
        try:
            config = self.shelly.get_switch_config()
            in_mode = config.get("in_mode")
            auto_off = config.get("auto_off")
            initial_state = config.get("initial_state")
            warnings: list[str] = []
            if self.settings.require_detached_mode and in_mode != "detached":
                warnings.append(
                    "Comando disabilitato: configurare lo Shelly con Input mode Detached."
                )
            if initial_state not in {None, "off"}:
                warnings.append("Impostare Initial state del relè su Off.")
            if auto_off is False:
                warnings.append(
                    "Auto off Shelly non attivo; l'app usa comunque un impulso temporizzato."
                )
            with self._lock:
                self._snapshot.switch_in_mode = str(in_mode) if in_mode is not None else None
                self._snapshot.switch_auto_off = bool(auto_off) if auto_off is not None else None
                self._snapshot.switch_initial_state = (
                    str(initial_state) if initial_state is not None else None
                )
                self._snapshot.safety_warning = " ".join(warnings) or None
        except Exception as exc:
            LOGGER.warning("Verifica configurazione Switch fallita: %s", exc)
            with self._lock:
                self._snapshot.safety_warning = (
                    "Impossibile verificare la modalità Detached dello Shelly; "
                    "comando temporaneamente disabilitato."
                )
                if self.settings.require_detached_mode:
                    self._snapshot.switch_in_mode = None

    def _handle_transition(self, transition: Transition) -> None:
        if (
            transition.kind == "CLOSE"
            and transition.previous_alert_sent
            and self.settings.telegram_notify_closed_after_alert
            and self.notifier.enabled
        ):
            duration = self._format_duration(transition.duration_seconds or 0)
            message = f"✅ Garage chiuso. È rimasto aperto per {duration}."
            try:
                self.notifier.send(message)
            except Exception:
                LOGGER.exception("Invio notifica Telegram di chiusura fallito")

    def _maybe_send_open_alert(self, now: float) -> None:
        with self._lock:
            snapshot = RuntimeSnapshot(**asdict(self._snapshot))

        if (
            not snapshot.online
            or not snapshot.garage_open
            or snapshot.state_since is None
            or snapshot.alert_sent
            or not self.notifier.enabled
        ):
            return

        open_for = int(now - snapshot.state_since)
        if open_for < self.settings.open_alert_seconds:
            return

        if now - self._last_alert_attempt < 60:
            return
        self._last_alert_attempt = now

        local_time = datetime.fromtimestamp(snapshot.state_since, ZoneInfo(self.settings.timezone))
        message = (
            "⚠️ Il garage è ancora aperto.\n"
            f"Aperto dalle {local_time:%H:%M del %d/%m/%Y}.\n"
            f"Durata: {self._format_duration(open_for)}."
        )
        try:
            self.notifier.send(message)
            self.database.mark_alert_sent(now)
            with self._lock:
                self._snapshot.alert_sent = True
            LOGGER.info("Notifica garage aperto inviata")
        except Exception:
            LOGGER.exception("Invio notifica Telegram fallito; nuovo tentativo tra 60 secondi")

    @staticmethod
    def _format_duration(seconds: int) -> str:
        seconds = max(0, seconds)
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours} h {minutes} min"
        if minutes:
            return f"{minutes} min {secs} s"
        return f"{secs} s"
