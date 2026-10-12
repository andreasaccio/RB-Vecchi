#!/usr/bin/env python3
# Registro della ricarica dai CSV di rb-carica. SOLA LETTURA, solo libreria
# standard. Una sessione va dalla chiusura all'apertura del relè dello Shelly
# .101, che lo script ricarica-notturna comanda sullo Shelly stesso.
# - causa dell'accensione: "programma" (fra le 01:00 e le 01:02), "ritorno_corrente"
#   (Shelly riavviato: uptime che cala, initial_state=on), "manuale" (app Shelly o
#   pulsante "Carica ora", che la dashboard registra a parte), "gia_accesa" (relè
#   già chiuso all'inizio dei dati);
# - esito: "fine_carica" (dopo la carica almeno MIN_STANDBY s sotto SOGLIA_STANDBY
#   prima dello spegnimento: il caso dello script), "senza_carica" (spenta senza
#   aver mai superato SOGLIA_CARICA), "interrotta" (spenta durante o subito dopo la
#   carica), "riavvio" (Shelly riavviato durante la sessione), "in_corso";
# - un cambio di stato avvenuto in un buco di dati (> BUCO s fra due campioni ok)
#   ha orario approssimato: "inizio"/"fine" sono il primo campione dopo il buco;
# - energia dal contatore aenergy, solo incrementi: un contatore che cala
#   (riavvio) non toglie energia;
# - una sessione intera dentro un buco di dati non si vede.
import argparse, json, os, sys, time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from giornaliero import directory, scrivi_json_atomico
from stato_rete import leggi

SOGLIA_CARICA = 100.0     # W
SOGLIA_STANDBY = 20.0     # W
MIN_STANDBY = 480         # s (lo script spegne dopo 600 s)
BUCO = 30                 # s
FINESTRA = 7 * 86400      # s
MAX_SESSIONI = 30
PROGRAMMA = (1, 0)        # ora, minuti dello Schedule sullo Shelly
TOLLERANZA_PROGRAMMA = 120  # s


def campioni(righe):
    """Campioni ok: (ts, uptime, output, apower, aenergy). Righe malformate saltate."""
    out = []
    for r in righe:
        if len(r) < 9 or r[1] != "ok":
            continue
        try:
            out.append((r[0], int(r[2]), r[4] == "1", float(r[5]), float(r[8])))
        except ValueError:
            continue
    return out


def da_programma(da, a):
    """True se l'intervallo [da, a] tocca le 01:00-01:02 locali."""
    for t in (da, a):
        d = datetime.fromtimestamp(t)
        inizio = d.replace(hour=PROGRAMMA[0], minute=PROGRAMMA[1], second=0, microsecond=0)
        if inizio.timestamp() <= a and da <= inizio.timestamp() + TOLLERANZA_PROGRAMMA:
            return True
    return False


def sessioni(cc):
    """Sessioni dal più vecchio al più recente."""
    out, cur, prec = [], None, None

    def apri(c, causa, inizio, approssimato):
        return {"inizio": inizio, "inizio_approssimato": approssimato, "causa": causa,
                "fine": None, "fine_approssimata": False, "esito": "in_corso",
                "carica_da": None, "carica_a": None, "energia_Wh": 0.0,
                "potenza_max_W": c[3], "ultima_potenza_W": c[3]}

    def chiudi(s, fine, approssimata, esito=None):
        s["fine"], s["fine_approssimata"] = fine, approssimata
        if esito is None:
            if s["carica_da"] is None:
                esito = "senza_carica"
            elif fine - s["carica_a"] >= MIN_STANDBY:
                esito = "fine_carica"
            else:
                esito = "interrotta"
        s["esito"] = esito
        out.append(s)

    for c in cc:
        ts, uptime, acceso, p, e = c
        buco = prec is not None and ts - prec[0] > BUCO
        riavvio = prec is not None and uptime < prec[1]
        if cur is not None:
            if riavvio:
                chiudi(cur, max(prec[0], ts - uptime), buco, "riavvio")
                cur = None
            else:
                if e >= prec[4]:
                    cur["energia_Wh"] += e - prec[4]
                if not acceso:
                    chiudi(cur, ts, buco)
                    cur = None
        if cur is None and acceso:
            if prec is None:
                cur = apri(c, "gia_accesa", ts, True)
            elif riavvio:
                cur = apri(c, "ritorno_corrente", max(prec[0], ts - uptime), buco)
            elif prec[2]:
                # acceso prima e dopo senza sessione aperta: non succede, per sicurezza
                cur = apri(c, "gia_accesa", ts, True)
            else:
                causa = "programma" if da_programma(prec[0] if buco else ts, ts) else "manuale"
                cur = apri(c, causa, ts, buco)
                # l'energia fra l'ultimo campione spento e questo è della sessione
                if e >= prec[4]:
                    cur["energia_Wh"] += e - prec[4]
        if cur is not None:
            if p > SOGLIA_CARICA:
                if cur["carica_da"] is None:
                    cur["carica_da"] = ts
                cur["carica_a"] = ts
            cur["potenza_max_W"] = max(cur["potenza_max_W"], p)
            cur["ultima_potenza_W"] = p
        prec = c
    if cur is not None:
        out.append(cur)
    return out


def registro(base, adesso):
    t0 = time.monotonic()
    righe, _ = leggi(base, "rb-carica", adesso - FINESTRA, adesso, 3)
    ss = sessioni(campioni(righe))[-MAX_SESSIONI:]
    voci = []
    for s in reversed(ss):
        voci.append({
            "inizio": int(s["inizio"]),
            "inizio_approssimato": s["inizio_approssimato"],
            "causa": s["causa"],
            "fine": None if s["fine"] is None else int(s["fine"]),
            "fine_approssimata": s["fine_approssimata"],
            "esito": s["esito"],
            "carica_da": None if s["carica_da"] is None else int(s["carica_da"]),
            "carica_a": None if s["carica_a"] is None else int(s["carica_a"]),
            "energia_Wh": round(s["energia_Wh"], 1),
            "potenza_max_W": round(s["potenza_max_W"], 1),
            "in_carica": s["esito"] == "in_corso" and s["ultima_potenza_W"] > SOGLIA_CARICA,
        })
    return {
        "versione": 1,
        "generato": int(adesso),
        "dal": int(adesso - FINESTRA),
        "sessioni": voci,
        "calcolo_ms": int((time.monotonic() - t0) * 1000),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Registro della ricarica dai CSV di rb-carica")
    ap.add_argument("--dir", default=directory(), help="directory dei CSV giornalieri")
    ap.add_argument("--ora", type=float, default=None, help="istante di riferimento, epoch")
    ap.add_argument("--uscita", help="file JSON da scrivere in modo atomico")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.dir):
        print("Directory dei dati inesistente: %s" % a.dir, file=sys.stderr)
        return 1
    dati = registro(a.dir, a.ora if a.ora is not None else time.time())
    if a.uscita:
        scrivi_json_atomico(a.uscita, dati)
    else:
        json.dump(dati, sys.stdout, ensure_ascii=False, indent=1)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
