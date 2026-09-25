"use strict";

const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
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
  eventList: document.getElementById("eventList"),
  telegramTestButton: document.getElementById("telegramTestButton"),
  telegramTestResult: document.getElementById("telegramTestResult"),
  footerClock: document.getElementById("footerClock"),
  toast: document.getElementById("toast"),
};

let latestStatus = null;
let toastTimer = null;
let requestRunning = false;

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

function formatDateTime(epochSeconds) {
  if (!epochSeconds) return "—";
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(epochSeconds * 1000));
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
    elements.connectionPill.className = "pill pill-offline";
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
    elements.connectionPill.className = "pill pill-online";
    elements.pulseButton.disabled = !status.command_allowed;
    elements.staleWarning.classList.add("hidden");
  } else if (status.garage_open === false) {
    card.classList.add("state-closed");
    elements.garageState.textContent = "Chiuso";
    elements.stateSince.textContent = `Da ${formatDuration(status.state_duration_seconds)}`;
    elements.connectionPill.textContent = "Online";
    elements.connectionPill.className = "pill pill-online";
    elements.pulseButton.disabled = !status.command_allowed;
    elements.staleWarning.classList.add("hidden");
  } else {
    card.classList.add("state-unknown");
    elements.garageState.textContent = "Stato non disponibile";
    elements.stateSince.textContent = "In attesa della prima lettura…";
    elements.connectionPill.textContent = "Attesa";
    elements.connectionPill.className = "pill pill-muted";
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
  if (!available) {
    elements.caricaPower.textContent = "—";
    elements.caricaNote.textContent = `Non disponibile: ${carica?.motivo || "dati della ricarica assenti"}.`;
    elements.caricaWarning.classList.add("hidden");
    return;
  }
  const watts = Math.round(carica.potenza_W);
  elements.caricaPower.textContent = new Intl.NumberFormat("it-IT").format(watts);
  elements.caricaNote.textContent = watts === 0 ? "Nessun assorbimento" : "Potenza assorbita dal caricabatterie";
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

function renderEvents(events) {
  if (!Array.isArray(events) || events.length === 0) {
    elements.eventList.innerHTML = '<p class="empty-state">Nessun evento registrato.</p>';
    return;
  }

  elements.eventList.replaceChildren(...events.map((event) => {
    const item = document.createElement("article");
    let typeClass = "event-initial";
    let icon = "•";
    let title = event.garage_open ? "Stato iniziale: aperto" : "Stato iniziale: chiuso";
    if (event.event_type === "OPEN") {
      typeClass = "event-open";
      icon = "↑";
      title = "Garage aperto";
    } else if (event.event_type === "CLOSE") {
      typeClass = "event-close";
      icon = "↓";
      title = "Garage chiuso";
    }
    item.className = `event-item ${typeClass}`;

    const iconBox = document.createElement("div");
    iconBox.className = "event-icon";
    iconBox.textContent = icon;

    const main = document.createElement("div");
    main.className = "event-main";
    const strong = document.createElement("strong");
    strong.textContent = title;
    const time = document.createElement("span");
    time.textContent = formatEventDate(event.event_ts);
    main.append(strong, time);

    const duration = document.createElement("div");
    duration.className = "event-duration";
    duration.textContent = event.duration_seconds ? formatDuration(event.duration_seconds, true) : "";

    item.append(iconBox, main, duration);
    return item;
  }));
}

function showToast(message, isError = false) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", isError);
  elements.toast.classList.add("visible");
  toastTimer = setTimeout(() => elements.toast.classList.remove("visible"), 3200);
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
    ...options,
    headers: {
      "Accept": "application/json",
      ...(options.headers || {}),
    },
  });
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("Sessione scaduta");
  }
  const payload = await response.json().catch(() => ({ ok: false, error: "Risposta non valida" }));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Errore HTTP ${response.status}`);
  }
  return payload;
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

const TELEGRAM_TEST_COOLDOWN_MS = 30000;

function showTelegramResult(message, isError) {
  elements.telegramTestResult.textContent = message;
  elements.telegramTestResult.classList.toggle("success", !isError);
  elements.telegramTestResult.classList.toggle("error", isError);
}

async function sendTelegramTest() {
  elements.telegramTestButton.disabled = true;
  elements.telegramTestResult.classList.remove("success", "error");
  elements.telegramTestResult.textContent = "Invio in corso…";
  let reenableAfter = TELEGRAM_TEST_COOLDOWN_MS;
  try {
    const payload = await apiFetch("/api/telegram/test", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    });
    const message = payload.message || "Messaggio di prova inviato";
    showTelegramResult(`${message} (${formatDateTime(Date.now() / 1000)})`, false);
    showToast(message);
  } catch (error) {
    const message = error.message || "Test Telegram non riuscito";
    showTelegramResult(message, true);
    showToast(message, true);
    reenableAfter = 2500;
  } finally {
    setTimeout(() => { elements.telegramTestButton.disabled = false; }, reenableAfter);
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

elements.telegramTestButton?.addEventListener("click", sendTelegramTest);

function updateClock() {
  elements.footerClock.textContent = new Intl.DateTimeFormat("it-IT", {
    weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"
  }).format(new Date());
  if (latestStatus?.online && latestStatus.state_since) {
    latestStatus.state_duration_seconds = Math.max(0, Math.floor(Date.now() / 1000 - latestStatus.state_since));
    elements.stateSince.textContent = `Da ${formatDuration(latestStatus.state_duration_seconds)}`;
  }
}

loadDashboard(true);
loadPowerline();
loadCarica();
updateClock();
setInterval(loadStatus, 2500);
setInterval(loadPowerline, 30000);
setInterval(loadCarica, 10000);
setInterval(() => loadDashboard(false), 15000);
setInterval(updateClock, 1000);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js").catch(console.warn));
}
