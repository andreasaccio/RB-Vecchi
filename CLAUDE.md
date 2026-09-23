# RB-Vecchi

Monitor del basculante del garage. Raspberry (Ubuntu 24.04, aarch64) + Shelly 1 Gen3.
Documentazione in docs/: handoff tecnico e stato accertato in produzione del 22/09/2026.

## Vincoli
- Il servizio gira da /opt/rb-vecchi come utente rbvecchi, NON da questo repository.
  La distribuzione avviene con update.sh sul Raspberry, non con git pull in /opt.
- Il repository contiene 35 file; in produzione ne sono installati 22 (vedi install.sh).
- Questo NON è un antifurto: serve a segnalare un basculante lasciato aperto per
  dimenticanza. Un buco di rete ritarda la segnalazione, non la annulla.
- In produzione INPUT_TRUE_IS_OPEN=false e RELAY_PULSE_SECONDS=0.5, diversi dai default.
- Lo Shelly è irraggiungibile a tratti (powerline). Ogni modifica deve tollerarlo.
- Non toccare mai /etc/rb-vecchi.env nel codice: contiene i segreti di produzione.
- Non aggiornare il firmware dello Shelly (1.7.5 installato, 2.0.0 disponibile).

## Lavori previsti
1. Notifica di irraggiungibilità CONDIZIONATA all'ultimo stato noto "aperto".
   Una notifica secca produrrebbe un messaggio al giorno: rumore inutile.
2. Correzione di state_since dopo un periodo cieco (oggi sottostima la durata).
3. Contabilizzazione ricarica quadriciclo con Shelly 1PM: usare SEMPRE il contatore
   cumulativo del dispositivo, mai la somma dei campioni di potenza.

## Deploy
Claude Code lavora sul Surface: scrive, committa e fa push su GitHub.
Sul Raspberry il deploy è manuale e richiede SEMPRE il pull:
  cd /home/pi/RB-Vecchi && git pull && sudo ./update.sh && ./verifica-produzione.sh
update.sh NON fa git pull: copia in /opt ciò che trova nel repository locale.
Se il commit stampato da verifica-produzione.sh non cambia, il deploy non è avvenuto.

## Verifica
./verifica-produzione.sh sul Raspberry confronta /opt con il repository.
