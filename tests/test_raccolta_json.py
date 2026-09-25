import importlib.util
import json
import subprocess
import sys
from pathlib import Path

RACCOLTA = Path(__file__).resolve().parent.parent / "raccolta"
sys.path.insert(0, str(RACCOLTA))

import sistema  # noqa: E402
from giornaliero import scrivi_json_atomico  # noqa: E402


def carica_rb_carica():
    spec = importlib.util.spec_from_file_location("rb_carica", RACCOLTA / "rb-carica.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)  # il ciclo principale è sotto __main__
    return modulo


STATUS = {
    "switch:0": {"output": True, "apower": 412.34, "voltage": 231.27, "current": 1.8123,
                 "aenergy": {"total": 1234.5678}, "temperature": {"tC": 43.21}},
    "sys": {"uptime": 62137, "reset_reason": 3},
    "wifi": {"rssi": -50, "bssid": "b0:c5:54:d6:77:c8"},
}


# ---------------------------------------------------------------- rb-carica

def test_carica_riga_csv_invariata_e_campi_json() -> None:
    rb = carica_rb_carica()
    c, riga = rb.leggi(1790340000.4, chiama=lambda metodo: STATUS)
    assert riga == ("1790340000,ok,62137,3,1,412.3,231.3,1.812,1234.568,43.2,"
                    "-50,b0:c5:54:d6:77:c8\n")
    assert c == {"ts": 1790340000.4, "stato": "ok", "uptime": 62137, "reset_reason": 3,
                 "output": True, "apower_W": 412.34, "voltage_V": 231.27,
                 "current_A": 1.8123, "aenergy_Wh": 1234.5678, "temp_C": 43.21,
                 "rssi": -50, "bssid": "b0:c5:54:d6:77:c8"}


def test_carica_senza_wifi_e_ko() -> None:
    rb = carica_rb_carica()
    senza_wifi = {k: v for k, v in STATUS.items() if k != "wifi"}
    _, riga = rb.leggi(1.0, chiama=lambda m: senza_wifi)
    assert riga.endswith(",43.2,,\n")

    def giu(metodo):
        raise TimeoutError()
    c, riga = rb.leggi(2.0, chiama=giu)
    assert (c, riga) == ({"ts": 2.0, "stato": "KO", "errore": "TimeoutError"},
                         "2,KO,TimeoutError\n")

    rotto = json.loads(json.dumps(STATUS))
    rotto["sys"]["reset_reason"] = None                # %d fallisce: è un KO
    assert rb.leggi(3.0, chiama=lambda m: rotto)[0]["stato"] == "KO"


def test_carica_device_info_all_avvio_poi_ogni_6_ore() -> None:
    rb = carica_rb_carica()
    chiamate = []

    def chiama(metodo):
        chiamate.append(metodo)
        return {"model": "S3SW-001P16EU", "app": "S1PMG3", "ver": "2.0.1",
                "mac": "DCDA0CE12EE8", "auth_en": False}

    info = rb.InfoDispositivo(chiama)
    info.aggiorna(1000.0)
    info.aggiorna(1000.0 + 6 * 3600 - 1)
    assert chiamate == ["Shelly.GetDeviceInfo"]
    assert info.dati == {"modello": "S3SW-001P16EU", "app": "S1PMG3",
                         "firmware": "2.0.1", "info_ts": 1000.0}
    info.aggiorna(1000.0 + 6 * 3600)
    assert len(chiamate) == 2


def test_carica_device_info_fallito_riprova_fra_10_minuti() -> None:
    rb = carica_rb_carica()
    chiamate = []

    def giu(metodo):
        chiamate.append(metodo)
        raise OSError("rete")

    info = rb.InfoDispositivo(giu)
    info.aggiorna(1000.0)
    info.aggiorna(1000.0 + 599)
    info.aggiorna(1000.0 + 600)
    assert len(chiamate) == 2 and info.dati["modello"] is None


def test_carica_ultimo_json(tmp_path: Path) -> None:
    rb = carica_rb_carica()
    c, _ = rb.leggi(1790340000.0, chiama=lambda m: STATUS)
    p = tmp_path / "carica-ultimo.json"
    scrivi_json_atomico(p, rb.ultimo(c, {"modello": "S3SW-001P16EU", "firmware": "2.0.1"},
                                     1790340000.0, 1790340000.2))
    d = json.loads(p.read_text())
    assert d["apower_W"] == 412.34 and d["output"] is True
    assert (d["modello"], d["ultimo_ok"], d["generato"]) == ("S3SW-001P16EU", 1790340000.0, 1790340000.2)
    assert oct(p.stat().st_mode & 0o777) == "0o644"


# ---------------------------------------------------------------- sistema

SYSTEMCTL = ("ActiveState=active\nId=rb-vecchi.service\n\n"
             "Id=rb-carica.service\nActiveState=active\n\n"
             "Id=rb-plc.service\nActiveState=failed\n\n"
             "Id=rb-link.service\nActiveState=activating\n\n"
             "Id=rb-stato-rete.timer\nActiveState=active\n")


def radice_finta(base: Path) -> Path:
    (base / "proc").mkdir(parents=True)
    (base / "proc/loadavg").write_text("0.52 0.40 0.31 1/234 5678\n")
    (base / "proc/uptime").write_text("90061.23 350000.00\n")
    (base / "proc/meminfo").write_text("MemTotal:  3884000 kB\nMemFree: 1000000 kB\n"
                                       "MemAvailable:  2884000 kB\n")
    (base / "sys/class/thermal/thermal_zone0").mkdir(parents=True)
    (base / "sys/class/thermal/thermal_zone0/temp").write_text("48312\n")
    (base / "var/run").mkdir(parents=True)
    return base


def test_sistema_letture_locali(tmp_path: Path) -> None:
    radice = radice_finta(tmp_path)
    esegui = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, SYSTEMCTL, "")  # noqa: E731
    d = sistema.raccogli(str(radice), esegui, adesso=1000)
    assert d["generato"] == 1000
    assert d["carico"] == {"1min": 0.52, "5min": 0.40, "15min": 0.31}
    assert d["temperatura_cpu_C"] == 48.3
    assert d["memoria"] == {"usata_B": 1000000 * 1024, "totale_B": 3884000 * 1024}
    assert d["uptime_s"] == 90061
    assert d["riavvio_richiesto"] is False
    assert d["disco_radice"]["totale_B"] > 0
    assert d["unita"] == {"rb-vecchi.service": "active", "rb-carica.service": "active",
                          "rb-plc.service": "failed", "rb-link.service": "activating",
                          "rb-stato-rete.timer": "active"}

    (radice / "var/run/reboot-required").write_text("*** System restart required ***\n")
    assert sistema.raccogli(str(radice), esegui)["riavvio_richiesto"] is True


def test_sistema_dati_assenti_e_systemctl_fallito(tmp_path: Path) -> None:
    def rotto(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 5)
    d = sistema.raccogli(str(tmp_path), rotto)
    assert d["carico"] is None and d["temperatura_cpu_C"] is None
    assert d["memoria"] is None and d["uptime_s"] is None
    assert set(d["unita"].values()) == {None}


def test_sistema_main_scrive_json(tmp_path: Path) -> None:
    radice = radice_finta(tmp_path / "r")
    uscita = tmp_path / "sistema.json"
    assert sistema.main(["--uscita", str(uscita), "--radice", str(radice)]) == 0
    assert json.loads(uscita.read_text())["uptime_s"] == 90061
