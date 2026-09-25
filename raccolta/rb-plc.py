#!/usr/bin/env python3
# Campionatore PLC D-Link, SOLA LETTURA: st_stats.php -> CSV giornaliero
import re, time, urllib.request

from giornaliero import Giornaliero

ADATT = [("casa", "192.168.1.66"), ("garage", "192.168.1.67")]
PASSO = 120

def riga(nome, ip):
    t = time.time()
    try:
        with urllib.request.urlopen("http://%s/st_stats.php" % ip, timeout=5) as r:
            html = r.read().decode("utf-8", "replace")
        v = re.findall(r'<td align="left">(\d+)</td>', html)
        if len(v) < 18:
            return t, "%.0f,%s,KO,pochi_valori_%d\n" % (t, nome, len(v))
        plc = v[12:18]  # tx_pkt,rx_pkt,tx_drop,rx_drop,tx_byte,rx_byte
        return t, "%.0f,%s,ok,%s\n" % (t, nome, ",".join(plc))
    except Exception as e:
        return t, "%.0f,%s,KO,%s\n" % (t, nome, type(e).__name__)

out = Giornaliero("rb-plc")
while True:
    for nome, ip in ADATT:
        out.scrivi(*riga(nome, ip))
    time.sleep(PASSO - time.time() % PASSO)
