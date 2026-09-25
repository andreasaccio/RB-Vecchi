#!/usr/bin/env python3
# Migrazione una tantum dei dati raccolti in /var/tmp dalle unità transitorie
# nei file giornalieri di /var/lib/rb-raccolta. SOLA LETTURA sugli originali,
# che non vengono cancellati. Rifiuta di scrivere su file già esistenti:
# va lanciato a raccoglitori fermi, prima di install-raccolta.sh.
#
#   rb-carica.csv, rb-plc.csv  ts già epoch, colonne invariate
#   rb-link.log                "AAAA-MM-GG_hh:mm:ss host stato" in ora locale
#                              CEST (+02:00) -> "ts,host,stato" epoch
# Le righe non conformi sono scartate e contate.
import argparse, os, re, sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from giornaliero import INTESTAZIONI, giorno, percorso

CEST = timezone(timedelta(hours=2))
# Fine dell'ora legale 2026: dopo questo istante l'ora locale non è più CEST.
FINE_CEST = datetime(2026, 10, 25, 1, 0, tzinfo=timezone.utc).timestamp()

NUM = r"-?\d+(?:\.\d+)?"
RE_TS = re.compile(r"^\d+(?:\.\d+)?$")
RE_CARICA_OK = re.compile(
    r"^\d+,ok,\d+,-?\d+,[01],%s,%s,%s,%s,%s,(-?\d+)?,[0-9A-Fa-f:]*$" % ((NUM,) * 5))
RE_CARICA_KO = re.compile(r"^\d+,KO,\w+$")
RE_PLC_OK = re.compile(r"^\d+,(casa|garage),ok(,\d+){6}$")
RE_PLC_KO = re.compile(r"^\d+,(casa|garage),KO,\w+$")
RE_LINK = re.compile(
    r"^(\d{4}-\d\d-\d\d_\d\d:\d\d:\d\d) (\d{1,3}(?:\.\d{1,3}){3}) (ok|KO)$")


def converti_carica(riga):
    if RE_CARICA_OK.match(riga) or RE_CARICA_KO.match(riga):
        return float(riga.split(",", 1)[0]), riga
    return None


def converti_plc(riga):
    if RE_PLC_OK.match(riga) or RE_PLC_KO.match(riga):
        return float(riga.split(",", 1)[0]), riga
    return None


def converti_link(riga):
    m = RE_LINK.match(riga)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%Y-%m-%d_%H:%M:%S").replace(tzinfo=CEST)
    except ValueError:
        return None
    ts = dt.timestamp()
    if ts >= FINE_CEST:
        return None
    return ts, "%.0f,%s,%s" % (ts, m.group(2), m.group(3))


SORGENTI = [
    ("rb-carica", "rb-carica.csv", converti_carica),
    ("rb-plc", "rb-plc.csv", converti_plc),
    ("rb-link", "rb-link.log", converti_link),
]


def leggi(nome, file, conv):
    """Restituisce ({giorno: [righe]}, lette, intestazioni, scartate)."""
    per_giorno, lette, intest, scartate = {}, 0, 0, 0
    intestazione = INTESTAZIONI[nome].strip()
    with open(file, encoding="utf-8", errors="replace") as f:
        for grezza in f:
            lette += 1
            riga = grezza.rstrip("\r\n")
            if riga == intestazione:
                intest += 1
                continue
            r = conv(riga)
            if r is None:
                scartate += 1
                continue
            ts, testo = r
            per_giorno.setdefault(giorno(ts), []).append(testo + "\n")
    return per_giorno, lette, intest, scartate


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--origine", default="/var/tmp")
    ap.add_argument("--uscita", default="/var/lib/rb-raccolta")
    ap.add_argument("--prova", action="store_true",
                    help="conta e controlla, non scrive nulla")
    a = ap.parse_args(argv)

    risultati = []
    for nome, file, conv in SORGENTI:
        p = os.path.join(a.origine, file)
        if not os.path.exists(p):
            print("MANCA %s: saltato" % p)
            continue
        risultati.append((nome, p) + leggi(nome, p, conv))

    esistenti = [percorso(nome, g, a.uscita)
                 for nome, _, per_giorno, *_ in risultati for g in per_giorno
                 if os.path.exists(percorso(nome, g, a.uscita))]
    if esistenti:
        for e in esistenti:
            print("ESISTE GIÀ %s" % e, file=sys.stderr)
        print("Nessun file scritto: migrazione da fare a raccoglitori fermi, "
              "prima di install-raccolta.sh.", file=sys.stderr)
        return 1

    for nome, p, per_giorno, lette, intest, scartate in risultati:
        convertite = sum(len(v) for v in per_giorno.values())
        print("%s: %d righe lette, %d convertite, %d intestazioni, %d SCARTATE"
              % (p, lette, convertite, intest, scartate))
        for g in sorted(per_giorno):
            dest = percorso(nome, g, a.uscita)
            print("  %s  %d righe" % (dest, len(per_giorno[g])))
            if a.prova:
                continue
            os.makedirs(a.uscita, exist_ok=True)
            with open(dest, "x") as f:
                f.write(INTESTAZIONI[nome])
                f.writelines(per_giorno[g])
    if a.prova:
        print("Prova: nessun file scritto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
