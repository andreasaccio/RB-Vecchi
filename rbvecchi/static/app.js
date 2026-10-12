"use strict";

// Pagina principale. apiFetch, showToast, svgIcon, rigaElenco, statoPresa,
// caricaOra e csrfToken vengono da common.js.

const elements = {
  garageCard: document.getElementById("garageCard"),
  garageState: document.getElementById("garageState"),
  stateSince: document.getElementById("stateSince"),
  staleWarning: document.getElementById("staleWarning"),
  connectionPill: document.getElementById("connectionPill"),
  pulseButton: document.getElementById("pulseButton"),
  confirmPulseButton: document.getElementById("confirmPulseButton"),
  commandDialog: document.getElementById("commandDialog"),
  dialogText: document.getElementById("dialogText"),
  openingsToday: document.getElementById("openingsToday"),
  openTimeToday: document.getElementById("openTimeToday"),
  powerlineCard: document.getElementById("powerlineCard"),
  powerlineState: document.getElementById("powerlineState"),
  powerlineReason: document.getElementById("powerlineReason"),
  powerlineAge: document.getElementById("powerlineAge"),
  powerlineAvailability: document.getElementById("powerlineAvailability"),
  powerlineLastEpisode: document.getElementById("powerlineLastEpisode"),
  caricaCard: document.getElementById("caricaCard"),
  caricaAge: document.getElementById("caricaAge"),
  caricaPower: document.getElementById("caricaPower"),
  caricaNote: document.getElementById("caricaNote"),
  caricaWarning: document.getElementById("caricaWarning"),
  caricaChip: document.getElementById("caricaChip"),
  caricaUltima: document.getElementById("caricaUltima"),
  caricaOraButton: document.getElementById("caricaOraButton"),
  eventList: document.getElementById("eventList"),
  eventCount: document.getElementById("eventCount"),
  eventMore: document.getElementById("eventMore"),
  headerClock: document.getElementById("headerClock"),
};

const EVENTI_BREVE = 8;
let latestStatus = null;
let requestRunning = false;
let ultimiEventi = [];
let eventiCompleti = false;

function formatDuration(totalSeconds, compact = false) {
  if (totalSeconds === null || totalSeconds === undefined || Number.isNaN(totalSeconds)) return "—";
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (days) return compact ? `${days}g ${hours}h` : `${days} giorni, ${hours} ore`;
  if (hours) return compact ? `${hours}h ${minutes}m` : `${hours} ore e ${minutes} min`;
  if (minutes) return compact ? `${minutes}m ${secs}s` : `${minutes} min e ${secs} s`;
  return `${secs} s`;
}

function formatEventDate(epochSeconds) {
  const date = new Date(epochSeconds * 1000);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  return new Intl.DateTimeFormat("it-IT", sameDay ? {
    hour: "2-digit", minute: "2-digit", second: "2-digit"
  } : {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"
  }).format(date);
}

function updateStatus(status) {
  latestStatus = status;
  const card = elements.garageCard;
  card.classList.remove("state-open", "state-closed", "state-offline", "state-unknown");

  if (!status.online) {
    card.classList.add("state-offline");
    elements.garageState.textContent = "Shelly non raggiungibile";
    elements.stateSince.textContent = status.last_error || "Connessione non disponibile";
    elements.connectionPill.textContent = "Offline";
    elements.connectionPill.className = "chip err";
    elements.pulseButton.disabled = true;
    elements.staleWarning.classList.remove("hidden");
    elements.staleWarning.textContent = status.last_success
      ? `Ultima lettura valida ${formatDuration(status.stale_seconds)} fa.`
      : "Nessuna lettura valida ricevuta.";
  } else if (status.garage_open === true) {
    card.classList.add("state-open");
    elements.garageState.textContent = "Aperto";
    elements.stateSince.textContent = `Da ${formatDuration(status.state_duration_seconds)}`;
    elements.connectionPill.textContent = "Online";
    elements.connectionPill.className = "chip ok";
    elements.pulseButton.disabled = !status.command_allowed;
    elements.staleWarning.classList.add("hidden");
  } else if (status.garage_open === false) {
    card.classList.add("state-closed");
    elements.garageState.textContent = "Chiuso";
    elements.stateSince.textContent = `Da ${formatDuration(status.state_duration_seconds)}`;
    elements.connectionPill.textContent = "Online";
    elements.connectionPill.className = "chip ok";
    elements.pulseButton.disabled = !status.command_allowed;
    elements.staleWarning.classList.add("hidden");
  } else {
    card.classList.add("state-unknown");
    elements.garageState.textContent = "Stato non disponibile";
    elements.stateSince.textContent = "In attesa della prima lettura…";
    elements.connectionPill.textContent = "Attesa";
    elements.connectionPill.className = "chip";
    elements.pulseButton.disabled = true;
  }

  if (status.online && status.safety_warning) {
    elements.staleWarning.classList.remove("hidden");
    elements.staleWarning.textContent = status.safety_warning;
  }
}

