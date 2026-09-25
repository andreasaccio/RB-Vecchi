import json
import time
from dataclasses import replace
from pathlib import Path

from rbvecchi.raccolta import leggi_riepilogo
from rbvecchi.web import create_app
from test_monitor import settings

RIEPILOGO = {
    "versione": 1,
    "stato": "instabile",
    "motivo": "nelle 24 ore: 1 episodio KO sul .67",
    "ultimo_giro": 0,
    "garage": {
        "disponibilita_24h": 99.87,
        "ok_24h": 17258,
        "ko_24h": 22,
        "episodi_24h": 1,
        "perdite_isolate_24h": 4,
        "ultimo_episodio": {"inizio": 1790300000, "durata_s": 95, "giri": 19, "in_corso": False},
    },
    "plc": {},
    "scartati_plc_24h": 0,
    "riavvii_24h": 0,
}


def scrivi(path: Path, generato: float, **cambi) -> None:
    path.write_text(json.dumps({**RIEPILOGO, "generato": int(generato), **cambi}))


def client(tmp_path: Path):
    cfg = replace(settings(tmp_path), raccolta_dir=tmp_path)
    app = create_app(cfg, start_monitor=False)
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "password"})
    return c


def test_riepilogo_valido(tmp_path: Path) -> None:
    p = tmp_path / "stato-rete.json"
    scrivi(p, 1000)
    r = leggi_riepilogo(p, adesso=1040)
    assert (r["stato"], r["eta_s"]) == ("instabile", 40)
    assert r["garage"]["disponibilita_24h"] == 99.87
    assert r["garage"]["ultimo_episodio"] == {"inizio": 1790300000, "durata_s": 95, "in_corso": False}


def test_riepilogo_vecchio_mancante_corrotto(tmp_path: Path) -> None:
    p = tmp_path / "stato-rete.json"
    assert leggi_riepilogo(p)["stato"] == "non_disponibile"            # mancante

    scrivi(p, 1000)
    vecchio = leggi_riepilogo(p, adesso=1000 + 301)
    assert vecchio["stato"] == "non_disponibile" and "fermi da 5 min" in vecchio["motivo"]
    assert leggi_riepilogo(p, adesso=1000 + 300)["stato"] == "instabile"

    for contenuto in ['{"stato": "stab', "[]", '{"stato": "boh", "generato": 1000}',
                      '{"stato": "stabile"}', '{"stato": "stabile", "generato": "1000"}']:
        p.write_text(contenuto)
        r = leggi_riepilogo(p, adesso=1000)
        assert r["stato"] == "non_disponibile" and "non valido" in r["motivo"], contenuto

    p.write_bytes(b"\xff\xfe")
    assert leggi_riepilogo(p, adesso=1000)["stato"] == "non_disponibile"


def test_riepilogo_illeggibile(tmp_path: Path) -> None:
    d = tmp_path / "stato-rete.json"
    d.mkdir()                                  # una directory al posto del file
    r = leggi_riepilogo(d)
    assert r["stato"] == "non_disponibile" and "illeggibile" in r["motivo"]


def test_endpoint_powerline(tmp_path: Path) -> None:
    c = client(tmp_path)
    p = tmp_path / "stato-rete.json"

    r = c.get("/api/powerline")                # file mancante
    assert r.status_code == 200 and r.get_json()["powerline"]["stato"] == "non_disponibile"

    scrivi(p, time.time() - 10)
    body = c.get("/api/powerline").get_json()
    assert body["ok"] is True and body["powerline"]["stato"] == "instabile"

    scrivi(p, time.time() - 600)               # vecchio
    assert c.get("/api/powerline").get_json()["powerline"]["stato"] == "non_disponibile"

    p.write_text("{corrotto")                  # corrotto
    assert c.get("/api/powerline").get_json()["powerline"]["stato"] == "non_disponibile"


def test_status_non_dipende_dal_riepilogo(tmp_path: Path) -> None:
    c = client(tmp_path)
    (tmp_path / "stato-rete.json").write_text("{corrotto")
    r = c.get("/api/status")
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert "powerline" not in r.get_json()["status"]


def test_powerline_richiede_login(tmp_path: Path) -> None:
    cfg = replace(settings(tmp_path), raccolta_dir=tmp_path)
    r = create_app(cfg, start_monitor=False).test_client().get("/api/powerline")
    assert r.status_code == 401


