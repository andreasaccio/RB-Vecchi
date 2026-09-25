"""Lettura del riepilogo powerline scritto dalla raccolta dati.

Solo lettura e validazione del file JSON prodotto da rb-stato-rete.service:
nessuna analisi qui. Qualunque problema (file assente, illeggibile, corrotto,
vecchio) diventa lo stato "non_disponibile" con il motivo.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STATI = {"stabile", "instabile", "interrotta", "non_disponibile"}
MAX_ETA_SECONDI = 300
MAX_BYTE = 64 * 1024


def _non_disponibile(motivo: str, generato: float | None = None) -> dict[str, Any]:
    return {"stato": "non_disponibile", "motivo": motivo, "generato": generato,
            "eta_s": None, "garage": None, "scartati_plc_24h": None, "riavvii_24h": None}


def _numero(valore: Any) -> float | None:
    if isinstance(valore, bool) or not isinstance(valore, (int, float)):
        return None
    return valore


def _garage(dati: Any) -> dict[str, Any] | None:
    if not isinstance(dati, dict):
        return None
    ultimo = dati.get("ultimo_episodio")
    if isinstance(ultimo, dict) and _numero(ultimo.get("inizio")) is not None:
        ultimo = {"inizio": ultimo["inizio"],
                  "durata_s": _numero(ultimo.get("durata_s")),
                  "in_corso": ultimo.get("in_corso") is True}
    else:
        ultimo = None
    return {
        "disponibilita_24h": _numero(dati.get("disponibilita_24h")),
        "episodi_24h": _numero(dati.get("episodi_24h")),
        "perdite_isolate_24h": _numero(dati.get("perdite_isolate_24h")),
        "ultimo_episodio": ultimo,
    }


def leggi_riepilogo(percorso: Path, adesso: float | None = None) -> dict[str, Any]:
    adesso = time.time() if adesso is None else adesso
    try:
        with open(percorso, "rb") as f:
            grezzo = f.read(MAX_BYTE + 1)
    except FileNotFoundError:
        return _non_disponibile("riepilogo della raccolta dati assente")
    except OSError:
        return _non_disponibile("riepilogo della raccolta dati illeggibile")
    if len(grezzo) > MAX_BYTE:
        return _non_disponibile("riepilogo della raccolta dati non valido")
    try:
        dati = json.loads(grezzo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _non_disponibile("riepilogo della raccolta dati non valido")

    if not isinstance(dati, dict):
        return _non_disponibile("riepilogo della raccolta dati non valido")
    generato = _numero(dati.get("generato"))
    stato = dati.get("stato")
    if generato is None or stato not in STATI:
        return _non_disponibile("riepilogo della raccolta dati non valido")
    eta = adesso - generato
    if eta > MAX_ETA_SECONDI:
        return _non_disponibile(
            f"riepilogo fermo da {int(eta // 60)} min: raccolta dati non aggiornata",
            generato)
    if eta < -60:
        return _non_disponibile("riepilogo con orario nel futuro", generato)

    motivo = dati.get("motivo")
    return {
        "stato": stato,
        "motivo": motivo if isinstance(motivo, str) else "",
        "generato": generato,
        "eta_s": max(0, int(eta)),
        "garage": _garage(dati.get("garage")),
        "scartati_plc_24h": _numero(dati.get("scartati_plc_24h")),
        "riavvii_24h": _numero(dati.get("riavvii_24h")),
    }
