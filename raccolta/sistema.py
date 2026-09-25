#!/usr/bin/env python3
# Stato del Raspberry per la dashboard -> sistema.json. SOLO letture locali:
# /proc, /sys, statvfs, uname e systemctl show (nessuna rete, nessuna scrittura
# fuori dal file di uscita).
import argparse, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from giornaliero import directory, scrivi_json_atomico

UNITA = ["rb-vecchi.service", "rb-carica.service", "rb-plc.service",
         "rb-link.service", "rb-stato-rete.timer"]


def _leggi(radice, rel):
    try:
        with open(os.path.join(radice, rel), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def carico(radice):
    t = _leggi(radice, "proc/loadavg")
    try:
        a, b, c = (float(x) for x in t.split()[:3])
        return {"1min": a, "5min": b, "15min": c}
    except (AttributeError, ValueError):
        return None


def temperatura_cpu(radice):
    t = _leggi(radice, "sys/class/thermal/thermal_zone0/temp")
    try:
        return round(int(t.strip()) / 1000.0, 1)
    except (AttributeError, ValueError):
        return None


def memoria(radice):
    t = _leggi(radice, "proc/meminfo")
    if t is None:
        return None
    kb = {}
    for r in t.splitlines():
        parti = r.split()
        if len(parti) >= 2 and parti[1].isdigit():
            kb[parti[0].rstrip(":")] = int(parti[1])
    if "MemTotal" not in kb or "MemAvailable" not in kb:
        return None
    return {"usata_B": (kb["MemTotal"] - kb["MemAvailable"]) * 1024,
            "totale_B": kb["MemTotal"] * 1024}


def disco(percorso):
    try:
        s = os.statvfs(percorso)
    except OSError:
        return None
    return {"usato_B": (s.f_blocks - s.f_bfree) * s.f_frsize,
            "totale_B": s.f_blocks * s.f_frsize}


def uptime(radice):
    t = _leggi(radice, "proc/uptime")
    try:
        return int(float(t.split()[0]))
    except (AttributeError, ValueError, IndexError):
        return None


def stati_unita(unita, esegui=subprocess.run):
    """ActiveState di ciascuna unità con un solo systemctl show; None se ignoto."""
    esito = dict.fromkeys(unita)
    try:
        r = esegui(["systemctl", "show", "-p", "Id", "-p", "ActiveState", "--", *unita],
                   capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return esito
    for blocco in r.stdout.split("\n\n"):
        campi = dict(riga.split("=", 1) for riga in blocco.splitlines() if "=" in riga)
        if campi.get("Id") in esito:
            esito[campi["Id"]] = campi.get("ActiveState")
    return esito


def raccogli(radice="/", esegui=subprocess.run, adesso=None):
    return {
        "versione": 1,
        "generato": int(time.time() if adesso is None else adesso),
        "carico": carico(radice),
        "temperatura_cpu_C": temperatura_cpu(radice),
        "memoria": memoria(radice),
        "disco_radice": disco(radice),
        "uptime_s": uptime(radice),
        "kernel": os.uname().release,
        "riavvio_richiesto": os.path.exists(os.path.join(radice, "var/run/reboot-required")),
        "unita": stati_unita(UNITA, esegui),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Stato del Raspberry in JSON")
    ap.add_argument("--uscita", default=os.path.join(directory(), "sistema.json"))
    ap.add_argument("--radice", default="/", help="per i test")
    a = ap.parse_args(argv)
    scrivi_json_atomico(a.uscita, raccogli(a.radice))
    return 0


if __name__ == "__main__":
    sys.exit(main())
