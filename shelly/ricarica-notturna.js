// RB-Vecchi - ricarica notturna della Tazzari (Shelly 1PM Gen3, 192.168.1.101)
// Gira SULLO Shelly: non dipende dalla rete ne' dal Raspberry.
//
// Ogni accensione del rele' apre una sessione: quella programmata alle 01:00
// (Schedule dello Shelly), una manuale dall'app o il ritorno della corrente
// dopo un blackout (initial_state=on).
//   prova:  entro ATTESA_AVVIO s la potenza deve superare SOGLIA_CARICA per
//           due campioni di fila, altrimenti spegne (niente da caricare, o
//           auto non collegata: 1,3 W).
//   carica: quando la potenza resta sotto SOGLIA_STANDBY per ATTESA_FINE s
//           di fila spegne. Una ricarica breve nel frattempo azzera l'attesa.
// Valori dai dati dell'11/10/2026: standby 7,8 W, carica 850-880 W, ricarica
// breve 225-235 W, prima ricarica breve 25 min dopo la fine; alla
// riaccensione la carica riparte entro 10 s.

let SOGLIA_CARICA = 100;   // W
let SOGLIA_STANDBY = 20;   // W
let ATTESA_AVVIO = 300;    // s
let ATTESA_FINE = 600;     // s
let PASSO = 10;            // s

let stato = "spento";      // spento | prova | carica
let tAcceso = 0;
let tSotto = -1;
let sopra = 0;

function log(testo) {
  print("ricarica: " + testo);
}

function spegni(motivo) {
  log("spengo, " + motivo);
  stato = "spento";
  Shelly.call("Switch.Set", { id: 0, on: false });
}

function giro() {
  let sw = Shelly.getComponentStatus("switch:0");
  let t = Shelly.getComponentStatus("sys").uptime;
  if (!sw.output) {
    if (stato !== "spento") log("rele' aperto da fuori, sessione chiusa");
    stato = "spento";
    return;
  }
  let p = sw.apower;
  if (stato === "spento") {
    stato = "prova";
    tAcceso = t;
    sopra = 0;
    log("rele' chiuso, attendo la carica");
  }
  if (stato === "prova") {
    if (p > SOGLIA_CARICA) {
      sopra = sopra + 1;
      if (sopra >= 2) {
        stato = "carica";
        tSotto = -1;
        log("carica in corso (" + p + " W)");
      }
    } else {
      sopra = 0;
      if (t - tAcceso >= ATTESA_AVVIO) spegni("nessuna carica partita (" + p + " W)");
    }
    return;
  }
  // stato === "carica"
  if (p < SOGLIA_STANDBY) {
    if (tSotto < 0) tSotto = t;
    if (t - tSotto >= ATTESA_FINE) spegni("fine carica (" + p + " W)");
  } else {
    tSotto = -1;
  }
}

Timer.set(PASSO * 1000, true, giro);
giro();
