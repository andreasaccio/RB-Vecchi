import importlib.util
import sys
from pathlib import Path

RACCOLTA = Path(__file__).resolve().parent.parent / "raccolta"
sys.path.insert(0, str(RACCOLTA))


def carica_rb_link():
    spec = importlib.util.spec_from_file_location("rb_link", RACCOLTA / "rb-link.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)  # il ciclo principale è sotto __main__
    return modulo


class PingFinto:
    ESITI = {"192.168.1.1": (0, b""), "192.168.1.66": (1, b""),
             "192.168.1.67": (2, b"ping: socket: Operation not permitted\n"
                                 b"ping: => missing cap_net_raw+p capability or setuid?\n")}

    def __init__(self, argv, **_):
        self.returncode, self._err = self.ESITI.get(argv[-1], (0, b""))

    def communicate(self):
        return None, self._err


def test_giro_ok_ko_err_e_stderr_nel_journal(monkeypatch, capsys) -> None:
    rb_link = carica_rb_link()
    monkeypatch.setattr(rb_link, "HOST", list(PingFinto.ESITI))
    monkeypatch.setattr(rb_link.subprocess, "Popen", PingFinto)

    t, righe = rb_link.giro()
    stati = [r.strip().split(",")[1:] for r in righe]
    assert stati == [["192.168.1.1", "ok"], ["192.168.1.66", "KO"], ["192.168.1.67", "ERR"]]
    assert len({r.split(",")[0] for r in righe}) == 1   # stesso ts per il giro

    err = capsys.readouterr().err
    assert "192.168.1.67" in err and "esito 2" in err
    assert "missing cap_net_raw+p" in err

    rb_link.giro()                                     # stesso ERR al giro dopo
    assert capsys.readouterr().err == ""


def test_stderr_al_massimo_una_volta_all_ora(capsys) -> None:
    rb_link = carica_rb_link()
    assert rb_link.registra_err("h", 2, b"primo", adesso=1000.0)
    assert not rb_link.registra_err("h", 2, b"x", adesso=1000.0 + 3599)
    assert rb_link.registra_err("h", 2, b"dopo un'ora", adesso=1000.0 + 3600)
    assert not rb_link.registra_err("h", 2, b"x", adesso=1000.0 + 3700)
    err = capsys.readouterr().err.splitlines()
    assert len(err) == 2 and "primo" in err[0] and "dopo un'ora" in err[1]
