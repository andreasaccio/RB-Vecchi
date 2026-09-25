#!/usr/bin/env python3
# Campionatore, SOLA LETTURA: Shelly ricarica -> CSV giornaliero, più
# carica-ultimo.json con l'ultimo campione per la dashboard.
# Chiamate: Shelly.GetStatus a ogni campione; Shelly.GetDeviceInfo all'avvio
# e poi ogni 6 ore (dopo un fallimento si riprova fra 10 minuti).
import json, os, sys, time, urllib.request

from giornaliero import Giornaliero, directory, scrivi_json_atomico

BASE = "http://192.168.1.101/rpc/"
PASSO = 10
INFO_OGNI = 6 * 3600
INFO_RIPROVA = 600
ULTIMO = "carica-ultimo.json"


def rpc(metodo):
    with urllib.request.urlopen(BASE + metodo, timeout=4) as r:
        return json.load(r)


def campione(s, t):
    """Campi della riga CSV da una risposta di Shelly.GetStatus."""
    sw, sy, wf = s["switch:0"], s["sys"], s.get("wifi", {})
    return {
        "ts": t, "stato": "ok", "uptime": sy["uptime"],
        "reset_reason": sy.get("reset_reason", -1), "output": bool(sw["output"]),
        "apower_W": sw["apower"], "voltage_V": sw["voltage"], "current_A": sw["current"],
        "aenergy_Wh": sw["aenergy"]["total"], "temp_C": sw["temperature"]["tC"],
        "rssi": wf.get("rssi"), "bssid": wf.get("bssid"),
    }


def riga_csv(c):
    if c["stato"] != "ok":
        return "%.0f,KO,%s\n" % (c["ts"], c["errore"])
    return "%.0f,ok,%d,%d,%d,%.1f,%.1f,%.3f,%.3f,%.1f,%s,%s\n" % (
        c["ts"], c["uptime"], c["reset_reason"], int(c["output"]), c["apower_W"],
        c["voltage_V"], c["current_A"], c["aenergy_Wh"], c["temp_C"],
        "" if c["rssi"] is None else c["rssi"], c["bssid"] or "")


def leggi(t, chiama=rpc):
    """(campione, riga CSV). Qualunque errore, anche di formato, è un KO."""
    try:
        c = campione(chiama("Shelly.GetStatus"), t)
        return c, riga_csv(c)
    except Exception as e:
        c = {"ts": t, "stato": "KO", "errore": type(e).__name__}
        return c, riga_csv(c)


class InfoDispositivo:
    def __init__(self, chiama=rpc):
        self.chiama = chiama
        self.dati = {"modello": None, "app": None, "firmware": None, "info_ts": None}
        self.prossima = 0.0

    def aggiorna(self, adesso):
        if adesso < self.prossima:
            return
        try:
            d = self.chiama("Shelly.GetDeviceInfo")
            self.dati = {"modello": d.get("model"), "app": d.get("app"),
                         "firmware": d.get("ver"), "info_ts": adesso}
            self.prossima = adesso + INFO_OGNI
        except Exception:
            self.prossima = adesso + INFO_RIPROVA


def ultimo(c, info, ultimo_ok, generato):
    """Contenuto di carica-ultimo.json."""
    return {**c, **info, "ultimo_ok": ultimo_ok, "generato": generato}


if __name__ == "__main__":
    out = Giornaliero("rb-carica")
    info = InfoDispositivo()
    destinazione = os.path.join(directory(), ULTIMO)
    ultimo_ok = None
    while True:
        c, riga = leggi(time.time())
        out.scrivi(c["ts"], riga)
        if c["stato"] == "ok":
            ultimo_ok = c["ts"]
        info.aggiorna(time.time())
        try:
            scrivi_json_atomico(destinazione, ultimo(c, info.dati, ultimo_ok, time.time()))
        except OSError as e:
            print("%s non scritto: %s" % (ULTIMO, e), file=sys.stderr, flush=True)
        time.sleep(PASSO - time.time() % PASSO)
