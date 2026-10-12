import json
import re
import time
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from rbvecchi import bolletta, raccolta
from rbvecchi.bolletta import InvioBollette, Periodo
from rbvecchi.db import Database
from rbvecchi.notifier import TelegramError, TelegramNotifier
from rbvecchi.pdf import Documento, larghezza
from rbvecchi.web import create_app
from test_monitor import settings

TZ = ZoneInfo("Europe/Rome")


def ts(*args) -> float:
    return datetime(*args, tzinfo=TZ).timestamp()


def consumi(giorni, sessioni=(), contatore_ts=None) -> dict:
    """giorni: [(AAAA-MM-GG, Wh)], letture cumulative da 1000 Wh."""
    righe, lettura = [], 1000.0
    for g, wh in giorni:
        righe.append([g, wh, lettura, lettura + wh])
        lettura += wh
    return {"stato": "ok", "giorni": righe, "sessioni": list(sessioni),
            "contatore": {"ts": contatore_ts or ts(2026, 11, 1, 0, 5), "Wh": lettura}}


def sessione(inizio, wh, causa="programma", esito="fine_carica", carica=True):
    return {"inizio": inizio, "inizio_approssimato": False, "causa": causa, "fine": inizio + 3600,
            "fine_approssimata": False, "esito": esito, "carica_da": inizio if carica else None,
            "carica_a": inizio + 3000 if carica else None, "energia_Wh": wh,
            "potenza_max_W": 870.0, "in_carica": False}


# ---------------------------------------------------------------- periodi e prezzi

def test_periodi_di_calendario() -> None:
    p = Periodo.da_data(date(2026, 10, 12))
    assert (p.id, p.dal, p.al, p.titolo) == ("2026-B5", date(2026, 9, 1), date(2026, 10, 31),
                                             "settembre – ottobre 2026")
    assert Periodo.da_data(date(2027, 2, 28)).id == "2027-B1"
    assert Periodo(2027, 1).precedente() == Periodo(2026, 6)
    assert Periodo(2028, 1).al == date(2028, 2, 29)              # bisestile
    assert Periodo.da_id("2026-B6") == Periodo(2026, 6)
    for errato in ("2026-B7", "2026-B0", "x", "2026-b5"):
        with pytest.raises(ValueError):
            Periodo.da_id(errato)
    assert p.fine_ts(TZ) == ts(2026, 11, 1)


def test_prezzo_del_giorno() -> None:
    tariffe = [{"dal": "2026-10-20", "eur_kwh": 0.27}, {"dal": "2026-09-01", "eur_kwh": 0.25}]
    assert bolletta.prezzo_del_giorno([], "2026-10-01") == bolletta.PREZZO_PREDEFINITO == 0.25
    assert bolletta.prezzo_del_giorno(tariffe, "2026-08-31") == 0.25          # predefinito
    assert bolletta.prezzo_del_giorno(tariffe, "2026-10-19") == 0.25
    assert bolletta.prezzo_del_giorno(tariffe, "2026-10-20") == 0.27


def test_calcolo_con_cambio_di_prezzo_e_letture() -> None:
    giorni = [("2026-08-31", 5000), ("2026-09-01", 1000), ("2026-10-19", 2000),
              ("2026-10-20", 4000), ("2026-11-01", 9000)]
    s = [sessione(ts(2026, 9, 1, 1), 1000), sessione(ts(2026, 10, 20, 1), 4000),
         sessione(ts(2026, 8, 31, 1), 5000), sessione(ts(2026, 10, 21, 15), 20, "manuale",
                                                    "senza_carica", carica=False)]
    tariffe = [{"dal": "2026-10-20", "eur_kwh": 0.30}]
    b = bolletta.calcola(consumi(giorni, s), tariffe, Periodo(2026, 5), ts(2026, 11, 1, 9), TZ)
    assert b["kWh"] == 7.0
    assert b["euro"] == round(3 * 0.25 + 4 * 0.30, 2) == 1.95
    assert b["prezzi"] == [0.25, 0.30]
    assert b["letture"] == {"iniziale_kWh": 6.0, "finale_kWh": 13.0,
                            "primo_giorno": "2026-09-01", "ultimo_giorno": "2026-10-20"}
    assert [x["kWh"] for x in b["sessioni"]] == [1.0, 4.0, 0.02]
    assert b["sessioni"][1]["euro"] == 1.2 and b["sessioni"][2]["carica"] is False
    assert b["copertura"] == {"giorni_con_dati": 3, "giorni_periodo": 61}
    assert b["parziale"] is False                     # dati dal 1° e contatore dopo la fine


