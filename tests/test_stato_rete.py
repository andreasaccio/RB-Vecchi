import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "raccolta"))

import stato_rete  # noqa: E402
from giornaliero import INTESTAZIONI, giorno  # noqa: E402

T0 = 1790287200.0  # 25/09/2026 00:00 CEST


def scrivi(base: Path, nome: str, righe: list[str]) -> None:
    per_giorno: dict[str, list[str]] = {}
    for r in righe:
        per_giorno.setdefault(giorno(float(r.split(",")[0])), []).append(r)
    for g, rr in per_giorno.items():
        (base / f"{nome}-{g}.csv").write_text(INTESTAZIONI[nome] + "\n".join(rr) + "\n")


def giri(host: str, stati: str, da: float) -> list[str]:
    return [f"{da + 5 * i:.0f},{host},{'ok' if s == '.' else 'KO'}"
            for i, s in enumerate(stati)]


def link(base: Path, fine: float) -> dict:
    righe, scartate = stato_rete.leggi(base, "rb-link", T0, fine, 3)
    assert scartate == 0
    return stato_rete.analizza_link(righe, T0, fine)


def test_ko_singolo_contro_episodio(tmp_path: Path) -> None:
    scrivi(tmp_path, "rb-link",
           giri("192.168.1.1", "..X...XXX..", T0)
           + giri("192.168.1.100", "...........", T0))
    esito = link(tmp_path, T0 + 50)

    n = esito["nodi"]["192.168.1.1"]
    assert (n["ok"], n["KO"], n["isolate"]) == (7, 4, 1)
    assert len(n["episodi"]) == 1
    e = n["episodi"][0]
    assert (e["da"], e["a"], e["giri"], e["bordo"]) == (T0 + 30, T0 + 40, 3, None)
    assert esito["nodi"]["192.168.1.100"]["KO"] == 0
    assert esito["buchi"] == []


def test_buco_di_dati_non_conta_ne_ok_ne_ko(tmp_path: Path) -> None:
    # KO, poi 10 minuti senza righe, poi KO: non sono giri consecutivi.
    prima = giri("192.168.1.100", "..X", T0)
    dopo = giri("192.168.1.100", "X..", T0 + 10 + 600)
    scrivi(tmp_path, "rb-link", prima + dopo)
    esito = link(tmp_path, T0 + 625)

    assert esito["buchi"] == [(T0 + 10, T0 + 610)]
    n = esito["nodi"]["192.168.1.100"]
    assert (n["ok"], n["KO"], n["isolate"], n["episodi"]) == (4, 2, 2, [])


def test_err_e_bordo_finestra_sono_dati_mancanti(tmp_path: Path) -> None:
    righe = giri("192.168.1.1", "....", T0) + [
        f"{T0 + 20 + 5 * i:.0f},192.168.1.1,ERR" for i in range(20)]
    scrivi(tmp_path, "rb-link", righe)
    esito = link(tmp_path, T0 + 3600)

    assert esito["err"] == 20
    assert esito["nodi"]["192.168.1.1"]["ok"] == 4
    assert esito["buchi"] == [(T0 + 15, T0 + 3600)]


def test_episodio_chiuso_da_dati_mancanti(tmp_path: Path) -> None:
    scrivi(tmp_path, "rb-link", giri("192.168.1.67", "..XXX", T0))
    e = link(tmp_path, T0 + 3600)["nodi"]["192.168.1.67"]["episodi"]
    assert len(e) == 1 and e[0]["bordo"] == "dati mancanti"


def plc(tmp_path: Path, righe: list[str], fine: float) -> dict:
    scrivi(tmp_path, "rb-plc", righe)
    r, _ = stato_rete.leggi(tmp_path, "rb-plc", T0, fine, 3)
    return stato_rete.analizza_plc(r, T0, fine)


def test_riavvio_adattatore_riparte_dal_nuovo_valore(tmp_path: Path) -> None:
    a = plc(tmp_path, [
        f"{T0:.0f},casa,ok,1000,2000,5,7,100000,200000",
        f"{T0 + 120:.0f},casa,ok,1100,2100,6,7,110000,210000",
        f"{T0 + 240:.0f},casa,KO,URLError",
        f"{T0 + 360:.0f},casa,ok,40,50,0,1,4000,5000",       # riavvio
        f"{T0 + 480:.0f},casa,ok,140,150,2,1,14000,15000",
    ], T0 + 480)["casa"]

    assert a["riavvii"] == [T0 + 360]
    assert (a["ok"], a["KO"], a["azzeramenti"]) == (4, 1, [])
    assert a["incrementi"] == {"tx_pkt": 200, "rx_pkt": 200, "tx_drop": 3,
                               "rx_drop": 0, "tx_byte": 20000, "rx_byte": 20000}


