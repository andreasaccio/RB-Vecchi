"use strict";

// Pagina /ricarica: consumi, grafici, registro, prezzo e bollette. Tutti i testi
// che arrivano dai dati passano da textContent; i grafici sono SVG con soli
// attributi (niente stili in linea, per la Content-Security-Policy).
// apiFetch, showToast, svgIcon, rigaElenco, vuoto, statoPresa, caricaOra e
// csrfToken vengono da common.js.

const NS = SVG_NS;
const $ = (id) => document.getElementById(id);
const tip = $("chartTip");
let dati = null;
let comandi = [];
let registroCompleto = false;
const REGISTRO_BREVE = 10;

const CAUSE = {
  programma: "programma delle 01:00",
  manuale: "accesa a mano",
  ritorno_corrente: "ritorno della corrente",
  gia_accesa: "già accesa",
};
const ESITI = {
  fine_carica: "spenta a fine carica",
  senza_carica: "niente da caricare",
  interrotta: "spenta durante la carica",
  riavvio: "Shelly riavviato",
  in_corso: "in corso",
};

// ---------------------------------------------------------------- formati

function numero(value, decimals = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("it-IT", {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  }).format(value);
}
const kwh = (v, d = 3) => `${numero(v, d)} kWh`;
const euro = (v) => `${numero(v, 2)} €`;

