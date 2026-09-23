# RB-Vecchi - Stato accertato in produzione

**Data dei rilievi:** 22 settembre 2026
**Metodo:** comandi in sola lettura eseguiti sul Raspberry di produzione e letture RPC dello Shelly. Nessun impulso inviato, nessuna configurazione modificata, nessun test Telegram spedito.

> Questo documento integra `RB-Vecchi_HANDOFF_2026-09-22.md`. Dove i due divergono, prevale questo, perché l'handoff descriveva il pacchetto consegnato mentre qui sono riportate misure sull'impianto reale. Le voci sono marcate **[M]** quando misurate direttamente, **[D]** quando dedotte da dati misurati, **[A]** quando ancora aperte.

## 1. Correzioni all'handoff

| Voce | Handoff | Accertato |
|---|---|---|
| Sistema operativo | Raspbian / Raspberry Pi OS | **Ubuntu 24.04.2 LTS, aarch64** [M] |
| Versione Python | non documentato | **3.12.3** [M] |
| `INPUT_TRUE_IS_OPEN` | default `true` | **`false`** in produzione [M] |
| `RELAY_PULSE_SECONDS` | default 0,7 s | **0,5 s** in produzione [M] |
| `SHELLY_PASSWORD` | non documentato | **vuota**, e `auth_en: false` sul dispositivo [M] |
| Firmware Shelly | non documentato | **1.7.5** installato, 2.0.0 disponibile [M] |
| Esito prova sul motore | non documentato | **107 impulsi con effetto verificato** [M][D] |
| Telegram | configurazione finale non documentata | **configurato dal 24/07 17:17** [M]; consegna [A] |

## 2. Ambiente di esercizio

Servizio `rb-vecchi` attivo e abilitato, unit senza drop-in, identica a quella del pacchetto. Avvio del 22/09 alle 06:36:41, innescato da `needrestart` dopo cinque esecuzioni apt fra le 06:31:50 e le 06:36:03 [D]. Prima di quel riavvio il processo girava dal boot del 7 agosto, con 1h 09min di CPU consumata [M].

Boot del Raspberry: 07/08/2026 20:59:25. Boot dello Shelly: 07/08/2026 20:58:14 con `reset_reason: 1`, cioè accensione da mancanza di alimentazione. Settantuno secondi di distanza fra i due: **blackout** e ripresa autonoma di entrambi gli apparati [D].

Pacchetti nel virtualenv, tutti dentro gli intervalli dichiarati in `requirements.txt` [M]:

```text
Flask 3.1.3   gunicorn 23.0.0   requests 2.34.2   python-dotenv 1.2.2
```

File in `/opt/rb-vecchi`: 22 file, tutti con data 24/07/2026, nessun file estraneo, nessuna modifica successiva all'installazione [M]. Mancano soltanto README, VERSION, test e script di installazione, coerentemente con la selezione operata da `install.sh`.

**[A] Confronto degli hash** fra `/opt/rb-vecchi` e l'archivio `RB-Vecchi-v1.0.0.zip`: da eseguire. Finché non è fatto, l'identità fra codice in produzione e v1.0.0 è probabile ma non provata.

## 3. Configurazione reale

`/etc/rb-vecchi.env`, `root:rbvecchi` 0640, 737 byte, ultima modifica **24/07/2026 17:17**, mai più toccato [M].

Valori non predefiniti: `APP_NAME="RB-Vecchi · Casa"`, `INPUT_TRUE_IS_OPEN=false`, `RELAY_PULSE_SECONDS=0.5`, `SHELLY_PASSWORD` vuota.

Telegram: token di 46 caratteri e chat ID di 9, entrambi valorizzati, `TELEGRAM_NOTIFY_CLOSED_AFTER_ALERT=true`. Autenticazione web attiva, utente `admin`, password di 9 caratteri, `SECRET_KEY` di 64 caratteri. Nessun valore sensibile è riportato in questo documento.

Poiché il file è stato scritto alle 17:17 del 24 luglio e non è più cambiato, **Telegram era già configurato al momento del test del 27 luglio** [D].

