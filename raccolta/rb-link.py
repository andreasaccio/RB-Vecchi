#!/usr/bin/env python3
# Logger di rete, SOLA LETTURA: ping -> CSV giornaliero ts,host,stato
# Ogni giro: un ping per host, timeout 1 s, stesso ts per tutto il giro.
# I ping del giro partono insieme: con più host KO il giro resta sotto 5 s.
# stato: ok (risposta), KO (nessuna risposta), ERR (ping non eseguibile,
# es. permessi: non è una misura e in analisi vale come dato mancante).
# Su ERR lo stderr di ping va nel journal: alla prima occorrenza, poi al
# massimo una volta all'ora.
import subprocess, sys, time

from giornaliero import Giornaliero

HOST = ["192.168.1.1", "192.168.1.66", "192.168.1.67",
        "192.168.1.100", "192.168.1.101"]
PASSO = 5
INTERVALLO_LOG = 3600

_ultimo_log = None


def registra_err(host, rc, err, adesso=None):
    global _ultimo_log
    adesso = time.monotonic() if adesso is None else adesso
    if _ultimo_log is not None and adesso - _ultimo_log < INTERVALLO_LOG:
        return False
    _ultimo_log = adesso
    testo = " | ".join(r.strip() for r in err.decode("utf-8", "replace").splitlines()
                       if r.strip())
    print("ping %s: esito %d, stato ERR: %s" % (host, rc, testo or "nessun messaggio"),
          file=sys.stderr, flush=True)
    return True


def giro():
    t = time.time()
    proc = [(h, subprocess.Popen(["ping", "-c1", "-W1", h],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.PIPE)) for h in HOST]
    righe = []
    for h, p in proc:
        _, err = p.communicate()
        rc = p.returncode
        stato = "ok" if rc == 0 else "KO" if rc == 1 else "ERR"
        if stato == "ERR":
            registra_err(h, rc, err or b"")
        righe.append("%.0f,%s,%s\n" % (t, h, stato))
    return t, righe


if __name__ == "__main__":
    out = Giornaliero("rb-link")
    while True:
        t, righe = giro()
        for r in righe:
            out.scrivi(t, r)
        time.sleep(PASSO - time.time() % PASSO)
