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