## 4. Polarità del contatto: risolta

Il software legge `Input raw: True` come portone **CHIUSO**, per effetto di `INPUT_TRUE_IS_OPEN=false`.

L'interpretazione è confermata dal comportamento, non solo dalla configurazione [D]. Incrociando la tabella `commands` con la tabella `events`, ogni impulso inviato a portone chiuso è seguito da un evento `OPEN`, e ogni impulso inviato a portone aperto da un evento `CLOSE`. I ritardi sono asimmetrici in modo fisicamente sensato:

| Impulso | Evento | Ritardo |
|---|---|---:|
| 19/09 20:27:34 | OPEN 20:27:38 | 4,0 s |
| 19/09 20:30:50 | CLOSE 20:31:06 | 16,1 s |
| 19/09 21:08:59 | OPEN 21:09:02 | 3,0 s |
| 20/09 21:53:26 | OPEN 21:53:31 | 5,0 s |
| 20/09 21:54:21 | CLOSE 21:54:36 | 15,1 s |

L'apertura viene rilevata in 3-5 secondi perché il contatto lascia subito la posizione di chiusura; la chiusura in 15-16 secondi perché il contatto la riacquista solo a corsa completata. Con la polarità invertita si osserverebbe l'asimmetria opposta, fisicamente implausibile.

**Resta [A]** la natura fisica del sensore, i morsetti e lo schema elettrico. La polarità logica è però da considerarsi accertata.

## 5. Comando del basculante: verificato

107 righe in `commands`, tutte `PULSE` con `success=1` [M]. Cinque impulsi su cinque, nella finestra in cui comandi ed eventi si sovrappongono, hanno prodotto un movimento rilevato dal sensore [D].

L'handoff riportava l'esito di una prova sul motore come non documentato: la catena impulso → movimento → rilevazione è ora dimostrata su dati di esercizio.

Gli eventi senza impulso corrispondente sono manovre da telecomando [D].

## 6. Storico e allarmi

205 eventi dal 24/07/2026 16:54:31, di cui 102 chiusure. Durata massima di apertura: 1030 secondi [M].

Otto aperture hanno superato la soglia di 300 secondi, quindi **l'allarme è scattato otto volte** [D]:

| Chiusura | Durata |
|---|---:|
| 24/07/2026 18:14 | 326 s |
| 21/08/2026 18:16 | 376 s |
| 22/08/2026 20:14 | 492 s |
| 23/08/2026 18:11 | 680 s |
| 24/08/2026 20:13 | 1030 s |
| 06/09/2026 11:14 | 932 s |
| 16/09/2026 17:53 | 506 s |
| 16/09/2026 19:42 | 426 s |

Con `TELEGRAM_NOTIFY_CLOSED_AFTER_ALERT=true` ciascun episodio dovrebbe aver prodotto due messaggi, allarme e rientro, per un totale di sedici.

**[A] Verifica della consegna:** confrontare questi istanti con la cronologia della chat Telegram. È la prova che chiude la questione senza spedire alcun test. Va tenuto conto che l'elenco è un minimo: durante le finestre di irraggiungibilità l'allarme non viene valutato, quindi altre aperture oltre soglia possono non aver prodotto nulla.

## 7. Rete e connettività

### 7.1 Topologia

```text
router 192.168.1.1
  |-- ethernet --> Raspberry (eth0, via cavo)
  |-- ethernet --> PLC casa
                    ~~ rete elettrica ~~
                   PLC garage con AP integrato  192.168.1.52
                     |-- wifi SSID "Finanza" --> Shelly 1 Gen3  192.168.1.100
```

Il Raspberry è collegato al router via cavo [M]: la sua connettività non dipende dal powerline. L'unica tratta fragile è quella elettrica fra i due adattatori.

L'apparato in garage ha un solo MAC, `58:04:4f:51:1b:78`, usato sia come BSSID radio sia come indirizzo di gestione su `192.168.1.52` [M]. Interfaccia web basata sul framework `$.su`, compatibile con apparati TP-Link [D].