const POWERLINE_LABELS = {
  stabile: "Stabile",
  instabile: "Instabile",
  interrotta: "Interrotta",
  non_disponibile: "Non disponibile",
};

function formatPercent(value) {
  if (value === null || value === undefined) return "—";
  return `${new Intl.NumberFormat("it-IT", { maximumFractionDigits: 2 }).format(value)} %`;
}

function updatePowerline(powerline) {
  const state = POWERLINE_LABELS[powerline?.stato] ? powerline.stato : "non_disponibile";
  const card = elements.powerlineCard;
  card.classList.remove(...Object.keys(POWERLINE_LABELS).map((key) => `pl-${key}`));
  card.classList.add(`pl-${state}`);
  elements.powerlineState.textContent = POWERLINE_LABELS[state];
  elements.powerlineReason.textContent = powerline?.motivo || "Riepilogo non disponibile.";
  elements.powerlineAge.textContent = powerline?.eta_s === null || powerline?.eta_s === undefined
    ? ""
    : `agg. ${formatDuration(powerline.eta_s, true)} fa`;

  const garage = powerline?.garage;
  if (!garage) {
    elements.powerlineAvailability.textContent = "—";
    elements.powerlineLastEpisode.textContent = "—";
    return;
  }
  const extra = [];
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  if (garage.episodi_24h) extra.push(plural(garage.episodi_24h, "episodio", "episodi"));
  if (garage.perdite_isolate_24h) {
    extra.push(plural(garage.perdite_isolate_24h, "perdita isolata", "perdite isolate"));
  }
  elements.powerlineAvailability.textContent = formatPercent(garage.disponibilita_24h)
    + (extra.length ? ` · ${extra.join(", ")}` : "");

  const last = garage.ultimo_episodio;
  if (!last) {
    elements.powerlineLastEpisode.textContent = "nessuno nelle 24 h";
  } else if (last.in_corso) {
    elements.powerlineLastEpisode.textContent = `in corso dalle ${formatEventDate(last.inizio)}`;
  } else {
    elements.powerlineLastEpisode.textContent =
      `${formatEventDate(last.inizio)}, durata ${formatDuration(last.durata_s, true)}`;
  }
}

async function loadPowerline() {
  try {
    const payload = await apiFetch("/api/powerline");
    updatePowerline(payload.powerline);
  } catch (error) {
    updatePowerline({ stato: "non_disponibile", motivo: "Riepilogo non raggiungibile dalla dashboard." });
  }
}

