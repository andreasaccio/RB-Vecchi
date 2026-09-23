# RB-Vecchi - Handoff tecnico

**Data:** 22 settembre 2026  
**Referente:** Andrea Sarti  
**Progetto:** monitoraggio e comando del basculante del garage, con notifiche Telegram e interfaccia web; estensione richiesta per contabilizzare la ricarica del quadriciclo elettrico.  
**Ultima release recuperata:** `RB-Vecchi-v1.0.0.zip`, consegnata il 24 luglio 2026.

> Questo documento distingue la configurazione prevista dal pacchetto dalla configurazione realmente impostata sul Raspberry. I valori predefiniti non dimostrano quali valori siano oggi in produzione. Dove il dato non emerge dalle conversazioni recuperate o dai sorgenti originali, è riportato **non documentato**.

## Fonti e significato delle indicazioni

**[C1]** Conversazione RB-Vecchi del 24 luglio 2026: requisiti, consegna della v1.0.0, conferma dell'utente di avere installato il progetto, giudizio «bello e funzionale» e Telegram non configurato durante l'installazione.

**[C2]** Conversazione del 27 luglio 2026: richiesta di provare l'invio Telegram e istruzioni per il test. Conferma della ricezione: **non documentato**.

**[C3]** Conversazione del 22 settembre 2026 sulla contabilizzazione della ricarica del quadriciclo nel garage gestito da RB-Vecchi.

**[S]** Sorgenti e README del pacchetto originale recuperato dalla Library. Il relativo file `.sha256` è stato verificato con esito positivo. I riferimenti `file:funzione` nel documento puntano a questo pacchetto, non a una ricostruzione del codice.

**[V]** Verifiche svolte il 22 settembre 2026 per questo handoff, in ambiente separato: lettura dei sorgenti, verifica della sintassi, quattro test originali e controlli simulati di persistenza. Non sono stati contattati lo Shelly reale o Telegram, né è stato azionato il portone.

```text
Archivio: RB-Vecchi-v1.0.0.zip
SHA-256: db0a160bdfaf6d4010e8778efe081639a33cffe48fd0ede02565d85741290eaf
```

**Perimetro:** RB-Vecchi non è Camper Hub/LeoRaspy. Modello Raspberry, indirizzi, utenti di servizio, firmware, token e impostazioni degli altri progetti non vanno trasferiti automaticamente a questo ambiente.

## 1. Scopo del progetto e stato attuale

### 1.1 Funzione principale

Il progetto deve leggere lo stato del basculante dal contatto collegato allo Shelly, registrare aperture e chiusure con le rispettive durate, avvisare via Telegram quando rimane aperto per cinque minuti e permettere l'invio di un impulso passo-passo da una pagina utilizzabile su iPhone. [C1]

La v1.0.0 realizza una catena locale:

```text
Contatto portone -> input:0 Shelly -> polling Raspberry -> SQLite
                                                      -> dashboard web
                                                      -> notifiche Telegram

Browser autenticato -> POST impulso -> Raspberry -> switch:0 Shelly
```

### 1.2 Stato verificabile

| Componente | Stato documentato |
|---|---|
| Installazione | Il 24 luglio l'utente dichiara il progetto installato e lo descrive come «bello e funzionale». [C1] |
| Applicazione consegnata | v1.0.0 con Flask, SQLite, Gunicorn, systemd, dashboard, login, diagnostica e configuratore. [S] |
| Lettura e storico | Implementati nei sorgenti. La conferma generale dell'utente non sostituisce un verbale di collaudo di ogni funzione. |
| Comando impulsivo | Implementato con controllo della modalità Detached. Esito specifico di una prova sul motore: **non documentato**. |
| Telegram | Implementato. Non configurato durante la prima installazione; in seguito sono state fornite istruzioni e richiesto un test. Ricezione effettiva e configurazione finale: **non documentato**. |
| Persistenza allarme | Implementata in SQLite; verificata anche con riavvii simulati in questo handoff. [V] |
| Release successiva alla v1.0.0 | **non documentato**. Non è provato che i file oggi sul Raspberry coincidano ancora con lo ZIP recuperato. |
| Contabilizzazione ricarica | Richiesta il 22 settembre. Non presente nei sorgenti della v1.0.0. [C3, S] |

Non sono stati recuperati un export corrente di `/etc/rb-vecchi.env`, una copia del database di produzione o un elenco dei pacchetti effettivamente installati sul Raspberry. Lo stato operativo odierno del servizio è **non documentato** oltre alla conferma storica dell'installazione.

## 2. Hardware, firmware e cablaggio

### 2.1 Inventario

| Voce | Dato |
|---|---|
| Raspberry | **Raspberry Pi 4**. [C1] |
| RAM, revisione della scheda, alimentatore, microSD/SSD | **non documentato** |
| Sistema operativo | Raspbian / Raspberry Pi OS; release, architettura e versione Python installata: **non documentato** |
| Nome effettivo del sistema e IP del Raspberry | **non documentato**. `RB-Vecchi.local:8080` è un indirizzo esemplificativo del README, non la prova di un hostname configurato. |
| Modulo del portone | **Shelly 1 Gen3**, non Shelly 1PM Gen3. [C1, S] |
| Codice hardware/SKU, MAC, seriale | **non documentato** |
| IP Shelly | **192.168.1.100**, indicato nel progetto e usato come default. [C1, S] |
| Generazione | Gen3; integrazione attraverso API RPC della famiglia Gen2+. |
| Firmware installato, build, canale e data aggiornamento | **non documentato**. Non dedurre la versione da altri Shelly di Andrea. |
| Motore e centrale del basculante | Marca, modello e morsettiera: **non documentato** |
| Sensore sul portone | Modello e natura fisica effettiva, magnetico/meccanico/fine corsa: **non documentato** |

### 2.2 Comando della centrale

Il controllo software è un **impulso sul canale `switch:0`**, con `SHELLY_SWITCH_ID=0` nel pacchetto. La durata predefinita è **0,7 secondi**, configurabile tramite `RELAY_PULSE_SECONDS`. Il comando è passo-passo: non esistono due uscite separate per apertura e chiusura. [S: `shelly.py:pulse_relay`, `.env.example`]

