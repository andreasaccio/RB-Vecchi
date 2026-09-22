# RB-Vecchi · Dashboard garage

Applicazione per Raspberry Pi 4 con Raspberry Pi OS/Raspbian che:

- legge lo stato del basculante da `input:0` di uno Shelly 1 Gen3;
- registra su SQLite aperture, chiusure e durata delle aperture;
- invia un avviso Telegram quando il garage resta aperto oltre la soglia configurata;
- può inviare una notifica di rientro quando il garage viene richiuso;
- comanda `switch:0` con un breve impulso passo-passo;
- blocca automaticamente il comando se non riesce a verificare la modalità `detached`;
- offre una pagina responsive, protetta da login e adatta a Safari su iPhone;
- continua a funzionare automaticamente dopo il riavvio del Raspberry.

## 1. Configurazione indispensabile dello Shelly

Prima di attivare il comando remoto, verificare nell'interfaccia dello Shelly 1 Gen3:

1. **Input 0** configurato come tipo **Switch**, non come pulsante stateless.
2. **Input mode del relè** impostato su **Detached**: il contatto usato per rilevare il portone non deve comandare direttamente il relè.
3. **Initial state** del relè impostato su **Off**.
4. **Auto off** attivo, indicativamente tra 0,5 e 1 secondo. L'applicazione invia comunque anche il parametro `toggle_after` come ulteriore protezione.
5. Indirizzo IP riservato o statico: `192.168.1.100`.

Controllo rapido dello stato dell'ingresso:

```bash
curl -s "http://192.168.1.100/rpc/Input.GetStatus?id=0"
```

Risposta attesa:

```json
{"id":0,"state":false}
```

Se sullo Shelly è attiva l'autenticazione HTTP Digest:

```bash
curl --digest -u 'admin:PASSWORD' -s \
  "http://192.168.1.100/rpc/Input.GetStatus?id=0"
```

Verifica della modalità del relè:

```bash
curl -s "http://192.168.1.100/rpc/Switch.GetConfig?id=0"
```

Il campo `in_mode` deve risultare `detached`.

> Sicurezza: il comando è passo-passo. Quando il garage è chiuso, un impulso può avviare l'apertura; quando è aperto, può avviare la chiusura. La pagina chiede sempre conferma, ma non sostituisce fotocellule, coste sensibili e protezioni della centrale del basculante. Non pubblicare direttamente il servizio su Internet.

## 2. Preparazione Telegram

1. Creare un bot con **@BotFather** e conservare il token.
2. Aprire la chat con il nuovo bot e inviargli almeno un messaggio.
3. Recuperare il `chat.id` con:

```bash
curl -s "https://api.telegram.org/botTOKEN/getUpdates"
```

Nel risultato cercare una sezione simile a:

```json
"chat":{"id":123456789}
```

Token e chat ID vengono richiesti durante l'installazione. Possono anche essere lasciati vuoti e aggiunti in seguito.

## 3. Installazione sul Raspberry

Copiare la cartella `RB-Vecchi` sul Raspberry, entrare nella cartella ed eseguire:

```bash
chmod +x install.sh
sudo ./install.sh
```

Lo script:

- installa Python e crea un ambiente virtuale in `/opt/rb-vecchi`;
- crea l'utente di servizio non interattivo `rbvecchi`;
- salva il database in `/var/lib/rb-vecchi/garage.db`;
- crea la configurazione protetta `/etc/rb-vecchi.env`;
- installa e avvia il servizio systemd `rb-vecchi.service`.

Al termine mostra gli indirizzi utilizzabili, normalmente:

```text
http://RB-Vecchi.local:8080
```

oppure:

```text
http://INDIRIZZO-IP-RASPBERRY:8080
```

## 4. Verifica del servizio

```bash
sudo systemctl status rb-vecchi
sudo journalctl -u rb-vecchi -f
```

Verifica sintetica:

```bash
curl -s http://127.0.0.1:8080/healthz
```

Se lo Shelly è raggiungibile, il risultato contiene `"ok":true`.

## 5. Diagnostica rapida

```bash
sudo -u rbvecchi /opt/rb-vecchi/venv/bin/python \
  /opt/rb-vecchi/diagnose.py
```

Per provare anche Telegram:

```bash
sudo -u rbvecchi /opt/rb-vecchi/venv/bin/python \
  /opt/rb-vecchi/diagnose.py --telegram-test
```

## 6. Correzione stato aperto/chiuso

Il contatto magnetico può risultare normalmente aperto o normalmente chiuso. Se la pagina mostra lo stato contrario a quello reale, rieseguire la configurazione:

```bash
sudo /opt/rb-vecchi/venv/bin/python \
  /opt/rb-vecchi/configure.py --output /etc/rb-vecchi.env
sudo systemctl restart rb-vecchi
```

Alla domanda:

```text
Lo stato logico TRUE dell'input indica garage APERTO?
```

rispondere `n` per invertire la logica.

## 7. Parametri principali

La configurazione è in `/etc/rb-vecchi.env`.

| Variabile | Funzione | Valore predefinito |
|---|---|---:|
| `SHELLY_HOST` | IP o URL dello Shelly | `192.168.1.100` |
| `INPUT_TRUE_IS_OPEN` | Mappatura logica del sensore | `true` |
| `POLL_INTERVAL_SECONDS` | Frequenza di lettura | `2` |
| `GARAGE_OPEN_ALERT_SECONDS` | Ritardo allarme Telegram | `300` |
| `RELAY_PULSE_SECONDS` | Durata impulso relè | `0.7` |
| `REQUIRE_DETACHED_MODE` | Blocca il comando se il relè non è detached | `true` |
| `WEB_USERNAME` | Utente pagina web | `admin` |
| `WEB_PASSWORD` | Password pagina web | generata/configurata |
| `LISTEN_PORT` | Porta HTTP | `8080` |

Dopo modifiche manuali:

```bash
sudo systemctl restart rb-vecchi
```

## 8. Storico e backup

Lo storico è salvato in:

```text
/var/lib/rb-vecchi/garage.db
```

Backup coerente a servizio fermo:

```bash
sudo systemctl stop rb-vecchi
sudo cp /var/lib/rb-vecchi/garage.db /percorso/backup/garage-$(date +%F).db
sudo systemctl start rb-vecchi
```

## 9. Uso da iPhone

Aprire la pagina con Safari. Dal menu **Condividi** scegliere **Aggiungi alla schermata Home** per avere un'icona dedicata. La pagina è ottimizzata per schermi piccoli e rispetta le aree protette degli iPhone con notch o Dynamic Island.

Per l'accesso da fuori casa utilizzare una VPN, ad esempio WireGuard o OpenVPN. Evitare port forwarding diretto verso la porta 8080.

## 10. Aggiornamento del software

Dalla nuova cartella del pacchetto:

```bash
sudo ./update.sh
```

La configurazione e il database non vengono cancellati.

## Riferimenti API

- Shelly Gen2+ RPC: `https://shelly-api-docs.shelly.cloud/gen2/General/RPCChannels/`
- Shelly Input: `https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Input/`
- Shelly Switch: `https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Switch/`
- Telegram Bot API: `https://core.telegram.org/bots/api`