def test_contatore_azzerato_da_solo(tmp_path: Path) -> None:
    a = plc(tmp_path, [
        f"{T0:.0f},garage,ok,1000,2000,0,0,4294960000,200000",
        f"{T0 + 120:.0f},garage,ok,1100,2100,0,4,3000,210000",  # tx_byte azzerato
        f"{T0 + 240:.0f},garage,ok,1200,2200,0,4,13000,220000",
    ], T0 + 240)["garage"]

    assert a["riavvii"] == []
    assert a["azzeramenti"] == [(T0 + 120, "tx_byte")]
    assert a["incrementi"]["tx_byte"] == 10000
    assert a["incrementi"]["tx_pkt"] == 200
    assert a["incrementi"]["rx_drop"] == 4


def test_buco_plc_e_simmetria_informativa(tmp_path: Path) -> None:
    r = plc(tmp_path, [
        f"{T0:.0f},casa,ok,0,0,0,0,0,0",
        f"{T0:.0f},garage,ok,0,0,0,0,0,0",
        f"{T0 + 3600:.0f},casa,ok,356063,300,0,0,61980000,1000",
        f"{T0 + 3600:.0f},garage,ok,310,367665,0,0,1100,74410000",
    ], T0 + 3600)
    assert r["casa"]["buchi"] == [(T0, T0 + 3600)]
    coppie = dict((d, (tx, rx)) for d, tx, rx in stato_rete.simmetria(r))
    assert coppie["casa tx -> garage rx, pacchetti"] == (356063, 367665)


def test_righe_non_conformi_e_file_di_due_giorni(tmp_path: Path) -> None:
    ieri = T0 - 10
    scrivi(tmp_path, "rb-link", [f"{ieri:.0f},192.168.1.1,ok", f"{T0:.0f},192.168.1.1,ok"])
    with open(tmp_path / f"rb-link-{giorno(T0)}.csv", "a") as f:
        f.write("spazzatura\n1790287205,192.168.1.1\n")
    righe, scartate = stato_rete.leggi(tmp_path, "rb-link", ieri - 1, T0 + 10, 3)
    assert [r[0] for r in righe] == [ieri, T0]
    assert scartate == 2


def test_main_stampa_rapporto(tmp_path: Path, capsys) -> None:
    scrivi(tmp_path, "rb-link", giri("192.168.1.1", ".XX.", T0))
    scrivi(tmp_path, "rb-plc", [f"{T0:.0f},casa,ok,1,1,0,0,1,1",
                                f"{T0:.0f},garage,ok,1,1,0,0,1,1"])
    assert stato_rete.main(["--dir", str(tmp_path), "--ora", str(T0 + 60),
                            "--finestra", "24h"]) == 0
    out = capsys.readouterr().out
    assert "Ultime 24 ore" in out
    assert "episodi KO" in out
    assert "informativa" in out


# ---------------------------------------------------------------- riepilogo --json

import json  # noqa: E402
import os  # noqa: E402

TUTTI = ["192.168.1.1", "192.168.1.66", "192.168.1.67", "192.168.1.100", "192.168.1.101"]
SIMBOLI = {".": "ok", "X": "KO", "E": "ERR"}


def rete(base: Path, stati: dict[str, str], n: int, plc_righe: list[str] | None = None) -> float:
    """n giri da T0 per tutti i nodi (ok salvo diversa indicazione); restituisce
    l'istante 2 s dopo l'ultimo giro."""
    righe = [f"{T0 + 5 * i:.0f},{h},{SIMBOLI[stati.get(h, '.' * n)[i]]}"
             for i in range(n) for h in TUTTI]
    scrivi(base, "rb-link", righe)
    scrivi(base, "rb-plc", plc_righe if plc_righe is not None else [
        f"{T0:.0f},casa,ok,100,100,0,0,1000,1000",
        f"{T0:.0f},garage,ok,100,100,0,0,1000,1000",
        f"{T0 + 120:.0f},casa,ok,200,200,0,0,2000,2000",
        f"{T0 + 120:.0f},garage,ok,200,200,0,0,2000,2000",
    ])
    return T0 + 5 * (n - 1) + 2


def test_riepilogo_stabile(tmp_path: Path) -> None:
    r = stato_rete.riepilogo(tmp_path, rete(tmp_path, {}, 30))
    assert r["stato"] == "stabile"
    assert r["garage"]["disponibilita_24h"] == 100.0
    assert r["garage"]["episodi_24h"] == 0 and r["garage"]["ultimo_episodio"] is None
    assert (r["scartati_plc_24h"], r["riavvii_24h"]) == (0, 0)
    assert r["generato"] == int(T0 + 147) and r["ultimo_giro"] == int(T0 + 145)


