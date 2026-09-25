#!/usr/bin/env python3
# Logger di rete, SOLA LETTURA: ping -> CSV giornaliero ts,host,stato
# Ogni giro: un ping per host, timeout 1 s, stesso ts per tutto il giro.
# I ping del giro partono insieme: con più host KO il giro resta sotto 5 s.
# stato: ok (risposta), KO (nessuna risposta), ERR (ping non eseguibile,
# es. permessi: non è una misura e in analisi vale come dato mancante).
import subprocess, time

from giornaliero import Giornaliero

HOST = ["192.168.1.1", "192.168.1.66", "192.168.1.67",
        "192.168.1.100", "192.168.1.101"]
PASSO = 5

def giro():
    t = time.time()
    proc = [(h, subprocess.Popen(["ping", "-c1", "-W1", h],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)) for h in HOST]
    righe = []
    for h, p in proc:
        rc = p.wait()
        stato = "ok" if rc == 0 else "KO" if rc == 1 else "ERR"
        righe.append("%.0f,%s,%s\n" % (t, h, stato))
    return t, righe

out = Giornaliero("rb-link")
while True:
    t, righe = giro()
    for r in righe:
        out.scrivi(t, r)
    time.sleep(PASSO - time.time() % PASSO)