# ---------------------------------------------------------------- ricarica

from rbvecchi import raccolta  # noqa: E402

CARICA = {
    "ts": 1000.0, "stato": "ok", "uptime": 62137, "reset_reason": 3, "output": True,
    "apower_W": 412.34, "voltage_V": 231.27, "current_A": 1.8123, "aenergy_Wh": 12.3,
    "temp_C": 43.2, "rssi": -50, "bssid": "b0:c5:54:d6:77:c8",
    "modello": "S3SW-001P16EU", "app": "S1PMG3", "firmware": "2.0.1", "info_ts": 900.0,
    "ultimo_ok": 1000.0, "generato": 1000.2,
}


def scrivi_carica(base: Path, **cambi) -> Path:
    p = base / raccolta.CARICA
    p.write_text(json.dumps({**CARICA, **cambi}))
    return p


def test_carica_valida(tmp_path: Path) -> None:
    r = raccolta.leggi_carica(scrivi_carica(tmp_path), adesso=1030)
    assert (r["stato"], r["eta_s"], r["potenza_W"], r["rele_chiuso"]) == ("ok", 30, 412.34, True)
    assert (r["modello"], r["firmware"], r["reset_reason"]) == ("S3SW-001P16EU", "2.0.1", 3)
    assert r["avviso"] is None


def test_carica_rele_aperto_da_avviso(tmp_path: Path) -> None:
    r = raccolta.leggi_carica(scrivi_carica(tmp_path, output=False, apower_W=0.0), adesso=1005)
    assert r["stato"] == "ok" and r["potenza_W"] == 0.0
    assert r["avviso"] == "relè della presa aperto: la ricarica non ha corrente"


def test_carica_mancante_vecchia_corrotta_ko(tmp_path: Path) -> None:
    p = tmp_path / raccolta.CARICA
    assert raccolta.leggi_carica(p)["stato"] == "non_disponibile"             # mancante

    scrivi_carica(tmp_path)
    assert raccolta.leggi_carica(p, adesso=1060)["stato"] == "ok"
    vecchia = raccolta.leggi_carica(p, adesso=1061)                            # > 60 s
    assert vecchia["stato"] == "non_disponibile" and "fermi da 1 min" in vecchia["motivo"]

    for contenuto in ["{rotto", "[1]", '{"ts": "1000", "stato": "ok"}',
                      json.dumps({**CARICA, "output": "true"}),
                      json.dumps({**CARICA, "apower_W": None})]:
        p.write_text(contenuto)
        r = raccolta.leggi_carica(p, adesso=1000)
        assert r["stato"] == "non_disponibile" and "non valido" in r["motivo"], contenuto
        assert r["avviso"] is None

    p.write_text(json.dumps({"ts": 1000.0, "stato": "KO", "errore": "TimeoutError"}))
    r = raccolta.leggi_carica(p, adesso=1005)
    assert r["stato"] == "non_disponibile" and r["motivo"] == "Shelly ricarica non risponde (TimeoutError)"
    assert r["avviso"] is None and r["eta_s"] == 5


def test_endpoint_carica(tmp_path: Path) -> None:
    c = client(tmp_path)
    assert c.get("/api/carica").get_json()["carica"]["stato"] == "non_disponibile"
    scrivi_carica(tmp_path, ts=time.time() - 5, output=False)
    body = c.get("/api/carica").get_json()
    assert body["ok"] is True and body["carica"]["avviso"].startswith("relè della presa aperto")
    scrivi_carica(tmp_path, ts=time.time() - 120)
    assert c.get("/api/carica").get_json()["carica"]["stato"] == "non_disponibile"
    (tmp_path / raccolta.CARICA).write_text("\x00rotto")
    assert c.get("/api/carica").get_json()["carica"]["stato"] == "non_disponibile"


# ---------------------------------------------------------------- Raspberry

SISTEMA = {
    "versione": 1, "generato": 1000, "carico": {"1min": 0.5, "5min": 0.4, "15min": 0.3},
    "temperatura_cpu_C": 48.3, "memoria": {"usata_B": 10, "totale_B": 40},
    "disco_radice": {"usato_B": 5, "totale_B": 50}, "uptime_s": 90061,
    "kernel": "6.8.0-1015-raspi", "riavvio_richiesto": True,
    "unita": {"rb-vecchi.service": "active", "rb-plc.service": "failed"},
    "estraneo": "non deve passare",
}