**Conseguenza diagnostica:** l'RSSI dello Shelly misura solo il salto fra dispositivo e AP, due metri nello stesso locale. Resta eccellente (-45 dBm) anche mentre la tratta powerline è interrotta. **Il campo RSSI della dashboard non è un indicatore di salute della catena** [D].

### 7.2 Misura dell'irraggiungibilità

Analisi di 324.172 warning nel journal, raggruppati in finestre con soglia di 60 secondi [M]:

```text
periodo   : 24/07 21:24 -> 22/09 06:47   (59,4 giorni)
finestre  : 196
offline   : 14 giorni 4h 53min  =  23,9% del periodo
durata    : mediana 4min 08s    max 3 giorni 12h 49min
```

La finestra più lunga va dal 28/07 22:22 al 01/08 11:11.

### 7.3 Due regimi e la causa

Fino al 23/08 i distacchi coprono dieci, venti, ventidue ore al giorno. Dal 24/08 in poi nessun giorno supera i 35 minuti [M].

Il 23/08 l'utente è rientrato dalle ferie ed è intervenuto fisicamente sull'adattatore powerline, **ruotando la spina nella presa e invertendo di fatto fase e neutro**. Le spine Schuko sono inseribili in due versi e l'accoppiamento del segnale HomePlug verso la linea non è simmetrico: impedenza vista dal modem e rumore di modo comune cambiano con l'orientamento. Il miglioramento coincide con l'intervento [D].

Il fatto che una rotazione della spina produca un salto così netto indica che **il collegamento lavorava, e continua a lavorare, vicino al limite** [D]. Il residuo attuale è lo stesso fenomeno attenuato, non un fenomeno diverso.

### 7.4 Ipotesi scartata

Il motore del basculante era il sospettato principale come sorgente di disturbo. **È escluso** [M]: una sola finestra su 196 inizia entro due minuti da un evento del portone, contro 1,9 attese per pura coincidenza. Nessuna correlazione.

### 7.5 Effetti collaterali osservati

Lo Shelly non sincronizza l'orologio dall'08/08/2026 20:58:46, cioè da 44 giorni. Tenta una sincronizzazione al giorno e la trova chiusa [D]. Irrilevante per la v1.0.0, che usa l'orologio del Raspberry; rilevante se una funzione futura si appoggiasse a timestamp o schedulazioni generati dal dispositivo.

### 7.6 Aperto

**[A]** Marca e modello degli adattatori; se sono innestati direttamente nella presa a muro o passano da ciabatte, prolunghe o filtri antidisturbo; se le due prese stanno sulla stessa fase; velocità di sincronizzazione dichiarata dalla pagina di stato del PLC; esistenza di un risparmio energetico o di una schedulazione sull'apparato. Un logger a tre nodi verso `192.168.1.1`, `192.168.1.52` e `192.168.1.100` è stato avviato per distinguere quale tratta cade.

## 8. Shelly 1 Gen3: dati del dispositivo

| Voce | Valore |
|---|---|
| Modello | `S3SW-001X16EU` |
| Nome | `Garage` |
| MAC | `80B54E3B228C` |
| Firmware installato | **1.7.5** (`20260311-095909/1.7.5-g9979d16`) |
| Aggiornamento disponibile | stable 2.0.0, beta 2.0.1-beta3 |
| Autenticazione | **`auth_en: false`** |
| Relè | `in_mode: detached`, initial state off, auto off attivo |
| Wi-Fi | SSID `Finanza`, BSSID `58:04:4f:51:1b:78`, RSSI -45 dBm |

### 8.1 Trappola del firmware: confermata sul campo

La sezione 10.1 dell'handoff segnalava che `get_status()` preferisce `sys.available_updates.stable.version` a `sys.fw_id`. Sul dispositivo reale entrambi sono presenti: **la dashboard mostra 2.0.0 mentre il firmware installato è 1.7.5**. Non è più un limite dedotto dal codice, è un dato errato visibile in produzione.

### 8.2 Assenza di autenticazione

