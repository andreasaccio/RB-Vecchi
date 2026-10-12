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
# Il motore è incrementale: lo stato (carica-stato.json) tiene l'ultimo campione,
# la sessione aperta, l'archivio delle sessioni e i Wh per giorno; a ogni giro si
# leggono solo i campioni nuovi. Senza stato valido si ricostruisce dagli ultimi
# RICOSTRUZIONE_GIORNI giorni di CSV.
# Wh per giorno: incrementi del contatore attribuiti al giorno (data locale) del
# campione che li registra; un buco di dati a cavallo della mezzanotte finisce
# tutto nel giorno dopo. "prima"/"ultima" sono le letture grezze del contatore.
import argparse, json, os, sys, time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from giornaliero import directory, scrivi_json_atomico
from stato_rete import leggi

SOGLIA_CARICA = 100.0     # W
SOGLIA_STANDBY = 20.0     # W
MIN_STANDBY = 480         # s (lo script spegne dopo 600 s)
BUCO = 30                 # s
FINESTRA = 7 * 86400      # s
MAX_SESSIONI = 30
ARCHIVIO_GIORNI = 400     # sessioni e giorni tenuti nello stato
RICOSTRUZIONE_GIORNI = 70  # senza stato si riparte da qui (copre due bimestri)
MAX_SESSIONI_CONSUMI = 200
PASSO_PROFILO = 60        # s
MAX_PUNTI_PROFILO = 1440  # 24 h al minuto
STATO = "carica-stato.json"   # stato interno del motore, non per la dashboard
VERSIONE_STATO = 1
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