def test_parziale_se_mancano_l_inizio_o_la_fine() -> None:
    c = consumi([("2026-09-22", 1000)], contatore_ts=ts(2026, 11, 1, 0, 5))
    assert bolletta.calcola(c, [], Periodo(2026, 5), ts(2026, 11, 1, 9), TZ)["parziale"] is True
    c = consumi([("2026-09-01", 1000)], contatore_ts=ts(2026, 10, 31, 22))
    assert bolletta.calcola(c, [], Periodo(2026, 5), ts(2026, 11, 1, 9), TZ)["parziale"] is True


def test_testo_telegram() -> None:
    c = consumi([("2026-09-22", 280600)], [sessione(ts(2026, 9, 22, 1), 280600)])
    b = bolletta.calcola(c, [], Periodo(2026, 5), ts(2026, 11, 1, 9), TZ)
    testo = bolletta.testo_telegram(b, TZ)
    assert "settembre – ottobre 2026" in testo
    assert "Consumo: 280,60 kWh" in testo and "Totale: 70,15 €" in testo
    assert "Prezzo: 0,250 €/kWh" in testo and "Sessioni: 1 (1 con carica)" in testo
    assert "Periodo parziale: dati per 1 giorni su 61." in testo
    assert len(testo) < 1024                           # didascalia di sendDocument


def test_numeri_all_italiana() -> None:
    assert bolletta.num(1234567.891, 2) == "1.234.567,89"
    assert bolletta.num(0.25, 3) == "0,250"
    assert bolletta.num(None) == "n/d"


# ---------------------------------------------------------------- PDF

def struttura_pdf(dati: bytes) -> int:
    """Controlla xref e oggetti; restituisce il numero di pagine."""
    assert dati.startswith(b"%PDF-1.4") and dati.rstrip().endswith(b"%%EOF")
    xref = int(re.search(rb"startxref\n(\d+)\n", dati).group(1))
    assert dati[xref:xref + 4] == b"xref"
    n = int(re.search(rb"xref\n0 (\d+)\n", dati).group(1))
    voci = re.findall(rb"(\d{10}) 00000 n \n", dati[xref:])
    assert len(voci) == n - 1
    for i, pos in enumerate(voci, start=1):
        assert dati[int(pos):].startswith(b"%d 0 obj" % i)
    return int(re.search(rb"/Type /Pages /Count (\d+)", dati).group(1))


def test_pdf_minimo_valido_con_accenti_ed_euro() -> None:
    d = Documento("Prova – è")
    d.testo(48, 60, "Perché più € (parentesi) \\", 12)
    d.rettangolo(48, 80, 100, 20, riempimento=(0.9, 0.9, 0.9), bordo=(0, 0, 0))
    d.linea(48, 110, 200, 110)
    d.nuova_pagina()
    dati = d.bytes()
    assert struttura_pdf(dati) == 2
    assert b"Perch\xe9 pi\xf9 \x80 \\(parentesi\\) \\\\" in dati
    assert b"/Title <feff" in dati                     # titolo in UTF-16
    assert larghezza("0123456789", 10) == 55.6 and larghezza("€", 10, True) == 5.56