function updateCarica(carica) {
  const available = carica?.stato === "ok";
  elements.caricaCard.classList.toggle("carica-non_disponibile", !available);
  elements.caricaAge.textContent = carica?.eta_s === null || carica?.eta_s === undefined
    ? ""
    : `agg. ${formatDuration(carica.eta_s, true)} fa`;
  const presa = statoPresa(carica);
  impostaChip(elements.caricaChip, presa.testo, presa.tono);
  if (!available) {
    elements.caricaPower.textContent = "—";
    elements.caricaNote.textContent = `Non disponibile: ${carica?.motivo || "dati della ricarica assenti"}.`;
    elements.caricaWarning.classList.add("hidden");
    return;
  }
  const watts = Math.round(carica.potenza_W);
  elements.caricaPower.textContent = new Intl.NumberFormat("it-IT").format(watts);
  elements.caricaNote.textContent = carica.nota
    || (watts === 0 ? "Nessun assorbimento" : "Potenza assorbita dal caricabatterie");
  elements.caricaWarning.textContent = carica.avviso || "";
  elements.caricaWarning.classList.toggle("hidden", !carica.avviso);
}

async function loadCarica() {
  try {
    const payload = await apiFetch("/api/carica");
    updateCarica(payload.carica);
  } catch (error) {
    updateCarica({ stato: "non_disponibile", motivo: "dati non raggiungibili dalla dashboard" });
  }
}

const CAUSE_CARICA = {
  programma: "programma delle 01:00",
  manuale: "accesa a mano",
  ritorno_corrente: "ritorno della corrente",
  gia_accesa: "già accesa",
};
const ESITI_CARICA = {
  fine_carica: "spenta a fine carica",
  senza_carica: "niente da caricare",
  interrotta: "spenta durante la carica",
  riavvio: "Shelly riavviato",
};

function formatWh(value) {
  if (value >= 1000) {
    return `${new Intl.NumberFormat("it-IT", { maximumFractionDigits: 2 }).format(value / 1000)} kWh`;
  }
  return `${new Intl.NumberFormat("it-IT", { maximumFractionDigits: value < 100 ? 1 : 0 }).format(value)} Wh`;
}

function sessionText(s, conEsito = true) {
  const circa = (flag) => (flag ? " circa" : "");
  const parts = [`${formatEventDate(s.inizio)}${circa(s.inizio_approssimato)}`];
  if (s.fine) parts[0] += ` → ${formatEventDate(s.fine)}${circa(s.fine_approssimata)}`;
  parts.push(CAUSE_CARICA[s.causa] || s.causa);
  if (conEsito && s.esito !== "in_corso") parts.push(ESITI_CARICA[s.esito] || s.esito);
  return parts.join(" · ");
}

function renderUltimaCarica(registro) {
  const ultima = registro?.stato === "ok" ? registro.sessioni[0] : null;
  if (registro?.stato !== "ok") {
    elements.caricaUltima.textContent = `Registro non disponibile: ${registro?.motivo || "dati assenti"}.`;
  } else if (!ultima) {
    elements.caricaUltima.textContent = "Nessuna accensione della presa negli ultimi 7 giorni.";
  } else {
    elements.caricaUltima.textContent = `Ultima: ${sessionText(ultima)}`
      + (ultima.carica_da && ultima.energia_Wh !== null ? ` · ${formatWh(ultima.energia_Wh)}` : "");
  }
}

async function loadRegistroCarica() {
  try {
    const payload = await apiFetch("/api/carica/registro");
    renderUltimaCarica(payload.registro);
  } catch (error) {
    renderUltimaCarica({ stato: "non_disponibile", motivo: "dati non raggiungibili dalla dashboard" });
  }
}

function sendCaricaOra() {
  caricaOra(elements.caricaOraButton, () => {
    setTimeout(loadCarica, 3000);
    setTimeout(loadRegistroCarica, 3000);
    setTimeout(loadRegistroCarica, 70000);
  });
}

