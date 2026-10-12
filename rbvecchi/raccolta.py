"""Lettura dei file JSON scritti dalla raccolta dati in /var/lib/rb-raccolta.

Solo lettura e validazione: nessuna analisi e nessun accesso alla rete qui.
Qualunque problema (file assente, illeggibile, non valido, vecchio) diventa lo
stato "non_disponibile" con il motivo. Ogni campo viene copiato solo se del
tipo atteso: nella dashboard non arriva nient'altro da quei file.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STATO_RETE = "stato-rete.json"
CARICA = "carica-ultimo.json"
SISTEMA = "sistema.json"
REGISTRO_CARICA = "carica-registro.json"

STATI_POWERLINE = {"stabile", "instabile", "interrotta", "non_disponibile"}
MAX_ETA_POWERLINE = 300
MAX_ETA_CARICA = 60
MAX_ETA_SISTEMA = 300
MAX_ETA_REGISTRO = 300
MAX_SESSIONI = 50
CAUSE = {"programma", "manuale", "ritorno_corrente", "gia_accesa"}
ESITI = {"fine_carica", "senza_carica", "interrotta", "riavvio", "in_corso"}
MAX_BYTE = 64 * 1024
# Il relè lo apre lo script ricarica-notturna sullo Shelly a fine carica e lo
# richiude alle 01:00 (o "Carica ora"): relè aperto è lo stato normale.
NOTA_RELE_APERTO = ("presa spenta dal programma di ricarica: si riaccende alle 01:00 "
                    "o con «Carica ora»")
CONTATORI = ("tx_pkt", "rx_pkt", "tx_drop", "rx_drop", "tx_byte", "rx_byte")


class NonDisponibile(Exception):
    pass


def _numero(valore: Any) -> float | None:
    if isinstance(valore, bool) or not isinstance(valore, (int, float)):
        return None
    return valore


def _testo(valore: Any) -> str | None:
    return valore if isinstance(valore, str) else None


def _booleano(valore: Any) -> bool | None:
    return valore if isinstance(valore, bool) else None


def _leggi(percorso: Path) -> dict[str, Any]:
    try:
        with open(percorso, "rb") as f:
            grezzo = f.read(MAX_BYTE + 1)
    except FileNotFoundError:
        raise NonDisponibile("file della raccolta dati assente") from None
    except OSError:
        raise NonDisponibile("file della raccolta dati illeggibile") from None
    if len(grezzo) > MAX_BYTE:
        raise NonDisponibile("file della raccolta dati non valido")
    try:
        dati = json.loads(grezzo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise NonDisponibile("file della raccolta dati non valido") from None
    if not isinstance(dati, dict):
        raise NonDisponibile("file della raccolta dati non valido")
    return dati


def _eta(istante: float | None, adesso: float, massima: int, cosa: str) -> int:
    if istante is None:
        raise NonDisponibile("file della raccolta dati non valido")
    eta = adesso - istante
    if eta > massima:
        minuti = int(eta // 60)
        durata = f"{minuti} min" if minuti else f"{int(eta)} s"
        raise NonDisponibile(f"{cosa} fermi da {durata}: raccolta dati non aggiornata")
    if eta < -60:
        raise NonDisponibile(f"{cosa} con orario nel futuro")
    return max(0, int(eta))


# ---------------------------------------------------------------- powerline

def _nd_powerline(motivo: str) -> dict[str, Any]:
    return {"stato": "non_disponibile", "motivo": motivo, "generato": None, "eta_s": None,
            "garage": None, "plc": {}, "scartati_plc_24h": None, "riavvii_24h": None,
            "ultimo_giro": None, "calcolo_ms": None}


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


def _adattatore(dati: Any) -> dict[str, Any] | None:
    if not isinstance(dati, dict):
        return None
    lettura = dati.get("ultima_lettura")
    campione = dati.get("ultimo_campione")
    return {
        "ip": _testo(dati.get("ip")),
        "scartati_tx_24h": _numero(dati.get("scartati_tx_24h")),
        "scartati_rx_24h": _numero(dati.get("scartati_rx_24h")),
        "riavvii_24h": _numero(dati.get("riavvii_24h")),
        "ultimo_riavvio_24h": _numero(dati.get("ultimo_riavvio_24h")),
        "ultima_lettura": {"ts": _numero(lettura.get("ts")),
                           "stato": _testo(lettura.get("stato"))}
        if isinstance(lettura, dict) else None,
        "ultimo_campione": {k: _numero(campione.get(k)) for k in ("ts",) + CONTATORI}
        if isinstance(campione, dict) else None,
    }


def leggi_riepilogo(percorso: Path, adesso: float | None = None) -> dict[str, Any]:
    adesso = time.time() if adesso is None else adesso
    try:
        dati = _leggi(percorso)
        stato = dati.get("stato")
        if stato not in STATI_POWERLINE:
            raise NonDisponibile("file della raccolta dati non valido")
        generato = _numero(dati.get("generato"))
        eta = _eta(generato, adesso, MAX_ETA_POWERLINE, "dati della powerline")
    except NonDisponibile as e:
        return _nd_powerline(str(e))
    plc = dati.get("plc") if isinstance(dati.get("plc"), dict) else {}
    return {
        "stato": stato,
        "motivo": _testo(dati.get("motivo")) or "",
        "generato": generato,
        "eta_s": eta,
        "garage": _garage(dati.get("garage")),
        "plc": {nome: a for nome in ("casa", "garage")
                if (a := _adattatore(plc.get(nome))) is not None},
        "scartati_plc_24h": _numero(dati.get("scartati_plc_24h")),
        "riavvii_24h": _numero(dati.get("riavvii_24h")),
        "ultimo_giro": _numero(dati.get("ultimo_giro")),
        "calcolo_ms": _numero(dati.get("calcolo_ms")),
    }


# ---------------------------------------------------------------- ricarica

def leggi_carica(percorso: Path, adesso: float | None = None) -> dict[str, Any]:
    """Ultimo campione dello Shelly della ricarica, scritto da rb-carica."""
    adesso = time.time() if adesso is None else adesso
    try:
        dati = _leggi(percorso)
        ts = _numero(dati.get("ts"))
        eta = _eta(ts, adesso, MAX_ETA_CARICA, "dati della ricarica")
    except NonDisponibile as e:
        return {"stato": "non_disponibile", "motivo": str(e), "eta_s": None, "avviso": None,
                "nota": None}

    esito = {
        "stato": "ok", "motivo": "", "ts": ts, "eta_s": eta,
        "potenza_W": _numero(dati.get("apower_W")),
        "tensione_V": _numero(dati.get("voltage_V")),
        "corrente_A": _numero(dati.get("current_A")),
        "rele_chiuso": _booleano(dati.get("output")),
        "temperatura_C": _numero(dati.get("temp_C")),
        "uptime_s": _numero(dati.get("uptime")),
        "reset_reason": _numero(dati.get("reset_reason")),
        "rssi": _numero(dati.get("rssi")),
        "bssid": _testo(dati.get("bssid")),
        "modello": _testo(dati.get("modello")),
        "app": _testo(dati.get("app")),
        "firmware": _testo(dati.get("firmware")),
        "info_ts": _numero(dati.get("info_ts")),
        "ultimo_ok": _numero(dati.get("ultimo_ok")),
        "avviso": None,
        "nota": None,
    }
    if dati.get("stato") != "ok":
        errore = _testo(dati.get("errore"))
        esito.update(stato="non_disponibile",
                     motivo="Shelly ricarica non risponde" + (f" ({errore})" if errore else ""))
        return esito
    if esito["potenza_W"] is None or esito["rele_chiuso"] is None:
        return {"stato": "non_disponibile", "motivo": "file della raccolta dati non valido",
                "eta_s": None, "avviso": None, "nota": None}
    if esito["rele_chiuso"] is False:
        esito["nota"] = NOTA_RELE_APERTO
    return esito


def _sessione(dati: Any) -> dict[str, Any] | None:
    if not isinstance(dati, dict):
        return None
    inizio = _numero(dati.get("inizio"))
    if inizio is None or dati.get("causa") not in CAUSE or dati.get("esito") not in ESITI:
        return None
    return {
        "inizio": inizio,
        "inizio_approssimato": dati.get("inizio_approssimato") is True,
        "causa": dati["causa"],
        "fine": _numero(dati.get("fine")),
        "fine_approssimata": dati.get("fine_approssimata") is True,
        "esito": dati["esito"],
        "carica_da": _numero(dati.get("carica_da")),
        "carica_a": _numero(dati.get("carica_a")),
        "energia_Wh": _numero(dati.get("energia_Wh")),
        "potenza_max_W": _numero(dati.get("potenza_max_W")),
        "in_carica": dati.get("in_carica") is True,
    }


def leggi_registro_carica(percorso: Path, adesso: float | None = None) -> dict[str, Any]:
    """Sessioni di ricarica ricostruite dalla raccolta (raccolta/sessioni_carica.py)."""
    adesso = time.time() if adesso is None else adesso
    try:
        dati = _leggi(percorso)
        generato = _numero(dati.get("generato"))
        eta = _eta(generato, adesso, MAX_ETA_REGISTRO, "registro della ricarica")
        grezze = dati.get("sessioni")
        if not isinstance(grezze, list):
            raise NonDisponibile("file della raccolta dati non valido")
    except NonDisponibile as e:
        return {"stato": "non_disponibile", "motivo": str(e), "eta_s": None, "sessioni": []}
    sessioni = [s for s in map(_sessione, grezze[:MAX_SESSIONI]) if s is not None]
    return {"stato": "ok", "motivo": "", "generato": generato, "eta_s": eta,
            "dal": _numero(dati.get("dal")), "sessioni": sessioni}


# ---------------------------------------------------------------- Raspberry

def _coppia(dati: Any, a: str, b: str) -> dict[str, Any] | None:
    if not isinstance(dati, dict):
        return None
    return {a: _numero(dati.get(a)), b: _numero(dati.get(b))}


def leggi_sistema(percorso: Path, adesso: float | None = None) -> dict[str, Any]:
    adesso = time.time() if adesso is None else adesso
    try:
        dati = _leggi(percorso)
        generato = _numero(dati.get("generato"))
        eta = _eta(generato, adesso, MAX_ETA_SISTEMA, "dati del Raspberry")
    except NonDisponibile as e:
        return {"stato": "non_disponibile", "motivo": str(e), "eta_s": None}
    carico = dati.get("carico")
    unita = dati.get("unita") if isinstance(dati.get("unita"), dict) else {}
    return {
        "stato": "ok", "motivo": "", "generato": generato, "eta_s": eta,
        "carico": {k: _numero(carico.get(k)) for k in ("1min", "5min", "15min")}
        if isinstance(carico, dict) else None,
        "temperatura_cpu_C": _numero(dati.get("temperatura_cpu_C")),
        "memoria": _coppia(dati.get("memoria"), "usata_B", "totale_B"),
        "disco_radice": _coppia(dati.get("disco_radice"), "usato_B", "totale_B"),
        "uptime_s": _numero(dati.get("uptime_s")),
        "kernel": _testo(dati.get("kernel")),
        "riavvio_richiesto": _booleano(dati.get("riavvio_richiesto")),
        "unita": {nome: _testo(stato) for nome, stato in unita.items()
                  if isinstance(nome, str)},
    }
