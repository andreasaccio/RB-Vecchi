#!/usr/bin/env python3
# Stato della rete dai CSV giornalieri dei raccoglitori. SOLA LETTURA.
# Solo libreria standard. Regole:
# - episodio KO = almeno 2 giri consecutivi KO; un KO singolo è una
#   "perdita isolata";
# - periodi senza righe = dati mancanti, riportati a parte, né ok né KO.
#   Una sequenza di KO interrotta da dati mancanti non è consecutiva;
# - rb-link stato ERR (ping non eseguibile) non è una misura: dato mancante;
# - contatore PLC che cala: se calano tx_pkt o rx_pkt è un riavvio
#   dell'adattatore (si riparte dal nuovo valore per tutti i contatori),
#   altrimenti è un azzeramento di quel solo contatore (si riparte da lì);
# - simmetria tx/rx fra .66 e .67: solo rapporto informativo.
# Con --json: riepilogo powerline per la dashboard (regole in classifica()).
import argparse, csv, json, os, sys, time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from giornaliero import directory, percorso, scrivi_json_atomico

PASSO_LINK, BUCO_LINK = 5, 30      # s; oltre BUCO fra due giri = dati mancanti
PASSO_PLC, BUCO_PLC = 120, 360
CONTATORI = ("tx_pkt", "rx_pkt", "tx_drop", "rx_drop", "tx_byte", "rx_byte")
NODI = {
    "192.168.1.1": "router",
    "192.168.1.66": "PLC casa",
    "192.168.1.67": "PLC garage",
    "192.168.1.100": "Shelly basculante",
    "192.168.1.101": "Shelly ricarica",
}
FINESTRE = {"24h": ("Ultime 24 ore", 86400), "7g": ("Ultimi 7 giorni", 7 * 86400)}

# Regole del riepilogo powerline (--json), tutte qui. Valori iniziali, da
# rivedere con i dati.
CASA, GARAGE = "192.168.1.66", "192.168.1.67"
ADATTATORI = {"casa": CASA, "garage": GARAGE}
FINESTRA_RIEPILOGO = 86400        # s, le "24 h"
DATI_VECCHI = 120                 # s: rb-link più vecchio di così -> non_disponibile
GIRI_INTERROTTA = 2               # ultimi giri con .67 KO -> interrotta
MAX_PERDITE_ISOLATE = 20          # oltre, sul .67 nelle 24 h -> instabile


# ---------------------------------------------------------------- lettura

def leggi(base, nome, inizio, fine, colonne):
    """Righe di tutti i file giornalieri che coprono [inizio, fine], ordinate
    per ts. Restituisce (righe, scartate): ogni riga è una lista con ts float."""
    righe, scartate = [], 0
    d, ultimo = date.fromtimestamp(inizio), date.fromtimestamp(fine)
    # un giorno di margine: il nome usa la data locale del campione
    d -= timedelta(days=1)
    while d <= ultimo:
        p = percorso(nome, d.isoformat(), base)
        d += timedelta(days=1)
        if not os.path.exists(p):
            continue
        with open(p, newline="", encoding="utf-8", errors="replace") as f:
            for r in csv.reader(f):
                if not r or r[0] == "ts":
                    continue
                try:
                    ts = float(r[0])
                except ValueError:
                    scartate += 1
                    continue
                if len(r) < colonne:
                    scartate += 1
                    continue
                if inizio <= ts <= fine:
                    righe.append([ts] + r[1:])
    righe.sort(key=lambda r: r[0])
    return righe, scartate


def buchi(tempi, inizio, fine, soglia):
    """Intervalli senza dati: distanze fra tempi consecutivi (e dai bordi
    della finestra) oltre la soglia."""
    out, prec = [], inizio
    for t in tempi:
        if t - prec > soglia:
            out.append((prec, t))
        prec = t
    if fine - prec > soglia:
        out.append((prec, fine))
    return out


# ---------------------------------------------------------------- analisi

