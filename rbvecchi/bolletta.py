"""Contabilità della ricarica e bolletta bimestrale.

Nessuna analisi dei campioni qui: i Wh per giorno, le letture del contatore e le
sessioni li calcola la raccolta (raccolta/sessioni_carica.py, carica-consumi.json).
Qui si sommano i giorni del periodo e si applica a ciascun giorno il prezzo in
vigore quel giorno (tabella tariffe). Alla prima emissione la bolletta viene
fissata nel database come fotografia JSON: un PDF rigenerato dopo è identico.
"""
from __future__ import annotations

import calendar
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .pdf import Documento

LOGGER = logging.getLogger(__name__)

PREZZO_PREDEFINITO = 0.25          # €/kWh se non è mai stato impostato un prezzo
ORA_INVIO = 9                      # il primo giorno del bimestre, dalle 09:00
ATTESA_MAX_DATI = 3 * 86400        # dopo la fine del periodo si emette anche con dati incompleti
MAX_RITARDO_AUTOMATICO = 20 * 86400  # oltre, niente invio automatico (al primo avvio non parte
                                     # la bolletta di un bimestre vecchio): resta l'invio a mano
INTERVALLO_CONTROLLO = 900         # s fra due controlli del thread di invio
MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre")
CAUSE = {"programma": "programma 01:00", "manuale": "a mano",
         "ritorno_corrente": "ritorno corrente", "gia_accesa": "già accesa"}
ESITI = {"fine_carica": "fine carica", "senza_carica": "niente da caricare",
         "interrotta": "interrotta", "riavvio": "Shelly riavviato", "in_corso": "in corso"}


# ---------------------------------------------------------------- periodi

