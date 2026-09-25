# Scrittura dei CSV giornalieri comune ai raccoglitori (e a migra-dati.py).
# Un file per raccoglitore e per giorno, data LOCALE del campione nel nome,
# intestazione in testa a ogni file. I timestamp nelle righe sono epoch.
import os, time

DIR_PREDEFINITA = "/var/lib/rb-raccolta"

INTESTAZIONI = {
    "rb-carica": ("ts,stato,uptime,reset_reason,output,apower_W,voltage_V,"
                  "current_A,aenergy_Wh,temp_C,rssi,bssid\n"),
    "rb-plc": "ts,adatt,stato,tx_pkt,rx_pkt,tx_drop,rx_drop,tx_byte,rx_byte\n",
    "rb-link": "ts,host,stato\n",
}


def directory():
    return os.environ.get("RB_RACCOLTA_DIR") or DIR_PREDEFINITA


def giorno(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def percorso(nome, data, base=None):
    return os.path.join(base or directory(), "%s-%s.csv" % (nome, data))


class Giornaliero:
    """Apre il file del giorno del campione; al cambio di data passa al nuovo."""

    def __init__(self, nome, base=None):
        self.nome = nome
        self.base = base or directory()
        self.intestazione = INTESTAZIONI[nome]
        self._data = None
        self._f = None

    def scrivi(self, ts, riga):
        data = giorno(ts)
        if data != self._data:
            self.chiudi()
            os.makedirs(self.base, exist_ok=True)
            p = percorso(self.nome, data, self.base)
            self._f = open(p, "a", buffering=1)
            if self._f.tell() == 0:
                self._f.write(self.intestazione)
            self._data = data
        self._f.write(riga)

    def chiudi(self):
        if self._f is not None:
            self._f.close()
        self._f = None
        self._data = None