function renderEvents(events) {
  ultimiEventi = Array.isArray(events) ? events : [];
  elements.eventCount.textContent = ultimiEventi.length ? `ultimi ${ultimiEventi.length}` : "";
  if (ultimiEventi.length === 0) {
    elements.eventList.replaceChildren(vuoto("Nessun evento registrato."));
    elements.eventMore.classList.add("hidden");
    return;
  }
  const visibili = eventiCompleti ? ultimiEventi : ultimiEventi.slice(0, EVENTI_BREVE);
  elements.eventList.replaceChildren(...visibili.map((event) => {
    let voce = { icona: "dot", tono: "", titolo: event.garage_open ? "Stato iniziale: aperto" : "Stato iniziale: chiuso" };
    if (event.event_type === "OPEN") voce = { icona: "up", tono: "warn", titolo: "Garage aperto" };
    else if (event.event_type === "CLOSE") voce = { icona: "down", tono: "ok", titolo: "Garage chiuso" };
    return rigaElenco({
      ...voce,
      sotto: formatEventDate(event.event_ts),
      destra: event.duration_seconds ? formatDuration(event.duration_seconds, true) : "",
    });
  }));
  const altri = ultimiEventi.length > EVENTI_BREVE;
  elements.eventMore.classList.toggle("hidden", !altri);
  elements.eventMore.textContent = eventiCompleti ? "Mostra solo gli ultimi" : `Mostra tutti i ${ultimiEventi.length} eventi`;
}

async function loadDashboard(showErrors = true) {
  if (requestRunning) return;
  requestRunning = true;
  try {
    const payload = await apiFetch("/api/dashboard");
    updateStatus(payload.status);
    elements.openingsToday.textContent = String(payload.stats.openings ?? 0);
    elements.openTimeToday.textContent = formatDuration(payload.stats.open_seconds, true);
    renderEvents(payload.events);
  } catch (error) {
    if (showErrors) showToast(error.message || "Aggiornamento non riuscito", true);
  } finally {
    requestRunning = false;
  }
}

async function loadStatus() {
  try {
    const payload = await apiFetch("/api/status");
    updateStatus(payload.status);
  } catch (error) {
    console.warn(error);
  }
}

async function sendPulse() {
  elements.confirmPulseButton.disabled = true;
  elements.pulseButton.disabled = true;
  try {
    const payload = await apiFetch("/api/garage/pulse", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    });
    showToast(payload.message || "Impulso inviato");
    if (navigator.vibrate) navigator.vibrate(40);
    setTimeout(loadStatus, 800);
  } catch (error) {
    showToast(error.message || "Comando non riuscito", true);
  } finally {
    elements.confirmPulseButton.disabled = false;
    setTimeout(() => {
      elements.pulseButton.disabled = !(latestStatus && latestStatus.command_allowed);
    }, 2500);
  }
}

elements.pulseButton?.addEventListener("click", () => {
  const state = latestStatus?.garage_open;
  elements.dialogText.textContent = state === true
    ? "Il garage risulta aperto. Verrà inviato un impulso passo-passo: verificare che l'area sia libera."
    : state === false
      ? "Il garage risulta chiuso. L'impulso passo-passo potrebbe avviare l'apertura."
      : "Verrà inviato un impulso passo-passo al basculante.";
  elements.commandDialog.showModal();
});

elements.commandDialog?.addEventListener("close", () => {
  if (elements.commandDialog.returnValue === "default") sendPulse();
});

elements.caricaOraButton?.addEventListener("click", sendCaricaOra);
elements.eventMore?.addEventListener("click", () => {
  eventiCompleti = !eventiCompleti;
  renderEvents(ultimiEventi);
});

function updateClock() {
  const adesso = new Intl.DateTimeFormat("it-IT", {
    weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit"
  }).format(new Date());
  if (elements.headerClock.textContent !== adesso) elements.headerClock.textContent = adesso;
  if (latestStatus?.online && latestStatus.state_since) {
    latestStatus.state_duration_seconds = Math.max(0, Math.floor(Date.now() / 1000 - latestStatus.state_since));
    elements.stateSince.textContent = `Da ${formatDuration(latestStatus.state_duration_seconds)}`;
  }
}

loadDashboard(true);
loadPowerline();
loadCarica();
loadRegistroCarica();
updateClock();
setInterval(loadStatus, 2500);
setInterval(loadPowerline, 30000);
setInterval(loadCarica, 10000);
setInterval(loadRegistroCarica, 60000);
setInterval(() => loadDashboard(false), 15000);
setInterval(updateClock, 1000);