@dataclass(frozen=True)
class Periodo:
    anno: int
    numero: int                    # 1 = gennaio-febbraio ... 6 = novembre-dicembre

    @classmethod
    def da_data(cls, d: date) -> "Periodo":
        return cls(d.year, (d.month + 1) // 2)

    @classmethod
    def da_id(cls, testo: str) -> "Periodo":
        m = re.fullmatch(r"(\d{4})-B([1-6])", testo)
        if not m:
            raise ValueError("periodo non valido")
        return cls(int(m.group(1)), int(m.group(2)))

    @property
    def id(self) -> str:
        return f"{self.anno}-B{self.numero}"

    @property
    def dal(self) -> date:
        return date(self.anno, 2 * self.numero - 1, 1)

    @property
    def al(self) -> date:
        mese = 2 * self.numero
        return date(self.anno, mese, calendar.monthrange(self.anno, mese)[1])

    @property
    def titolo(self) -> str:
        return f"{MESI[2 * self.numero - 2]} – {MESI[2 * self.numero - 1]} {self.anno}"

    def precedente(self) -> "Periodo":
        return Periodo(self.anno, self.numero - 1) if self.numero > 1 else Periodo(self.anno - 1, 6)

    def inizio_ts(self, tz: ZoneInfo) -> float:
        return datetime.combine(self.dal, datetime.min.time(), tz).timestamp()

    def fine_ts(self, tz: ZoneInfo) -> float:
        return datetime.combine(self.al + timedelta(days=1), datetime.min.time(), tz).timestamp()


# ---------------------------------------------------------------- prezzi

def prezzo_del_giorno(tariffe: list[dict[str, Any]], giorno: str) -> float:
    """Prezzo in vigore il giorno indicato: l'ultimo con "dal" <= giorno."""
    prezzo = PREZZO_PREDEFINITO
    for t in sorted(tariffe, key=lambda t: t["dal"]):
        if t["dal"] <= giorno:
            prezzo = float(t["eur_kwh"])
    return prezzo


# ---------------------------------------------------------------- calcolo

def calcola(consumi: dict[str, Any], tariffe: list[dict[str, Any]], periodo: Periodo,
            adesso: float, tz: ZoneInfo) -> dict[str, Any]:
    dal, al = periodo.dal.isoformat(), periodo.al.isoformat()
    inizio, fine = periodo.inizio_ts(tz), periodo.fine_ts(tz)
    giorni = [g for g in consumi.get("giorni", []) if dal <= g[0] <= al]
    righe, kwh, euro = [], 0.0, 0.0
    for giorno, wh, _, _ in giorni:
        prezzo = prezzo_del_giorno(tariffe, giorno)
        righe.append({"giorno": giorno, "kWh": round(wh / 1000, 3), "eur_kwh": prezzo,
                      "euro": round(wh / 1000 * prezzo, 4)})
        kwh += wh / 1000
        euro += wh / 1000 * prezzo
    usati = sorted({(r["eur_kwh"]) for r in righe})
    sessioni = []
    for s in sorted(consumi.get("sessioni", []), key=lambda s: s["inizio"]):
        if not inizio <= s["inizio"] < fine:
            continue
        giorno = datetime.fromtimestamp(s["inizio"], tz).date().isoformat()
        skwh = (s["energia_Wh"] or 0) / 1000
        sessioni.append({"inizio": s["inizio"], "fine": s["fine"], "causa": s["causa"],
                         "esito": s["esito"], "carica": s["carica_da"] is not None,
                         "kWh": round(skwh, 3),
                         "euro": round(skwh * prezzo_del_giorno(tariffe, giorno), 4)})
    contatore = consumi.get("contatore") or {}
    dati_fino_a = contatore.get("ts")
    lettura_iniziale = giorni[0][2] / 1000 if giorni else None
    lettura_finale = giorni[-1][3] / 1000 if giorni else None
    giorni_periodo = (periodo.al - periodo.dal).days + 1
    return {
        "versione": 1,
        "periodo": periodo.id,
        "titolo": periodo.titolo,
        "dal": dal,
        "al": al,
        "kWh": round(kwh, 3),
        "euro": round(euro, 2),
        "prezzi": usati or [prezzo_del_giorno(tariffe, dal)],
        "letture": {"iniziale_kWh": lettura_iniziale, "finale_kWh": lettura_finale,
                    "primo_giorno": giorni[0][0] if giorni else None,
                    "ultimo_giorno": giorni[-1][0] if giorni else None},
        "giorni": righe,
        "sessioni": sessioni,
        "copertura": {"giorni_con_dati": len(giorni), "giorni_periodo": giorni_periodo},
        "parziale": (not giorni or giorni[0][0] > dal or dati_fino_a is None
                     or dati_fino_a < fine),
        "dati_fino_a": dati_fino_a,
        "emessa": int(adesso),
    }


# ---------------------------------------------------------------- formati

def num(x: float | None, decimali: int = 2) -> str:
    if x is None:
        return "n/d"
    testo = f"{x:,.{decimali}f}"
    return testo.replace(",", "§").replace(".", ",").replace("§", ".")


def data_it(giorno: str) -> str:
    a, m, g = giorno.split("-")
    return f"{g}/{m}/{a}"


def ora_it(ts: float | None, tz: ZoneInfo, con_data: bool = True) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts, tz).strftime("%d/%m %H:%M" if con_data else "%H:%M")


def prezzi_testo(b: dict[str, Any]) -> str:
    return " / ".join(f"{num(p, 3)} €/kWh" for p in b["prezzi"])


def nome_file(b: dict[str, Any]) -> str:
    return f"bolletta-ricarica-{b['periodo']}.pdf"


def testo_telegram(b: dict[str, Any], tz: ZoneInfo) -> str:
    righe = [
        f"🧾 Bolletta ricarica {b['titolo']}",
        f"Consumo: {num(b['kWh'], 2)} kWh",
        f"Prezzo: {prezzi_testo(b)}",
        f"Totale: {num(b['euro'], 2)} €",
    ]
    letture = b["letture"]
    if letture["iniziale_kWh"] is not None:
        righe.append(f"Contatore: {num(letture['iniziale_kWh'], 2)} → "
                     f"{num(letture['finale_kWh'], 2)} kWh")
    con_carica = sum(1 for s in b["sessioni"] if s["carica"])
    righe.append(f"Sessioni: {len(b['sessioni'])} ({con_carica} con carica)")
    if b["parziale"]:
        cop = b["copertura"]
        righe.append(f"Periodo parziale: dati per {cop['giorni_con_dati']} giorni "
                     f"su {cop['giorni_periodo']}.")
    righe.append("Dettaglio nel PDF allegato.")
    return "\n".join(righe)