function ora(ts, seconds = false) {
  if (!ts) return "—";
  return new Intl.DateTimeFormat("it-IT", seconds
    ? { hour: "2-digit", minute: "2-digit", second: "2-digit" }
    : { hour: "2-digit", minute: "2-digit" }).format(new Date(ts * 1000));
}
function giornoBreve(ts) {
  return new Intl.DateTimeFormat("it-IT", { weekday: "short", day: "2-digit", month: "2-digit" })
    .format(new Date(ts * 1000));
}
function dataIt(iso) {
  const [a, m, g] = iso.split("-");
  return `${g}/${m}/${a}`;
}
function dataOra(ts) {
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(ts * 1000));
}
function durata(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${s} s`;
}
const MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
const MESI_LUNGHI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
  "agosto", "settembre", "ottobre", "novembre", "dicembre"];

// ---------------------------------------------------------------- presa adesso

function renderPresa(c) {
  const ok = c?.stato === "ok";
  $("caricaCard").classList.toggle("carica-non_disponibile", !ok);
  const presa = statoPresa(c);
  impostaChip($("caricaChip"), presa.testo, presa.tono);
  $("caricaAge").textContent = c?.eta_s === null || c?.eta_s === undefined ? "" : `agg. ${durata(c.eta_s)} fa`;
  $("caricaPower").textContent = ok ? new Intl.NumberFormat("it-IT").format(Math.round(c.potenza_W)) : "—";
  let nota = ok ? (c.nota || (Math.round(c.potenza_W) === 0 ? "Nessun assorbimento" : "Potenza assorbita dal caricabatterie"))
    : `Non disponibile: ${c?.motivo || "dati della ricarica assenti"}.`;
  if (ok && c.avviso) nota = `Attenzione: ${c.avviso}`;
  $("caricaNote").textContent = nota;
}

async function caricaPresa() {
  try {
    renderPresa((await apiFetch("/api/carica")).carica);
  } catch (error) {
    renderPresa({ stato: "non_disponibile", motivo: "dati non raggiungibili dalla pagina" });
  }
}

// ---------------------------------------------------------------- tooltip

function mostraTip(righe, x, y) {
  tip.replaceChildren(...righe.map((testo, i) => {
    const el = document.createElement(i === 0 ? "strong" : "span");
    el.textContent = testo;
    if (i > 0 && i < righe.length - 1) el.append(document.createElement("br"));
    return el;
  }));
  tip.classList.remove("hidden");
  const w = tip.offsetWidth;
  const h = tip.offsetHeight;
  tip.style.left = `${Math.min(Math.max(8, x - w / 2), window.innerWidth - w - 8)}px`;
  tip.style.top = `${Math.max(8, y - h - 12)}px`;
}
function nascondiTip() { tip.classList.add("hidden"); }

function svgEl(name, attrs = {}) {
  const el = document.createElementNS(NS, name);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v)));
  return el;
}

function passoTondo(massimo, tacche = 4) {
  if (!(massimo > 0)) return 1;
  const grezzo = massimo / tacche;
  const potenza = 10 ** Math.floor(Math.log10(grezzo));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * potenza >= grezzo) return m * potenza;
  return 10 * potenza;
}

// ---------------------------------------------------------------- grafico a colonne

function graficoColonne(box, voci, { decimaliTacche = 1, unita = "kWh", etichetta = null, ogni = 1 }) {
  box.replaceChildren();
  if (!voci.length) {
    const vuoto = document.createElement("p");
    vuoto.className = "chart-vuoto";
    vuoto.textContent = "Nessun dato ancora.";
    box.append(vuoto);
    return;
  }
  const W = Math.max(280, box.clientWidth || 600);
  const H = 190;
  const sx = 40, dx = 6, su = 18, giu = 24;
  const pw = W - sx - dx;
  const ph = H - su - giu;
  const massimo = Math.max(...voci.map((v) => v.valore), 0);
  const passo = passoTondo(massimo);
  const tetto = Math.max(passo, Math.ceil(massimo / passo) * passo);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H });

  for (let v = 0; v <= tetto + 1e-9; v += passo) {
    const y = su + ph - (ph * v) / tetto;
    svg.append(svgEl("line", { class: v === 0 ? "axis" : "grid", x1: sx, x2: W - dx, y1: y, y2: y }));
    const t = svgEl("text", { class: "tick", x: sx - 6, y: y + 4, "text-anchor": "end" });
    t.textContent = numero(v, v === 0 ? 0 : decimaliTacche);
    svg.append(t);
  }

  const banda = pw / voci.length;
  const larghezza = Math.max(1, Math.min(24, banda - 2));
  voci.forEach((voce, i) => {
    const x = sx + i * banda + (banda - larghezza) / 2;
    const base = su + ph;
    const h = voce.valore > 0 ? Math.max(1.5, (ph * voce.valore) / tetto) : 0;
    let barra = null;
    if (h > 0) {
      const r = Math.min(4, larghezza / 2, h);
      const y = base - h;
      barra = svgEl("path", {
        class: "bar",
        d: `M${x},${base} V${y + r} Q${x},${y} ${x + r},${y} H${x + larghezza - r} `
          + `Q${x + larghezza},${y} ${x + larghezza},${y + r} V${base} Z`,
      });
      svg.append(barra);
    }
    // un'etichetta ogni "ogni" colonne, più l'ultima se non è troppo vicina
    if (i % ogni === 0 || (i === voci.length - 1 && i % ogni >= ogni / 2)) {
      const t = svgEl("text", { class: "tick", x: sx + i * banda + banda / 2, y: H - 6, "text-anchor": "middle" });
      t.textContent = voce.asse;
      svg.append(t);
    }
    if (etichetta === i && voce.valore > 0) {
      const t = svgEl("text", { class: "etichetta", x: x + larghezza / 2, y: base - h - 6, "text-anchor": "middle" });
      t.textContent = numero(voce.valore, 1);
      svg.append(t);
    }
    const hit = svgEl("rect", { class: "hit", x: sx + i * banda, y: su, width: banda, height: ph, tabindex: 0 });
    hit.setAttribute("aria-label", `${voce.titolo}: ${numero(voce.valore, 3)} ${unita}`);
    const accendi = (cx, cy) => {
      barra?.classList.add("attivo");
      mostraTip([`${numero(voce.valore, 3)} ${unita}`, voce.titolo, ...(voce.extra || [])], cx, cy);
    };
    const spegni = () => { barra?.classList.remove("attivo"); nascondiTip(); };
    hit.addEventListener("pointermove", (e) => accendi(e.clientX, e.clientY));
    hit.addEventListener("pointerleave", spegni);
    hit.addEventListener("focus", () => {
      const r = hit.getBoundingClientRect();
      accendi(r.left + r.width / 2, r.top + r.height / 2);
    });
    hit.addEventListener("blur", spegni);
    svg.append(hit);
  });
  box.append(svg);
}

// ---------------------------------------------------------------- grafico a linea

function graficoProfilo(box, profilo) {
  box.replaceChildren();
  if (!profilo || !profilo.punti?.length) {
    const vuoto = document.createElement("p");
    vuoto.className = "chart-vuoto";
    vuoto.textContent = "Nessuna carica registrata.";
    box.append(vuoto);
    return;
  }
  const punti = profilo.punti;
  const W = Math.max(280, box.clientWidth || 600);
  const H = 200;
  const sx = 44, dx = 8, su = 14, giu = 24;
  const pw = W - sx - dx;
  const ph = H - su - giu;
  const t0 = punti[0][0];
  const t1 = Math.max(punti[punti.length - 1][0], t0 + 60);
  const massimo = Math.max(...punti.map((p) => p[1]), 0);
  const passo = passoTondo(massimo);
  const tetto = Math.max(passo, Math.ceil(massimo / passo) * passo);
  const X = (t) => sx + (pw * (t - t0)) / (t1 - t0);
  const Y = (w) => su + ph - (ph * w) / tetto;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H });

  for (let v = 0; v <= tetto + 1e-9; v += passo) {
    svg.append(svgEl("line", { class: v === 0 ? "axis" : "grid", x1: sx, x2: W - dx, y1: Y(v), y2: Y(v) }));
    const t = svgEl("text", { class: "tick", x: sx - 6, y: Y(v) + 4, "text-anchor": "end" });
    t.textContent = numero(v, 0);
    svg.append(t);
  }
  const tacche = 4;
  for (let i = 0; i <= tacche; i += 1) {
    const ts = t0 + ((t1 - t0) * i) / tacche;
    const t = svgEl("text", {
      class: "tick", x: X(ts), y: H - 6,
      "text-anchor": i === 0 ? "start" : i === tacche ? "end" : "middle",
    });
    t.textContent = ora(ts);
    svg.append(t);
  }

  const linea = punti.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ");
  svg.append(svgEl("path", { class: "area", d: `${linea} L${X(punti[punti.length - 1][0])},${Y(0)} L${X(t0)},${Y(0)} Z` }));
  svg.append(svgEl("path", { class: "linea", d: linea }));

  const mirino = svgEl("line", { class: "mirino hidden", x1: 0, x2: 0, y1: su, y2: su + ph });
  const punto = svgEl("circle", { class: "punto hidden", r: 4, cx: 0, cy: 0 });
  svg.append(mirino, punto);
  const overlay = svgEl("rect", { class: "hit", x: sx, y: su, width: pw, height: ph, tabindex: 0 });
  overlay.setAttribute("aria-label", "Potenza minuto per minuto: frecce per scorrere");
  let indice = punti.length - 1;
  const segna = (i, cx, cy) => {
    indice = Math.max(0, Math.min(punti.length - 1, i));
    const [ts, w] = punti[indice];
    mirino.setAttribute("x1", X(ts)); mirino.setAttribute("x2", X(ts));
    punto.setAttribute("cx", X(ts)); punto.setAttribute("cy", Y(w));
    mirino.classList.remove("hidden"); punto.classList.remove("hidden");
    const r = svg.getBoundingClientRect();
    mostraTip([`${numero(w, 0)} W`, `ore ${ora(ts)}`],
      cx ?? r.left + (X(ts) / W) * r.width, cy ?? r.top + (Y(w) / H) * r.height);
  };
  const vicino = (clientX) => {
    const r = svg.getBoundingClientRect();
    const ts = t0 + ((((clientX - r.left) / r.width) * W - sx) / pw) * (t1 - t0);
    let migliore = 0;
    punti.forEach((p, i) => { if (Math.abs(p[0] - ts) < Math.abs(punti[migliore][0] - ts)) migliore = i; });
    return migliore;
  };
  const spegni = () => { mirino.classList.add("hidden"); punto.classList.add("hidden"); nascondiTip(); };
  overlay.addEventListener("pointermove", (e) => segna(vicino(e.clientX), e.clientX, e.clientY));
  overlay.addEventListener("pointerleave", spegni);
  overlay.addEventListener("focus", () => segna(indice));
  overlay.addEventListener("blur", spegni);
  overlay.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      segna(indice + (e.key === "ArrowLeft" ? -1 : 1));
    }
  });
  svg.append(overlay);
  box.append(svg);
}

// ---------------------------------------------------------------- tabelle

function tabella(box, intestazioni, righe) {
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const tr = document.createElement("tr");
  intestazioni.forEach((h) => { const th = document.createElement("th"); th.textContent = h; tr.append(th); });
  thead.append(tr);
  const tbody = document.createElement("tbody");
  righe.forEach((valori) => {
    const r = document.createElement("tr");
    valori.forEach((v) => { const td = document.createElement("td"); td.textContent = v; r.append(td); });
    tbody.append(r);
  });
  table.append(thead, tbody);
  box.replaceChildren(table);
}

// ---------------------------------------------------------------- sezioni

function ultimiGiorni(giorni, n) {
  const perGiorno = new Map(giorni.map((g) => [g.giorno, g]));
  const out = [];
  const oggi = new Date();
  for (let i = n - 1; i >= 0; i -= 1) {
    const d = new Date(oggi.getFullYear(), oggi.getMonth(), oggi.getDate() - i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    out.push({ iso, d, dato: perGiorno.get(iso) || null });
  }
  return out;
}

function ultimiMesi(mesi, n) {
  const perMese = new Map(mesi.map((m) => [m.mese, m]));
  const out = [];
  const oggi = new Date();
  for (let i = n - 1; i >= 0; i -= 1) {
    const d = new Date(oggi.getFullYear(), oggi.getMonth() - i, 1);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    out.push({ iso, d, dato: perMese.get(iso) || null });
  }
  return out;
}

function renderRiepilogo(d) {
  const r = d.riepilogo;
  $("statOggi").textContent = kwh(r.oggi.kWh, 2);
  $("statOggiEuro").textContent = euro(r.oggi.euro);
  $("statMese").textContent = kwh(r.mese.kWh, 2);
  $("statMeseEuro").textContent = euro(r.mese.euro);
  $("statBimestre").textContent = r.bimestre.kWh === null ? "—" : kwh(r.bimestre.kWh, 2);
  $("statBimestreEuro").textContent = r.bimestre.euro === null ? "—" : `${euro(r.bimestre.euro)} stimati`;
  $("titoloBimestre").textContent = `Bimestre ${r.bimestre.titolo}`;
  const c = d.consumi;
  $("etaConsumi").textContent = c.eta_s === null || c.eta_s === undefined
    ? "non disponibile" : `agg. ${durata(c.eta_s)} fa`;
  const parti = [`Prezzo attuale ${numero(d.prezzo_attuale, 3)} €/kWh`];
  if (c.contatore) parti.push(`contatore Shelly ${numero(c.contatore.Wh / 1000, 3)} kWh`);
  $("notaPrezzo").textContent = parti.join(" · ");
  const nd = $("ndConsumi");
  nd.textContent = c.stato === "ok" ? "" : `Dati della raccolta non disponibili: ${c.motivo}.`;
  nd.classList.toggle("hidden", c.stato === "ok");
}

function renderGrafici(d) {
  const giorni = ultimiGiorni(d.giorni, 60);
  graficoColonne($("graficoGiorni"), giorni.map(({ d: data, dato }) => ({
    valore: dato ? dato.kWh : 0,
    asse: `${data.getDate()}/${data.getMonth() + 1}`,
    titolo: giornoBreve(data.getTime() / 1000),
    extra: dato ? [euro(dato.euro)] : ["nessun dato"],
  })), { decimaliTacche: 1, ogni: 10 });
  tabella($("tabellaGiorni"), ["Giorno", "kWh", "€"], giorni.slice().reverse()
    .filter((g) => g.dato)
    .map((g) => [dataIt(g.iso), numero(g.dato.kWh, 3), numero(g.dato.euro, 2)]));

  const mesi = ultimiMesi(d.mesi, 12);
  graficoColonne($("graficoMesi"), mesi.map(({ d: data, dato }) => ({
    valore: dato ? dato.kWh : 0,
    asse: MESI[data.getMonth()],
    titolo: `${MESI_LUNGHI[data.getMonth()]} ${data.getFullYear()}`,
    extra: dato ? [euro(dato.euro)] : ["nessun dato"],
  })), { decimaliTacche: 0, etichetta: mesi.length - 1 });
  tabella($("tabellaMesi"), ["Mese", "kWh", "€"], mesi.slice().reverse()
    .filter((m) => m.dato)
    .map((m) => [`${MESI_LUNGHI[m.d.getMonth()]} ${m.d.getFullYear()}`, numero(m.dato.kWh, 3), numero(m.dato.euro, 2)]));

  const profilo = d.consumi.profilo;
  graficoProfilo($("graficoProfilo"), profilo);
  const sessione = profilo && (d.consumi.sessioni || []).find((s) => s.inizio === profilo.inizio);
  if (!profilo) {
    $("riassuntoProfilo").textContent = "Il grafico compare dopo la prima carica registrata.";
  } else {
    const parti = [`Accesa ${giornoBreve(profilo.inizio)} alle ${ora(profilo.inizio)}`];
    if (sessione) {
      parti.push(sessione.fine ? `spenta alle ${ora(sessione.fine)}` : "in corso");
      parti.push(kwh(sessione.energia_Wh / 1000, 3), euro(sessione.euro), `picco ${numero(sessione.potenza_max_W, 0)} W`);
    }
    $("riassuntoProfilo").textContent = parti.join(" · ");
  }
}

function tempo(dt, testo) {
  const div = document.createElement("div");
  const t = document.createElement("dt");
  t.textContent = dt;
  const v = document.createElement("dd");
  v.textContent = testo;
  div.append(t, v);
  return div;
}

function rigaComando(c) {
  return rigaElenco({
    icona: "bolt",
    tono: c.ok ? "info" : "err",
    titolo: c.ok ? "Carica ora dall'app" : "Carica ora non riuscita",
    sotto: `${giornoBreve(c.ts)} alle ${ora(c.ts, true)}${c.dettaglio ? ` · ${c.dettaglio}` : ""}`,
  });
}

function renderRegistro(sessioni) {
  const box = $("registroDettagliato");
  // i comandi più vecchi della prima sessione in elenco restano fuori
  const limite = sessioni.length ? sessioni[sessioni.length - 1].inizio - 3600 : 0;
  const voci = [
    ...sessioni.map((s) => ({ ts: s.inizio, s })),
    ...comandi.filter((c) => c.ts >= limite).map((c) => ({ ts: c.ts, c })),
  ].sort((a, b) => b.ts - a.ts);
  if (!voci.length) {
    box.replaceChildren(vuoto("Nessuna accensione registrata."));
    return;
  }
  const visibili = registroCompleto ? voci : voci.slice(0, REGISTRO_BREVE);
  box.replaceChildren(...visibili.map(({ s, c }) => {
    if (c) return rigaComando(c);
    const art = document.createElement("article");
    art.className = "sessione";
    const testa = document.createElement("div");
    testa.className = "sessione-testa";
    const titolo = document.createElement("strong");
    if (s.esito === "in_corso") titolo.textContent = s.in_carica ? "In carica" : "Presa accesa";
    else if (s.carica_da) titolo.textContent = `${kwh(s.energia_Wh / 1000, 3)} · ${euro(s.euro)}`;
    else titolo.textContent = `Niente da caricare · ${kwh(s.energia_Wh / 1000, 3)}`;
    const quando = document.createElement("span");
    quando.textContent = giornoBreve(s.inizio);
    testa.append(titolo, quando);

    const dl = document.createElement("dl");
    dl.className = "tempi";
    const circa = (flag) => (flag ? " ~" : "");
    dl.append(
      tempo("Accesa", `${ora(s.inizio)}${circa(s.inizio_approssimato)}`),
      tempo("In carica", !s.carica_da ? "—"
        : s.carica_a && s.esito !== "in_corso" ? `${ora(s.carica_da)}–${ora(s.carica_a)}`
          : `dalle ${ora(s.carica_da)}`),
      tempo("Spenta", s.fine ? `${ora(s.fine)}${circa(s.fine_approssimata)}` : "—"),
    );
    const nota = document.createElement("p");
    nota.className = "sessione-nota";
    const parti = [CAUSE[s.causa] || s.causa, ESITI[s.esito] || s.esito];
    if (s.fine) parti.push(`durata ${durata(s.fine - s.inizio)}`);
    if (s.carica_da) parti.push(`picco ${numero(s.potenza_max_W, 0)} W`);
    nota.textContent = parti.join(" · ");
    const icona = document.createElement("div");
    const tono = s.esito === "in_corso" ? "info" : s.carica_da ? "ok" : "";
    icona.className = `row-icon${tono ? ` ${tono}` : ""}`;
    icona.append(svgIcon(s.carica_da || s.esito === "in_corso" ? "bolt" : "power"));
    const corpo = document.createElement("div");
    corpo.append(testa, dl, nota);
    art.append(icona, corpo);
    return art;
  }));
  if (voci.length > REGISTRO_BREVE) {
    const altre = document.createElement("button");
    altre.type = "button";
    altre.className = "link-more rows-more";
    altre.textContent = registroCompleto ? `Mostra solo le ultime ${REGISTRO_BREVE} voci`
      : `Mostra tutte le ${voci.length} voci`;
    altre.addEventListener("click", () => {
      registroCompleto = !registroCompleto;
      renderRegistro(sessioni);
    });
    box.append(altre);
  }
}

function renderPrezzo(d) {
  $("prezzoAttuale").textContent = `${numero(d.prezzo_attuale, 3)} €/kWh`;
  const input = $("prezzoInput");
  if (document.activeElement !== input) input.value = String(d.prezzo_attuale);
  const dal = $("prezzoDal");
  dal.min = d.prezzo_dal_minimo;
  if (!dal.value) {
    const oggi = new Date();
    dal.value = `${oggi.getFullYear()}-${String(oggi.getMonth() + 1).padStart(2, "0")}-${String(oggi.getDate()).padStart(2, "0")}`;
  }
  const dl = $("storicoPrezzi");
  if (!d.tariffe.length) {
    dl.replaceChildren(tempo("Prezzo predefinito", `${numero(d.prezzo_predefinito, 3)} €/kWh, mai modificato`));
    return;
  }
  dl.replaceChildren(...d.tariffe.slice().reverse().map((t) => tempo(`dal ${dataIt(t.dal)}`, `${numero(t.eur_kwh, 3)} €/kWh`)));
}

function renderBollette(bollette) {
  const box = $("elencoBollette");
  if (!bollette.length) {
    box.replaceChildren(vuoto("Nessuna bolletta."));
    return;
  }
  box.replaceChildren(...bollette.map((b) => {
    const riga = document.createElement("article");
    riga.className = "bolletta";
    const testo = document.createElement("div");
    const titolo = document.createElement("p");
    titolo.className = "bolletta-titolo";
    titolo.textContent = b.titolo.charAt(0).toUpperCase() + b.titolo.slice(1);
    const stato = document.createElement("p");
    stato.className = "bolletta-stato";
    if (b.stato === "in_corso") stato.textContent = "Bimestre in corso: anteprima";
    else if (b.stato === "da_emettere") stato.textContent = "Da emettere: invio automatico il 1° del bimestre alle 09:00";
    else if (b.stato === "inviata") {
      stato.textContent = `Inviata su Telegram il ${dataOra(b.inviata_ts)}`;
      stato.classList.add("ok");
    } else {
      stato.textContent = `Non inviata${b.ultimo_esito ? `: ${b.ultimo_esito}` : ""}`;
      stato.classList.add("err");
    }
    if (b.parziale) stato.textContent += " · periodo parziale";
    testo.append(titolo, stato);

    const importo = document.createElement("div");
    importo.className = "bolletta-importo";
    importo.textContent = b.euro === null ? "—" : euro(b.euro);
    const sotto = document.createElement("small");
    sotto.textContent = b.kWh === null ? "" : kwh(b.kWh, 3);
    importo.append(sotto);

    const azioni = document.createElement("div");
    azioni.className = "bolletta-azioni";
    const pdf = document.createElement("a");
    pdf.className = "btn btn-secondary";
    pdf.href = `/ricarica/bolletta/${encodeURIComponent(b.periodo)}.pdf`;
    pdf.target = "_blank";
    pdf.rel = "noopener";
    pdf.append(svgIcon("file"), b.stato === "in_corso" || b.stato === "da_emettere" ? "Anteprima PDF" : "PDF");
    azioni.append(pdf);
    if (b.stato !== "in_corso") {
      const invia = document.createElement("button");
      invia.type = "button";
      invia.className = "btn btn-secondary";
      invia.append(svgIcon("send"), b.stato === "inviata" ? "Reinvia su Telegram" : "Invia su Telegram");
      invia.addEventListener("click", () => inviaBolletta(b, invia));
      azioni.append(invia);
    }
    riga.append(testo, importo, azioni);
    return riga;
  }));
}

// ---------------------------------------------------------------- azioni

async function inviaBolletta(b, bottone) {
  const domanda = b.stato === "inviata"
    ? `Reinviare su Telegram la bolletta ${b.titolo}?`
    : `Emettere e inviare su Telegram la bolletta ${b.titolo}? Una volta emessa non cambia più.`;
  if (!window.confirm(domanda)) return;
  bottone.disabled = true;
  try {
    const payload = await apiFetch(`/api/ricarica/bolletta/${encodeURIComponent(b.periodo)}/invia`, {
      method: "POST", headers: { "X-CSRF-Token": csrfToken },
    });
    showToast(payload.message || "Bolletta inviata");
    carica();
  } catch (error) {
    showToast(error.message || "Invio non riuscito", true);
    bottone.disabled = false;
  }
}

$("prezzoForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const valore = $("prezzoInput").value;
  const dal = $("prezzoDal").value;
  if (!window.confirm(`Impostare ${valore} €/kWh dal ${dataIt(dal)}?`)) return;
  try {
    const payload = await apiFetch("/api/ricarica/prezzo", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken, "Content-Type": "application/json" },
      body: JSON.stringify({ eur_kwh: valore, dal }),
    });
    showToast(payload.message || "Prezzo salvato");
    $("prezzoInput").blur();
    carica();
  } catch (error) {
    showToast(error.message || "Prezzo non salvato", true);
  }
});

function disegna() {
  if (!dati) return;
  renderRiepilogo(dati);
  renderGrafici(dati);
  renderRegistro(dati.consumi.sessioni || []);
  renderPrezzo(dati);
  renderBollette(dati.bollette || []);
}

async function carica() {
  try {
    const [consumi, registro] = await Promise.all([
      apiFetch("/api/ricarica"),
      apiFetch("/api/carica/registro").catch(() => ({ comandi: [] })),
    ]);
    comandi = Array.isArray(registro.comandi) ? registro.comandi : [];
    dati = consumi;
    disegna();
  } catch (error) {
    showToast(error.message || "Aggiornamento non riuscito", true);
  }
}

$("refreshButton").addEventListener("click", () => { caricaPresa(); carica(); });
$("caricaOraButton").addEventListener("click", () => {
  caricaOra($("caricaOraButton"), () => {
    setTimeout(caricaPresa, 3000);
    setTimeout(carica, 3000);
    setTimeout(carica, 70000);
  });
});
let ridimensiona = null;
window.addEventListener("resize", () => {
  clearTimeout(ridimensiona);
  ridimensiona = setTimeout(() => { if (dati) renderGrafici(dati); }, 150);
});
caricaPresa();
carica();
setInterval(caricaPresa, 10000);
setInterval(carica, 60000);
