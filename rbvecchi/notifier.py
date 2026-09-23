from __future__ import annotations

import requests


class TelegramError(RuntimeError):
    """Errore di invio Telegram, con il motivo riportato dall'API.

    Il messaggio non contiene mai l'URL della richiesta, che include il token.
    """

    def __init__(self, description: str, error_code: int | None = None) -> None:
        self.description = description
        self.error_code = error_code
        prefix = f"Telegram {error_code}: " if error_code is not None else ""
        super().__init__(f"{prefix}{description}")


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 8.0) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, message: str) -> None:
        if not self.enabled:
            raise RuntimeError("Telegram non configurato")
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            response = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "disable_web_page_preview": True,
                },
                timeout=self.timeout,
            )
        except requests.Timeout:
            raise TelegramError("Telegram non raggiungibile: timeout") from None
        except requests.RequestException as exc:
            # Il testo delle eccezioni di requests contiene l'URL con il token.
            raise TelegramError(
                f"Telegram non raggiungibile: {type(exc).__name__}"
            ) from None

        # Telegram risponde agli errori con 4xx e il motivo in "description":
        # va letto prima di guardare il codice HTTP.
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise TelegramError(
                f"Telegram: risposta non valida (HTTP {response.status_code})"
            )
        if not payload.get("ok"):
            raise TelegramError(
                payload.get("description") or "Errore Telegram sconosciuto",
                payload.get("error_code", response.status_code),
            )