class Motore:
    """Elabora i campioni uno alla volta e tiene lo stato fra un giro e l'altro:
    sessioni (archivio di ARCHIVIO_GIORNI), Wh per giorno dal contatore e profilo
    di potenza al minuto dell'ultima sessione con carica."""

    def __init__(self):
        self.prec = None          # ultimo campione ok
        self.cur = None           # sessione aperta
        self.chiuse = []          # sessioni chiuse, dalla più vecchia
        self.giorni = {}          # "AAAA-MM-GG" -> {"Wh", "prima", "ultima"}
        self.buf = None           # profilo della sessione aperta
        self.profilo = None       # profilo dell'ultima sessione chiusa con carica

    # ---------------------------------------------------------- sessioni
    def _apri(self, c, causa, inizio, approssimato):
        self.cur = {"inizio": inizio, "inizio_approssimato": approssimato, "causa": causa,
                    "fine": None, "fine_approssimata": False, "esito": "in_corso",
                    "carica_da": None, "carica_a": None, "energia_Wh": 0.0,
                    "potenza_max_W": c[3], "ultima_potenza_W": c[3]}
        self.buf = {"inizio": inizio, "passo": PASSO_PROFILO, "punti": []}

    def _chiudi(self, fine, approssimata, esito=None):
        s = self.cur
        s["fine"], s["fine_approssimata"] = fine, approssimata
        if esito is None:
            if s["carica_da"] is None:
                esito = "senza_carica"
            elif fine - s["carica_a"] >= MIN_STANDBY:
                esito = "fine_carica"
            else:
                esito = "interrotta"
        s["esito"] = esito
        self.chiuse.append(s)
        if s["carica_da"] is not None:
            self.profilo = self.buf
        self.cur = self.buf = None

    def _profilo(self, ts, p):
        # media al minuto: [minuto, somma W, campioni]
        m = int(ts // PASSO_PROFILO * PASSO_PROFILO)
        punti = self.buf["punti"]
        if punti and punti[-1][0] == m:
            punti[-1][1] += p
            punti[-1][2] += 1
        else:
            punti.append([m, p, 1])
            del punti[:-MAX_PUNTI_PROFILO]

    def aggiungi(self, c):
        ts, uptime, acceso, p, e = c
        prec = self.prec
        buco = prec is not None and ts - prec[0] > BUCO
        riavvio = prec is not None and uptime < prec[1]
        delta = e - prec[4] if prec is not None and not riavvio and e >= prec[4] else 0.0

        # energia del giorno (data locale del campione): solo incrementi
        g = self.giorni.setdefault(date.fromtimestamp(ts).isoformat(),
                                   {"Wh": 0.0, "prima": e, "ultima": e})
        g["Wh"] += delta
        g["ultima"] = e

        if self.cur is not None:
            if riavvio:
                self._chiudi(max(prec[0], ts - uptime), buco, "riavvio")
            else:
                self.cur["energia_Wh"] += delta
                if not acceso:
                    self._chiudi(ts, buco)
        if self.cur is None and acceso:
            if prec is None:
                self._apri(c, "gia_accesa", ts, True)
            elif riavvio:
                self._apri(c, "ritorno_corrente", max(prec[0], ts - uptime), buco)
            elif prec[2]:
                # acceso prima e dopo senza sessione aperta: non succede, per sicurezza
                self._apri(c, "gia_accesa", ts, True)
            else:
                causa = "programma" if da_programma(prec[0] if buco else ts, ts) else "manuale"
                self._apri(c, causa, ts, buco)
                # l'energia fra l'ultimo campione spento e questo è della sessione
                self.cur["energia_Wh"] += delta
        if self.cur is not None:
            if p > SOGLIA_CARICA:
                if self.cur["carica_da"] is None:
                    self.cur["carica_da"] = ts
                self.cur["carica_a"] = ts
            self.cur["potenza_max_W"] = max(self.cur["potenza_max_W"], p)
            self.cur["ultima_potenza_W"] = p
            self._profilo(ts, p)
        self.prec = c

    def tutte(self):
        """Sessioni dalla più vecchia alla più recente, aperta compresa."""
        return self.chiuse + ([self.cur] if self.cur is not None else [])

    def profilo_attuale(self):
        if self.cur is not None and self.cur["carica_da"] is not None:
            return self.buf
        return self.profilo

    def pota(self, adesso):
        limite = adesso - ARCHIVIO_GIORNI * 86400
        self.chiuse = [s for s in self.chiuse if s["inizio"] >= limite]
        primo = date.fromtimestamp(limite).isoformat()
        self.giorni = {g: v for g, v in self.giorni.items() if g >= primo}

    # ---------------------------------------------------------- stato su disco
    def salva(self):
        return {"versione": VERSIONE_STATO, "prec": self.prec, "cur": self.cur,
                "chiuse": self.chiuse, "giorni": self.giorni, "buf": self.buf,
                "profilo": self.profilo}

    @classmethod
    def carica(cls, dati):
        if not isinstance(dati, dict) or dati.get("versione") != VERSIONE_STATO:
            raise ValueError("stato assente o di un'altra versione")
        m = cls()
        m.prec = tuple(dati["prec"]) if dati["prec"] is not None else None
        m.cur, m.chiuse, m.giorni = dati["cur"], dati["chiuse"], dati["giorni"]
        m.buf, m.profilo = dati["buf"], dati["profilo"]
        return m


def sessioni(cc):
    """Sessioni dal più vecchio al più recente (tutte in un colpo, per i test)."""
    m = Motore()
    for c in cc:
        m.aggiungi(c)
    return m.tutte()


def _voce(s):
    return {
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
    }


def inizio_bimestre_precedente(adesso):
    d = date.fromtimestamp(adesso)
    mese = d.month - (d.month - 1) % 2           # 1, 3, 5, 7, 9, 11
    anno, mese = (d.year, mese - 2) if mese > 2 else (d.year - 1, mese + 10)
    return datetime(anno, mese, 1).timestamp()


def aggiorna(base, adesso, stato_file=None):
    """Elabora i campioni nuovi e restituisce (registro, consumi)."""
    t0 = time.monotonic()
    stato_file = stato_file or os.path.join(base, STATO)
    try:
        with open(stato_file, encoding="utf-8") as f:
            m = Motore.carica(json.load(f))
        da = m.prec[0] + 0.5 if m.prec is not None else adesso - RICOSTRUZIONE_GIORNI * 86400
    except (OSError, ValueError, KeyError, TypeError):
        m = Motore()
        da = adesso - RICOSTRUZIONE_GIORNI * 86400
    righe, _ = leggi(base, "rb-carica", da, adesso, 3)
    for c in campioni(righe):
        m.aggiungi(c)
    m.pota(adesso)
    scrivi_json_atomico(stato_file, m.salva())

    tutte = m.tutte()
    recenti = [s for s in tutte if s["inizio"] >= adesso - FINESTRA or s["fine"] is None]
    calcolo_ms = int((time.monotonic() - t0) * 1000)
    registro = {
        "versione": 1, "generato": int(adesso), "dal": int(adesso - FINESTRA),
        "sessioni": [_voce(s) for s in reversed(recenti[-MAX_SESSIONI:])],
        "calcolo_ms": calcolo_ms,
    }
    dal_bimestre = inizio_bimestre_precedente(adesso)
    profilo = m.profilo_attuale()
    consumi = {
        "versione": 1, "generato": int(adesso),
        "giorni": [[g, round(v["Wh"], 1), round(v["prima"], 3), round(v["ultima"], 3)]
                   for g, v in sorted(m.giorni.items())],
        "sessioni_dal": int(dal_bimestre),
        "sessioni": [_voce(s) for s in reversed(tutte) if s["inizio"] >= dal_bimestre
                     or s["fine"] is None or s["fine"] >= dal_bimestre][:MAX_SESSIONI_CONSUMI],
        "profilo": None if profilo is None else {
            "inizio": int(profilo["inizio"]), "passo": profilo["passo"],
            "punti": [[t, round(somma / n, 1)] for t, somma, n in profilo["punti"]]},
        "contatore": None if m.prec is None else {"ts": int(m.prec[0]),
                                                   "Wh": round(m.prec[4], 3)},
        "calcolo_ms": calcolo_ms,
    }
    return registro, consumi


def main(argv=None):
    ap = argparse.ArgumentParser(description="Registro e consumi della ricarica dai CSV di rb-carica")
    ap.add_argument("--dir", default=directory(), help="directory dei CSV giornalieri")
    ap.add_argument("--ora", type=float, default=None, help="istante di riferimento, epoch")
    ap.add_argument("--uscita", help="carica-registro.json da scrivere in modo atomico")
    ap.add_argument("--consumi", help="carica-consumi.json da scrivere in modo atomico")
    ap.add_argument("--stato", help="file di stato del motore (predefinito: %s in --dir)" % STATO)
    a = ap.parse_args(argv)
    if not os.path.isdir(a.dir):
        print("Directory dei dati inesistente: %s" % a.dir, file=sys.stderr)
        return 1
    registro, consumi = aggiorna(a.dir, a.ora if a.ora is not None else time.time(), a.stato)
    if a.uscita:
        scrivi_json_atomico(a.uscita, registro)
    if a.consumi:
        scrivi_json_atomico(a.consumi, consumi)
    if not a.uscita and not a.consumi:
        json.dump(registro, sys.stdout, ensure_ascii=False, indent=1)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
