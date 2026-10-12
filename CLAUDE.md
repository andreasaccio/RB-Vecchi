# RB-Vecchi

Monitor del basculante del garage. Raspberry (Ubuntu 24.04, aarch64) + Shelly 1 Gen3
(basculante). In garage c'è anche uno Shelly 1PM Gen3 per la ricarica del quadriciclo.
Documentazione in docs/: handoff tecnico e stato accertato del 22/09/2026 (la parte
rete descrive l'impianto TP-Link, rimosso il 24/09 e rimesso l'11/10); stato della rete
del 25/09/2026 (periodo D-Link, storico).

## Vincoli
- Il servizio gira da /opt/rb-vecchi come utente rbvecchi, NON da questo repository.
  La distribuzione avviene con update.sh sul Raspberry, non con git pull in /opt.
- Il repository contiene 63 file; in produzione ne sono installati 25 in /opt/rb-vecchi
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
- Powerline TP-Link dall'11/10/2026 (di nuovo, dopo la prova D-Link dal 24/09):
  in casa un adattatore senza Wi-Fi né interfaccia web, quindi senza IP; in garage
  un TL-WPA4220 con AP Wi-Fi integrato, 192.168.1.52 in DHCP (MAC 58:04:4F:51:1B:78),
  da cui passano entrambi gli Shelly.
- Il PLC casa non si può pingare: il riferimento lato casa è il router (.1).
  Un guasto del PLC casa si vede come .52 KO con il router ok.
- Dal TL-WPA4220 si misura solo il ping: nessun contatore PLC.
- D-Link DHP-W310AV (.66 casa, .67 garage) dismessi: i loro dati restano nei CSV
  storici. Se tornassero: da loro si legge solo st_stats.php (GET, senza login), mai
  hedwig.cgi, pigwidgeon.cgi o reboot.php (scrivono o riavviano); getcfg.php dà le
  password in chiaro e il suo output non va mai salvato, registrato né committato.
- Timestamp sempre dal Raspberry, mai dall'orologio degli adattatori.

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
- Due raccoglitori in raccolta/: rb-carica (energia Shelly .101) e rb-link (ping di
  router, PLC garage .52 e Shelly). rb-plc (contatori dei D-Link) è dismesso
  dall'11/10/2026: install-raccolta.sh ne ferma e rimuove unità e programma, i CSV
  rb-plc-*.csv restano e stato_rete.py li legge ancora per le finestre che li
  comprendono. Unità systemd permanenti separate
  dal basculante, utente di sistema rbraccolta, programmi in /opt/rb-raccolta,
  dati in /var/lib/rb-raccolta (RB_RACCOLTA_DIR).
- Un CSV al giorno per raccoglitore (data locale nel nome, intestazione in ogni
  file), ts in secondi epoch. Colonne di rb-carica e rb-plc da non cambiare.
- Sola lettura verso gli apparati: rb-carica solo Shelly.GetStatus e
  Shelly.GetDeviceInfo, rb-link solo ping. Stato ERR di rb-link = ping non eseguibile,
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
    rb-carica a ogni campione, con modello e firmware da GetDeviceInfo;
  - carica-registro.json: sessioni di ricarica degli ultimi 7 giorni (al massimo
    30), ricostruite dai CSV di rb-carica da raccolta/sessioni_carica.py. Una
    sessione va dalla chiusura all'apertura del relè; causa (programma /
    manuale / ritorno_corrente / gia_accesa), esito (fine_carica / senza_carica
    / interrotta / riavvio / in_corso), energia dal contatore. Un cambio che cade
    in un buco di dati ha l'orario approssimato e così è marcato.
  stato-rete.json, sistema.json e carica-registro.json li scrive il oneshot
  rb-stato-rete.service, lanciato ogni 60 s da rb-stato-rete.timer.