# ---------------------------------------------------------------- PDF

INCHIOSTRO = (0.07, 0.09, 0.15)
GRIGIO = (0.4, 0.44, 0.5)
LINEA = (0.85, 0.87, 0.9)
FONDO = (0.95, 0.96, 0.98)
ACCENTO = (0.15, 0.39, 0.92)


class _Impaginatore:
    """Flusso verticale con salto pagina automatico."""

    def __init__(self, doc: Documento, piede: str) -> None:
        self.doc, self.piede = doc, piede
        self.x0, self.x1 = 48.0, doc.w - 48.0
        self.y = 56.0
        self.pagina = 1
        self._numera()

    def _numera(self) -> None:
        self.doc.testo(self.x0, self.doc.h - 28, self.piede, 7.5, colore=GRIGIO)
        self.doc.testo(self.x1, self.doc.h - 28, f"pagina {self.pagina}", 7.5,
                       colore=GRIGIO, allinea="destra")

    def spazio(self, altezza: float) -> None:
        if self.y + altezza > self.doc.h - 52:
            self.doc.nuova_pagina()
            self.pagina += 1
            self.y = 56.0
            self._numera()

    def titolo_sezione(self, testo: str) -> None:
        self.spazio(40)
        self.y += 22
        self.doc.testo(self.x0, self.y, testo, 11.5, grassetto=True)
        self.y += 8
        self.doc.linea(self.x0, self.y, self.x1, self.y, 0.8, LINEA)
        self.y += 4

    def tabella(self, colonne: list[tuple[str, float, str]], righe: list[list[str]],
                corpo: float = 8.5, passo: float = 13.0, totale_finale: bool = False) -> None:
        """colonne: (intestazione, larghezza relativa, allineamento)."""
        totale = sum(c[1] for c in colonne)
        larghezze = [(self.x1 - self.x0) * c[1] / totale for c in colonne]

        def riga(valori: list[str], grassetto: bool, colore=INCHIOSTRO) -> None:
            x = self.x0
            for (_, _, allinea), w, v in zip(colonne, larghezze, valori):
                if allinea == "destra":
                    self.doc.testo(x + w - 4, self.y, v, corpo, grassetto, colore, "destra")
                else:
                    self.doc.testo(x + 4, self.y, v, corpo, grassetto, colore)
                x += w

        def intestazione() -> None:
            self.y += passo
            riga([c[0] for c in colonne], True, GRIGIO)
            self.y += 4
            self.doc.linea(self.x0, self.y, self.x1, self.y, 0.5, LINEA)

        self.spazio(passo * 3)
        intestazione()
        for i, valori in enumerate(righe):
            if self.y + passo > self.doc.h - 52:
                self.spazio(passo * 3)
                intestazione()
            ultima = totale_finale and i == len(righe) - 1
            if ultima:
                self.doc.linea(self.x0, self.y + 2, self.x1, self.y + 2, 0.8, GRIGIO)
            elif i % 2 == 1:
                self.doc.rettangolo(self.x0, self.y + 2, self.x1 - self.x0, passo, FONDO)
            self.y += passo
            riga(valori, ultima)