def analizza_link(righe, inizio, fine):
    misure = [r for r in righe if r[2] in ("ok", "KO")]
    tempi = sorted({r[0] for r in misure})
    esito = {
        "buchi": buchi(tempi, inizio, fine, BUCO_LINK),
        "err": sum(1 for r in righe if r[2] == "ERR"),
        "altri": sum(1 for r in righe if r[2] not in ("ok", "KO", "ERR")),
        "nodi": {},
    }
    per_host = {}
    for ts, host, stato in (r[:3] for r in misure):
        per_host.setdefault(host, []).append((ts, stato))

    for host, seq in per_host.items():
        n = {"ok": 0, "KO": 0, "isolate": 0, "episodi": []}
        corsa = []          # ts dei KO consecutivi in corso
        prec = None

        def chiudi(bordo):
            if len(corsa) >= 2:
                n["episodi"].append({"da": corsa[0], "a": corsa[-1],
                                     "giri": len(corsa), "bordo": bordo})
            elif len(corsa) == 1:
                n["isolate"] += 1
            corsa.clear()

        for ts, stato in seq:
            if prec is not None and ts - prec > BUCO_LINK:
                chiudi("dati mancanti")
            n[stato] += 1
            if stato == "KO":
                corsa.append(ts)
            else:
                chiudi(None)
            prec = ts
        if corsa and fine - corsa[-1] > BUCO_LINK:
            chiudi("dati mancanti")
        else:
            chiudi("in corso" if corsa else None)
        esito["nodi"][host] = n
    return esito


def analizza_plc(righe, inizio, fine):
    esito = {}
    per_adatt = {}
    for r in righe:
        per_adatt.setdefault(r[1], []).append(r)
    for adatt, seq in per_adatt.items():
        a = {"ok": 0, "KO": 0, "riavvii": [], "azzeramenti": [],
             "incrementi": dict.fromkeys(CONTATORI, 0),
             "buchi": buchi([r[0] for r in seq], inizio, fine, BUCO_PLC),
             "ultimo_campione": None,
             "ultima_lettura": {"ts": seq[-1][0], "stato": seq[-1][2]}}
        prec = None
        for r in seq:
            if r[2] != "ok":
                a["KO"] += 1
                continue
            try:
                v = dict(zip(CONTATORI, (int(x) for x in r[3:9])))
            except ValueError:
                a["KO"] += 1
                continue
            if len(v) < len(CONTATORI):
                a["KO"] += 1
                continue
            a["ok"] += 1
            a["ultimo_campione"] = {"ts": r[0], **v}
            if prec is not None:
                if v["tx_pkt"] < prec["tx_pkt"] or v["rx_pkt"] < prec["rx_pkt"]:
                    a["riavvii"].append(r[0])
                else:
                    for c in CONTATORI:
                        if v[c] < prec[c]:
                            a["azzeramenti"].append((r[0], c))
                        else:
                            a["incrementi"][c] += v[c] - prec[c]
            prec = v
        esito[adatt] = a
    return esito


def simmetria(plc):
    """Coppie (descrizione, trasmessi, ricevuti) per i due versi."""
    if "casa" not in plc or "garage" not in plc:
        return []
    c, g = plc["casa"]["incrementi"], plc["garage"]["incrementi"]
    return [
        ("casa tx -> garage rx, pacchetti", c["tx_pkt"], g["rx_pkt"]),
        ("casa tx -> garage rx, byte", c["tx_byte"], g["rx_byte"]),
        ("garage tx -> casa rx, pacchetti", g["tx_pkt"], c["rx_pkt"]),
        ("garage tx -> casa rx, byte", g["tx_byte"], c["rx_byte"]),
    ]


# ---------------------------------------------------------------- riepilogo

def classifica(ultimi_giri, adesso, garage, plc):
    """Stato e motivo del collegamento powerline. Tutte le regole sono qui.
    ultimi_giri: [(ts, {host: stato})] dal più vecchio al più recente."""
    if not ultimi_giri:
        return "non_disponibile", "nessun dato di rb-link nelle 24 ore"
    ts_ultimo, ultimo = ultimi_giri[-1]
    if adesso - ts_ultimo > DATI_VECCHI:
        return ("non_disponibile", "dati di rb-link fermi da %s" % durata(adesso - ts_ultimo))
    if "ERR" in ultimo.values():
        return "non_disponibile", "ultimo giro di rb-link con ERR: ping non eseguibile"

    coda = ultimi_giri[-GIRI_INTERROTTA:]
    consecutivi = len(coda) == GIRI_INTERROTTA and all(
        b[0] - a[0] <= BUCO_LINK for a, b in zip(coda, coda[1:]))
    if consecutivi and all(g.get(GARAGE) == "KO" for _, g in coda):
        if all(g.get(CASA) == "KO" for _, g in coda):
            return "interrotta", "lato casa: non rispondono né il PLC casa (.66) né il PLC garage (.67)"
        if all(g.get(CASA) == "ok" for _, g in coda):
            return ("interrotta", "il PLC garage (.67) non risponde da %d giri, il PLC casa (.66) sì"
                    % giri_ko_in_coda(ultimi_giri))

    motivi = []
    if garage and garage["episodi"]:
        motivi.append("%d episodi KO sul .67" % len(garage["episodi"])
                      if len(garage["episodi"]) > 1 else "1 episodio KO sul .67")
    scartati = sum(a["incrementi"]["tx_drop"] + a["incrementi"]["rx_drop"] for a in plc.values())
    if scartati:
        motivi.append("%d pacchetti PLC scartati" % scartati)
    riavvii = sum(len(a["riavvii"]) for a in plc.values())
    if riavvii:
        motivi.append("%d riavvii di adattatore" % riavvii if riavvii > 1
                      else "1 riavvio di adattatore")
    if garage and garage["isolate"] > MAX_PERDITE_ISOLATE:
        motivi.append("%d perdite isolate sul .67" % garage["isolate"])
    if motivi:
        return "instabile", "nelle 24 ore: " + ", ".join(motivi)
    return "stabile", "nelle 24 ore nessun episodio, scarto o riavvio"


