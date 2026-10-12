import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
import requests

from rbvecchi import raccolta
from rbvecchi import shelly as shelly_module
from rbvecchi.shelly import PresaRicarica, ShellyError
from rbvecchi.web import create_app
from test_monitor import settings


class PresaFinta:
    def __init__(self, *esiti):
        self.esiti = list(esiti)
        self.chiamate = 0

    def __call__(self):
        self.chiamate += 1
        esito = self.esiti.pop(0) if self.esiti else False
        if isinstance(esito, Exception):
            raise esito
        return esito


def client(tmp_path: Path, monkeypatch, presa: PresaFinta):
    monkeypatch.setattr(shelly_module.PresaRicarica, "accendi", lambda _self: presa())
    app = create_app(replace(settings(tmp_path), raccolta_dir=tmp_path), start_monitor=False)
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "password"})
    with c.session_transaction() as sess:
        csrf = sess["csrf_token"]
    return app, c, csrf


def avvia(c, csrf):
    return c.post("/api/carica/avvia", headers={"X-CSRF-Token": csrf})


# ---------------------------------------------------------------- Carica ora

def test_richiede_login_e_csrf(tmp_path, monkeypatch) -> None:
    presa = PresaFinta()
    app, c, csrf = client(tmp_path, monkeypatch, presa)
    assert c.post("/api/carica/avvia").status_code == 403
    assert avvia(c, "sbagliato").status_code == 403
    assert app.test_client().post("/api/carica/avvia",
                                  headers={"X-CSRF-Token": csrf}).status_code == 401
    assert presa.chiamate == 0


def test_accende_registra_e_rispetta_l_attesa(tmp_path, monkeypatch) -> None:
    presa = PresaFinta(False)
    app, c, csrf = client(tmp_path, monkeypatch, presa)
    r = avvia(c, csrf)
    assert r.status_code == 200 and r.get_json()["era_accesa"] is False
    assert "Presa accesa" in r.get_json()["message"]
    secondo = avvia(c, csrf)
    assert secondo.status_code == 429 and secondo.get_json()["retry_after"] > 0
    assert presa.chiamate == 1
    [comando] = app.extensions["database"].list_commands("CARICA_ON")
    assert (comando["ok"], comando["dettaglio"]) == (True, "presa accesa")
    assert app.extensions["database"].list_commands("PULSE") == []


def test_presa_gia_accesa(tmp_path, monkeypatch) -> None:
    _, c, csrf = client(tmp_path, monkeypatch, PresaFinta(True))
    body = avvia(c, csrf).get_json()
    assert body["ok"] is True and body["message"] == "La presa era già accesa"


def test_shelly_irraggiungibile_non_blocca_il_nuovo_tentativo(tmp_path, monkeypatch) -> None:
    presa = PresaFinta(ShellyError("Shelly della ricarica non raggiungibile: timeout"), False)
    app, c, csrf = client(tmp_path, monkeypatch, presa)
    r = avvia(c, csrf)
    assert r.status_code == 503 and "non raggiungibile" in r.get_json()["error"]
    assert avvia(c, csrf).status_code == 200
    comandi = app.extensions["database"].list_commands("CARICA_ON")
    assert [x["ok"] for x in comandi] == [True, False]       # più recente per primo


# ---------------------------------------------------------------- client della presa

class SessioneFinta:
    def __init__(self, risposta):
        self.risposta, self.inviato = risposta, None

    def post(self, url, json, timeout):
        self.inviato = (url, json)
        if isinstance(self.risposta, Exception):
            raise self.risposta
        return self.risposta


class Risposta:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(str(self.status))

    def json(self):
        return self.payload


def test_presa_manda_solo_switch_set_on() -> None:
    p = PresaRicarica("http://192.168.1.101/")
    p.session = SessioneFinta(Risposta({"was_on": False}))
    assert p.accendi() is False
    assert p.session.inviato == ("http://192.168.1.101/rpc/Switch.Set", {"id": 0, "on": True})
    p.session = SessioneFinta(Risposta({"was_on": True}))
    assert p.accendi() is True


@pytest.mark.parametrize("risposta", [
    requests.ConnectionError("rete"),
    Risposta({}, status=500),
    Risposta({"code": -103, "error": {"message": "Invalid argument"}}),
])
def test_presa_errori(risposta) -> None:
    p = PresaRicarica("http://192.168.1.101")
    p.session = SessioneFinta(risposta)
    with pytest.raises(ShellyError):
        p.accendi()


# ---------------------------------------------------------------- registro

SESSIONE = {"inizio": 1000, "inizio_approssimato": False, "causa": "programma", "fine": 1720,
            "fine_approssimata": False, "esito": "fine_carica", "carica_da": 1000,
            "carica_a": 1110, "energia_Wh": 18.2, "potenza_max_W": 880.3, "in_carica": False}


def scrivi_registro(base: Path, generato: float, sessioni) -> Path:
    p = base / raccolta.REGISTRO_CARICA
    p.write_text(json.dumps({"versione": 1, "generato": generato, "dal": 0, "sessioni": sessioni}))
    return p


def test_registro_valido_e_filtrato(tmp_path) -> None:
    sporca = {**SESSIONE, "causa": "boh"}
    p = scrivi_registro(tmp_path, 2000, [SESSIONE, sporca, "x", {**SESSIONE, "energia_Wh": "18"}])
    r = raccolta.leggi_registro_carica(p, adesso=2030)
    assert (r["stato"], r["eta_s"]) == ("ok", 30)
    assert r["sessioni"][0] == SESSIONE
    assert len(r["sessioni"]) == 2 and r["sessioni"][1]["energia_Wh"] is None


def test_registro_mancante_vecchio_corrotto(tmp_path) -> None:
    p = tmp_path / raccolta.REGISTRO_CARICA
    assert raccolta.leggi_registro_carica(p)["stato"] == "non_disponibile"
    scrivi_registro(tmp_path, 2000, [SESSIONE])
    assert raccolta.leggi_registro_carica(p, adesso=2301)["stato"] == "non_disponibile"
    for contenuto in ["{rotto", "[]", '{"generato": 2000}', '{"generato": 2000, "sessioni": {}}']:
        p.write_text(contenuto)
        r = raccolta.leggi_registro_carica(p, adesso=2000)
        assert r["stato"] == "non_disponibile" and r["sessioni"] == [], contenuto


def test_endpoint_registro_con_i_comandi(tmp_path, monkeypatch) -> None:
    _, c, csrf = client(tmp_path, monkeypatch, PresaFinta(False))
    body = c.get("/api/carica/registro").get_json()
    assert body["registro"]["stato"] == "non_disponibile" and body["comandi"] == []
    scrivi_registro(tmp_path, time.time() - 10, [SESSIONE])
    avvia(c, csrf)
    body = c.get("/api/carica/registro").get_json()
    assert body["registro"]["sessioni"] == [SESSIONE]
    assert [x["dettaglio"] for x in body["comandi"]] == ["presa accesa"]
