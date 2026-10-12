"use strict";

// Funzioni comuni a tutte le pagine, caricate prima dello script della pagina.
// Sono script classici: i nomi qui sotto sono globali e le pagine non li
// ridichiarano.

const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
const SVG_NS = "http://www.w3.org/2000/svg";
// Stessa soglia di SOGLIA_CARICA in raccolta/sessioni_carica.py e nello script
// sullo Shelly: sopra, il caricabatterie sta caricando.
const SOGLIA_CARICA_W = 100;
const CARICA_ORA_ATTESA_MS = 30000;
let toastTimer = null;

async function apiFetch(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
    ...options,
    headers: { Accept: "application/json", ...(options.headers || {}) },
  });
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("Sessione scaduta");
  }
  const payload = await response.json().catch(() => ({ ok: false, error: "Risposta non valida" }));
  if (!response.ok || payload.ok === false) throw new Error(payload.error || `Errore HTTP ${response.status}`);
  return payload;
}

function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("visible");
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 3600);
}

// Icona dallo sprite di base.html.
function svgIcon(nome) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#i-${nome}`);
  svg.append(use);
  return svg;
}

// Riga di elenco: icona tonda, titolo, sottotitolo e valore a destra.
function rigaElenco({ icona = "dot", tono = "", titolo, sotto = "", destra = "" }) {
  const row = document.createElement("article");
  row.className = "row";
  const box = document.createElement("div");
  box.className = `row-icon${tono ? ` ${tono}` : ""}`;
  box.append(svgIcon(icona));
  const main = document.createElement("div");
  const t = document.createElement("p");
  t.className = "row-title";
  t.textContent = titolo;
  main.append(t);
  if (sotto) {
    const s = document.createElement("p");
    s.className = "row-sub";
    s.textContent = sotto;
    main.append(s);
  }
  const end = document.createElement("div");
  end.className = "row-end";
  end.textContent = destra;
  row.append(box, main, end);
  return row;
}

function vuoto(testo) {
  const p = document.createElement("p");
  p.className = "empty";
  p.textContent = testo;
  return p;
}

// Etichetta breve dello stato della presa di ricarica, per il chip.
function statoPresa(carica) {
  if (carica?.stato !== "ok") return { testo: "Non disponibile", tono: "warn" };
  if (carica.rele_chiuso === false) return { testo: "Presa spenta", tono: "" };
  if (carica.potenza_W > SOGLIA_CARICA_W) return { testo: "In carica", tono: "info" };
  return { testo: "Presa accesa", tono: "ok" };
}

function impostaChip(el, testo, tono) {
  el.textContent = testo;
  el.className = `chip${tono ? ` ${tono}` : ""}`;
}

// «Carica ora»: accende la presa (solo accensione) e riabilita il pulsante
// dopo l'attesa minima.
async function caricaOra(bottone, dopo) {
  bottone.disabled = true;
  try {
    const payload = await apiFetch("/api/carica/avvia", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    });
    showToast(payload.message || "Presa accesa");
    if (dopo) dopo(true);
  } catch (error) {
    showToast(error.message || "Comando non riuscito", true);
    if (dopo) dopo(false);
  } finally {
    setTimeout(() => { bottone.disabled = false; }, CARICA_ORA_ATTESA_MS);
  }
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js").catch(console.warn));
}