def test_sistema_valido_e_filtrato(tmp_path: Path) -> None:
    p = tmp_path / raccolta.SISTEMA
    p.write_text(json.dumps(SISTEMA))
    r = raccolta.leggi_sistema(p, adesso=1100)
    assert (r["stato"], r["eta_s"], r["kernel"]) == ("ok", 100, "6.8.0-1015-raspi")
    assert r["unita"] == {"rb-vecchi.service": "active", "rb-plc.service": "failed"}
    assert r["riavvio_richiesto"] is True and "estraneo" not in r


def test_sistema_mancante_vecchio_corrotto(tmp_path: Path) -> None:
    p = tmp_path / raccolta.SISTEMA
    assert raccolta.leggi_sistema(p)["stato"] == "non_disponibile"
    p.write_text(json.dumps(SISTEMA))
    assert raccolta.leggi_sistema(p, adesso=1301)["stato"] == "non_disponibile"
    p.write_text('{"generato": "ieri"}')
    assert raccolta.leggi_sistema(p, adesso=1000)["stato"] == "non_disponibile"


def test_endpoint_sistema(tmp_path: Path) -> None:
    c = client(tmp_path)
    assert c.get("/api/sistema").get_json()["sistema"]["stato"] == "non_disponibile"
    (tmp_path / raccolta.SISTEMA).write_text(json.dumps({**SISTEMA, "generato": int(time.time())}))
    assert c.get("/api/sistema").get_json()["sistema"]["stato"] == "ok"


# ---------------------------------------------------------------- powerline per adattatore

def test_riepilogo_dettagli_adattatori(tmp_path: Path) -> None:
    p = tmp_path / "stato-rete.json"
    plc = {"casa": {"ip": "192.168.1.66", "scartati_tx_24h": 0, "scartati_rx_24h": 2,
                    "riavvii_24h": 1, "ultimo_riavvio_24h": 990,
                    "ultima_lettura": {"ts": 995, "stato": "ok"},
                    "ultimo_campione": {"ts": 995, "tx_pkt": 1, "rx_pkt": 2, "tx_drop": 0,
                                        "rx_drop": 2, "tx_byte": 3, "rx_byte": 4,
                                        "estraneo": 9}},
           "intruso": {"ip": "x"}}
    scrivi(p, 1000, plc=plc, calcolo_ms=101)
    r = leggi_riepilogo(p, adesso=1010)
    assert set(r["plc"]) == {"casa"} and r["calcolo_ms"] == 101
    casa = r["plc"]["casa"]
    assert casa["ultimo_riavvio_24h"] == 990 and casa["ultima_lettura"] == {"ts": 995, "stato": "ok"}
    assert "estraneo" not in casa["ultimo_campione"] and casa["ultimo_campione"]["rx_byte"] == 4


# ---------------------------------------------------------------- pagine

def test_pagina_principale_senza_scheda_dispositivo(tmp_path: Path) -> None:
    html = client(tmp_path).get("/").get_data(as_text=True)
    assert 'id="caricaCard"' in html and 'href="/dettagli"' in html
    for tolto in ("Dispositivo", 'id="wifiSignal"', 'id="temperature"', 'id="inputState"',
                  "secondary-metrics"):
        assert tolto not in html


def test_pagina_dettagli(tmp_path: Path) -> None:
    anonimo = create_app(replace(settings(tmp_path), raccolta_dir=tmp_path),
                         start_monitor=False).test_client()
    r = anonimo.get("/dettagli")
    assert r.status_code == 302 and "/login" in r.headers["Location"]

    html = client(tmp_path).get("/dettagli").get_data(as_text=True)
    for sezione in ("sezBasculante", "sezRicarica", "sezPowerline", "sezRaspberry"):
        assert f'id="{sezione}"' in html
    assert 'data-indirizzo="192.168.1.100"' in html and 'data-avviso="5"' in html
    for segreto in ("password", "secret", "token"):         # dai Settings di prova
        assert segreto not in html.lower()