def test_pdf_bolletta_su_piu_pagine() -> None:
    giorni = [(f"2026-09-{g:02d}", 1000 + g) for g in range(1, 31)] + \
             [(f"2026-10-{g:02d}", 2000 + g) for g in range(1, 32)]
    s = [sessione(ts(2026, 9, g, 1), 1000) for g in range(1, 31)]
    b = bolletta.calcola(consumi(giorni, s), [], Periodo(2026, 5), ts(2026, 11, 1, 9), TZ)
    dati = bolletta.pdf_bolletta(b, TZ, "RB-Vecchi · Casa")
    assert struttura_pdf(dati) >= 2
    assert b"Bolletta ricarica quadriciclo" in dati and b"ANTEPRIMA" not in dati
    assert b"ANTEPRIMA" in bolletta.pdf_bolletta(b, TZ, "RB-Vecchi", anteprima=True)


# ---------------------------------------------------------------- invio automatico

class TelegramFinto:
    def __init__(self, *errori, enabled=True):
        self.errori = list(errori)
        self.enabled = enabled
        self.documenti = []

    def send_document(self, nome, contenuto, didascalia):
        if self.errori:
            raise self.errori.pop(0)
        self.documenti.append((nome, contenuto, didascalia))


def invio(tmp_path: Path, telegram, dati) -> InvioBollette:
    return InvioBollette(Database(tmp_path / "g.db"), telegram, lambda: dati, "Europe/Rome", "RB")


def test_invio_dal_primo_giorno_alle_nove_una_sola_volta(tmp_path: Path) -> None:
    tg = TelegramFinto()
    inv = invio(tmp_path, tg, consumi([("2026-09-01", 1000), ("2026-10-31", 2000)]))
    # il 31/10 si guarda ancora luglio-agosto, finito da due mesi
    assert inv.controlla(ts(2026, 10, 31, 23)) == "periodo troppo vecchio per l'invio automatico"
    assert inv.controlla(ts(2026, 11, 1, 8, 59)) == "attesa: prima dell'orario di invio"
    assert inv.controlla(ts(2026, 11, 1, 9, 0)) == "inviata"
    assert inv.controlla(ts(2026, 11, 1, 9, 15)) == "già inviata"
    assert inv.controlla(ts(2026, 12, 20, 9, 0)) == "già inviata"
    [(nome, pdf, didascalia)] = tg.documenti
    assert nome == "bolletta-ricarica-2026-B5.pdf" and pdf.startswith(b"%PDF")
    assert "Totale: 0,75 €" in didascalia
    riga = inv.database.get_bolletta("2026-B5")
    assert riga["inviata_ts"] == ts(2026, 11, 1, 9) and riga["tentativi"] == 1


def test_attende_i_dati_poi_emette_comunque(tmp_path: Path) -> None:
    c = consumi([("2026-09-05", 1000)], contatore_ts=ts(2026, 10, 30, 12))   # Shelly muto
    tg = TelegramFinto()
    inv = invio(tmp_path, tg, c)
    assert inv.controlla(ts(2026, 11, 1, 9)) == "attesa dati"
    assert inv.controlla(ts(2026, 11, 3, 23, 59)) == "attesa dati"
    assert inv.controlla(ts(2026, 11, 4, 0, 1)) == "inviata"
    assert "Periodo parziale" in tg.documenti[0][2]


def test_errore_telegram_si_riprova_con_la_stessa_fotografia(tmp_path: Path) -> None:
    dati = consumi([("2026-09-01", 1000)])
    tg = TelegramFinto(TelegramError("Bad Request: chat not found", 400))
    inv = invio(tmp_path, tg, dati)
    assert inv.controlla(ts(2026, 11, 1, 9)).startswith("errore: Telegram 400")
    riga = inv.database.get_bolletta("2026-B5")
    assert riga["inviata_ts"] is None and riga["tentativi"] == 1
    dati["giorni"].append(["2026-10-01", 99999, 0, 0])        # dati cambiati dopo l'emissione
    assert inv.controlla(ts(2026, 11, 1, 9, 15)) == "inviata"
    assert "Consumo: 1,00 kWh" in tg.documenti[0][2]          # fotografia invariata
    assert inv.database.get_bolletta("2026-B5")["tentativi"] == 2