def giri_ko_in_coda(ultimi_giri):
    n = 0
    for _, g in reversed(ultimi_giri):
        if g.get(GARAGE) != "KO":
            break
        n += 1
    return n


def riepilogo(base, adesso):
    """Riepilogo powerline delle ultime 24 ore per la dashboard."""
    t0 = time.monotonic()
    inizio = adesso - FINESTRA_RIEPILOGO
    righe, _ = leggi(base, "rb-link", inizio, adesso, 3)
    link = analizza_link(righe, inizio, adesso)
    giri = {}
    for ts, host, stato in (r[:3] for r in righe):
        giri.setdefault(ts, {})[host] = stato
    ultimi_giri = [(ts, giri[ts]) for ts in sorted(giri)[-(GIRI_INTERROTTA + 50):]]

    righe_plc, _ = leggi(base, "rb-plc", inizio, adesso, 3)
    plc = analizza_plc(righe_plc, inizio, adesso)
    g = link["nodi"].get(GARAGE)
    stato, motivo = classifica(ultimi_giri, adesso, g, plc)

    garage = None
    if g:
        ultimo = max(g["episodi"], key=lambda e: e["da"]) if g["episodi"] else None
        garage = {
            "disponibilita_24h": round(100.0 * g["ok"] / (g["ok"] + g["KO"]), 3),
            "ok_24h": g["ok"], "ko_24h": g["KO"],
            "episodi_24h": len(g["episodi"]),
            "perdite_isolate_24h": g["isolate"],
            "ultimo_episodio": None if ultimo is None else {
                "inizio": int(ultimo["da"]),
                "durata_s": int(ultimo["a"] - ultimo["da"] + PASSO_LINK),
                "giri": ultimo["giri"],
                "in_corso": ultimo["bordo"] == "in corso",
            },
        }
    return {
        "versione": 1,
        "generato": int(adesso),
        "stato": stato,
        "motivo": motivo,
        "ultimo_giro": int(ultimi_giri[-1][0]) if ultimi_giri else None,
        "garage": garage,
        "plc": {
            adatt: {"ip": ADATTATORI.get(adatt),
                    "scartati_tx_24h": a["incrementi"]["tx_drop"],
                    "scartati_rx_24h": a["incrementi"]["rx_drop"],
                    "riavvii_24h": len(a["riavvii"]),
                    "ultimo_riavvio_24h": int(a["riavvii"][-1]) if a["riavvii"] else None,
                    "ultima_lettura": {"ts": int(a["ultima_lettura"]["ts"]),
                                       "stato": a["ultima_lettura"]["stato"]},
                    "ultimo_campione": None if a["ultimo_campione"] is None else
                    {k: int(v) for k, v in a["ultimo_campione"].items()}}
            for adatt, a in sorted(plc.items())
        },
        "scartati_plc_24h": sum(a["incrementi"]["tx_drop"] + a["incrementi"]["rx_drop"]
                                for a in plc.values()),
        "riavvii_24h": sum(len(a["riavvii"]) for a in plc.values()),
        "calcolo_ms": int((time.monotonic() - t0) * 1000),
    }


# ---------------------------------------------------------------- stampa