Il collegamento fisico fra relè e centrale, i morsetti utilizzati, l'eventuale parallelo con un pulsante, tensioni e alimentazione dello Shelly sono **non documentato**. Non è disponibile uno schema elettrico verificato. Non descrivere il relè come se alimentasse direttamente il motore: il dato documentato è il comando passo-passo.

Un esito positivo dell'API significa che la richiesta di impulso ha ricevuto una risposta positiva; **non certifica l'effettiva apertura o chiusura del portone**. La posizione va riletta dal sensore.

### 2.3 Ingresso del contatto

Il contatto viene letto da **`input:0`**, con `SHELLY_INPUT_ID=0`. La corrispondenza è parametrica:

```python
garage_open = raw_input_state if INPUT_TRUE_IS_OPEN else not raw_input_state
```

`INPUT_TRUE_IS_OPEN=true` è il default del pacchetto, **non una conferma della polarità reale**.

| Dettaglio del contatto | Stato |
|---|---|
| Ingresso logico utilizzato | `input:0` |
| Contatto normalmente aperto (NA) o normalmente chiuso (NC) | **non documentato** |
| Valore letto a portone fisicamente chiuso | **non documentato** |
| Valore letto a portone fisicamente aperto | **non documentato** |
| Morsetti e riferimenti elettrici del contatto | **non documentato** |
| Inversione eventualmente configurata sullo Shelly | **non documentato** |
| Filtri antirimbalzo esterni o configurazione fisica di debounce | **non documentato** |

Il README prescrive **Input 0 di tipo Switch**, per ottenere uno stato digitale, e **`in_mode=detached` sul componente Switch del relè**, per evitare che il contatto di rilevazione azioni direttamente l'uscita. Tipo dell'ingresso e modalità del relè sono impostazioni distinte.

Prescrive inoltre `Initial state=Off` e Auto off indicativamente fra 0,5 e 1 secondo. Queste sono istruzioni consegnate, non un dump delle impostazioni reali. [S: `README.md`, sezione 1]

## 3. Integrazione Shelly

### 3.1 Endpoint realmente presenti

Base URL predefinito: `http://192.168.1.100`.

| Metodo e percorso | Utilizzo |
|---|---|
| `GET /rpc/Shelly.GetStatus` | Lettura periodica del monitor e diagnostica. |
| `GET /rpc/Switch.GetConfig?id=0` | Controllo configurazione del relè: `in_mode`, `auto_off`, `initial_state`. |
| `POST /rpc/Switch.Set` | Invio impulso. |
| `GET /rpc/Input.GetStatus?id=0` | Comando diagnostico manuale nel README; **non** è l'endpoint usato dal ciclo principale. |

Corpo JSON effettivo dell'impulso, con i default:

```json
{"id": 0, "on": true, "toggle_after": 0.7, "tag": "rb-vecchi"}
```

Il client usa `requests.Session`. Se `SHELLY_PASSWORD` è valorizzata, configura `HTTPDigestAuth`, con utente predefinito `admin`; altrimenti non imposta autenticazione. Password e stato effettivo dell'autenticazione sul dispositivo: **non documentato**. [S: `shelly.py`]

### 3.2 Stato e temporizzazioni

La posizione proviene esclusivamente da `payload["input:0"]["state"]`, non da `switch:0.output`. Quest'ultimo rappresenta lo stato del relè e viene mostrato separatamente.

Vengono raccolti anche RSSI Wi-Fi, uptime, temperatura del componente Switch quando presente e un campo denominato `firmware`. Il significato di quest'ultimo contiene un limite descritto nella sezione 10.

| Parametro | Default v1.0.0 |
|---|---:|
| `POLL_INTERVAL_SECONDS` | 2,0 s |
| `SHELLY_TIMEOUT_SECONDS` | 4,0 s per richiesta |
| Verifica `Switch.GetConfig` | Ogni 300 s, intervallo codificato nel monitor |
| `RELAY_PULSE_SECONDS` | 0,7 s |
| `COMMAND_COOLDOWN_SECONDS` | 3,0 s |
| `REQUIRE_DETACHED_MODE` | `true` |

Il polling avviene in un thread `garage-monitor`, indipendente dal fatto che un browser sia aperto. L'attesa è calcolata sottraendo il tempo già trascorso nel ciclo e mantenendo almeno 0,1 s di pausa. I due secondi sono quindi un obiettivo, non una garanzia in presenza di timeout o operazioni lente. [S: `monitor.py:_run`]

**Webhook/actions:** nessun endpoint ricevente o sottoscrizione eventi Shelly è implementato; il progetto usa polling HTTP. Eventuali actions/webhook configurati manualmente sul dispositivo reale: **non documentato**. MQTT, WebSocket e cloud Shelly non sono usati da questi sorgenti.

### 3.3 Controlli prima dell'impulso

Il backend rifiuta l'impulso se lo snapshot è offline, se non è trascorso il cooldown oppure se Detached è richiesto ma non risulta verificato. La pagina aggiunge una conferma esplicita e il controllo CSRF. [S: `monitor.py:pulse`, `web.py:api_pulse`]

La verifica di Detached usa **l'ultima configurazione letta**, non una nuova richiesta ad ogni comando. Una configurazione non Detached blocca il comando; Auto off disattivato e Initial state diverso da Off producono avvertimenti, ma non costituiscono da soli ulteriori blocchi nell'implementazione.

La verifica fallita di `Switch.GetConfig` azzera `switch_in_mode` quando Detached è obbligatorio. Il successivo tentativo può avvenire fino a 300 secondi dopo: il pulsante web «Aggiorna» non forza questo controllo.

### 3.4 Shelly irraggiungibile

Un errore di trasporto, HTTP, JSON o lettura dell'ingresso imposta `online=false` e `last_error`, scrive un warning e lascia attivo il ciclo di tentativi. L'ultimo stato del portone e il suo timestamp non vengono cancellati, ma il comando viene bloccato. La pagina visualizza lo stato offline e l'età dell'ultima lettura valida.

