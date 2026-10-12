import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "raccolta"))

import sessioni_carica  # noqa: E402
from giornaliero import INTESTAZIONI, giorno  # noqa: E402

UNA = datetime(2026, 10, 12, 1, 0, 0).timestamp()      # 01:00 locali del 12/10


def scrivi(base: Path, righe: list[str]) -> None:
    per_giorno: dict[str, list[str]] = {}
    for r in righe:
        per_giorno.setdefault(giorno(float(r.split(",")[0])), []).append(r)
    for g, rr in per_giorno.items():
        (base / f"rb-carica-{g}.csv").write_text(INTESTAZIONI["rb-carica"] + "\n".join(rr) + "\n")


class Shelly:
    """Campioni ogni 10 s con uptime e contatore coerenti."""

    def __init__(self, t: float, uptime: int = 1000, energia: float = 2000.0):
        self.t, self.uptime, self.energia, self.righe = t, uptime, energia, []

    def per(self, secondi: int, acceso: bool, potenza: float = 0.0) -> "Shelly":
        for _ in range(secondi // 10):
            p = potenza if acceso else 0.0
            self.energia += p * 10 / 3600
            self.righe.append(f"{self.t:.0f},ok,{self.uptime},1,{int(acceso)},{p:.1f},"
                              f"243.0,0.1,{self.energia:.3f},48.0,-50,aa:bb")
            self.t += 10
            self.uptime += 10
        return self

    def buco(self, secondi: int) -> "Shelly":
        for _ in range(secondi // 10):
            self.righe.append(f"{self.t:.0f},KO,URLError")
            self.t += 10
            self.uptime += 10
        return self

    def riavvio(self, uptime: int) -> "Shelly":
        self.uptime = uptime
        return self


def registro(tmp_path: Path, s: Shelly) -> list[dict]:
    scrivi(tmp_path, s.righe)
    return sessioni_carica.aggiorna(tmp_path, s.t)[0]["sessioni"]


def test_programma_carica_e_fine_carica(tmp_path: Path) -> None:
    s = Shelly(UNA - 600).per(600, False).per(1800, True, 860.0).per(600, True, 7.8).per(60, False)
    [v] = registro(tmp_path, s)
    assert (v["causa"], v["esito"], v["inizio"], v["inizio_approssimato"]) == (
        "programma", "fine_carica", int(UNA), False)
    assert (v["carica_da"], v["carica_a"]) == (int(UNA), int(UNA + 1790))
    assert v["fine"] == int(UNA + 2400) and v["potenza_max_W"] == 860.0
    assert 429 < v["energia_Wh"] < 432          # 860 W per 30 min più lo standby


def test_manuale_senza_carica(tmp_path: Path) -> None:
    s = Shelly(UNA + 14 * 3600).per(60, False).per(300, True, 1.3).per(60, False)
    [v] = registro(tmp_path, s)
    assert (v["causa"], v["esito"], v["carica_da"]) == ("manuale", "senza_carica", None)


def test_spenta_durante_la_carica_e_interrotta(tmp_path: Path) -> None:
    s = Shelly(UNA + 3600).per(60, False).per(600, True, 860.0).per(60, True, 7.8).per(60, False)
    assert registro(tmp_path, s)[0]["esito"] == "interrotta"


def test_ritorno_corrente_e_riavvio_durante_la_sessione(tmp_path: Path) -> None:
    s = Shelly(UNA + 3600).per(60, False).per(300, True, 860.0)
    s.riavvio(5).per(300, True, 7.8)
    nuova, vecchia = registro(tmp_path, s)
    assert (vecchia["causa"], vecchia["esito"]) == ("manuale", "riavvio")
    assert nuova["causa"] == "ritorno_corrente" and nuova["esito"] == "in_corso"
    assert nuova["inizio"] == vecchia["fine"] == int(UNA + 3600 + 360 - 5)


def test_accensione_in_un_buco_di_dati_e_approssimata(tmp_path: Path) -> None:
    s = Shelly(UNA - 900).per(300, False).buco(900).per(300, True, 860.0)
    [v] = registro(tmp_path, s)
    assert (v["causa"], v["inizio_approssimato"]) == ("programma", True)
    assert v["in_carica"] is True and v["fine"] is None


def test_gia_accesa_e_contatore_che_cala(tmp_path: Path) -> None:
    s = Shelly(UNA + 7200).per(300, True, 860.0)
    s.energia -= 5.0                        # contatore che torna indietro (riavvio)
    s.per(300, True, 860.0).per(60, False)
    [v] = registro(tmp_path, s)
    assert (v["causa"], v["inizio_approssimato"]) == ("gia_accesa", True)
    assert 138 < v["energia_Wh"] < 139.5    # 2 x 29 incrementi: il calo non toglie energia


def test_piu_recente_per_primo_e_limite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sessioni_carica, "MAX_SESSIONI", 3)
    s = Shelly(UNA + 3600)
    for _ in range(5):
        s.per(60, False).per(60, True, 1.3)
    s.per(60, False)
    vv = registro(tmp_path, s)
    assert len(vv) == 3 and vv[0]["inizio"] > vv[1]["inizio"] > vv[2]["inizio"]


def test_main_scrive_json_atomico(tmp_path: Path) -> None:
    s = Shelly(UNA - 60).per(60, False).per(120, True, 860.0)
    scrivi(tmp_path, s.righe)
    uscita = tmp_path / "carica-registro.json"
    assert sessioni_carica.main(["--dir", str(tmp_path), "--ora", str(s.t),
                                 "--uscita", str(uscita)]) == 0
    dati = json.loads(uscita.read_text())
    assert dati["generato"] == int(s.t) and dati["sessioni"][0]["causa"] == "programma"
    assert oct(os.stat(uscita).st_mode & 0o777) == "0o644"


# ---------------------------------------------------------------- motore incrementale

def consumi(tmp_path: Path, s: Shelly) -> dict:
    scrivi(tmp_path, s.righe)
    return sessioni_carica.aggiorna(tmp_path, s.t)[1]


def test_a_rate_come_in_un_colpo(tmp_path: Path) -> None:
    s = Shelly(UNA - 3600).per(3600, False).per(1800, True, 860.0).per(600, True, 7.8)
    s.per(600, False).buco(300).per(300, True, 1.3).per(60, False)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    scrivi(a, s.righe), scrivi(b, s.righe)
    for t in range(int(UNA - 3000), int(s.t), 997):     # un giro ogni ~17 min
        sessioni_carica.aggiorna(a, t)
    ra, ca = sessioni_carica.aggiorna(a, s.t)
    rb, cb = sessioni_carica.aggiorna(b, s.t)
    assert ra["sessioni"] == rb["sessioni"] and len(ra["sessioni"]) == 2
    assert ca["giorni"] == cb["giorni"] and ca["profilo"] == cb["profilo"]


def test_wh_per_giorno_e_letture(tmp_path: Path) -> None:
    s = Shelly(UNA - 3 * 3600, energia=1000.0).per(3600, True, 7.8)   # 22:00-23:00 dell'11
    s.per(7200, True, 860.0)                                             # 23:00-01:00
    c = consumi(tmp_path, s)
    (g1, wh1, prima1, ultima1), (g2, wh2, prima2, ultima2) = c["giorni"]
    assert (g1, g2) == ("2026-10-11", "2026-10-12")
    assert abs(wh1 - (7.8 * 3590 + 860 * 3600) / 3600) < 0.5     # il primo campione non ha incremento
    assert abs(wh2 - 860.0) < 0.5
    assert round(prima1) == 1000 and abs(ultima1 - prima2) < 2.5 and ultima2 == c["contatore"]["Wh"]


def test_profilo_dell_ultima_carica_resta_dopo_una_sessione_senza_carica(tmp_path: Path) -> None:
    s = Shelly(UNA - 60).per(60, False).per(300, True, 860.0).per(600, True, 7.8).per(60, False)
    s.per(600, False).per(300, True, 1.3).per(60, False)
    c = consumi(tmp_path, s)
    assert c["sessioni"][0]["esito"] == "senza_carica"
    p = c["profilo"]
    assert p["inizio"] == int(UNA) and p["passo"] == 60
    assert p["punti"][0] == [int(UNA), 860.0] and p["punti"][-1][1] == 7.8
    assert len(p["punti"]) == 15


def test_stato_corrotto_si_ricostruisce(tmp_path: Path) -> None:
    s = Shelly(UNA - 60).per(60, False).per(300, True, 860.0).per(60, False)
    scrivi(tmp_path, s.righe)
    (tmp_path / sessioni_carica.STATO).write_text("{rotto")
    registro, _ = sessioni_carica.aggiorna(tmp_path, s.t)
    assert registro["sessioni"][0]["causa"] == "programma"
    stato = json.loads((tmp_path / sessioni_carica.STATO).read_text())
    assert stato["versione"] == sessioni_carica.VERSIONE_STATO


def test_consumi_dal_bimestre_precedente(tmp_path: Path) -> None:
    agosto = datetime(2026, 8, 20, 15, 0).timestamp()
    settembre = datetime(2026, 9, 2, 15, 0).timestamp()
    s = Shelly(agosto).per(60, False).per(120, True, 1.3).per(60, False)
    s.t = settembre
    s.per(60, False).per(120, True, 1.3).per(60, False)
    s.t = UNA + 3600
    s.per(60, False)
    c = consumi(tmp_path, s)
    # 12/10: bimestre in corso settembre-ottobre, precedente luglio-agosto
    assert c["sessioni_dal"] == int(datetime(2026, 7, 1).timestamp())
    assert len(c["sessioni"]) == 2


def test_bimestre_precedente_a_cavallo_d_anno() -> None:
    gennaio = datetime(2027, 1, 15).timestamp()
    assert sessioni_carica.inizio_bimestre_precedente(gennaio) == datetime(2026, 11, 1).timestamp()
    marzo = datetime(2027, 3, 1, 0, 30).timestamp()
    assert sessioni_carica.inizio_bimestre_precedente(marzo) == datetime(2027, 1, 1).timestamp()


def test_archivio_potato(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sessioni_carica, "ARCHIVIO_GIORNI", 1)
    s = Shelly(UNA - 3 * 86400).per(60, False).per(120, True, 1.3).per(60, False)
    s.t = UNA
    s.per(60, False).per(120, True, 1.3).per(60, False)
    scrivi(tmp_path, s.righe)
    sessioni_carica.aggiorna(tmp_path, UNA - 3 * 86400 + 600)        # prima sessione nello stato
    _, c = sessioni_carica.aggiorna(tmp_path, s.t)
    stato = json.loads((tmp_path / sessioni_carica.STATO).read_text())
    assert len(stato["chiuse"]) == 1 and all(g >= "2026-10-11" for g in stato["giorni"])