`auth_en: false` e `SHELLY_PASSWORD` vuota: chiunque si trovi sulla rete Wi-Fi può azionare il basculante con una singola richiesta HTTP, senza passare da login, CSRF, cooldown e controllo Detached dell'applicazione [M].

**Da non fare ora:** l'aggiornamento a 2.0.0 è un cambio di major su un dispositivo che comanda un basculante. Va pianificato a impianto stabile, con una via di ritorno, non durante l'indagine sulla rete.

## 9. Requisiti emersi per gli sviluppi

### 9.1 Notifica di irraggiungibilità, condizionata

Il sistema non segnala in alcun modo la perdita del dispositivo. Per due mesi è stato cieco quasi un quarto del tempo senza dirlo.

Una notifica secca di offline sarebbe però controproducente: con distacchi quasi quotidiani produrrebbe un messaggio al giorno per una condizione che non richiede azione, e il rumore farebbe ignorare anche i messaggi utili.

**Forma corretta:** segnalare l'irraggiungibilità **solo se l'ultimo stato noto era "aperto"**, dopo una soglia di alcuni minuti. È l'unico caso in cui l'assenza di dati è informativa.

### 9.2 Correzione di `state_since` dopo un periodo cieco

Se un buco di osservazione inizia a portone chiuso e finisce a portone aperto, alla prima lettura valida `state_since` viene fissato a quell'istante. Il messaggio di allarme riporta quindi un orario di apertura posticipato e una durata sottostimata di tutta la finestra.

Per la finalità del progetto — segnalare un basculante lasciato aperto per dimenticanza — l'avviso arriva comunque, ma con un'informazione sbagliata su da quanto dura. Da correggere.

### 9.3 Portata dell'allarme

Il sistema **non è un antifurto**. Serve a segnalare che qualcuno ha lasciato aperto il basculante e se n'è andato. Ne discende che un'interruzione di rete ritarda la segnalazione ma non la annulla: se il portone è ancora aperto al ritorno della connettività, la soglia viene valutata e l'allarme parte. Un'apertura e chiusura interamente contenute in un buco non costituiscono un mancato avviso.

### 9.4 Contabilizzazione della ricarica

Uno **Shelly 1PM** è in arrivo il 23/09/2026.

**Vincolo di progetto:** il conteggio deve basarsi sul **contatore cumulativo di energia del dispositivo**, letto e differenziato a ogni campionamento, mai sulla somma delle potenze istantanee campionate. Il contatore è mantenuto a bordo e non si azzera al riavvio, quindi il totale dei kWh del periodo resta corretto anche con giorni di irraggiungibilità. La cronologia delle fasi di carica e mantenimento, che richiede campionamento continuo, va invece dichiarata parziale quando il periodo contiene finestre offline.

**Gestione dell'azzeramento:** se una lettura risulta minore della precedente non è un consumo negativo ma un reset del contatore, per ripristino di fabbrica o aggiornamento firmware. Va gestito ripartendo dal nuovo zero.

**Invio della rendicontazione:** il Raspberry è collegato via cavo, quindi la spedizione non dipende dal powerline; solo la lettura del misuratore ne dipende. Alla scadenza del bimestre, se il misuratore non è leggibile, la rendicontazione va marcata come dovuta su disco e spedita alla prima lettura valida, anche giorni dopo. Non uno scheduler che tenta a orario fisso e salta il periodo in caso di fallimento.

**[A]** Modello e posizione del misuratore, circuito dedicato, tariffa e regole di calcolo, soglie delle fasi, destinatari e SMTP, data di partenza del periodo. Da verificare inoltre se il 1PM Gen3 conservi una serie storica interrogabile a posteriori, oltre al contatore cumulativo.

## 10. Attività aperte, in ordine

1. Confronto degli hash fra `/opt/rb-vecchi` e l'archivio v1.0.0.
2. Verifica della consegna Telegram sulle otto date della sezione 6.
3. Lettura della pagina di stato del PLC e prove sull'installazione fisica degli adattatori.
4. Notifica di irraggiungibilità condizionata e correzione di `state_since`.
5. Specifica della contabilizzazione, dopo l'arrivo e l'installazione del 1PM.