Non viene inviato un allarme Telegram specifico di dispositivo offline; durante l'assenza di letture valide non viene valutato l'allarme di apertura. Alla prima lettura valida riprende la riconciliazione con il database.

Se l'ingresso manca o ha `state=null`, viene restituito un errore che invita a configurare l'ingresso come tipo Switch. Non viene interpretato automaticamente come portone chiuso. [S: `shelly.py:get_status`, `monitor.py:_run`]

## 4. Logica dell'allarme

### 4.1 Stato persistente e tempo di apertura

SQLite contiene una riga singleton `current_state` con:

```text
garage_open | state_since | alert_sent | updated_at
```

Al primo campionamento assoluto, il programma registra un evento `INITIAL` e usa come `state_since` l'ora di quella lettura. Se il portone era già aperto, non può conoscerne l'ora reale di apertura precedente.

Un cambio chiuso -> aperto crea `OPEN`, aggiorna `state_since` e azzera `alert_sent`. Un cambio aperto -> chiuso crea `CLOSE`, registra la durata dell'apertura e azzera il flag per il nuovo stato. Letture identiche aggiornano soltanto `updated_at`: non creano aperture duplicate. [S: `db.py:reconcile`]

Il tempo utilizzato per l'allarme è:

```python
open_for = int(time.time() - state_since)
```

I timestamp sono epoch in secondi; per il messaggio si convertono nel fuso `TIMEZONE`, predefinito `Europe/Rome`. La soglia è `GARAGE_OPEN_ALERT_SECONDS=300`. La condizione è **durata maggiore o uguale a 300 secondi**, non strettamente maggiore. [S, V]

### 4.2 Invio, ripetizioni e reset

L'allarme viene valutato solo quando il dispositivo è online, il portone risulta aperto, esiste un timestamp, Telegram è configurato e `alert_sent` è falso.

Dopo un invio riuscito viene impostato `alert_sent=1` nel database e nello snapshot. Non vi sono richiami periodici finché il portone resta aperto, escalation o destinatari multipli.

In caso di errore di invio, il flag rimane falso e si ritenta dopo almeno **60 secondi**. Questo intervallo è fisso nel codice; `_last_alert_attempt` è solo in memoria. Il retry riguarda un tentativo fallito, non la ripetizione di un allarme già inviato. [S: `monitor.py:_maybe_send_open_alert`]

Alla chiusura, il flag viene resettato dalla transizione. La notifica di rientro viene tentata solo se la precedente apertura aveva un allarme segnato come inviato e `TELEGRAM_NOTIFY_CLOSED_AFTER_ALERT=true`. Il fallimento di questa notifica viene registrato nei log, **senza retry persistente**. Una successiva apertura costituisce un nuovo episodio.

Reset manuale/acknowledgement/snooze dalla pagina o dal bot: non implementati nella v1.0.0.

### 4.3 Riavvio e duplicati

Il costruttore del monitor rilegge da SQLite `garage_open`, `state_since` e `alert_sent`. Dopo un normale riavvio, se il sensore conferma lo stesso stato aperto, il conteggio non riparte da zero e un allarme già segnato come inviato non viene reinviato. Anche il riavvio prima della soglia conserva il tempo già maturato. Questi comportamenti sono stati verificati con database temporanei. [S: `monitor.py:__init__`, V]

**Non esiste una garanzia assoluta di consegna una sola volta.** Il codice invia prima a Telegram e salva poi il flag. Un arresto fra le due operazioni, oppure un timeout dopo che Telegram ha già ricevuto il messaggio, può causare un duplicato al successivo tentativo. Non esistono outbox transazionale o registri persistenti degli ID dei messaggi Telegram. Questa è una limitazione rilevata nell'handoff, non un incidente precedentemente riferito dall'utente.

### 4.4 Periodi senza osservazione

Durante un riavvio o un guasto di rete il software non osserva i movimenti. Se ritrova lo stesso stato, assume continuità; se ritrova uno stato diverso, registra la transizione all'ora della nuova lettura. Aperture e chiusure interamente avvenute durante l'interruzione non sono ricostruibili.

Il tempo di apertura usa l'orologio di sistema, mentre intervalli di polling e cooldown dei comandi usano `time.monotonic()`. Salti dell'orologio possono quindi influenzare durata e soglia. Configurazione effettiva di NTP/RTC e gestione specifica di questi salti: **non documentato**.

## 5. Notifiche Telegram

### 5.1 Configurazione e direzione del traffico

Configurazioni previste:

```dotenv
TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""
TELEGRAM_NOTIFY_CLOSED_AFTER_ALERT=true
```

Token e chat ID devono essere entrambi presenti perché il notificatore risulti abilitato. Valori reali, username del bot, nome della chat, natura privata/gruppo della destinazione e amministratori del gruppo: **non documentato**.

I nomi `RB-Vecchi Garage`, `rb_vecchi_garage_bot` e gli ID numerici illustrativi comparivano nelle istruzioni come **esempi**, non come impostazioni accertate. Non riutilizzare i dati Telegram di Camper Hub.

Il codice effettua soltanto invii:

```text
POST https://api.telegram.org/bot<TOKEN>/sendMessage
JSON: chat_id, text, disable_web_page_preview=true
Timeout: 8 secondi
```

`getUpdates` è citato nel README per individuare manualmente il chat ID, non come ciclo di ricezione di comandi. Non sono implementati comandi entranti, polling del bot, webhook Telegram, pulsanti inline o apertura del garage tramite messaggi. [S: `notifier.py`, `README.md`]

### 5.2 Testi effettivi

Allarme apertura:

```text
⚠️ Il garage è ancora aperto.
Aperto dalle HH:MM del GG/MM/AAAA.
Durata: <durata>.
```

Notifica di rientro:

```text
✅ Garage chiuso. È rimasto aperto per <durata>.
```

Messaggio di `diagnose.py --telegram-test`:

```text
✅ Test RB-Vecchi: notifiche Telegram operative.
```