def test_riepilogo_instabile_per_episodio(tmp_path: Path) -> None:
    adesso = rete(tmp_path, {"192.168.1.67": "....XXX" + "." * 23}, 30)
    r = stato_rete.riepilogo(tmp_path, adesso)
    assert r["stato"] == "instabile" and "1 episodio KO sul .67" in r["motivo"]
    assert r["garage"]["ultimo_episodio"] == {
        "inizio": int(T0 + 20), "durata_s": 15, "giri": 3, "in_corso": False}
    assert r["garage"]["disponibilita_24h"] == 90.0


def test_riepilogo_instabile_per_scartati_e_riavvio(tmp_path: Path) -> None:
    plc_righe = [
        f"{T0:.0f},casa,ok,100,100,0,0,1000,1000",
        f"{T0 + 120:.0f},casa,ok,200,200,3,1,2000,2000",
        f"{T0:.0f},garage,ok,100,100,0,0,1000,1000",
        f"{T0 + 120:.0f},garage,ok,5,5,0,0,50,50",          # riavvio
    ]
    r = stato_rete.riepilogo(tmp_path, rete(tmp_path, {}, 30, plc_righe))
    assert r["stato"] == "instabile"
    assert "4 pacchetti PLC scartati" in r["motivo"] and "1 riavvio" in r["motivo"]
    assert r["plc"]["casa"] == {"scartati_tx_24h": 3, "scartati_rx_24h": 1, "riavvii_24h": 0}
    assert r["plc"]["garage"]["riavvii_24h"] == 1


def test_riepilogo_soglia_perdite_isolate(tmp_path: Path) -> None:
    venti = ".X" * 20 + "...."
    r = stato_rete.riepilogo(tmp_path, rete(tmp_path, {"192.168.1.67": venti}, len(venti)))
    assert r["garage"]["perdite_isolate_24h"] == 20 and r["stato"] == "stabile"

    ventuno = ".X" * 21 + "...."
    r = stato_rete.riepilogo(tmp_path, rete(tmp_path, {"192.168.1.67": ventuno}, len(ventuno)))
    assert r["stato"] == "instabile" and "21 perdite isolate" in r["motivo"]


def test_riepilogo_interrotta_lato_garage(tmp_path: Path) -> None:
    adesso = rete(tmp_path, {"192.168.1.67": "." * 27 + "XXX"}, 30)
    r = stato_rete.riepilogo(tmp_path, adesso)
    assert r["stato"] == "interrotta"
    assert "non risponde da 3 giri" in r["motivo"] and "(.66) sì" in r["motivo"]
    assert r["garage"]["ultimo_episodio"]["in_corso"] is True


def test_riepilogo_interrotta_lato_casa(tmp_path: Path) -> None:
    adesso = rete(tmp_path, {"192.168.1.66": "." * 28 + "XX",
                             "192.168.1.67": "." * 28 + "XX"}, 30)
    r = stato_rete.riepilogo(tmp_path, adesso)
    assert r["stato"] == "interrotta" and r["motivo"].startswith("lato casa")


def test_riepilogo_un_solo_ko_non_basta_per_interrotta(tmp_path: Path) -> None:
    adesso = rete(tmp_path, {"192.168.1.67": "." * 29 + "X"}, 30)
    assert stato_rete.riepilogo(tmp_path, adesso)["stato"] == "stabile"


def test_riepilogo_non_disponibile(tmp_path: Path) -> None:
    adesso = rete(tmp_path, {}, 30)
    r = stato_rete.riepilogo(tmp_path, adesso + 200)          # dati fermi da > 2 min
    assert r["stato"] == "non_disponibile" and "fermi da" in r["motivo"]

    rete(tmp_path, {"192.168.1.1": "." * 29 + "E"}, 30)       # ultimo giro con ERR
    r = stato_rete.riepilogo(tmp_path, adesso)
    assert r["stato"] == "non_disponibile" and "ERR" in r["motivo"]

    vuota = tmp_path / "vuota"
    vuota.mkdir()
    r = stato_rete.riepilogo(vuota, adesso)
    assert r["stato"] == "non_disponibile" and r["garage"] is None


def test_json_scritto_in_modo_atomico(tmp_path: Path) -> None:
    adesso = rete(tmp_path, {}, 30)
    uscita = tmp_path / "stato-rete.json"
    assert stato_rete.main(["--dir", str(tmp_path), "--ora", str(adesso),
                            "--json", "--uscita", str(uscita)]) == 0
    assert json.loads(uscita.read_text())["stato"] == "stabile"
    assert oct(os.stat(uscita).st_mode & 0o777) == "0o644"
    assert not [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]