def test_bimestre_vecchio_non_parte_da_solo(tmp_path: Path) -> None:
    # Al primo avvio (12/10) luglio-agosto ha dati ma è finito da più di 20 giorni.
    tg = TelegramFinto()
    inv = invio(tmp_path, tg, consumi([("2026-08-20", 1000)]))
    assert inv.controlla(ts(2026, 10, 12, 12)) == "periodo troppo vecchio per l'invio automatico"
    assert tg.documenti == [] and inv.database.get_bolletta("2026-B4") is None
    assert inv.controlla(ts(2026, 9, 20, 12)) == "inviata"          # entro 20 giorni sì


def test_senza_telegram_o_senza_dati(tmp_path: Path) -> None:
    inv = invio(tmp_path, TelegramFinto(enabled=False), consumi([("2026-09-01", 1000)]))
    assert inv.controlla(ts(2026, 11, 1, 9)) == "telegram non configurato"
    inv = invio(tmp_path / "x", TelegramFinto(), consumi([("2026-08-01", 1000)]))
    (tmp_path / "x").mkdir(exist_ok=True)
    assert inv.controlla(ts(2026, 11, 4, 9)) == "nessun dato per il periodo"


def test_send_document_multipart(monkeypatch) -> None:
    chiamate = []

    class Risposta:
        status_code = 200

        def json(self):
            return {"ok": True}

    def post(url, timeout, **kwargs):
        chiamate.append((url, kwargs))
        return Risposta()

    from rbvecchi import notifier as modulo
    monkeypatch.setattr(modulo.requests, "post", post)
    TelegramNotifier("123:ABC", "-100").send_document("b.pdf", b"%PDF", "x" * 2000)
    url, kwargs = chiamate[0]
    assert url.endswith("/sendDocument")
    assert kwargs["data"] == {"chat_id": "-100", "caption": "x" * 1024}
    assert kwargs["files"] == {"document": ("b.pdf", b"%PDF", "application/pdf")}


# ---------------------------------------------------------------- dashboard

def scrivi_consumi(base: Path, generato: float, **cambi) -> None:
    dati = {"versione": 1, "generato": generato,
            "giorni": [["2026-10-11", 1124.5, 1271.0, 2394.836], ["2026-10-12", 18.2, 2394.836, 2413.0]],
            "sessioni_dal": 0, "sessioni": [sessione(ts(2026, 10, 12, 1), 18.2)],
            "profilo": {"inizio": ts(2026, 10, 12, 1), "passo": 60, "punti": [[ts(2026, 10, 12, 1), 870.0]]},
            "contatore": {"ts": generato, "Wh": 2413.0}, **cambi}
    (base / raccolta.CONSUMI_CARICA).write_text(json.dumps(dati))


def client(tmp_path: Path, monkeypatch, telegram=None):
    app = create_app(replace(settings(tmp_path), raccolta_dir=tmp_path), start_monitor=False)
    if telegram is not None:
        app.extensions["bollette"].notifier = telegram
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "password"})
    with c.session_transaction() as sess:
        csrf = sess["csrf_token"]
    return app, c, csrf


def test_consumi_letti_e_filtrati(tmp_path: Path) -> None:
    p = tmp_path / raccolta.CONSUMI_CARICA
    assert raccolta.leggi_consumi(p)["stato"] == "non_disponibile"
    scrivi_consumi(tmp_path, 1000, giorni=[["2026-10-11", 1.0, 2.0, 3.0], ["x", 1, 2, 3], [1, 2]])
    r = raccolta.leggi_consumi(p, adesso=1100)
    assert r["stato"] == "ok" and r["giorni"] == [["2026-10-11", 1.0, 2.0, 3.0]]
    assert r["profilo"]["passo"] == 60 and r["contatore"]["Wh"] == 2413.0
    assert raccolta.leggi_consumi(p, adesso=1301)["stato"] == "non_disponibile"
    p.write_text('{"generato": 1000, "giorni": {}}')
    assert raccolta.leggi_consumi(p, adesso=1000)["stato"] == "non_disponibile"