La durata è formattata come `N h M min`, `N min M s` oppure `N s`. Non è impostato un `parse_mode`. I messaggi di allarme non includono `APP_NAME`, link alla dashboard o pulsanti.

Il testo diverso «Test Telegram RB-Vecchi riuscito» compariva in un esempio successivo di test manuale: non è il testo incorporato in `diagnose.py`. Ricezione del test del 27 luglio: **non documentato**. [C2, S]

## 6. Applicazione web

### 6.1 Stack e processo

Il backend è **Flask**, con template HTML, CSS locale e JavaScript senza un framework frontend aggiuntivo. SQLite conserva stato e storico. In esercizio `start.sh` avvia Gunicorn con **un worker e quattro thread**, timeout di 30 secondi e log su stdout/stderr. `wsgi.py` crea l'applicazione e il suo thread di monitoraggio. [S]

Le dipendenze dichiarate, non le versioni realmente installate, sono:

```text
Flask>=3.0,<4
requests>=2.31,<3
python-dotenv>=1.0,<2
gunicorn>=22,<24
```

### 6.2 Route complete

La colonna «Login» si riferisce alla protezione quando le credenziali web sono entrambe configurate.

| Metodo | Route | Login | Funzione |
|---|---|---|---|
| GET | `/login` | No | Mostra il modulo; reindirizza alla home se già autenticato. |
| POST | `/login` | No | Verifica utente/password, crea sessione e token CSRF. Errore credenziali: HTTP 401. |
| POST | `/logout` | No controllo esplicito | Cancella la sessione e rimanda al login. Non verifica CSRF. |
| GET | `/` | Sì | Render della dashboard e inserimento del token CSRF. |
| GET | `/api/dashboard` | Sì | Snapshot, statistiche del giorno, ultimi 50 eventi, ora server e fuso. |
| GET | `/api/status` | Sì | Snapshot corrente del monitor. Non forza una nuova chiamata allo Shelly. |
| GET | `/api/events?limit=50` | Sì | Eventi recenti; limite normalizzato fra 1 e 500. Parametro non numerico: 50. |
| POST | `/api/garage/pulse` | Sì + CSRF | Richiede `X-CSRF-Token`, invia impulso; errore operativo HTTP 503, CSRF non valido HTTP 403. |
| GET | `/healthz` | No | HTTP 200 se Shelly online, altrimenti 503; campi `ok` e `shelly_online`. |
| GET | `/manifest.webmanifest` | No | Manifest dell'app. |
| GET | `/service-worker.js` | No | Service worker; imposta `Service-Worker-Allowed: /`. |
| GET | `/static/<path:filename>` | No | Route statica creata da Flask per CSS, JavaScript e icone. |

I metodi automatici HEAD/OPTIONS non sono endpoint applicativi aggiuntivi. Non sono presenti route per cambiare configurazione, gestire account, ricevere webhook, comandare da Telegram, esportare CSV o generare report energetici. [S: `web.py:create_app`]

### 6.3 Contenuto dello snapshot

Lo snapshot distingue `online`, `garage_open`, `raw_input_state`, `state_since`, `alert_sent`, `last_success`, `last_error`, stato del relè e diagnostica. Espone inoltre `switch_in_mode`, `switch_auto_off`, `switch_initial_state`, `safety_warning`, `state_duration_seconds`, `stale_seconds`, `telegram_enabled`, `alert_after_seconds` e `command_allowed`.

`telegram_enabled=true` significa che token e chat ID sono valorizzati, **non** che la consegna sia stata provata. Analogamente, `ok=true` nelle API dashboard/status indica la riuscita della risposta API: per lo stato dello Shelly occorre leggere `status.online`. `/healthz` usa invece direttamente la disponibilità dello Shelly per determinare `ok` e il codice HTTP.

### 6.4 Pagina e aggiornamento

La dashboard è una pagina a schede, adattata a schermi piccoli: stato del basculante e tempo nello stato corrente, pulsante «Comanda basculante» con finestra di conferma, aperture odierne, tempo totale aperto oggi, RSSI, temperatura disponibile, dettagli del dispositivo e ultimi 50 eventi. Sono presenti logout, aggiornamento manuale, avvertimenti e messaggi temporanei di esito.

Gli intervalli del browser sono distinti dal polling Raspberry -> Shelly:

```text
/api/status       ogni 2,5 secondi
/api/dashboard    ogni 15 secondi, oltre al caricamento iniziale/manuale
Orologio/durata UI ogni 1 secondo
```

Dopo il comando viene pianificato un aggiornamento dello stato dopo 800 ms. Il pulsante viene riabilitato usando `command_allowed`; il cooldown effettivo di tre secondi viene comunque applicato dal backend.

Sono inclusi manifest, icone e service worker per gli asset statici. Non viene memorizzato uno stato del portone da utilizzare per comandi offline. Il funzionamento effettivamente collaudato delle funzionalità PWA su Safari e sull'URL utilizzato dall'utente è **non documentato**. [S: `templates/index.html`, `static/app.js`, `static/service-worker.js`]

### 6.5 Autenticazione ed esposizione

L'applicazione prevede un solo account configurato con `WEB_USERNAME` e `WEB_PASSWORD`, senza database utenti o ruoli. La password viene confrontata con `hmac.compare_digest` ed è conservata come valore nel file di configurazione, non come hash password.

La sessione Flask è firmata con `SECRET_KEY`, ha durata permanente configurata di 30 giorni e cookie `HttpOnly`, `SameSite=Lax`. Il flag `Secure` non è esplicitamente attivato nel codice. Il comando richiede CSRF; login e logout non implementano la stessa verifica. Sono impostati CSP, `X-Frame-Options: DENY`, `nosniff`, Referrer Policy e `Cache-Control: no-store` per le API.

**Attenzione:** se utente o password sono vuoti, `web_auth_enabled` diventa falso e l'app permette l'accesso senza login. Il normale configuratore genera una password se mancante, ma un avvio manuale con ambiente errato può usare impostazioni diverse da quelle del servizio. [S: `config.py`, `web.py`]

