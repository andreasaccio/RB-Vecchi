# RB-Vecchi

Monitor del basculante del garage. Raspberry (Ubuntu 24.04, aarch64) + Shelly 1 Gen3
(basculante). In garage c'è anche uno Shelly 1PM Gen3 per la ricarica del quadriciclo.
Documentazione in docs/: handoff tecnico e stato accertato del 22/09/2026 (storici: la
parte rete descrive l'impianto TP-Link rimosso il 24/09); stato della rete del 25/09/2026.

## Vincoli
- Il servizio gira da /opt/rb-vecchi come utente rbvecchi, NON da questo repository.
  La distribuzione avviene con update.sh sul Raspberry, non con git pull in /opt.
- Il repository contiene 61 file; in produzione ne sono installati 25 in /opt/rb-vecchi
  (vedi install.sh) più 6 in /opt/rb-raccolta (vedi install-raccolta.sh).
- Questo NON è un antifurto: serve a segnalare un basculante lasciato aperto per
  dimenticanza. Un buco di rete ritarda la segnalazione, non la annulla.
- In produzione INPUT_TRUE_IS_OPEN=false e RELAY_PULSE_SECONDS=0.5, diversi dai default.
- Entrambi gli Shelly passano dal powerline e sono irraggiungibili a tratti.
  Ogni modifica deve tollerarlo.
- Non toccare mai /etc/rb-vecchi.env nel codice: contiene i segreti di produzione.
- Non aggiornare il firmware dello Shelly del basculante (192.168.1.100,
  1.7.5 installato, 2.0.0 disponibile).
- Dal PC nessuna chiamata ai dispositivi reali della LAN (Shelly, adattatori,
  Raspberry) senza richiesta esplicita: i test girano su dati sintetici.
- Non simulare un'unità systemd lanciando il comando con systemd-run: se il comando
  è figlio diretto di systemd i privilegi possono differire da quelli dell'unità
  vera (caso di ping con NoNewPrivileges, 25/09). Si verifica l'uscita dell'unità vera.

## Rete
- Powerline D-Link DHP-W310AV: 192.168.1.66 casa, 192.168.1.67 garage.
  L'AP del garage è l'unico con SSID Finanza.
- Dagli adattatori si legge solo st_stats.php (GET, senza login).
  Mai chiamare hedwig.cgi, pigwidgeon.cgi o reboot.php: scrivono o riavviano.
- getcfg.php restituisce la configurazione con le password in chiaro: il suo output
  non va mai salvato, registrato né committato.
- Timestamp sempre dal Raspberry: gli adattatori hanno l'orologio fermo al 2000.

## Lavori previsti
1. Notifica di irraggiungibilità CONDIZIONATA all'ultimo stato noto "aperto".
   Una notifica secca produrrebbe un messaggio al giorno: rumore inutile.
2. Correzione di state_since dopo un periodo cieco (oggi sottostima la durata).
3. Contabilizzazione ricarica quadriciclo con Shelly 1PM: usare SEMPRE il contatore
   cumulativo del dispositivo, mai la somma dei campioni di potenza.
4. verifica-produzione.sh non segnala i file del repository che mancano in
   /opt/rb-vecchi: percorre solo i file presenti in /opt.
5. verifica-produzione.sh non confronta /etc/systemd/system/rb-vecchi.service
   con il repository.

## Deploy
Claude Code lavora sul PC (WSL): scrive, committa e fa push su GitHub.
Sul Raspberry il deploy è manuale e richiede SEMPRE il pull:
  cd /home/pi/RB-Vecchi && git pull && sudo ./update.sh && ./verifica-produzione.sh
update.sh NON fa git pull: copia in /opt ciò che trova nel repository locale.
Se il commit stampato da verifica-produzione.sh non cambia, il deploy non è avvenuto.

## Verifica
./verifica-produzione.sh sul Raspberry confronta /opt con il repository.
./stato-rete.sh sul Raspberry riassume la rete su 24 ore e 7 giorni (sola lettura).

## Raccolta dati
- Tre raccoglitori in raccolta/: rb-carica (energia Shelly .101), rb-plc
  (contatori PLC .66 .67), rb-link (ping). Unità systemd permanenti separate
  dal basculante, utente di sistema rbraccolta, programmi in /opt/rb-raccolta,
  dati in /var/lib/rb-raccolta (RB_RACCOLTA_DIR).
- Un CSV al giorno per raccoglitore (data locale nel nome, intestazione in ogni
  file), ts in secondi epoch. Colonne di rb-carica e rb-plc da non cambiare.
- Sola lettura verso gli apparati: rb-carica solo Shelly.GetStatus e
  Shelly.GetDeviceInfo, rb-plc solo
  st_stats.php, rb-link solo ping. Stato ERR di rb-link = ping non eseguibile,
  dato mancante e non KO.
- rb-link.service ha AmbientCapabilities=CAP_NET_RAW: sul Raspberry
  ping_group_range è "1 0" e con NoNewPrivileges la capability di
  /usr/bin/ping non vale. Senza, rb-link scrive solo ERR.
- Installazione e aggiornamento: sudo ./install-raccolta.sh (idempotente).
  Non riavvia MAI il basculante; update.sh a sua volta non tocca i raccoglitori.
- In analisi i periodi senza righe sono dati mancanti, né ok né KO.
- File JSON per la dashboard in /var/lib/rb-raccolta, tutti scritti in modo
  atomico (giornaliero.scrivi_json_atomico, 0644; directory 0755, leggibili da
  rbvecchi), ciascuno con il campo "generato":
  - stato-rete.json: riepilogo powerline delle 24 h (solo 24 h, niente 7 giorni
    ogni minuto), con i dettagli per adattatore. Stati: stabile / instabile /
    interrotta / non_disponibile; le regole stanno tutte in classifica() di
    raccolta/stato_rete.py;
  - sistema.json: stato del Raspberry (raccolta/sistema.py, solo letture locali);
  - carica-ultimo.json: ultimo campione dello Shelly ricarica, scritto da
    rb-carica a ogni campione, con modello e firmware da GetDeviceInfo.
  I primi due li scrive il oneshot rb-stato-rete.service, lanciato ogni 60 s da
  rb-stato-rete.timer.
- rbvecchi legge SOLO file della raccolta in /var/lib/rb-raccolta, in sola
  lettura (rbvecchi/raccolta.py), da endpoint separati: /api/powerline,
  /api/carica, /api/sistema. Nessun nuovo client di rete dentro rbvecchi e
  nessuna chiamata in più allo Shelly .100: per il basculante si usa solo ciò
  che il monitor legge già. Nessuna analisi in rbvecchi, nessun effetto su
  /api/status, sul monitor o sulle notifiche. File assente, illeggibile, non
  valido o vecchio (carica-ultimo.json 60 s, gli altri 5 minuti) =
  "non disponibile".
- Pagine: principale (basculante, powerline, comando, ricarica, statistiche) e
  /dettagli (Shelly basculante, Shelly ricarica, powerline, Raspberry), con la
  stessa autenticazione. Nessun segreto nelle pagine.
- Il Wi-Fi dello Shelly misura solo il salto Shelly-AP, non la salute della
  catena: l'indicatore di rete della dashboard è il riquadro Powerline.
- Modifiche a static/: cambiare CACHE_NAME in service-worker.js, altrimenti il
  telefono continua a usare i file vecchi dalla cache.

## Shelly ricarica quadriciclo (192.168.1.101)
- Shelly 1PM Gen3 (S3SW-001P16EU), firmware 2.0.1. Il caricabatterie è alimentato
  attraverso il relè.
- Per RB-Vecchi è in SOLA LETTURA: nessuna chiamata che scriva
  (Switch.Set, Switch.Toggle, SetConfig, Reboot). Chiamate ammesse:
  Shelly.GetStatus (rb-carica, ogni 10 s) e Shelly.GetDeviceInfo (rb-carica,
  all'avvio e poi ogni 6 ore).
- Relè sempre chiuso. initial_state=on e in_mode=detached sono intenzionali:
  con i valori di fabbrica (match_input, follow) il relè resta aperto dopo
  ogni blackout e la carica non riparte.
- Timestamp dal Raspberry, non dall'orologio dello Shelly.
- kWh solo da aenergy.total differenziato. Il codice deve riconoscere il riavvio
  (uptime che cala) e l'azzeramento del contatore (totale che cala).
- NON accertato: se aenergy.total sopravvive a un'interruzione di corrente.