def pdf_bolletta(b: dict[str, Any], tz: ZoneInfo, intestazione: str,
                 anteprima: bool = False) -> bytes:
    doc = Documento(f"Bolletta ricarica {b['titolo']}")
    imp = _Impaginatore(doc, f"{intestazione} · bolletta {b['periodo']} · "
                             "documento interno di ripartizione dei costi, non fiscale")
    d = doc
    x0, x1 = imp.x0, imp.x1

    # ---- testata
    d.testo(x0, imp.y, intestazione, 9, colore=GRIGIO)
    imp.y += 26
    d.testo(x0, imp.y, "Bolletta ricarica quadriciclo", 20, grassetto=True)
    if anteprima:
        d.testo(x1, imp.y, "ANTEPRIMA", 12, grassetto=True, colore=(0.85, 0.33, 0.1),
                allinea="destra")
    imp.y += 20
    d.testo(x0, imp.y, f"Periodo: {b['titolo']} (dal {data_it(b['dal'])} al {data_it(b['al'])})",
            10.5)
    imp.y += 15
    emessa = datetime.fromtimestamp(b["emessa"], tz).strftime("%d/%m/%Y")
    d.testo(x0, imp.y, f"Numero {b['periodo']} · {'calcolata' if anteprima else 'emessa'} "
                       f"il {emessa}", 9, colore=GRIGIO)

    # ---- riquadro del totale
    imp.y += 18
    alto = 74
    d.rettangolo(x0, imp.y, x1 - x0, alto, riempimento=FONDO, bordo=LINEA)
    d.rettangolo(x0, imp.y, 4, alto, riempimento=ACCENTO)
    d.testo(x0 + 18, imp.y + 24, "Totale del periodo", 10, colore=GRIGIO)
    d.testo(x0 + 18, imp.y + 52, f"{num(b['euro'], 2)} €", 26, grassetto=True)
    d.testo(x1 - 16, imp.y + 24, "Energia", 10, colore=GRIGIO, allinea="destra")
    d.testo(x1 - 16, imp.y + 44, f"{num(b['kWh'], 3)} kWh", 15, grassetto=True,
            allinea="destra")
    d.testo(x1 - 16, imp.y + 62, f"prezzo {prezzi_testo(b)}", 9, colore=GRIGIO,
            allinea="destra")
    imp.y += alto

    if b["parziale"]:
        imp.y += 18
        cop = b["copertura"]
        fino = (f", dati fino al {datetime.fromtimestamp(b['dati_fino_a'], tz):%d/%m/%Y %H:%M}"
                if b["dati_fino_a"] else "")
        d.testo(x0, imp.y, f"Periodo parziale: dati per {cop['giorni_con_dati']} giorni su "
                           f"{cop['giorni_periodo']}{fino}.", 9, colore=(0.7, 0.3, 0.05))

    # ---- letture
    imp.titolo_sezione("Letture del contatore (Shelly 1PM della presa di ricarica)")
    letture = b["letture"]
    differenza = (letture["finale_kWh"] - letture["iniziale_kWh"]
                  if letture["iniziale_kWh"] is not None else None)
    righe = [
        [f"Lettura iniziale ({data_it(letture['primo_giorno'])})" if letture["primo_giorno"]
         else "Lettura iniziale", f"{num(letture['iniziale_kWh'], 3)} kWh"],
        [f"Lettura finale ({data_it(letture['ultimo_giorno'])})" if letture["ultimo_giorno"]
         else "Lettura finale", f"{num(letture['finale_kWh'], 3)} kWh"],
        ["Differenza delle letture", f"{num(differenza, 3)} kWh"],
        ["Consumo fatturato (somma degli incrementi del contatore)", f"{num(b['kWh'], 3)} kWh"],
    ]
    imp.tabella([("Voce", 3, "sinistra"), ("Valore", 1, "destra")], righe, corpo=9, passo=15)
    if differenza is not None and abs(differenza - b["kWh"]) >= 0.01:
        imp.y += 14
        d.testo(x0, imp.y, "Le letture differiscono dal consumo perché il contatore dello Shelly "
                           "è ripartito (riavvio o interruzione di corrente):", 8, colore=GRIGIO)
        imp.y += 11
        d.testo(x0, imp.y, "si fattura la somma degli incrementi, che non perde energia.", 8,
                colore=GRIGIO)

    # ---- grafico giornaliero
    imp.titolo_sezione("Consumo giornaliero (kWh)")
    _grafico_giorni(imp, b)

    # ---- riepilogo
    imp.titolo_sezione("Riepilogo")
    con_carica = [s for s in b["sessioni"] if s["carica"]]
    righe = [
        ["Giorni con dati", f"{b['copertura']['giorni_con_dati']} su "
                            f"{b['copertura']['giorni_periodo']}"],
        ["Accensioni della presa", str(len(b["sessioni"]))],
        ["Sessioni con carica", str(len(con_carica))],
        ["Energia media per sessione con carica",
         f"{num(sum(s['kWh'] for s in con_carica) / len(con_carica), 3)} kWh"
         if con_carica else "—"],
    ]
    imp.tabella([("Voce", 3, "sinistra"), ("Valore", 1, "destra")], righe, corpo=9, passo=15)

    # ---- dettaglio giornaliero
    imp.titolo_sezione("Dettaglio giornaliero")
    righe = [[data_it(r["giorno"]), num(r["kWh"], 3), num(r["eur_kwh"], 3), num(r["euro"], 2)]
             for r in b["giorni"]]
    righe.append(["Totale", num(b["kWh"], 3), "", num(b["euro"], 2)])
    imp.tabella([("Giorno", 2, "sinistra"), ("kWh", 1.4, "destra"), ("€/kWh", 1.2, "destra"),
                 ("Importo €", 1.4, "destra")], righe, totale_finale=True)

    # ---- sessioni
    imp.titolo_sezione("Accensioni della presa")
    righe = [[ora_it(s["inizio"], tz), ora_it(s["fine"], tz) if s["fine"] else "in corso",
              CAUSE.get(s["causa"], s["causa"]), ESITI.get(s["esito"], s["esito"]),
              num(s["kWh"], 3), num(s["euro"], 2)] for s in b["sessioni"]]
    if righe:
        imp.tabella([("Accesa", 1.3, "sinistra"), ("Spenta", 1.3, "sinistra"),
                     ("Causa", 1.4, "sinistra"), ("Esito", 1.5, "sinistra"),
                     ("kWh", 0.9, "destra"), ("€", 0.8, "destra")], righe)
    else:
        imp.y += 16
        d.testo(x0, imp.y, "Nessuna accensione registrata nel periodo.", 9, colore=GRIGIO)

    imp.spazio(60)
    imp.y += 28
    for riga in (
        "Energia misurata dallo Shelly 1PM Gen3 che alimenta la presa di ricarica: comprende "
        "carica, ricariche di mantenimento",
        "e standby del caricabatterie. A ogni giorno si applica il prezzo €/kWh in vigore quel "
        "giorno, impostato nella dashboard RB-Vecchi.",
    ):
        d.testo(x0, imp.y, riga, 7.5, colore=GRIGIO)
        imp.y += 10
    return d.bytes()