Il bind predefinito è `0.0.0.0:8080` in HTTP: non è limitato a una specifica interfaccia LAN. Il README indica accesso remoto tramite VPN, con WireGuard/OpenVPN come esempi, e sconsiglia il port forwarding diretto. **VPN effettivamente presente, firewall, NAT, dominio pubblico, reverse proxy e HTTPS: non documentato.** Non affermare che l'accesso da Internet sia configurato, né che il solo bind garantisca isolamento dalla rete esterna.

## 7. Struttura del codice, configurazioni e segreti

### 7.1 Contenuto dell'archivio

```text
RB-Vecchi/
  README.md                  Requisiti, installazione, diagnostica e uso
  VERSION                    1.0.0
  LICENSE                    Licenza MIT del pacchetto
  .env.example               Esempio, non configurazione di produzione
  requirements.txt           Dipendenze runtime con intervalli di versione
  requirements-dev.txt       Dipendenze di sviluppo; pytest>=8,<9
  install.sh                 Installazione iniziale e configurazione
  update.sh                  Aggiornamento dei file e riavvio servizio
  configure.py               Generazione interattiva del file ambiente
  diagnose.py                Test letture Shelly e, opzionalmente, Telegram
  rb-vecchi.service          Unit systemd
  start.sh                   Avvio Gunicorn: 1 worker, 4 thread
  run.py                     Avvio diretto con server Flask
  wsgi.py                    Entrypoint Gunicorn
  rbvecchi/
    __init__.py
    config.py                Settings, valori predefiniti e caricamento env
    shelly.py                Client HTTP RPC e parsing dello stato
    db.py                    SQLite, transizioni, statistiche, comandi
    monitor.py               Polling, snapshot, allarmi e impulsi
    notifier.py              Invio Telegram sendMessage
    web.py                   Factory Flask, route, sessioni e CSRF
    templates/
      index.html             Dashboard
      login.html             Login
    static/
      app.js                 Polling browser, UI, conferma e invio comando
      app.css                Stili responsive
      manifest.webmanifest   Manifest
      service-worker.js      Cache degli asset statici
      icon-180.png
      icon-192.png
      icon-512.png
  tests/
    test_db.py               Transizioni e statistiche
    test_shelly.py           Parsing e richiesta impulsiva
    test_monitor.py          Allarme apertura e notifica chiusura
```

### 7.2 Layout previsto sul Raspberry

| Percorso/identità | Ruolo |
|---|---|
| `/opt/rb-vecchi` | Codice installato e script di runtime |
| `/opt/rb-vecchi/venv` | Ambiente virtuale Python |
| `/etc/rb-vecchi.env` | Configurazione e segreti |
| `/var/lib/rb-vecchi/garage.db` | Database persistente |
| `/etc/systemd/system/rb-vecchi.service` | Unit installata |
| Utente e gruppo `rbvecchi` | Identità di esecuzione del servizio |

`install.sh` non copia l'intero archivio: fra gli altri, README, test e `VERSION` non vengono installati come parte della selezione dei file. La presenza di `VERSION` nella cartella di produzione non è quindi garantita dal pacchetto.

### 7.3 Database

`db.py` abilita WAL, foreign keys e timeout SQLite di 10 secondi. Le tabelle sono:

| Tabella | Contenuto |
|---|---|
| `current_state` | Riga `id=1`: stato, istante iniziale, flag allarme e aggiornamento. |
| `events` | `event_ts`, tipo `INITIAL`/`OPEN`/`CLOSE`, stato, durata e origine `startup`/`shelly`. |
| `commands` | Timestamp, tipo `PULSE`, successo e dettaglio limitato a 1000 caratteri. |

Lo storico giornaliero conta gli eventi `OPEN` e integra gli intervalli aperti, considerando anche aperture iniziate prima della mezzanotte. Il flag di allarme non è uno storico completo delle consegne Telegram. I rifiuti del comando prima della chiamata allo Shelly, per esempio per cooldown, non vengono inseriti da `log_command`; vengono segnalati dalla route nei log.

Retention, archiviazione automatica, migrazioni versionate dello schema, esportazione dei comandi e politiche di manutenzione del database non sono implementate nel pacchetto. Eventuali procedure esterne: **non documentato**.

### 7.4 Configurazione e segreti