def ora(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m %H:%M:%S")


def durata(s):
    s = int(round(max(0, s)))
    g, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if g:
        return "%d g %d h %d min" % (g, h, m)
    if h:
        return "%d h %d min" % (h, m)
    if m:
        return "%d min %d s" % (m, s)
    return "%d s" % s


def stampa_buchi(bb, rientro="  "):
    if not bb:
        print(rientro + "dati mancanti: nessuno")
        return
    print(rientro + "dati mancanti: %d %s, %s in totale"
          % (len(bb), "periodo" if len(bb) == 1 else "periodi",
             durata(sum(b - a for a, b in bb))))
    for a, b in bb:
        print(rientro + "  %s -> %s  (%s)" % (ora(a), ora(b), durata(b - a)))


def rapporto(base, chiave, adesso):
    titolo, secondi = FINESTRE[chiave]
    inizio, fine = adesso - secondi, adesso
    print("== %s (%s -> %s) ==" % (titolo, ora(inizio), ora(fine)))

    righe, scartate = leggi(base, "rb-link", inizio, fine, 3)
    link = analizza_link(righe, inizio, fine)
    print("Ping (rb-link)")
    stampa_buchi(link["buchi"])
    if link["err"] or link["altri"] or scartate:
        print("  righe ERR (ping non eseguibile) %d, stato ignoto %d, "
              "non conformi %d: contate come dati mancanti"
              % (link["err"], link["altri"], scartate))
    if not link["nodi"]:
        print("  nessuna misura nella finestra")
    else:
        print("  %-14s %-18s %9s %8s %6s %8s %8s"
              % ("nodo", "", "disponib.", "ok", "KO", "isolate", "episodi"))
        for host in sorted(link["nodi"], key=lambda h: tuple(map(int, h.split(".")))):
            n = link["nodi"][host]
            disp = 100.0 * n["ok"] / (n["ok"] + n["KO"])
            print("  %-14s %-18s %8.3f%% %8d %6d %8d %8d"
                  % (host, NODI.get(host, ""), disp, n["ok"], n["KO"],
                     n["isolate"], len(n["episodi"])))
        episodi = [(e["da"], h, e) for h, n in link["nodi"].items() for e in n["episodi"]]
        if episodi:
            print("  episodi KO (>= 2 giri consecutivi):")
            for _, h, e in sorted(episodi):
                nota = "  [chiuso da %s]" % e["bordo"] if e["bordo"] else ""
                print("    %-14s %s -> %s  %d giri, ~%s%s"
                      % (h, ora(e["da"]), ora(e["a"]), e["giri"],
                         durata(e["a"] - e["da"] + PASSO_LINK), nota))

    righe, scartate = leggi(base, "rb-plc", inizio, fine, 3)
    plc = analizza_plc(righe, inizio, fine)
    print("Contatori PLC (rb-plc)")
    if scartate:
        print("  righe non conformi: %d" % scartate)
    if not plc:
        print("  nessun campione nella finestra")
    for adatt in sorted(plc):
        a = plc[adatt]
        i = a["incrementi"]
        print("  %s: campioni ok %d, KO %d; riavvii %d, azzeramenti %d"
              % (adatt, a["ok"], a["KO"], len(a["riavvii"]), len(a["azzeramenti"])))
        print("    scartati PLC: tx +%d, rx +%d  (su %d pacchetti tx, %d rx)"
              % (i["tx_drop"], i["rx_drop"], i["tx_pkt"], i["rx_pkt"]))
        for ts in a["riavvii"]:
            print("    riavvio (contatori ripartiti) al campione delle %s" % ora(ts))
        for ts, c in a["azzeramenti"]:
            print("    azzeramento di %s al campione delle %s" % (c, ora(ts)))
        stampa_buchi(a["buchi"], "    ")
    coppie = simmetria(plc)
    if coppie:
        print("  Simmetria tx/rx (informativa: il ricevente può contare più del")
        print("  trasmittente, non è un indicatore di perdita)")
        for descr, tx, rx in coppie:
            r = "%.3f" % (rx / tx) if tx else "n/d"
            print("    %-32s %12d / %12d  rx/tx = %s" % (descr, tx, rx, r))
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Stato della rete dai CSV di rb-raccolta")
    ap.add_argument("--dir", default=directory(), help="directory dei CSV giornalieri")
    ap.add_argument("--finestra", choices=sorted(FINESTRE), action="append",
                    help="24h o 7g (ripetibile; predefinite entrambe)")
    ap.add_argument("--ora", type=float, default=None,
                    help="fine della finestra, epoch (predefinita: adesso)")
    ap.add_argument("--json", action="store_true",
                    help="riepilogo powerline delle 24 ore in JSON, per la dashboard")
    ap.add_argument("--uscita", help="con --json: file da scrivere in modo atomico")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.dir):
        print("Directory dei dati inesistente: %s" % a.dir, file=sys.stderr)
        return 1
    adesso = a.ora if a.ora is not None else time.time()
    if a.json:
        dati = riepilogo(a.dir, adesso)
        if a.uscita:
            scrivi_json_atomico(a.uscita, dati)
        else:
            json.dump(dati, sys.stdout, ensure_ascii=False, indent=1)
            print()
        return 0
    for chiave in a.finestra or ["24h", "7g"]:
        rapporto(a.dir, chiave, adesso)
    return 0


if __name__ == "__main__":
    sys.exit(main())