def test_pagina_e_api_ricarica(tmp_path: Path, monkeypatch) -> None:
    app, c, _ = client(tmp_path, monkeypatch)
    assert app.test_client().get("/ricarica").status_code == 302
    pagina = c.get("/ricarica").get_data(as_text=True)
    assert "Consumi ricarica" in pagina and "ricarica.js" in pagina
    scrivi_consumi(tmp_path, time.time() - 5)
    d = c.get("/api/ricarica").get_json()
    assert d["consumi"]["stato"] == "ok" and d["prezzo_attuale"] == 0.25
    assert d["giorni"][0] == {"giorno": "2026-10-11", "kWh": 1.125, "euro": 0.2811}
    assert d["mesi"] == [{"mese": "2026-10", "kWh": 1.143, "euro": 0.29}]
    assert d["consumi"]["sessioni"][0]["euro"] == 0.0046
    assert d["bollette"][0]["stato"] == "in_corso"


def test_prezzo_modificabile_con_controlli(tmp_path: Path, monkeypatch) -> None:
    _, c, csrf = client(tmp_path, monkeypatch)
    oggi = datetime.now(TZ).date()
    inizio = Periodo.da_data(oggi).dal

    def imposta(**corpo):
        return c.post("/api/ricarica/prezzo", json=corpo, headers={"X-CSRF-Token": csrf})

    assert c.post("/api/ricarica/prezzo", json={"eur_kwh": 0.3}).status_code == 403
    assert imposta(eur_kwh="abc").status_code == 400
    assert imposta(eur_kwh=0).status_code == 400 and imposta(eur_kwh=6).status_code == 400
    assert imposta(eur_kwh=0.3, dal=date(inizio.year - 1, 1, 1).isoformat()).status_code == 400
    r = imposta(eur_kwh="0,31", dal=inizio.isoformat())
    assert r.status_code == 200 and r.get_json()["tariffe"][0]["eur_kwh"] == 0.31
    assert imposta(eur_kwh=0.32, dal=inizio.isoformat()).get_json()["tariffe"] == [
        {"dal": inizio.isoformat(), "eur_kwh": 0.32, "impostata_ts": pytest.approx(time.time(), abs=5)}]


def test_pdf_e_invio_manuale(tmp_path: Path, monkeypatch) -> None:
    tg = TelegramFinto()
    app, c, csrf = client(tmp_path, monkeypatch, tg)
    scrivi_consumi(tmp_path, time.time() - 5,
                   giorni=[["2026-07-15", 500.0, 0.0, 500.0], ["2026-10-11", 1000.0, 500.0, 1500.0]])
    assert c.get("/ricarica/bolletta/2026-B9.pdf").status_code == 404
    assert c.get("/ricarica/bolletta/2025-B1.pdf").status_code == 409          # nessun dato
    r = c.get("/ricarica/bolletta/2026-B4.pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and b"ANTEPRIMA" in r.data

    invia = lambda p: c.post(f"/api/ricarica/bolletta/{p}/invia", headers={"X-CSRF-Token": csrf})  # noqa: E731
    assert c.post("/api/ricarica/bolletta/2026-B4/invia").status_code == 403
    futuro = Periodo.da_data(datetime.now(TZ).date())
    assert invia(futuro.id).status_code == 409                                  # non ancora finito
    r = invia("2026-B4")
    assert r.status_code == 200 and len(tg.documenti) == 1
    assert invia("2026-B4").status_code == 429                                  # attesa fra invii
    r = c.get("/ricarica/bolletta/2026-B4.pdf")
    assert b"ANTEPRIMA" not in r.data                                           # ora è emessa
    schede = {s["periodo"]: s for s in c.get("/api/ricarica").get_json()["bollette"]}
    assert schede["2026-B4"]["stato"] == "inviata" and schede["2026-B4"]["kWh"] == 0.5