I valori sensibili previsti sono `SHELLY_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `WEB_PASSWORD` e `SECRET_KEY`. I valori di produzione sono **non documentato**; lo ZIP contiene soltanto esempi o valori fittizi di test.

L'installer assegna `/etc/rb-vecchi.env` a `root:rbvecchi` con permessi **0640**. La directory dati viene creata con proprietario `rbvecchi:rbvecchi` e permessi **0750**. Il servizio applica `UMask=0077`.

Systemd carica il file tramite `EnvironmentFile`. `diagnose.py` lo carica esplicitamente con `--env`, il cui default è `/etc/rb-vecchi.env`. Un `run.py` eseguito manualmente usa invece `load_dotenv()` e l'ambiente corrente: **non carica automaticamente quel percorso di sistema**. Questo dettaglio è importante per evitare test eseguiti con password, database o soglie differenti.

Il configuratore conserva alcuni valori esistenti, ma ricostruisce il file e riporta altri parametri ai default. Non usarlo come se fosse un editor che preserva tutte le personalizzazioni: vedere sezione 10.

## 8. Decisioni tecniche e motivazioni

La distinzione fra motivazione espressa e spiegazione ricavata dal codice è essenziale.

| Scelta documentata | Motivazione documentata o limite della ricostruzione |
|---|---|
| Soglia iniziale di cinque minuti | Requisito dell'utente. [C1] |
| Interfaccia responsive per iPhone | Requisito di uso mobile. [C1] |
| Relè Detached | Il contatto che rileva il portone non deve comandare direttamente il relè. Motivazione esplicita nel README. |
| `toggle_after` più raccomandazione Auto off | Impulso breve e ulteriore protezione rispetto a lasciare il relè attivo; esplicitato nel README. |
| Comando denominato impulso passo-passo | Il software non garantisce un comando direzionale «apri»/«chiudi»; la pagina chiede conferma e richiama le protezioni della centrale. |
| Stato letto dall'ingresso e non dall'uscita | Separazione concreta nel codice fra sensore del portone e comando. Ulteriore discussione storica della scelta: **non documentato**. |
| SQLite | Implementazione presente; la persistenza permette il ripristino dei timestamp e del flag. Confronto esplicito con altri database: **non documentato**. |
| Flask, Gunicorn e JavaScript locale | Stack consegnato. Valutazione comparativa con altri framework: **non documentato**. |
| Polling a due secondi | Default implementato. Motivazione esplicita del valore e confronto con webhook/MQTT: **non documentato**. |
| Un worker Gunicorn | Configurazione presente. Dal codice si ricava che ogni app crea un monitor; mantenere un processo evita di moltiplicarli. Questa motivazione è un'analisi dell'handoff, non una citazione di una decisione storica. |
| VPN invece di esposizione diretta | Raccomandazione esplicita del README. Scelta e implementazione concreta della VPN: **non documentato**. |

Alternative effettivamente discusse e poi scartate, come Home Assistant, Node-RED, MQTT, altri hardware o altri framework: **non documentato**. L'assenza di una tecnologia dal pacchetto non prova che sia stata valutata e respinta.

## 9. Problemi incontrati, interventi e trappole storiche

### 9.1 Telegram non configurato all'installazione

Il 24 luglio l'utente comunica di avere installato l'applicazione e di apprezzarne il funzionamento, ma di non avere impostato Telegram. Vengono fornite istruzioni per creare/configurare bot e chat ID, rieseguire `configure.py` e provare `diagnose.py --telegram-test`. Il 27 luglio viene richiesto un test di invio. [C1, C2]

**Intervento documentato:** istruzioni di configurazione e test.  
**Esito finale documentato:** **non documentato**. Non classificare il problema come certamente risolto.

### 9.2 Stato del contatto invertito o ingresso senza stato

Il README prevede la possibilità di invertire `INPUT_TRUE_IS_OPEN` e richiede un ingresso di tipo Switch. Sono istruzioni preventive e gestione di casi possibili, non la prova che l'utente abbia realmente incontrato e risolto un'inversione o un ingresso stateless.

**Errore effettivamente osservato sull'impianto:** **non documentato**.  
**Polarizzazione/configurazione finale applicata:** **non documentato**.

### 9.3 Blocco per modalità non Detached

Il controllo e il messaggio di blocco esistono nei sorgenti. Non è stato recuperato un log RB-Vecchi che dimostri un incidente del genere o una successiva correzione sullo Shelly reale.

**Caso operativo e soluzione applicata:** **non documentato**.

### 9.4 Limiti delle verifiche originali

Alla consegna l'assistente aveva dichiarato di non avere avviato il server Flask nell'ambiente di preparazione, rinviando la verifica sul Raspberry a servizio e diagnostica. Questo limite non va trasformato in un guasto avvenuto in produzione. La successiva conferma generale dell'utente attesta l'installazione, ma non documenta tutte le prove end-to-end.

Altri bug di esercizio RB-Vecchi, workaround applicati, modifiche manuali non inserite nel pacchetto, incidenti di rete e ripristini con esito documentato: **non documentato**. Le anomalie di Camper Hub, Bluetooth, BDS-180 o degli altri Raspberry non appartengono a questo progetto.

## 10. Bug, limiti attuali e roadmap

### 10.1 Risultati della revisione dei sorgenti

I punti seguenti sono **rilevati nel codice v1.0.0 durante questo handoff**, non presentati come problemi già segnalati dall'utente o già risolti.

| Punto | Comportamento e conseguenza | Riferimento |
|---|---|---|
| Campo firmware ambiguo | `get_status()` preferisce `sys.available_updates.stable.version` a `sys.fw_id`. Quando entrambi esistono, il campo chiamato firmware contiene la versione disponibile per aggiornamento, non quella installata. Priorità verificata con payload simulato. | `shelly.py:get_status` [V] |
| Browser disconnesso dal Raspberry | Un errore di `loadStatus()` viene solo scritto in console. Gli aggiornamenti periodici completi normalmente non mostrano errori. La UI può conservare il precedente stato online e continuare il conteggio locale, anche se il backend non è più raggiungibile. È distinto dal caso Shelly offline, gestito dal backend. | `static/app.js:loadStatus`, `loadDashboard`, `updateClock` |
| Configuratore non conservativo | Rieseguire `configure.py` reimposta ID a 0, timeout a 4 s, polling a 2 s, cooldown a 3 s, Detached obbligatorio, notifica chiusura attiva, percorso DB, fuso, bind e livello log ai valori codificati. Eventuali chiavi aggiuntive non vengono mantenute. | `configure.py:main` |
| Parametro soglia nel configuratore | L'interfaccia chiede minuti interi e converte in secondi; una soglia manuale non multipla di 60 non è preservata esattamente dal successivo passaggio nel configuratore. | `configure.py:main` |
| Verifica sicurezza in cache | Detached viene riletto ogni 300 s. Dopo un errore il blocco può durare fino al prossimo controllo; dopo una modifica esterna una precedente verifica può restare in uso fino a quel momento. | `monitor.py:_refresh_switch_config_if_needed` |
| Consegna Telegram non atomica | Un arresto fra invio e salvataggio del flag o un timeout ambiguo può produrre duplicati. La notifica di chiusura fallita non viene ritentata. | `monitor.py:_maybe_send_open_alert`, `_handle_transition` |
| Chiamate Telegram sincrone | L'invio avviene nello stesso thread del polling, con timeout del notificatore a 8 s. Una chiamata lenta ritarda le letture successive. | `monitor.py`, `notifier.py` |
| Risposta dell'impulso ambigua dopo errore | In caso di eccezione il cooldown viene azzerato; un timeout non dimostra che l'impulso non sia partito. Ripetere ciecamente un comando passo-passo potrebbe avere un effetto diverso da quello atteso. Non esiste verifica di posizione finale. | `monitor.py:pulse` |
| Cache frontend | Cache statica `rb-vecchi-static-v1` con strategia cache-first. Aggiornamenti futuri devono gestire la versione della cache per evitare asset vecchi dove il service worker è attivo. | `static/service-worker.js` |
| Più processi applicativi | Ogni `create_app()` può avviare un monitor. Aumentare i worker o avviare una seconda istanza può duplicare polling e tentativi di notifica; non c'è elezione di un singolo monitor. | `web.py:create_app`, `start.sh` |

Nessuna correzione di questi punti è stata applicata al pacchetto originale durante l'handoff.

### 10.2 Limiti funzionali della v1.0.0

La logica ha solo stato aperto/chiuso e disponibilità dello Shelly: non distingue apertura in corso, chiusura in corso, posizione percentuale o arresto intermedio. Non dispone di una logica di chiusura automatica o di conferma meccanica dell'esito di un impulso.

Non vi sono debounce applicativo dell'ingresso, registrazione esplicita dei periodi offline, notifiche di perdita/ripristino connettività, escalation dell'allarme, gestione multiutente, pagina impostazioni, gestione della ricarica o invio email. Lo storico non ricostruisce gli eventi persi durante l'assenza di osservazione.

Autenticazione, timestamp, recupero da interruzioni, retention e backup hanno i limiti già descritti. Uno storico corretto nei test non dimostra che il sensore reale sia collegato o interpretato correttamente.

### 10.3 Roadmap realmente richiesta: ricarica del quadriciclo

Il 22 settembre Andrea chiede di mettere in carica il proprio quadriciclo elettrico nel garage gestito da RB-Vecchi. Poiché la corrente non è pagata direttamente da lui, vuole contabilizzare consumi e importo da rendicontare. [C3]

La richiesta comprende un **report email bimestrale, cioè ogni due mesi, oppure con cadenza configurabile nell'app**, contenente energia consumata, cifra e breve cronologia delle fasi di carica/mantenimento.

Esempi forniti dall'utente, non misure verificate:

```text
Dalle 22:00 del 19/9 alle 8:34 del 21/9 mantenimento media 4w/ora
Dalle 8:34 del 21/9 alle 10:10 del 21/9 carica 1,2KW/ora
```

Per la futura specifica occorre distinguere potenza media in W/kW ed energia in Wh/kWh: le stringhe dell'esempio non vanno trattate come unità già corrette o come dati reali acquisiti.

Nella risposta progettuale era stata prospettata una catena misuratore Shelly -> Raspberry -> SQLite -> dashboard -> email, con un dispositivo capace di misurare energia. Shelly 1PM Gen3 era citato come esempio: **non è documentata la sua scelta, installazione o configurazione per questa estensione**. Le soglie esemplificative per distinguere le fasi non costituiscono soglie approvate o collaudate.

| Dettaglio dell'estensione | Stato |
|---|---|
| Misuratore da usare, modello e IP | **non documentato** come scelta finale |
| Cablaggio e circuito dedicato | **non documentato** |
| Tariffa al kWh e regole di calcolo del rimborso | **non documentato** |
| Tariffa unica/fasce, variazioni nel tempo e arrotondamenti | **non documentato** |
| Soglie e durata minima delle fasi carica/mantenimento | **non documentato** come valori decisi |
| Frequenza di raccolta, contatore energetico e gestione reset | **non documentato** come implementazione |
| Destinatari email, SMTP, credenziali e mittente | **non documentato** |
| Data di partenza del periodo, orario di invio e calendario finale | **non documentato** |
| Tabelle DB, route, pagina impostazioni e scheduler | Non presenti nella v1.0.0; implementazione successiva: **non documentato** |

### 10.4 Attività di prosecuzione emerse dall'handoff

Non sono una roadmap storica già approvata. La ripresa tecnica dovrebbe prima confrontare il software effettivamente installato con l'archivio, recuperare in modo protetto la configurazione e verificare i due stati del contatto, Detached e la ricezione Telegram. Successivamente possono essere valutate le anomalie della sezione 10.1 e sviluppata l'estensione di rendicontazione richiesta.

Non sostituire il sistema esistente sulla sola base dei default: cablaggio, credenziali e personalizzazioni runtime restano da accertare.

## 11. Esercizio: deploy, avvio, log, backup e aggiornamento

Le procedure seguenti provengono dal pacchetto. La loro presenza documenta come il software è stato consegnato, non prova che ogni procedura sia stata eseguita in produzione.

### 11.1 Installazione iniziale

Dalla cartella estratta `RB-Vecchi`:

```sh
chmod +x install.sh
sudo ./install.sh
```

Lo script richiede privilegi root, esegue `apt-get update`, installa `python3`, `python3-venv`, `python3-pip` e `ca-certificates`, crea l'utente di servizio non interattivo `rbvecchi`, copia il software in `/opt/rb-vecchi`, crea il virtualenv e installa le dipendenze. Esegue poi il configuratore, applica proprietario/permessi al file ambiente, installa la unit ed esegue `systemctl enable --now rb-vecchi.service`.

Non cambia l'hostname: stampa il nome realmente restituito dal sistema e il primo indirizzo trovato. Risoluzione `.local`, versione OS compatibile e versione Python del Raspberry: **non documentato** oltre all'indicazione generale Raspberry Pi OS/Raspbian.

### 11.2 Servizio e avvio

```sh
sudo systemctl status rb-vecchi
sudo systemctl restart rb-vecchi
sudo systemctl stop rb-vecchi
sudo systemctl start rb-vecchi
```

La unit usa:

```ini
User=rbvecchi
Group=rbvecchi
WorkingDirectory=/opt/rb-vecchi
EnvironmentFile=/etc/rb-vecchi.env
ExecStart=/opt/rb-vecchi/start.sh
Restart=on-failure
RestartSec=5
```

Parte dopo `network-online.target`. Sono impostati `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`, `ProtectHome=true` e scrittura consentita in `/var/lib/rb-vecchi`.

`Restart=on-failure` riguarda il processo di servizio: non è un watchdog applicativo del ciclo di polling. Non è documentato un supervisore esterno che controlli freschezza delle letture o blocchi del monitor.

Per l'esercizio mantenere l'avvio tramite systemd/Gunicorn del pacchetto. Un secondo `run.py` accanto al servizio può avviare un altro monitor; non è una modalità di diagnostica neutra.

### 11.3 Log e stato

```sh
sudo journalctl -u rb-vecchi -f
curl -s http://127.0.0.1:8080/healthz
```

I log applicativi e quelli access/error di Gunicorn confluiscono in stdout/stderr e quindi nel journal del servizio. Non è configurato un file dedicato sotto `/var/log` dal pacchetto.

Livello predefinito: `LOG_LEVEL=INFO`. La disponibilità di storico persistente del journal, retention, inoltro a un server esterno e monitoraggio dell'app: **non documentato**.

`/healthz` distingue Shelly online/offline; non attesta consegna Telegram, corretta polarità del contatto o movimento del portone.

### 11.4 Diagnostica e modifica configurazione

Letture Shelly e configurazione, senza impulso:

```sh
sudo -u rbvecchi /opt/rb-vecchi/venv/bin/python \
  /opt/rb-vecchi/diagnose.py