def _grafico_giorni(imp: _Impaginatore, b: dict[str, Any]) -> None:
    d = imp.doc
    alto = 120
    imp.spazio(alto + 40)
    top = imp.y + 14
    base = top + alto
    x0, x1 = imp.x0 + 30, imp.x1
    dal = date.fromisoformat(b["dal"])
    n = (date.fromisoformat(b["al"]) - dal).days + 1
    valori = {r["giorno"]: r["kWh"] for r in b["giorni"]}
    massimo = max(valori.values(), default=0) or 1.0
    # scala "tonda": 1, 2, 5 x 10^k
    passo = 1.0
    for cand in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50):
        if massimo / cand <= 4:
            passo = cand
            break
    tetto = passo * max(1, -(-massimo // passo))
    for i in range(int(round(tetto / passo)) + 1):
        y = base - alto * (i * passo) / tetto
        d.linea(x0, y, x1, y, 0.4, LINEA)
        d.testo(x0 - 6, y + 3, num(i * passo, 1 if passo < 1 else 0), 7, colore=GRIGIO,
                allinea="destra")
    larghezza = (x1 - x0) / n
    for i in range(n):
        giorno = (dal + timedelta(days=i)).isoformat()
        v = valori.get(giorno)
        x = x0 + i * larghezza
        if v:
            h = max(0.6, alto * v / tetto)
            d.rettangolo(x + larghezza * 0.15, base - h, larghezza * 0.7, h, riempimento=ACCENTO)
        if (dal + timedelta(days=i)).day in (1, 10, 20):
            d.testo(x + larghezza / 2, base + 11, (dal + timedelta(days=i)).strftime("%d/%m"), 7,
                    colore=GRIGIO, allinea="centro")
    d.linea(x0, base, x1, base, 0.8, GRIGIO)
    imp.y = base + 18


# ---------------------------------------------------------------- invio

class InvioBollette:
    """Emette e invia su Telegram la bolletta del bimestre appena chiuso: dal primo
    giorno del bimestre successivo alle ORA_INVIO, con un controllo ogni
    INTERVALLO_CONTROLLO secondi. Una sola emissione per periodo (fotografia nel
    database); se Telegram fallisce si riprova al controllo dopo."""

    def __init__(self, database, notifier, lettore_consumi: Callable[[], dict[str, Any]],
                 timezone: str, intestazione: str) -> None:
        self.database = database
        self.notifier = notifier
        self.lettore_consumi = lettore_consumi
        self.tz = ZoneInfo(timezone)
        self.intestazione = intestazione
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ---- bollette
    def fotografia(self, periodo: Periodo) -> dict[str, Any] | None:
        riga = self.database.get_bolletta(periodo.id)
        if riga is not None:
            return json.loads(riga["dati"])
        return None

    def emetti(self, periodo: Periodo, adesso: float) -> dict[str, Any] | None:
        """Fissa la bolletta del periodo (se non c'è) e la restituisce."""
        esistente = self.fotografia(periodo)
        if esistente is not None:
            return esistente
        consumi = self.lettore_consumi()
        if consumi.get("stato") != "ok":
            return None
        b = calcola(consumi, self.database.list_tariffe(), periodo, adesso, self.tz)
        if not b["giorni"]:
            return None
        self.database.fissa_bolletta(periodo.id, json.dumps(b, ensure_ascii=False), adesso)
        return self.fotografia(periodo)

    def anteprima(self, periodo: Periodo, adesso: float) -> dict[str, Any] | None:
        consumi = self.lettore_consumi()
        if consumi.get("stato") != "ok":
            return None
        return calcola(consumi, self.database.list_tariffe(), periodo, adesso, self.tz)

    def pdf(self, b: dict[str, Any], anteprima: bool = False) -> bytes:
        return pdf_bolletta(b, self.tz, self.intestazione, anteprima)

    def invia(self, b: dict[str, Any], adesso: float) -> tuple[bool, str]:
        with self._lock:
            try:
                self.notifier.send_document(nome_file(b), self.pdf(b), testo_telegram(b, self.tz))
            except Exception as exc:          # TelegramError o configurazione mancante
                self.database.esito_bolletta(b["periodo"], False, str(exc), adesso)
                LOGGER.warning("Bolletta %s non inviata: %s", b["periodo"], exc)
                return False, str(exc)
            self.database.esito_bolletta(b["periodo"], True, "inviata", adesso)
            LOGGER.info("Bolletta %s inviata su Telegram", b["periodo"])
            return True, "inviata"

    # ---- invio automatico
    def controlla(self, adesso: float | None = None) -> str:
        adesso = time.time() if adesso is None else adesso
        ora = datetime.fromtimestamp(adesso, self.tz)
        corrente = Periodo.da_data(ora.date())
        periodo = corrente.precedente()
        apertura = datetime.combine(corrente.dal, datetime.min.time(), self.tz) \
            + timedelta(hours=ORA_INVIO)
        if ora < apertura:
            return "attesa: prima dell'orario di invio"
        if not self.notifier.enabled:
            return "telegram non configurato"
        riga = self.database.get_bolletta(periodo.id)
        if riga is not None and riga["inviata_ts"] is not None:
            return "già inviata"
        if adesso > periodo.fine_ts(self.tz) + MAX_RITARDO_AUTOMATICO:
            return "periodo troppo vecchio per l'invio automatico"
        if riga is None:
            consumi = self.lettore_consumi()
            fine = periodo.fine_ts(self.tz)
            contatore = consumi.get("contatore") or {}
            pronti = (consumi.get("stato") == "ok" and (contatore.get("ts") or 0) >= fine)
            if not pronti and adesso < fine + ATTESA_MAX_DATI:
                return "attesa dati"
        b = self.emetti(periodo, adesso)
        if b is None:
            return "nessun dato per il periodo"
        ok, esito = self.invia(b, adesso)
        return "inviata" if ok else f"errore: {esito}"

    def _ciclo(self) -> None:
        while not self._stop.is_set():
            try:
                esito = self.controlla()
                LOGGER.debug("Controllo bolletta: %s", esito)
            except Exception:
                LOGGER.exception("Errore nel controllo della bolletta")
            self._stop.wait(INTERVALLO_CONTROLLO)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._ciclo, name="bollette", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
