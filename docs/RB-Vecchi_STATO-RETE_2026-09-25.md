# RB-Vecchi — Stato rete e impianto powerline

**Data:** 2026-09-25
**Scopo:** fotografia della rete dopo la sostituzione dei powerline.
Sostituisce di fatto la parte rete dei documenti del 2026-09-22, che restano
come storico e si riferiscono all'impianto TP-Link ormai rimosso.

**Legenda:** [M] misurato · [D] dedotto · [A] da accertare

---

## 1. Impianto powerline (D-Link)

Il 2026-09-24 i due adattatori TP-Link sono stati sostituiti da due
**D-Link DHP-W310AV** (HomePlug AV, hw A1) [M]:

| Ruolo  | IP           | Note                                   |
|--------|--------------|----------------------------------------|
| Casa   | 192.168.1.66 | firmware 1.03 (da schermata) [M/A]     |
| Garage | 192.168.1.67 | firmware 1.04 b01, 11 Dec 2013 [M]     |

MAC dell'adattatore garage [M]: LAN `b0:c5:54:d6:77:c7`,
Wi-Fi `b0:c5:54:d6:77:c8`, PLC `b0:c5:54:d6:77:c6`.

Il Raspberry è collegato al router via cavo: la sua connettività non dipende
dal powerline. L'unica tratta fragile è quella elettrica fra i due
adattatori [M].

## 2. Wi-Fi

Esiste un solo AP con SSID `Finanza`, quello integrato nell'adattatore
garage, BSSID `b0:c5:54:d6:77:c8`, canale 6, potenza radio al 50% [M].
Nessun altro AP porta questo SSID [M].

Client agganciati all'AP garage [M]:

| MAC                 | Dispositivo             |
|---------------------|-------------------------|
| 80:B5:4E:3B:22:8C   | Shelly basculante (.100)|
| DC:DA:0C:E1:2E:E8   | Shelly ricarica (.101)  |
| 7C:A7:B0:40:1D:3B   | telecamera Wi-Fi [D]    |

Nei log dell'AP compare a tratti `BA:58:45:39:C7:5C`, MAC ad
amministrazione locale (randomizzato): dispositivo transitorio, verosimilmente
un telefono [D].

L'AP dell'adattatore casa (.66) ha la radio accesa ma senza client. Vi è
stato attivato il filtro MAC con elenco vuoto per chiuderne l'accesso;
la modalità del filtro (consenti/blocca) va confermata [A].

**Conseguenza diagnostica:** l'RSSI dello Shelly misura solo il salto
dispositivo-AP, due metri nello stesso locale. Resta eccellente (-45/-50 dBm)
anche mentre la tratta powerline è interrotta. Il campo RSSI della dashboard
non è un indicatore di salute della catena [D].

## 3. Cosa espone l'interfaccia web dei D-Link

La velocità di sincronizzazione del powerline (PHY rate) **non** è esposta
dall'interfaccia web [M]. Sono disponibili solo, in `st_stats.php`, i
contatori cumulativi di pacchetti e byte, con i pacchetti scartati (Dropped),
suddivisi in LAN / Wi-Fi / PLC [M].

La pagina `st_stats.php` scrive i valori direttamente nell'HTML e non
richiede autenticazione: leggibile con un semplice GET [M].

Per la velocità reale del powerline servirà `open-plc-utils`, da installare
sul Raspberry quando si è sul posto [A].

## 4. Sicurezza — punti aperti

- `getcfg.php` restituisce l'intera configurazione **senza autenticazione**,
  password Wi-Fi in chiaro, PIN e password di gestione del PLC compresi.
  Falla nota di questo firmware; una password di amministrazione non la
  chiude. Chiunque sia sulla LAN può leggere la chiave del Wi-Fi [M].
- WPS abilitato sull'AP garage; da disattivare [M].
- Cifratura Wi-Fi in modalità mista `WPA+2PSK / TKIP+AES`; il TKIP è debole,
  preferibile WPA2 solo AES [M].
- Rete ospite `dlink_guest` (aperta) presente ma disattivata: ok [M].
- Lo Shelly del basculante accetta comandi con `auth_en: false`: chiunque
  sulla rete può comandare il relè (già noto, non introdotto dai D-Link) [M].

## 5. Orologio

Gli adattatori hanno l'orologio fermo (anno 2000), NTP non configurato [M].
Tutti i timestamp dei dati provengono dal Raspberry, mai dagli apparati [M].

## 6. Raccoglitori dati attivi

Tre processi indipendenti, tutti in sola lettura:

| Processo       | Cosa                          | Passo | File                    |
|----------------|-------------------------------|-------|-------------------------|
| rb-carica.py   | Shelly ricarica .101 (energia)| 10 s  | /var/tmp/rb-carica.csv  |
| rb-plc.py      | contatori PLC .66 e .67       | 120 s | /var/tmp/rb-plc.csv     |
| logger rete    | ping .1 .66 .67 .100 .101     | 5 s   | /var/tmp/rb-link.log    |

I tre raccoglitori girano come unità systemd transitorie (systemd-run, utente pi,
Restart=always): sopravvivono agli aggiornamenti e alla chiusura dei terminali,
non a un riavvio del Raspberry.

Il logger di rete contiene solo dati dal 2026-09-25 00:00 [M]. Buco di
registrazione il 25/09 dalle 06:33 alle 12:31: processo terminato durante gli
aggiornamenti automatici, non caduta di rete. In analisi l'assenza di righe è
un dato mancante, né ok né KO.

## 7. Prima osservazione (16 h)

Nelle prime ~16 ore i pacchetti scartati sono rimasti a **zero** su tutti i
contatori PLC di entrambi gli adattatori, e i contatori sono cresciuti senza
azzeramenti (nessun riavvio) [M]. Dato incoraggiante ma ancora breve: la
tenuta va confermata su più giorni.

## 8. Da accertare

- [A] PHY rate del powerline (open-plc-utils, sul posto)
- [A] `aenergy.total` dello Shelly sopravvive a un blackout (prova col
      magnetotermico a fine carica, sul posto)
- [A] profilo di potenza della prima carica → soglia carica/mantenimento
- [A] reservation DHCP per .66 .67 .100 .101 sul router
- [A] modalità del filtro MAC su .66
- [A] firmware effettivo di .66 (1.03 vs 1.04)
- [A] conferma che 7C:A7:B0:40:1D:3B è la telecamera