```

Test con invio reale al destinatario Telegram configurato:

```sh
sudo -u rbvecchi /opt/rb-vecchi/venv/bin/python \
  /opt/rb-vecchi/diagnose.py --telegram-test
```

Il test Telegram nello script viene eseguito **dopo** la lettura Shelly: se questa fallisce, lo script termina prima dell'invio. Codici di uscita: 0 esito regolare, 2 errore Shelly, 3 Telegram non configurato quando richiesto, 4 errore nell'invio Telegram.

Riconfigurazione prevista dal README:

```sh
sudo /opt/rb-vecchi/venv/bin/python \
  /opt/rb-vecchi/configure.py --output /etc/rb-vecchi.env
sudo systemctl restart rb-vecchi
```

Prima di riconfigurare occorre conservare la configurazione corrente: lo script può reimpostare personalizzazioni come descritto nella sezione 10. Per una modifica manuale del file ambiente il servizio deve essere riavviato. Il file contiene segreti: non copiarlo in chiaro in conversazioni o repository pubblici.

### 11.5 Backup e ripristino

Il README descrive una copia del database **a servizio fermo**, da una destinazione da predisporre:

```sh
sudo systemctl stop rb-vecchi
sudo cp /var/lib/rb-vecchi/garage.db /percorso/backup/garage-$(date +%F).db
sudo systemctl start rb-vecchi
```

`/percorso/backup` è un segnaposto, **non una destinazione realmente configurata**. La procedura considera il database; non implementa un backup completo automatico di codice e segreti.

Per un ripristino completo servirebbero anche la release software e `/etc/rb-vecchi.env`, compreso `SECRET_KEY`. La loro conservazione reale, cifratura, destinazione, periodicità, retention, ultima esecuzione e ultima prova di ripristino sono **non documentato**.

Non interpretare la procedura come autorizzazione a copiare il solo `.db` durante l'attività: il database è in modalità WAL. Una procedura diversa di backup online non è documentata nel pacchetto. Ripristinare un database più vecchio può inoltre ripristinare timestamp e flag d'allarme non aggiornati.

### 11.6 Aggiornamento

Dalla nuova cartella del pacchetto:

```sh
sudo ./update.sh
```

Lo script arresta il servizio, copia pacchetto Python e file di avvio, esegue l'installazione delle dipendenze, aggiorna la unit, ricarica systemd, riavvia e mostra lo stato. Non elimina configurazione e database.

Non esegue backup automatico, rollback, migrazioni versionate o verifica end-to-end. Con `set -e`, un errore intermedio può lasciare il servizio fermo. La copia non rimuove automaticamente eventuali vecchi file non più presenti in una futura release. Le dipendenze hanno intervalli di versione, non un lockfile: la riproduzione dell'ambiente richiede anche l'inventario delle versioni installate, che è **non documentato**.

Versione successiva effettivamente applicata, repository Git, branch di riferimento, pipeline di deploy e procedura di rollback provata: **non documentato**.

### 11.7 Verifiche eseguite per questo handoff

Il 22 settembre 2026 sono stati effettuati controlli in ambiente isolato, senza accesso al Raspberry:

| Verifica | Risultato |
|---|---|
| SHA-256 archivio rispetto al file originale | Corrispondente |
| Sintassi Python con `compileall` | Nessun errore |
| Sintassi shell con `sh -n` su install/update/start | Nessun errore |
| Suite originale `python -m pytest -q` | **4 passed** |
| Allarme al raggiungimento esatto di 300 secondi | Confermato con tempo simulato |
| Riavvio normale dopo allarme | Timestamp conservato; nessun reinvio dell'allarme già segnato |
| Riavvio prima dell'allarme | Tempo precedente conservato; soglia non riparte da zero |
| Priorità del campo firmware | Confermato il limite: versione disponibile preferita al campo installato quando entrambi sono presenti |

Gli strumenti aggiuntivi hanno usato database temporanei, risposte simulate e notificatori fittizi. Nell'ambiente di verifica non erano installati Flask e Gunicorn: **non è stato avviato o collaudato il server web completo**. I quattro test originali coprono database, client simulato e monitor; non sono test della centralina o di Telegram reale.

I risultati sono quindi evidenza del comportamento del codice nei casi provati, non certificazione dell'impianto fisico o dello stato attuale della produzione.

---

## Materiale da consegnare al nuovo assistente

Questo Markdown va accompagnato preferibilmente da `RB-Vecchi-v1.0.0.zip` e dal suo `.sha256`. Nel pacchetto di handoff sono inclusi anche i risultati delle verifiche del 22 settembre 2026. L'archivio software originale è rimasto invariato.

I materiali **non** includono il file ambiente di produzione, il database reale, uno schema elettrico, il firmware rilevato dal dispositivo o una prova di ricezione Telegram: tali elementi restano **non documentato**.

**Regola per proseguire:** usare i sorgenti come riferimento della v1.0.0, le conversazioni per i requisiti e le conferme storiche, e la configurazione reale quando sarà disponibile per descrivere l'impianto. Non trasformare un default, un esempio, una proposta o un test simulato in un fatto di produzione.