- rbvecchi legge SOLO file della raccolta in /var/lib/rb-raccolta, in sola
  lettura (rbvecchi/raccolta.py), da endpoint separati: /api/powerline,
  /api/carica, /api/carica/registro, /api/sistema. Unica eccezione di rete:
  POST /api/carica/avvia ("Carica ora": login, CSRF, al massimo una volta ogni
  30 s) chiude il relè dello Shelly .101 (PresaRicarica in rbvecchi/shelly.py,
  host CARICA_SHELLY_HOST, predefinito 192.168.1.101) e registra il comando nella
  tabella commands come CARICA_ON. Nessun altro client di rete dentro rbvecchi e
  nessuna chiamata in più allo Shelly .100: per il basculante si usa solo ciò
  che il monitor legge già. Nessuna analisi in rbvecchi, nessun effetto su
  /api/status, sul monitor o sulle notifiche. File assente, illeggibile, non
  valido o vecchio (carica-ultimo.json 60 s, gli altri 5 minuti) =
  "non disponibile".
- Pagine: principale (basculante, powerline, comando, ricarica con "Carica ora",
  statistiche, registro eventi, registro ricarica) e
  /dettagli (Shelly basculante, Shelly ricarica, powerline, Raspberry), con la
  stessa autenticazione. Nessun segreto nelle pagine.
- Il Wi-Fi dello Shelly misura solo il salto Shelly-AP, non la salute della
  catena: l'indicatore di rete della dashboard è il riquadro Powerline.
- Modifiche a static/: cambiare CACHE_NAME in service-worker.js, altrimenti il
  telefono continua a usare i file vecchi dalla cache.

## Shelly ricarica quadriciclo (192.168.1.101)
- Shelly 1PM Gen3 (S3SW-001P16EU), firmware 2.0.1. Il caricabatterie della Tazzari
  è alimentato attraverso il relè.
- Il relè lo comanda shelly/ricarica-notturna.js, che gira SULLO Shelly (installato
  a mano dalla pagina web: Scripts, "Run on startup"), più uno Schedule dello Shelly
  che chiude il relè ogni giorno alle 01:00. Ogni chiusura del relè (01:00, manuale,
  ritorno della corrente) apre una sessione: senza carica entro 5 min lo script apre
  il relè; dopo una carica lo apre quando la potenza resta sotto 20 W per 10 min.
  Fuori dalla carica il relè aperto è lo stato normale e la dashboard lo mostra
  come nota, non come avviso. Per cambiare lo script: si modifica il file nel
  repository e lo si reinstalla a mano sullo Shelly.
- RB-Vecchi fa una sola scrittura: Switch.Set {"id": 0, "on": true} da "Carica
  ora". Mai spegnere da RB-Vecchi (lo spegnimento è solo dello script), mai
  Switch.Toggle, SetConfig, Reboot, Script.*. Letture della raccolta:
  Shelly.GetStatus (rb-carica, ogni 10 s) e Shelly.GetDeviceInfo (rb-carica,
  all'avvio e poi ogni 6 ore).
- initial_state=on e in_mode=detached sono intenzionali: dopo un blackout il relè
  si richiude e lo script decide se c'è da caricare.
- Assorbimenti misurati l'11/10/2026: caricabatterie senza auto 1,3 W; standby a
  fine carica 7,8 W (circa 30 VA); carica 850-880 W con rampa finale di 2-3 min e
  stacco netto; ricariche brevi di mantenimento 225-235 W per circa 7 min (circa
  28 Wh), la prima 25 min dopo la fine; dopo una riaccensione con l'auto collegata
  la carica riparte entro 10 s.
- Timestamp dal Raspberry, non dall'orologio dello Shelly. Lo Schedule delle 01:00
  invece usa l'orologio dello Shelly, che deve essere sincronizzato.
- kWh solo da aenergy.total differenziato. Il codice deve riconoscere il riavvio
  (uptime che cala) e l'azzeramento del contatore (totale che cala).
- aenergy.total sopravvive a un'interruzione di corrente ma perde la frazione non
  ancora salvata (11/10/2026 alle 13:15: da 1301,66 a 1301,0 Wh).
