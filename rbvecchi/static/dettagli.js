"use strict";

// Pagina "Dettagli impianto": quattro sezioni indipendenti, ciascuna con la
// propria età dei dati e il proprio "non disponibile". Solo lettura.

const PASSO_MS = 10000;
const RESET_REASON = { 1: "accensione", 3: "riavvio software" };
const POWERLINE_LABELS = {
  stabile: "Stabile",
  instabile: "Instabile",
  interrotta: "Interrotta",
  non_disponibile: "Non disponibile",
};

function formatDuration(totalSeconds) {
  if (totalSeconds === null || totalSeconds === undefined || Number.isNaN(totalSeconds)) return "—";
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (days) return `${days}g ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${secs}s`;
  return `${secs} s`;
}

function formatDateTime(epochSeconds) {
  if (!epochSeconds) return "—";
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(new Date(epochSeconds * 1000));
}

function num(value, digits = 0, unit = "") {
  if (value === null || value === undefined) return "n/d";
  const text = new Intl.NumberFormat("it-IT", {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(value);
  return unit ? `${text} ${unit}` : text;
}

function gigabytes(bytes) {
  return num(bytes / 1e9, 1, "GB");
}

function usage(pair, usedKey, totalKey) {
  if (!pair || pair[usedKey] === null || pair[totalKey] === null || !pair[totalKey]) return "n/d";
  const percent = Math.round((100 * pair[usedKey]) / pair[totalKey]);
  return `${gigabytes(pair[usedKey])} di ${gigabytes(pair[totalKey])} (${percent} %)`;
}

function wifiLabel(rssi) {
  if (rssi === null || rssi === undefined) return "n/d";
  let quality = "Debole";
  if (rssi >= -55) quality = "Ottimo";
  else if (rssi >= -67) quality = "Buono";
  else if (rssi >= -75) quality = "Discreto";
  return `${quality} (${rssi} dBm)`;
}

function yesNo(value, yes, no) {
  if (value === null || value === undefined) return "n/d";
  return value ? yes : no;
}

async function apiFetch(url) {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
    headers: { "Accept": "application/json" },
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

// rows: [etichetta, valore, allarme?]; il valore va sempre in textContent.
function fillList(list, rows) {
  list.replaceChildren(...rows.map(([label, value, alarm]) => {
    const row = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    if (alarm) dd.classList.add("value-alarm");
    row.append(dt, dd);
    return row;
  }));
}

function renderSection(key, { age, note, noteIsAlarm = false, rows = [] }) {
  document.getElementById(`eta${key}`).textContent =
    age === null || age === undefined ? "non disponibile" : `agg. ${formatDuration(age)} fa`;
  const noteBox = document.getElementById(`nd${key}`);
  noteBox.textContent = note || "";
  noteBox.classList.toggle("hidden", !note);
  noteBox.classList.toggle("section-nd-alarm", Boolean(note) && noteIsAlarm);
  fillList(document.getElementById(`dl${key}`), rows);
}

function unavailable(key, reason) {
  renderSection(key, { age: null, note: `Non disponibile: ${reason}.` });
}

// ---------------------------------------------------------------- Shelly basculante

function renderBasculante(status) {
  const section = document.getElementById("sezBasculante");
  if (!status.last_success) {
    unavailable("Basculante", status.last_error || "nessuna lettura valida dallo Shelly");
    return;
  }
  const inputState = status.raw_input_state === null || status.raw_input_state === undefined
    ? "n/d"
    : (status.raw_input_state ? "attivo" : "a riposo");
  renderSection("Basculante", {
    age: status.stale_seconds,
    note: status.online ? "" : `Shelly non raggiungibile: valori dell'ultima lettura valida. ${status.last_error || ""}`,
    noteIsAlarm: !status.online,
    rows: [
      ["Collegamento", status.online ? "Online" : "Offline", !status.online],
      ["Indirizzo", section.dataset.indirizzo || "n/d"],
      ["Relè", yesNo(status.relay_output, "Attivo", "A riposo")],
      ["Input mode", status.switch_in_mode || "non verificato", status.switch_in_mode !== "detached"],
      ["Stato grezzo dell'ingresso", inputState],
      ["Temperatura", num(status.temperature_c, 1, "°C")],
      ["Wi-Fi Shelly (solo salto Shelly-AP)", wifiLabel(status.wifi_rssi)],
      ["Firmware", status.firmware || "n/d"],
      ["Uptime", formatDuration(status.uptime_seconds)],
      ["Ultimo aggiornamento", formatDateTime(status.last_success)],
      ["Avviso apertura", `dopo ${section.dataset.avviso} minuti`],
      ["Telegram", status.telegram_enabled ? "Attivo" : "Non configurato"],
    ],
  });
}

// ---------------------------------------------------------------- Shelly ricarica

function renderRicarica(carica) {
  if (carica.stato !== "ok") {
    renderSection("Ricarica", { age: carica.eta_s, note: `Non disponibile: ${carica.motivo}.` });
    return;
  }
  const resetLabel = carica.reset_reason === null || carica.reset_reason === undefined
    ? "n/d"
    : `${carica.reset_reason}${RESET_REASON[carica.reset_reason] ? ` (${RESET_REASON[carica.reset_reason]})` : ""}`;
  renderSection("Ricarica", {
    age: carica.eta_s,
    note: carica.avviso ? `Attenzione: ${carica.avviso}.` : "",
    noteIsAlarm: Boolean(carica.avviso),
    rows: [
      ["Potenza", num(carica.potenza_W, 1, "W")],
      ["Tensione", num(carica.tensione_V, 1, "V")],
      ["Corrente", num(carica.corrente_A, 3, "A")],
      ["Relè della presa", yesNo(carica.rele_chiuso, "chiuso (presa alimentata)", "APERTO"), carica.rele_chiuso === false],
      ["Temperatura", num(carica.temperatura_C, 1, "°C")],
      ["Uptime", formatDuration(carica.uptime_s)],
      ["Causa dell'ultimo avvio (reset_reason)", resetLabel],
      ["Wi-Fi", wifiLabel(carica.rssi)],
      ["AP (BSSID)", carica.bssid || "n/d"],
      ["Modello", carica.modello || "n/d"],
      ["Firmware", [carica.app, carica.firmware].filter(Boolean).join(" ") || "n/d"],
    ],
  });
}

// ---------------------------------------------------------------- Powerline

function renderAdattatori(plc) {
  const box = document.getElementById("plcAdattatori");
  const names = { casa: "PLC casa", garage: "PLC garage" };
  box.replaceChildren(...["casa", "garage"].filter((name) => plc && plc[name]).map((name) => {
    const a = plc[name];
    const s = a.ultimo_campione;
    const wrap = document.createElement("div");
    wrap.className = "plc-adapter";
    const title = document.createElement("h4");
    title.textContent = `${names[name]}${a.ip ? ` (${a.ip})` : ""}`;
    const list = document.createElement("dl");
    list.className = "details-list";
    const lastRead = a.ultima_lettura
      ? `${formatDateTime(a.ultima_lettura.ts)}, ${a.ultima_lettura.stato === "ok" ? "ok" : "non risponde"}`
      : "n/d";
    fillList(list, [
      ["Ultima lettura dei contatori", lastRead, a.ultima_lettura && a.ultima_lettura.stato !== "ok"],
      ["Pacchetti tx / rx", s ? `${num(s.tx_pkt)} / ${num(s.rx_pkt)}` : "n/d"],
      ["Byte tx / rx", s ? `${num(s.tx_byte)} / ${num(s.rx_byte)}` : "n/d"],
      ["Scartati tx / rx nelle 24 h", `${num(a.scartati_tx_24h)} / ${num(a.scartati_rx_24h)}`,
        Boolean(a.scartati_tx_24h || a.scartati_rx_24h)],
      ["Riavvii nelle 24 h", num(a.riavvii_24h), Boolean(a.riavvii_24h)],
      ["Ultimo riavvio (24 h)", a.ultimo_riavvio_24h ? formatDateTime(a.ultimo_riavvio_24h) : "nessuno"],
    ]);
    wrap.append(title, list);
    return wrap;
  }));
}

function renderPowerline(p) {
  if (p.stato === "non_disponibile" && !p.garage) {
    unavailable("Powerline", p.motivo || "riepilogo assente");
    renderAdattatori(null);
    return;
  }
  const g = p.garage || {};
  const last = g.ultimo_episodio;
  const lastText = !last
    ? "nessuno nelle 24 h"
    : (last.in_corso
      ? `in corso dalle ${formatDateTime(last.inizio)}`
      : `${formatDateTime(last.inizio)}, durata ${formatDuration(last.durata_s)}`);
  renderSection("Powerline", {
    age: p.eta_s,
    rows: [
      ["Stato", POWERLINE_LABELS[p.stato] || "Non disponibile", p.stato === "interrotta" || p.stato === "instabile"],
      ["Motivo", p.motivo || "—"],
      ["Disponibilità del .67 nelle 24 h", num(g.disponibilita_24h, 2, "%")],
      ["Episodi KO del .67 nelle 24 h", num(g.episodi_24h)],
      ["Perdite isolate del .67 nelle 24 h", num(g.perdite_isolate_24h)],
      ["Ultimo episodio", lastText],
      ["Pacchetti PLC scartati nelle 24 h", num(p.scartati_plc_24h), Boolean(p.scartati_plc_24h)],
      ["Riavvii degli adattatori nelle 24 h", num(p.riavvii_24h), Boolean(p.riavvii_24h)],
      ["Ultimo giro di ping", formatDateTime(p.ultimo_giro)],
      ["Tempo di calcolo del riepilogo", num(p.calcolo_ms, 0, "ms")],
    ],
  });
  renderAdattatori(p.plc);
}

// ---------------------------------------------------------------- Raspberry

function renderRaspberry(s) {
  if (s.stato !== "ok") {
    unavailable("Raspberry", s.motivo);
    return;
  }
  const load = s.carico
    ? `${num(s.carico["1min"], 2)} · ${num(s.carico["5min"], 2)} · ${num(s.carico["15min"], 2)}`
    : "n/d";
  const rows = [
    ["Carico 1 / 5 / 15 min", load],
    ["Temperatura CPU", num(s.temperatura_cpu_C, 1, "°C"), s.temperatura_cpu_C >= 75],
    ["RAM usata", usage(s.memoria, "usata_B", "totale_B")],
    ["Disco / usato", usage(s.disco_radice, "usato_B", "totale_B")],
    ["Uptime", formatDuration(s.uptime_s)],
    ["Kernel", s.kernel || "n/d"],
    ["Riavvio richiesto", yesNo(s.riavvio_richiesto, "sì", "no"), s.riavvio_richiesto === true],
  ];
  Object.entries(s.unita || {}).forEach(([unit, state]) => {
    rows.push([unit, state || "n/d", state !== "active"]);
  });
  renderSection("Raspberry", { age: s.eta_s, rows });
}

// ---------------------------------------------------------------- caricamento

async function loadSection(url, key, render, pick) {
  try {
    render(pick(await apiFetch(url)));
  } catch (error) {
    unavailable(key, "dati non raggiungibili dalla pagina");
  }
}

function loadAll() {
  loadSection("/api/status", "Basculante", renderBasculante, (p) => p.status);
  loadSection("/api/carica", "Ricarica", renderRicarica, (p) => p.carica);
  loadSection("/api/powerline", "Powerline", renderPowerline, (p) => p.powerline);
  loadSection("/api/sistema", "Raspberry", renderRaspberry, (p) => p.sistema);
}

function updateClock() {
  document.getElementById("footerClock").textContent = new Intl.DateTimeFormat("it-IT", {
    weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  }).format(new Date());
}

document.getElementById("refreshButton").addEventListener("click", loadAll);
loadAll();
updateClock();
setInterval(loadAll, PASSO_MS);
setInterval(updateClock, 1000);
