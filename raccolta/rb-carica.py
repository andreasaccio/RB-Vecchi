#!/usr/bin/env python3
# Campionatore, SOLA LETTURA: Shelly ricarica -> CSV giornaliero
import json, time, urllib.request

from giornaliero import Giornaliero

URL = "http://192.168.1.101/rpc/Shelly.GetStatus"
PASSO = 10

def riga():
    t = time.time()
    try:
        with urllib.request.urlopen(URL, timeout=4) as r:
            s = json.load(r)
        sw, sy, wf = s["switch:0"], s["sys"], s.get("wifi", {})
        return t, "%.0f,ok,%d,%d,%d,%.1f,%.1f,%.3f,%.3f,%.1f,%s,%s\n" % (
            t, sy["uptime"], sy.get("reset_reason", -1), int(sw["output"]),
            sw["apower"], sw["voltage"], sw["current"], sw["aenergy"]["total"],
            sw["temperature"]["tC"], wf.get("rssi", ""), wf.get("bssid", ""))
    except Exception as e:
        return t, "%.0f,KO,%s\n" % (t, type(e).__name__)

out = Giornaliero("rb-carica")
while True:
    out.scrivi(*riga())
    time.sleep(PASSO - time.time() % PASSO)
