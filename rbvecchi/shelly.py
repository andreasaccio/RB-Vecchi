from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from requests.auth import HTTPDigestAuth


class ShellyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ShellyStatus:
    raw_input_state: bool
    relay_output: bool | None
    wifi_rssi: int | None
    uptime_seconds: int | None
    temperature_c: float | None
    firmware: str | None


class ShellyClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        input_id: int = 0,
        switch_id: int = 0,
        timeout: float = 4.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.input_id = input_id
        self.switch_id = switch_id
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "RB-Vecchi/1.0"})
        if password:
            self.session.auth = HTTPDigestAuth(username or "admin", password)

    def _raise_for_rpc_error(self, payload: Any) -> None:
        if isinstance(payload, dict) and "error" in payload:
            error = payload["error"]
            if isinstance(error, dict):
                message = error.get("message") or str(error)
            else:
                message = str(error)
            raise ShellyError(f"Errore RPC Shelly: {message}")

    def get_status(self) -> ShellyStatus:
        url = f"{self.base_url}/rpc/Shelly.GetStatus"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ShellyError(f"Shelly non raggiungibile: {exc}") from exc
        except ValueError as exc:
            raise ShellyError("Risposta JSON non valida dallo Shelly") from exc

        self._raise_for_rpc_error(payload)
        input_status = payload.get(f"input:{self.input_id}")
        if not isinstance(input_status, dict) or input_status.get("state") is None:
            raise ShellyError(
                f"Lo stato di input:{self.input_id} non è disponibile. "
                "Configurare l'ingresso come tipo switch."
            )

        switch_status = payload.get(f"switch:{self.switch_id}", {})
        wifi_status = payload.get("wifi", {})
        sys_status = payload.get("sys", {})

        temperature_c: float | None = None
        temperature = switch_status.get("temperature")
        if isinstance(temperature, dict) and temperature.get("tC") is not None:
            temperature_c = float(temperature["tC"])

        firmware = None
        if isinstance(sys_status, dict):
            updates = sys_status.get("available_updates")
            if isinstance(updates, dict):
                stable = updates.get("stable")
                if isinstance(stable, dict):
                    firmware = stable.get("version")
            firmware = firmware or sys_status.get("fw_id")

        return ShellyStatus(
            raw_input_state=bool(input_status["state"]),
            relay_output=(
                bool(switch_status["output"])
                if isinstance(switch_status, dict) and "output" in switch_status
                else None
            ),
            wifi_rssi=(
                int(wifi_status["rssi"])
                if isinstance(wifi_status, dict) and wifi_status.get("rssi") is not None
                else None
            ),
            uptime_seconds=(
                int(sys_status["uptime"])
                if isinstance(sys_status, dict) and sys_status.get("uptime") is not None
                else None
            ),
            temperature_c=temperature_c,
            firmware=firmware,
        )

    def get_switch_config(self) -> dict[str, Any]:
        url = f"{self.base_url}/rpc/Switch.GetConfig"
        try:
            response = self.session.get(
                url, params={"id": self.switch_id}, timeout=self.timeout
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ShellyError(f"Impossibile verificare la configurazione Shelly: {exc}") from exc
        except ValueError as exc:
            raise ShellyError("Risposta JSON non valida dalla configurazione Shelly") from exc
        self._raise_for_rpc_error(payload)
        return payload

    def pulse_relay(self, seconds: float) -> dict[str, Any]:
        url = f"{self.base_url}/rpc/Switch.Set"
        body = {
            "id": self.switch_id,
            "on": True,
            "toggle_after": seconds,
            "tag": "rb-vecchi",
        }
        try:
            response = self.session.post(url, json=body, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ShellyError(f"Comando allo Shelly non riuscito: {exc}") from exc
        except ValueError as exc:
            raise ShellyError("Risposta JSON non valida dopo il comando") from exc

        self._raise_for_rpc_error(payload)
        return payload
