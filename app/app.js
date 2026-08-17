// Explorateur TDB PMSI-SMR — logique applicative (sql.js, 100% navigateur, aucun serveur).

let db = null;
let activeSource = "rhs";
let lastResult = null; // { titleText, metaText, tableHtml }
let uidCounter = 0;

let rowDimRows = [];  // { uid, srcKey, dimId, mode: 'code'|'libelle'|'both' }
let colDimRows = [];
let exprRows = [];    // { uid, measureId, aggId, label }

let activeMode = "pivot";       // 'pivot' | 'liste' (sous-mode du parcours "requetes")
let activeParcours = null;      // 'requetes' | 'dossier' | null (écran de choix)
let activeSortie = null;        // 'tableaux' | 'graphique' | null (écran de choix, dans "requetes")
let activeSourceListe = "rhs";
let filterRows = [];  // { uid, srcKey, kind:'dim'|'measure', id, op, val, val2 }
let listeColRows = []; // { uid, srcKey, kind:'dim'|'measure', id, mode }

// Filtres globaux (section "1. Filtres") : s'appliquent à toute l'exploration (tableau croisé,
// liste filtrée, graphique). Dimension -> choix multiple (values[]) ; mesure -> op/val/val2
// (mêmes opérateurs que les filtres locaux de la liste filtrée, y compris "in" = liste de valeurs).
let globalFilterRows = []; // { uid, srcKey, kind:'dim'|'measure', id, values:[], op, val, val2 }

// Mode "Graphique"
let activeSourceGraph = "rhs";
let graphXDimRows = [];      // axe X, max 3, imbriquées comme les lignes du pivot
let graphSeriesDimRows = []; // série/légende, max 3, facultatif (équivalent des colonnes du pivot)
let graphFacetDimRows = [];  // vignettes (petits multiples), max 3, facultatif
let graphExprRows = [];      // mesure(s) Y
let activeChartType = null;  // choisi par l'utilisateur, sinon suggéré automatiquement à la génération
let graphRingColors = [];    // couleur de base (hex) par anneau du camembert : [axe X, Série 1, Série 2, ...]

// ---------- Utilitaires date / semaine ISO ----------

function isoWeekDate(year, week, weekday) {
  // weekday: 1=lundi .. 7=dimanche
  const simple = new Date(Date.UTC(year, 0, 4));
  const dow = simple.getUTCDay() || 7;
  const monday1 = new Date(simple);
  monday1.setUTCDate(simple.getUTCDate() - (dow - 1));
  const result = new Date(monday1);
  result.setUTCDate(monday1.getUTCDate() + (week - 1) * 7 + (weekday - 1));
  return result;
}

function lastWeekOfMonth(year, month) {
  let last = null;
  for (let week = 1; week <= 53; week++) {
    const thursday = isoWeekDate(year, week, 4);
    if (isNaN(thursday)) break;
    const m = thursday.getUTCMonth() + 1;
    if (m > month) break;
    if (m === month) last = week;
  }
  return last;
}

function fmtDate(d) {
  return d.toISOString().slice(0, 10);
}

// ---------- Statut UI ----------

function status(msg, isErr) {
  const el = document.getElementById("status");
  el.textContent = msg || "";
  el.className = isErr ? "err" : "";
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// ---------- Chargement DB ----------

let sqlJsEngine = null;

async function init() {
  status("Chargement du moteur SQL (sql.js)…");
  try {
    sqlJsEngine = await initSqlJs({ locateFile: f => "lib/" + f });
  } catch (e) {
    status("Erreur de chargement du moteur SQL : " + e.message, true);
    return;
  }
  status("Chargement de la base PMSI (pmsi.db)…");
  try {
    const resp = await fetch("data/pmsi.db");
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const buf = await resp.arrayBuffer();
    db = new sqlJsEngine.Database(new Uint8Array(buf));
    status("Base chargée.");
    onDbReady();
  } catch (e) {
    // Cas typique : page ouverte en double-clic (file://), fetch() bloqué par le navigateur.
    status("Chargement automatique impossible — sélectionnez le fichier pmsi.db ci-dessous.");
    document.getElementById("panelDbPicker").style.display = "block";
    document.getElementById("dbFileInput").addEventListener("change", onDbFilePicked);
  }
}

async function onDbFilePicked(evt) {
  const file = evt.target.files[0];
  if (!file) return;
  status("Lecture du fichier sélectionné…");
  try {
    const buf = await file.arrayBuffer();
    db = new sqlJsEngine.Database(new Uint8Array(buf));
    status("Base chargée depuis " + file.name + ".");
    document.getElementById("panelDbPicker").style.display = "none";
    onDbReady();
  } catch (e) {
    status("Erreur de lecture du fichier : " + e.message, true);
  }
}

function onDbReady() {
  populateFiness();
  populateMoisSelect();
  populateFicheFiness();
  wireEvents();
  onFinessChange();
}

function queryAll(sql, params) {
  const stmt = db.prepare(sql);
  if (params && params.length) stmt.bind(params);
  const rows = [];
  while (stmt.step()) rows.push(stmt.getAsObject());
  stmt.free();
  return rows;
}

const MAX_FINESS = 5;

function populateFiness() {
  const rows = queryAll("SELECT DISTINCT finess_epmsi FROM rhs_groupe ORDER BY 1");
  const box = document.getElementById("checksFiness");
  box.innerHTML = "";
  rows.forEach((r, i) => {
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = r.finess_epmsi;
    cb.className = "finess-check";
    if (i === 0) cb.checked = true; // par défaut : le premier établissement seul
    label.appendChild(cb);
    label.appendChild(document.createTextNode(r.finess_epmsi));
    box.appendChild(label);
  });
  box.addEventListener("change", onFinessCheckChange);
}

function selectedFiness() {
  return [...document.querySelectorAll("#checksFiness input:checked")].map(c => c.value);
}

function onFinessCheckChange(evt) {
  const checked = document.querySelectorAll("#checksFiness input:checked");
  if (checked.length > MAX_FINESS) {
    evt.target.checked = false;
    status(`Maximum ${MAX_FINESS} établissements en comparaison.`, true);
    return;
  }
  onFinessChange();
}

function populateMoisSelect() {
  const noms = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"];
  const sel = document.getElementById("selMois");
  sel.innerHTML = "";
  noms.forEach((n, i) => {
    const opt = document.createElement("option");
    opt.value = i + 1;
    opt.textContent = n;
    if (i === 11) opt.selected = true;
    sel.appendChild(opt);
  });
}

function onFinessChange() {
  const finessList = selectedFiness();
  if (!finessList.length) {
    document.getElementById("checksAnnees").innerHTML = "";
    updateRecap();
    return;
  }
  const placeholders = finessList.map(() => "?").join(",");
  const rows = queryAll(
    `SELECT DISTINCT substr(numero_semaine,3,4) AS y FROM rhs_groupe WHERE finess_epmsi IN (${placeholders}) AND numero_semaine IS NOT NULL ORDER BY 1`,
    finessList
  );
  const box = document.getElementById("checksAnnees");
  box.innerHTML = "";
  rows.forEach((r, i) => {
    const id = "annee_" + r.y;
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = r.y;
    cb.id = id;
    if (i >= rows.length - 2) cb.checked = true; // par défaut : les 2 années les plus récentes
    label.appendChild(cb);
    label.appendChild(document.createTextNode(r.y));
    box.appendChild(label);
  });
  document.getElementById("panelModeTabs").style.display = "block";
  document.getElementById("panelPivot").style.display = "block";
  refreshDimUI();
  refreshListeUI();
  renderGlobalFilterList();
}

// ---------- Listes dynamiques : lignes / colonnes / expressions ----------

function defaultModeFor(dim) {
  return (dim && (dim.libCol || dim.libDerive)) ? "libelle" : "code";
}

function refreshDimUI() {
  const src = SOURCES[activeSource];
  rowDimRows = [{ uid: ++uidCounter, srcKey: activeSource, dimId: src.dims[0].id, mode: defaultModeFor(src.dims[0]) }];
  colDimRows = [];
  exprRows = [{ uid: ++uidCounter, measureId: src.measures[0].id, aggId: "count", label: "" }];
  renderDimsList("rowDimsList", rowDimRows, 1);
  renderDimsList("colDimsList", colDimRows, 0);
  renderExprList();
  updateRecap();
}

function dimDefOf(row) {
  const src = SOURCES[row.srcKey];
  return src ? src.dims.find(x => x.id === row.dimId) : null;
}

// Sélecteur de variable en ligne/colonne : une seule liste, groupée par fichier source
// (RHS groupé / VID-HOSP / Valorisation), chaque option précisant sa provenance entre
// parenthèses. Les 3 sources sont toujours proposées, quel que soit l'onglet actif —
// les variables d'un autre fichier que celui de l'onglet sont rattachées à la ligne via
// le séjour (finess + numéro admin séjour) au moment de générer le tableau.
function renderDimsList(containerId, arr, minCount) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  arr.forEach(row => {
    const div = document.createElement("div");
    div.className = "var-row";

    const sel = document.createElement("select");
    SOURCE_ORDER.forEach(srcKey => {
      const src = SOURCES[srcKey];
      const group = document.createElement("optgroup");
      group.label = src.label;
      src.dims.forEach(d => {
        const o = document.createElement("option");
        o.value = srcKey + "::" + d.id;
        o.textContent = `${d.label} (${src.short})`;
        if (srcKey === row.srcKey && d.id === row.dimId) o.selected = true;
        group.appendChild(o);
      });
      sel.appendChild(group);
    });
    sel.addEventListener("change", () => {
      const [srcKey, dimId] = sel.value.split("::");
      row.srcKey = srcKey; row.dimId = dimId;
      row.mode = defaultModeFor(dimDefOf(row));
      renderDimsList(containerId, arr, minCount);
      updateRecap();
    });
    div.appendChild(sel);

    const d = dimDefOf(row);
    if (d && (d.libCol || d.libDerive)) {
      const modeSel = document.createElement("select");
      modeSel.className = "mode-sel";
      [["libelle", "Libellé"], ["code", "Code"], ["both", "Code — Libellé"]].forEach(([v, t]) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = t;
        if (row.mode === v) o.selected = true;
        modeSel.appendChild(o);
      });
      modeSel.addEventListener("change", () => { row.mode = modeSel.value; updateRecap(); });
      div.appendChild(modeSel);
    }

    const rm = document.createElement("button");
    rm.className = "btn-remove"; rm.textContent = "✕"; rm.title = "Retirer";
    rm.disabled = arr.length <= minCount;
    rm.addEventListener("click", () => {
      if (arr.length <= minCount) return;
      const idx = arr.indexOf(row);
      if (idx >= 0) arr.splice(idx, 1);
      renderDimsList(containerId, arr, minCount);
      updateRecap();
    });
    div.appendChild(rm);

    container.appendChild(div);
  });
  updateGraphAddButtons();
}

// Boutons "+ Ajouter une variable" de l'axe X / Série / Vignettes du graphique : plafonnés à 3.
// Rappelé depuis renderDimsList (donc aussi pour les lignes/colonnes du pivot, sans effet là-bas
// puisque les listes graph sont indépendantes) pour rester à jour sans câblage supplémentaire.
function updateGraphAddButtons() {
  const bx = document.getElementById("btnAddGraphXDim");
  if (bx) bx.disabled = graphXDimRows.length >= 3;
  const bs = document.getElementById("btnAddGraphSeriesDim");
  if (bs) bs.disabled = graphSeriesDimRows.length >= 3;
  const bf = document.getElementById("btnAddGraphFacetDim");
  if (bf) bf.disabled = graphFacetDimRows.length >= 3;
  renderRingColorsUI();
}

function renderExprListGeneric(containerId, arr, srcKey, minCount) {
  const container = document.getElementById(containerId);
  const src = SOURCES[srcKey];
  container.innerHTML = "";
  arr.forEach(row => {
    const div = document.createElement("div");
    div.className = "var-row";

    const measSel = document.createElement("select");
    src.measures.forEach(m => {
      const o = document.createElement("option");
      o.value = m.id; o.textContent = m.label;
      if (m.id === row.measureId) o.selected = true;
      measSel.appendChild(o);
    });

    const aggSel = document.createElement("select");
    function fillAgg() {
      aggSel.innerHTML = "";
      const measure = src.measures.find(m => m.id === row.measureId);
      // Une mesure "distincte" (ex. nb de séjours) n'a pas de valeur numérique par ligne :
      // count et les % (basés sur un compte d'éléments distincts) restent valides, pas sum/avg/médiane/min/max.
      const DISTINCT_OK = ["count", "pct_total", "pct_row", "pct_col"];
      const opts = (measure && measure.distinctKey) ? AGG_DEFS.filter(a => DISTINCT_OK.includes(a.id)) : AGG_DEFS;
      if (measure && measure.distinctKey && !DISTINCT_OK.includes(row.aggId)) row.aggId = "count";
      opts.forEach(a => {
        const o = document.createElement("option");
        o.value = a.id; o.textContent = a.label;
        if (a.id === row.aggId) o.selected = true;
        aggSel.appendChild(o);
      });
    }
    fillAgg();

    measSel.addEventListener("change", () => { row.measureId = measSel.value; fillAgg(); updateRecap(); });
    aggSel.addEventListener("change", () => { row.aggId = aggSel.value; updateRecap(); });

    const labelInput = document.createElement("input");
    labelInput.className = "expr-label";
    labelInput.placeholder = "Libellé personnalisé (optionnel)";
    labelInput.value = row.label || "";
    labelInput.addEventListener("input", () => { row.label = labelInput.value; updateRecap(); });

    const rm = document.createElement("button");
    rm.className = "btn-remove"; rm.textContent = "✕"; rm.title = "Retirer";
    rm.disabled = arr.length <= minCount;
    rm.addEventListener("click", () => {
      if (arr.length <= minCount) return;
      const idx = arr.indexOf(row);
      if (idx >= 0) arr.splice(idx, 1);
      renderExprListGeneric(containerId, arr, srcKey, minCount);
      updateRecap();
    });

    div.appendChild(measSel); div.appendChild(aggSel); div.appendChild(labelInput); div.appendChild(rm);
    container.appendChild(div);
  });
}

function renderExprList() { renderExprListGeneric("exprList", exprRows, activeSource, 1); }

function labelForDimRow(row) {
  const d = dimDefOf(row);
  if (!d) return "?";
  const src = SOURCES[row.srcKey];
  const srcSuffix = ` [${src.short}]`;
  if (d.libCol || d.libDerive) {
    const modeLabel = row.mode === "code" ? "code" : row.mode === "both" ? "code + libellé" : "libellé";
    return `${d.label} (${modeLabel})${srcSuffix}`;
  }
  return d.label + srcSuffix;
}

function exprLabelFor(expr, srcKey) {
  const src = SOURCES[srcKey];
  const measure = src.measures.find(m => m.id === expr.measureId);
  const agg = AGG_DEFS.find(a => a.id === expr.aggId);
  if (expr.label && expr.label.trim()) return expr.label.trim();
  return `${agg ? agg.short : expr.aggId} — ${measure ? measure.label : expr.measureId}`;
}
function exprLabel(expr) { return exprLabelFor(expr, activeSource); }

function updateRecap() {
  const src = SOURCES[activeSource];
  const finessList = selectedFiness();
  const periods = computeSelectedPeriods();
  const box = document.getElementById("recapBox");
  box.innerHTML = `<dl>
    <dt>Établissement(s)</dt><dd>${finessList.length ? esc(finessList.join(", ")) : '<span style="color:#c0392b">aucun sélectionné</span>'}</dd>
    <dt>Période</dt><dd>${periods.length ? esc(periods.map(p => p.label).join(", ")) : '<span style="color:#c0392b">aucune période valide</span>'}</dd>
    <dt>Filtres globaux</dt><dd>${activeGlobalFilters().length ? activeGlobalFilters().map(f => esc(globalFilterLabel(f))).join(" ; ") : "(aucun)"}</dd>
    <dt>Table source (mesures)</dt><dd>${esc(src.label)}</dd>
    <dt>Lignes</dt><dd>${rowDimRows.map(r => esc(labelForDimRow(r))).join(" / ") || "—"}</dd>
    <dt>Colonnes</dt><dd>${colDimRows.length ? colDimRows.map(r => esc(labelForDimRow(r))).join(" / ") : "(aucune)"}</dd>
    <dt>Expressions</dt><dd>${exprRows.map(e => esc(exprLabel(e))).join(", ")}</dd>
  </dl>`;
  document.getElementById("panelRecap").style.display = "block";
}

// ---------- Requête + agrégation ----------

function computeSelectedPeriods() {
  const moisEl = document.getElementById("selMois");
  if (!moisEl) return [];
  const mois = Number(moisEl.value);
  const checked = [...document.querySelectorAll("#checksAnnees input:checked")].map(c => c.value);
  const periods = [];
  for (const y of checked) {
    const yearNum = Number(y);
    const maxWeek = lastWeekOfMonth(yearNum, mois);
    if (maxWeek == null) continue;
    const start = isoWeekDate(yearNum, 1, 1);
    const end = isoWeekDate(yearNum, maxWeek, 7);
    periods.push({ year: y, maxWeek, start, end, label: `${y} (semaines 01–${String(maxWeek).padStart(2, "0")})` });
  }
  return periods;
}

function buildQuery(sourceKey, finessList, periods) {
  const src = SOURCES[sourceKey];
  const clauses = [];
  const finessPlaceholders = finessList.map(() => "?").join(",");
  const params = [...finessList];
  if (src.periodKind === "semaine") {
    for (const p of periods) {
      clauses.push("(substr(r.numero_semaine,3,4)=? AND CAST(substr(r.numero_semaine,1,2) AS INTEGER)<=?)");
      params.push(p.year, p.maxWeek);
    }
  } else if (src.periodKind === "dates") {
    for (const p of periods) {
      clauses.push("(date(v.date_entree) <= date(?) AND (v.date_sortie IS NULL OR date(v.date_sortie) >= date(?)))");
      params.push(fmtDate(p.end), fmtDate(p.start));
    }
  } else if (src.periodKind === "campagne") {
    for (const p of periods) {
      clauses.push("va.campagne = ?");
      params.push(Number(p.year));
    }
  }
  const periodSql = clauses.length ? clauses.join(" OR ") : "1=1";
  const sql = src.sql.replace("%FINESS%", finessPlaceholders).replace("%PERIOD%", periodSql);
  return { sql, params };
}

function tagPeriod(rows, sourceKey, periods) {
  const src = SOURCES[sourceKey];
  for (const row of rows) {
    if (src.periodKind === "semaine") {
      row._periode_annee = row.numero_semaine ? row.numero_semaine.substring(2, 6) : null;
    } else if (src.periodKind === "campagne") {
      row._periode_annee = row.campagne != null ? String(row.campagne) : null;
    } else if (src.periodKind === "dates") {
      let matched = null;
      const entree = row.date_entree ? new Date(row.date_entree) : null;
      const sortie = row.date_sortie ? new Date(row.date_sortie) : null;
      for (const p of periods) {
        if (entree && entree <= p.end && (!sortie || sortie >= p.start)) {
          matched = p.year;
          break;
        }
      }
      row._periode_annee = matched;
    }
  }
}

function normVal(v) {
  return (v === null || v === undefined || v === "") ? "(vide)" : String(v);
}

// ---------- Jointure inter-sources (lignes/colonnes venant d'un autre fichier que celui
// de l'onglet actif) : rattachement par séjour = finess_epmsi + numero_admin_sejour, en
// normalisant le numéro (rhs_groupe/vid_hosp le stockent zero-paddé, valorisation_sejour non).

function admKey(finess, numadmin) {
  const n = Number(numadmin);
  return finess + "|" + (isNaN(n) ? String(numadmin) : n);
}

function buildForeignIndex(srcKey, finessList, periods) {
  const { sql, params } = buildQuery(srcKey, finessList, periods);
  const rows = queryAll(sql, params);
  tagPeriod(rows, srcKey, periods);
  const idx = new Map();
  for (const row of rows) {
    const key = admKey(row.finess_epmsi, row.numero_admin_sejour);
    if (!idx.has(key)) idx.set(key, []);
    idx.get(key).push(row);
  }
  return idx;
}

function resolveForeignRow(idx, baseRow) {
  if (!idx) return null;
  const candidates = idx.get(admKey(baseRow.finess_epmsi, baseRow.numero_admin_sejour));
  if (!candidates || !candidates.length) return null;
  const baseYear = baseRow._periode_annee;
  if (baseYear != null) {
    const match = candidates.find(r => String(r._periode_annee) === String(baseYear));
    if (match) return match;
  }
  return candidates[0];
}

// Résout, pour une configuration de dimension (rowDimRows/colDimRows/graphXDimRows/...), la ligne
// source à utiliser : la ligne de base si la dimension vient du même fichier que les lignes
// interrogées (baseSrcKey — PAS la variable globale activeSource, qui ne reflète que l'onglet
// "Tableau croisé" : en mode Graphique la table de base peut être différente), sinon la ligne
// correspondante du fichier tiers (via foreignIdx), ou null si aucun séjour ne correspond.
function sourceRowFor(cfg, baseRow, foreignIdx, baseSrcKey) {
  if (cfg.srcKey === baseSrcKey) return baseRow;
  return resolveForeignRow(foreignIdx[cfg.srcKey], baseRow);
}

function dimValue(dim, mode, row) {
  if (!row) return "(hors périmètre)";
  const codeVal = dim.derive ? dim.derive(row) : row[dim.col];
  const codeStr = normVal(codeVal);
  if (!dim.libCol && !dim.libDerive) return codeStr;
  const libValRaw = dim.libDerive ? dim.libDerive(row) : row[dim.libCol];
  const libStr = (libValRaw === null || libValRaw === undefined || libValRaw === "") ? null : String(libValRaw);
  if (mode === "code") return codeStr;
  if (mode === "both") return libStr ? `${codeStr} — ${libStr}` : codeStr;
  return libStr || codeStr; // mode "libelle" par défaut, repli sur le code si aucun libellé résolu
}

const CELL_SEP = "";
function cellKeyStr(rk, ck) { return rk + CELL_SEP + ck; }

function agFn(values, isDistinct, aggName) {
  if (isDistinct) return new Set(values).size;
  if (!values.length) return null;
  switch (aggName) {
    case "count": return values.length;
    case "sum": return values.reduce((a, b) => a + b, 0);
    case "avg": return values.reduce((a, b) => a + b, 0) / values.length;
    case "median": {
      const s = [...values].sort((a, b) => a - b);
      const mid = Math.floor(s.length / 2);
      return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
    }
    case "min": return Math.min(...values);
    case "max": return Math.max(...values);
    default: return values.reduce((a, b) => a + b, 0);
  }
}

function extractValues(cellRows, measure) {
  if (measure.distinctKey) return cellRows.map(r => measure.distinctKey(r));
  const vals = [];
  for (const r of cellRows) {
    let v = measure.derive ? measure.derive(r) : r[measure.col];
    if (v !== null && v !== undefined && v !== "") {
      v = Number(v);
      if (measure.scale) v *= measure.scale;
      if (!isNaN(v)) vals.push(v);
    }
  }
  return vals;
}

function computeExprPivot(cells, rowKeys, colKeys, measure, aggId) {
  const isDistinct = !!measure.distinctKey;
  const isPct = aggId === "pct_total" || aggId === "pct_row" || aggId === "pct_col";
  const grid = {}, rowTotal = {}, colTotal = {};
  let grandTotal = null;

  function cellValues(rk, ck) { return extractValues(cells.get(cellKeyStr(rk, ck)) || [], measure); }

  if (!isPct) {
    for (const rk of rowKeys) {
      grid[rk] = {};
      for (const ck of colKeys) grid[rk][ck] = agFn(cellValues(rk, ck), isDistinct, aggId);
    }
    for (const rk of rowKeys) {
      let all = []; for (const ck of colKeys) all = all.concat(cellValues(rk, ck));
      rowTotal[rk] = agFn(all, isDistinct, aggId);
    }
    for (const ck of colKeys) {
      let all = []; for (const rk of rowKeys) all = all.concat(cellValues(rk, ck));
      colTotal[ck] = agFn(all, isDistinct, aggId);
    }
    let all = []; for (const rk of rowKeys) for (const ck of colKeys) all = all.concat(cellValues(rk, ck));
    grandTotal = agFn(all, isDistinct, aggId);
  } else {
    const baseAgg = vals => isDistinct ? new Set(vals).size : vals.reduce((a, b) => a + b, 0);
    const base = {}, baseRow = {}, baseCol = {};
    for (const rk of rowKeys) {
      base[rk] = {};
      for (const ck of colKeys) base[rk][ck] = baseAgg(cellValues(rk, ck));
    }
    for (const rk of rowKeys) {
      let all = []; for (const ck of colKeys) all = all.concat(cellValues(rk, ck));
      baseRow[rk] = baseAgg(all);
    }
    for (const ck of colKeys) {
      let all = []; for (const rk of rowKeys) all = all.concat(cellValues(rk, ck));
      baseCol[ck] = baseAgg(all);
    }
    let all = []; for (const rk of rowKeys) for (const ck of colKeys) all = all.concat(cellValues(rk, ck));
    const baseGrand = baseAgg(all);

    for (const rk of rowKeys) {
      grid[rk] = {};
      for (const ck of colKeys) {
        const num = base[rk][ck];
        const den = aggId === "pct_total" ? baseGrand : aggId === "pct_row" ? baseRow[rk] : baseCol[ck];
        grid[rk][ck] = den ? (100 * num / den) : (num === 0 ? 0 : null);
      }
    }
    for (const rk of rowKeys) rowTotal[rk] = aggId === "pct_row" ? (baseRow[rk] ? 100 : null) : (baseGrand ? 100 * baseRow[rk] / baseGrand : null);
    for (const ck of colKeys) colTotal[ck] = aggId === "pct_col" ? (baseCol[ck] ? 100 : null) : (baseGrand ? 100 * baseCol[ck] / baseGrand : null);
    grandTotal = 100;
  }

  return { grid, rowTotal, colTotal, grandTotal, isPct };
}

function computeMultiPivot(rows, rowDimsCfg, colDimsCfg, exprsCfg, measures, foreignIdx, baseSrcKey) {
  function valueFor(cfg, row) {
    return dimValue(dimDefOf(cfg), cfg.mode, sourceRowFor(cfg, row, foreignIdx, baseSrcKey));
  }
  function partsFor(dimsCfg, row) { return dimsCfg.map(r => valueFor(r, row)); }

  const cells = new Map();
  const rowKeysSet = new Set(), colKeysSet = new Set();
  const rowPartsByKey = new Map(); // rowKey (string) -> [valeur dim1, valeur dim2, ...] (imbrication en lignes)
  const colPartsByKey = new Map(); // idem pour les colonnes
  for (const row of rows) {
    const rParts = partsFor(rowDimsCfg, row);
    const cParts = partsFor(colDimsCfg, row);
    const rk = rParts.join(" | ");
    const ck = colDimsCfg.length ? cParts.join(" | ") : "Total";
    rowKeysSet.add(rk); colKeysSet.add(ck);
    if (!rowPartsByKey.has(rk)) rowPartsByKey.set(rk, rParts);
    if (!colPartsByKey.has(ck)) colPartsByKey.set(ck, cParts);
    const key = cellKeyStr(rk, ck);
    if (!cells.has(key)) cells.set(key, []);
    cells.get(key).push(row);
  }

  const rowKeys = [...rowKeysSet].sort();
  const colKeys = [...colKeysSet].sort();

  const perExpr = {};
  for (const expr of exprsCfg) {
    const measure = measures.find(m => m.id === expr.measureId);
    perExpr[expr.uid] = computeExprPivot(cells, rowKeys, colKeys, measure, expr.aggId);
  }

  return { rowKeys, colKeys, perExpr, rowPartsByKey, colPartsByKey };
}

// Calcule, pour une liste de clés déjà triée (tableau de tableaux de valeurs, une entrée par
// dimension), quelles cellules d'en-tête afficher et sur combien de lignes/colonnes les fusionner,
// pour obtenir un regroupement imbriqué : la 1ère dimension n'apparaît qu'une fois par groupe
// (fusionnée), la 2e le détail à l'intérieur de ce groupe, etc. Utilisé pour les lignes (fusion
// verticale, rowspan) comme pour les colonnes (fusion horizontale, colspan) — même algorithme,
// seule l'utilisation du résultat diffère selon l'axe.
function computeMerge(partsList) {
  const n = partsList.length;
  const d = partsList.length ? partsList[0].length : 0;
  const show = partsList.map(() => new Array(d).fill(true));
  const span = partsList.map(() => new Array(d).fill(1));
  const groupStart = new Array(d).fill(0);
  for (let i = 1; i < n; i++) {
    let stillSame = true;
    for (let level = 0; level < d; level++) {
      stillSame = stillSame && partsList[i][level] === partsList[i - 1][level];
      if (stillSame) {
        show[i][level] = false;
        span[groupStart[level]][level]++;
      } else {
        span[i][level] = 1;
        groupStart[level] = i;
      }
    }
  }
  return { show, span };
}

function fmtVal(v, isPct) {
  if (v === null || v === undefined || (typeof v === "number" && isNaN(v))) return "—";
  if (isPct) return v.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " %";
  return v.toLocaleString("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function renderMultiPivotTable(pivot, rowDimsCfg, colDimsCfg, exprsCfg) {
  const n = exprsCfg.length;
  const nDims = rowDimsCfg.length;
  const nDimsCol = colDimsCfg.length;
  const rowLabels = rowDimsCfg.map(cfg => labelForDimRow(cfg));
  const rowsParts = pivot.rowKeys.map(rk => pivot.rowPartsByKey.get(rk));
  const { show, span } = computeMerge(rowsParts);

  let html = '<table class="pivot"><thead>';

  if (nDimsCol > 0) {
    // Imbrication en colonnes, symétrique de celle des lignes : la 1ère dimension se fusionne
    // horizontalement (colspan) sur toutes ses sous-colonnes, la 2e apparaît en détail dessous, etc.
    const colLabels = colDimsCfg.map(cfg => labelForDimRow(cfg));
    const colsParts = pivot.colKeys.map(ck => pivot.colPartsByKey.get(ck));
    const { show: colShow, span: colSpan } = computeMerge(colsParts);
    const headerRows = nDimsCol + 1;

    for (let level = 0; level < nDimsCol; level++) {
      html += "<tr>";
      if (level === 0) rowLabels.forEach(lbl => { html += `<th rowspan="${headerRows}">${esc(lbl)}</th>`; });
      pivot.colKeys.forEach((ck, i) => {
        if (colShow[i][level]) html += `<th colspan="${colSpan[i][level] * n}">${esc(colsParts[i][level])}</th>`;
      });
      if (level === 0) html += `<th colspan="${n}" rowspan="${nDimsCol}" class="totalcol">Total</th>`;
      html += "</tr>";
    }
    html += "<tr>";
    for (const ck of pivot.colKeys) for (const e of exprsCfg) html += `<th class="exprhead">${esc(exprLabel(e))}</th>`;
    for (const e of exprsCfg) html += `<th class="exprhead totalcol">${esc(exprLabel(e))}</th>`;
    html += "</tr></thead><tbody>";
  } else {
    html += '<tr>';
    rowLabels.forEach(lbl => { html += `<th rowspan="2">${esc(lbl)}</th>`; });
    for (const ck of pivot.colKeys) html += `<th colspan="${n}">${esc(ck)}</th>`;
    html += `<th colspan="${n}" class="totalcol">Total</th></tr><tr>`;
    for (const ck of pivot.colKeys) for (const e of exprsCfg) html += `<th class="exprhead">${esc(exprLabel(e))}</th>`;
    for (const e of exprsCfg) html += `<th class="exprhead totalcol">${esc(exprLabel(e))}</th>`;
    html += "</tr></thead><tbody>";
  }

  pivot.rowKeys.forEach((rk, i) => {
    html += "<tr>";
    for (let level = 0; level < nDims; level++) {
      if (show[i][level]) {
        const cls = level === 0 ? "rowhead" : "rowhead rowhead-nested";
        html += `<td class="${cls}" rowspan="${span[i][level]}">${esc(rowsParts[i][level])}</td>`;
      }
    }
    for (const ck of pivot.colKeys) {
      for (const e of exprsCfg) {
        const pr = pivot.perExpr[e.uid];
        html += "<td>" + fmtVal(pr.grid[rk][ck], pr.isPct) + "</td>";
      }
    }
    for (const e of exprsCfg) {
      const pr = pivot.perExpr[e.uid];
      html += '<td class="totalcol">' + fmtVal(pr.rowTotal[rk], pr.isPct) + "</td>";
    }
    html += "</tr>";
  });

  html += `<tr class="totalrow"><td class="rowhead" colspan="${nDims}">Total</td>`;
  for (const ck of pivot.colKeys) {
    for (const e of exprsCfg) {
      const pr = pivot.perExpr[e.uid];
      html += "<td>" + fmtVal(pr.colTotal[ck], pr.isPct) + "</td>";
    }
  }
  for (const e of exprsCfg) {
    const pr = pivot.perExpr[e.uid];
    html += '<td class="totalcol">' + fmtVal(pr.grandTotal, pr.isPct) + "</td>";
  }
  html += "</tr></tbody></table>";
  return html;
}

// ---------- Génération ----------

function generer() {
  try {
    const src = SOURCES[activeSource];
    const finessList = selectedFiness();
    const periods = computeSelectedPeriods();
    if (!finessList.length) { status("Sélectionnez au moins un établissement.", true); return; }
    if (!periods.length) { status("Sélectionnez au moins une année valide pour le mois choisi.", true); return; }
    if (!rowDimRows.length) { status("Ajoutez au moins une variable en lignes.", true); return; }
    if (!exprRows.length) { status("Ajoutez au moins une expression.", true); return; }

    status("Interrogation de la base…");
    const { sql, params } = buildQuery(activeSource, finessList, periods);
    let rows = queryAll(sql, params);
    tagPeriod(rows, activeSource, periods);

    // Fichiers tiers réellement utilisés en lignes/colonnes/filtres globaux : on les interroge et
    // on les indexe par séjour pour rattacher leurs variables aux lignes de la table active.
    const activeGF = activeGlobalFilters();
    const foreignSrcKeys = new Set(
      [...rowDimRows, ...colDimRows].map(r => r.srcKey)
        .concat(activeGF.map(f => f.srcKey))
        .filter(k => k !== activeSource)
    );
    const foreignIdx = {};
    for (const srcKey of foreignSrcKeys) foreignIdx[srcKey] = buildForeignIndex(srcKey, finessList, periods);

    rows = applyGlobalFilters(rows, activeSource, foreignIdx);

    const pivot = computeMultiPivot(rows, rowDimRows, colDimRows, exprRows, src.measures, foreignIdx, activeSource);
    const rowLabel = rowDimRows.map(r => labelForDimRow(r)).join(" / ");
    const tableHtml = renderMultiPivotTable(pivot, rowDimRows, colDimRows, exprRows);

    const titleText = `TDB PMSI-SMR — ${src.label} — Établissement(s) ${finessList.join(", ")}`;
    const metaText = `Période : ${periods.map(p => p.label).join(", ")} · Filtres globaux : ${activeGF.length} · Lignes : ${rowLabel} · ` +
      `Colonnes : ${colDimRows.length ? colDimRows.map(r => labelForDimRow(r)).join(" / ") : "(aucune)"} · ` +
      `Expressions : ${exprRows.map(e => exprLabel(e)).join(", ")} · ${rows.length} ligne(s) source analysée(s)`;

    document.getElementById("panelResult").style.display = "block";
    document.getElementById("resultMeta").textContent = metaText;
    document.getElementById("resultWrap").innerHTML = tableHtml;
    lastResult = { titleText, metaText, tableHtml };
    ["btnExportHtml", "btnExportPdf", "btnExportDoc", "btnExportXls"].forEach(id => document.getElementById(id).disabled = false);
    status(`Tableau généré (${pivot.rowKeys.length} ligne(s) × ${pivot.colKeys.length} colonne(s) × ${exprRows.length} expression(s)).`);
  } catch (e) {
    status("Erreur : " + e.message, true);
    console.error(e);
  }
}

// ---------- Mode "Liste filtrée" ----------

function catalogEntry(srcKey, kind, id) {
  const src = SOURCES[srcKey];
  if (!src) return null;
  const arr = kind === "measure" ? src.measures : src.dims;
  return (arr || []).find(x => x.id === id) || null;
}

// Construit les <optgroup> "Src — Variables" / "Src — Mesures" pour un select de
// filtre/colonne, couvrant les 7 sources (mêmes catalogues que le pivot).
function buildEntryOptions(sel, currentSrcKey, currentKind, currentId) {
  sel.innerHTML = "";
  SOURCE_ORDER.forEach(srcKey => {
    const src = SOURCES[srcKey];
    const gDim = document.createElement("optgroup");
    gDim.label = `${src.label} — variables`;
    src.dims.forEach(d => {
      const o = document.createElement("option");
      o.value = `${srcKey}::dim::${d.id}`;
      o.textContent = `${d.label} (${src.short})`;
      if (srcKey === currentSrcKey && currentKind === "dim" && d.id === currentId) o.selected = true;
      gDim.appendChild(o);
    });
    sel.appendChild(gDim);
    const gMeas = document.createElement("optgroup");
    gMeas.label = `${src.label} — mesures`;
    src.measures.forEach(m => {
      const o = document.createElement("option");
      o.value = `${srcKey}::measure::${m.id}`;
      o.textContent = `${m.label} (${src.short})`;
      if (srcKey === currentSrcKey && currentKind === "measure" && m.id === currentId) o.selected = true;
      gMeas.appendChild(o);
    });
    sel.appendChild(gMeas);
  });
}

// Suggestions de valeurs pour un filtre "dimension" : peuple un <datalist> natif
// (autocomplétion du navigateur, pas de widget custom) avec les valeurs distinctes
// réellement présentes dans la base pour l'établissement/période en cours — requête
// bornée (LIMIT) pour rester rapide même sur une colonne à fort cardinal (diagnostics, actes).
const FILTER_DATALIST_LIMIT = 500;

function fillFilterDatalist(dlId, srcKey, entry) {
  let dl = document.getElementById(dlId);
  if (!dl) {
    dl = document.createElement("datalist");
    dl.id = dlId;
    document.body.appendChild(dl);
  }
  dl.innerHTML = "";
  const finessList = selectedFiness();
  const periods = computeSelectedPeriods();
  if (!finessList.length || !periods.length) return;
  try {
    const { sql, params } = buildQuery(srcKey, finessList, periods);
    const cols = entry.libCol ? `${entry.col} AS v, ${entry.libCol} AS l` : `${entry.col} AS v`;
    const q = `SELECT DISTINCT ${cols} FROM (${sql}) WHERE ${entry.col} IS NOT NULL AND ${entry.col} <> ''
               ORDER BY ${entry.col} LIMIT ${FILTER_DATALIST_LIMIT}`;
    const rows = queryAll(q, params);
    rows.forEach(r => {
      const o = document.createElement("option");
      o.value = String(r.v);
      if (entry.libCol && r.l) o.label = `${r.v} — ${r.l}`;
      dl.appendChild(o);
    });
  } catch (e) {
    console.warn("Suggestions de filtre indisponibles pour " + srcKey + "." + entry.col, e);
  }
}

function opsFor(kind) {
  return kind === "measure"
    ? [["between", "entre"], ["eq", "="], ["gte", "≥"], ["lte", "≤"], ["in", "liste (séparée par ; ou ,)"]]
    : [["eq", "="], ["neq", "≠"], ["contains", "contient"]];
}

function matchesFilter(f, row) {
  if (!row) return false;
  const entry = catalogEntry(f.srcKey, f.kind, f.id);
  if (!entry) return true;
  if (f.kind === "dim") {
    const raw = entry.derive ? entry.derive(row) : row[entry.col];
    const s = normVal(raw).toLowerCase();
    const v = (f.val || "").trim().toLowerCase();
    if (!v) return true; // filtre présent mais sans valeur : pas de restriction (utile pour "juste rattaché à ce fichier")
    if (f.op === "eq") return s === v;
    if (f.op === "neq") return s !== v;
    if (f.op === "contains") return s.includes(v);
    return true;
  }
  let n = entry.derive ? entry.derive(row) : row[entry.col];
  if (n === null || n === undefined || n === "") return false;
  n = Number(n);
  if (entry.scale) n *= entry.scale;
  if (isNaN(n)) return false;
  const v1 = f.val !== "" && f.val != null ? Number(f.val) : null;
  const v2 = f.val2 !== "" && f.val2 != null ? Number(f.val2) : null;
  if (f.op === "eq") return v1 === null ? true : n === v1;
  if (f.op === "gte") return v1 === null ? true : n >= v1;
  if (f.op === "lte") return v1 === null ? true : n <= v1;
  if (f.op === "between") return (v1 === null || n >= v1) && (v2 === null || n <= v2);
  if (f.op === "in") {
    const list = (f.val || "").split(/[;,]/).map(s => Number(s.trim())).filter(x => !isNaN(x));
    return list.length ? list.includes(n) : true;
  }
  return true;
}

// ---------- Filtres globaux (section "1. Filtres") ----------
// S'appliquent partout (tableau croisé, liste filtrée, graphique), avant toute autre logique de
// mode. Dimension -> choix multiple parmi les valeurs distinctes réellement présentes en base
// (rattachement par séjour si la variable vient d'un autre fichier, même mécanisme que rowDimRows).
// Mesure -> mêmes opérateurs que les filtres locaux de la liste filtrée (matchesFilter, dont "in").

function activeGlobalFilters() {
  return globalFilterRows.filter(f => {
    const entry = catalogEntry(f.srcKey, f.kind, f.id);
    if (!entry) return false;
    if (f.kind === "dim") return !!(f.values && f.values.length);
    return true;
  });
}

function matchesGlobalFilter(gf, row) {
  if (!row) return false;
  const entry = catalogEntry(gf.srcKey, gf.kind, gf.id);
  if (!entry) return true;
  if (gf.kind === "dim") {
    if (!gf.values || !gf.values.length) return true;
    const raw = entry.derive ? entry.derive(row) : row[entry.col];
    return gf.values.includes(normVal(raw));
  }
  return matchesFilter(gf, row);
}

function applyGlobalFilters(rows, srcKeyOfRows, foreignIdx) {
  const active = activeGlobalFilters();
  if (!active.length) return rows;
  return rows.filter(row => active.every(f => {
    if (f.srcKey === srcKeyOfRows) return matchesGlobalFilter(f, row);
    const idx = foreignIdx[f.srcKey];
    const candidates = (idx && idx.get(admKey(row.finess_epmsi, row.numero_admin_sejour))) || [];
    return candidates.some(r => matchesGlobalFilter(f, r));
  }));
}

function globalFilterLabel(f) {
  const entry = catalogEntry(f.srcKey, f.kind, f.id);
  const src = SOURCES[f.srcKey];
  if (!entry) return "?";
  const name = `${entry.label} [${src.short}]`;
  if (f.kind === "dim") return `${name} ∈ {${f.values.join(", ")}}`;
  const opLbl = (opsFor("measure").find(([v]) => v === f.op) || [null, "?"])[1];
  if (f.op === "between") return `${name} ${opLbl} [${f.val || "…"} – ${f.val2 || "…"}]`;
  return `${name} ${opLbl} ${f.val || "…"}`;
}

const GLOBAL_FILTER_VALUES_LIMIT = 500;

function fillGlobalDimValues(selectEl, srcKey, entry, gf) {
  selectEl.innerHTML = "";
  const finessList = selectedFiness();
  const periods = computeSelectedPeriods();
  if (!finessList.length || !periods.length) return;
  try {
    const { sql, params } = buildQuery(srcKey, finessList, periods);
    const cols = entry.libCol ? `${entry.col} AS v, ${entry.libCol} AS l` : `${entry.col} AS v`;
    const q = `SELECT DISTINCT ${cols} FROM (${sql}) WHERE ${entry.col} IS NOT NULL AND ${entry.col} <> ''
               ORDER BY ${entry.col} LIMIT ${GLOBAL_FILTER_VALUES_LIMIT}`;
    const rows = queryAll(q, params);
    rows.forEach(r => {
      const o = document.createElement("option");
      o.value = normVal(r.v);
      o.textContent = entry.libCol && r.l ? `${r.v} — ${r.l}` : String(r.v);
      if (gf.values && gf.values.includes(o.value)) o.selected = true;
      selectEl.appendChild(o);
    });
  } catch (e) {
    console.warn("Valeurs indisponibles pour le filtre global " + srcKey + "." + entry.col, e);
  }
}

function renderGlobalFilterList() {
  const container = document.getElementById("globalFilterList");
  if (!container) return;
  container.innerHTML = "";
  globalFilterRows.forEach(f => {
    const div = document.createElement("div");
    div.className = "filter-row";

    const sel = document.createElement("select");
    buildEntryOptions(sel, f.srcKey, f.kind, f.id);
    sel.addEventListener("change", () => {
      const [srcKey, kind, id] = sel.value.split("::");
      f.srcKey = srcKey; f.kind = kind; f.id = id;
      if (kind === "measure") { f.op = "between"; f.val = ""; f.val2 = ""; }
      else { f.values = []; }
      renderGlobalFilterList();
    });
    div.appendChild(sel);

    const entry = catalogEntry(f.srcKey, f.kind, f.id);

    if (f.kind === "dim") {
      if (entry && entry.col) {
        const msel = document.createElement("select");
        msel.multiple = true;
        msel.className = "filter-multiselect";
        fillGlobalDimValues(msel, f.srcKey, entry, f);
        msel.addEventListener("change", () => { f.values = [...msel.selectedOptions].map(o => o.value); });
        div.appendChild(msel);
      } else {
        const note = document.createElement("span");
        note.className = "filter-note";
        note.textContent = "(variable calculée — filtre par valeurs indisponible)";
        div.appendChild(note);
      }
    } else {
      const opSel = document.createElement("select");
      opSel.className = "op-sel";
      opsFor("measure").forEach(([v, t]) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = t;
        if (f.op === v) o.selected = true;
        opSel.appendChild(o);
      });
      opSel.addEventListener("change", () => { f.op = opSel.value; renderGlobalFilterList(); });
      div.appendChild(opSel);

      const val1 = document.createElement("input");
      val1.className = "filter-val";
      val1.placeholder = f.op === "between" ? "min" : f.op === "in" ? "ex. 1;2;5" : "valeur";
      val1.value = f.val || "";
      val1.addEventListener("input", () => { f.val = val1.value; });
      div.appendChild(val1);

      if (f.op === "between") {
        const val2 = document.createElement("input");
        val2.className = "filter-val2";
        val2.placeholder = "max";
        val2.value = f.val2 || "";
        val2.addEventListener("input", () => { f.val2 = val2.value; });
        div.appendChild(val2);
      }
    }

    const rm = document.createElement("button");
    rm.className = "btn-remove"; rm.textContent = "✕"; rm.title = "Retirer";
    rm.addEventListener("click", () => {
      const idx = globalFilterRows.indexOf(f);
      if (idx >= 0) globalFilterRows.splice(idx, 1);
      renderGlobalFilterList();
    });
    div.appendChild(rm);

    container.appendChild(div);
  });
}

function refreshListeUI() {
  const src = SOURCES[activeSourceListe];
  filterRows = [];
  listeColRows = src.dims.slice(0, Math.min(5, src.dims.length))
    .map(d => ({ uid: ++uidCounter, srcKey: activeSourceListe, kind: "dim", id: d.id, mode: defaultModeFor(d) }));
  renderFilterList();
  renderListeColsList();
}

function renderFilterList() {
  const container = document.getElementById("filterList");
  container.innerHTML = "";
  filterRows.forEach(f => {
    const div = document.createElement("div");
    div.className = "filter-row";

    const sel = document.createElement("select");
    buildEntryOptions(sel, f.srcKey, f.kind, f.id);
    sel.addEventListener("change", () => {
      const [srcKey, kind, id] = sel.value.split("::");
      f.srcKey = srcKey; f.kind = kind; f.id = id;
      f.op = kind === "measure" ? "between" : "eq";
      f.val = ""; f.val2 = "";
      renderFilterList();
    });
    div.appendChild(sel);

    const opSel = document.createElement("select");
    opSel.className = "op-sel";
    opsFor(f.kind).forEach(([v, t]) => {
      const o = document.createElement("option");
      o.value = v; o.textContent = t;
      if (f.op === v) o.selected = true;
      opSel.appendChild(o);
    });
    opSel.addEventListener("change", () => { f.op = opSel.value; renderFilterList(); });
    div.appendChild(opSel);

    const val1 = document.createElement("input");
    val1.className = "filter-val";
    val1.placeholder = f.kind === "measure" ? (f.op === "between" ? "min" : "valeur") : "valeur (texte)";
    val1.value = f.val || "";
    val1.addEventListener("input", () => { f.val = val1.value; });
    div.appendChild(val1);

    const entryForList = catalogEntry(f.srcKey, f.kind, f.id);
    if (f.kind === "dim" && entryForList && entryForList.col) {
      const dlId = `dl_filter_${f.uid}`;
      val1.setAttribute("list", dlId);
      fillFilterDatalist(dlId, f.srcKey, entryForList);
    }

    if (f.kind === "measure" && f.op === "between") {
      const val2 = document.createElement("input");
      val2.className = "filter-val2";
      val2.placeholder = "max";
      val2.value = f.val2 || "";
      val2.addEventListener("input", () => { f.val2 = val2.value; });
      div.appendChild(val2);
    }

    const rm = document.createElement("button");
    rm.className = "btn-remove"; rm.textContent = "✕"; rm.title = "Retirer";
    rm.addEventListener("click", () => {
      const idx = filterRows.indexOf(f);
      if (idx >= 0) filterRows.splice(idx, 1);
      renderFilterList();
    });
    div.appendChild(rm);

    container.appendChild(div);
  });
}

function renderListeColsList() {
  const container = document.getElementById("listeColsList");
  container.innerHTML = "";
  listeColRows.forEach(c => {
    const div = document.createElement("div");
    div.className = "var-row";

    const sel = document.createElement("select");
    buildEntryOptions(sel, c.srcKey, c.kind, c.id);
    sel.addEventListener("change", () => {
      const [srcKey, kind, id] = sel.value.split("::");
      c.srcKey = srcKey; c.kind = kind; c.id = id;
      c.mode = defaultModeFor(catalogEntry(srcKey, kind, id));
      renderListeColsList();
    });
    div.appendChild(sel);

    const entry = catalogEntry(c.srcKey, c.kind, c.id);
    if (c.kind === "dim" && entry && (entry.libCol || entry.libDerive)) {
      const modeSel = document.createElement("select");
      modeSel.className = "mode-sel";
      [["libelle", "Libellé"], ["code", "Code"], ["both", "Code — Libellé"]].forEach(([v, t]) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = t;
        if (c.mode === v) o.selected = true;
        modeSel.appendChild(o);
      });
      modeSel.addEventListener("change", () => { c.mode = modeSel.value; });
      div.appendChild(modeSel);
    }

    const rm = document.createElement("button");
    rm.className = "btn-remove"; rm.textContent = "✕"; rm.title = "Retirer";
    rm.disabled = listeColRows.length <= 1;
    rm.addEventListener("click", () => {
      if (listeColRows.length <= 1) return;
      const idx = listeColRows.indexOf(c);
      if (idx >= 0) listeColRows.splice(idx, 1);
      renderListeColsList();
    });
    div.appendChild(rm);

    container.appendChild(div);
  });
}

function listeColLabel(c) {
  const entry = catalogEntry(c.srcKey, c.kind, c.id);
  const src = SOURCES[c.srcKey];
  if (!entry) return "?";
  if (c.kind === "dim" && (entry.libCol || entry.libDerive)) {
    const modeLabel = c.mode === "code" ? "code" : c.mode === "both" ? "code + libellé" : "libellé";
    return `${entry.label} (${modeLabel}) [${src.short}]`;
  }
  return `${entry.label} [${src.short}]`;
}

function listeColValue(c, baseRow, foreignIdx) {
  const entry = catalogEntry(c.srcKey, c.kind, c.id);
  if (!entry) return "";
  const srcRow = c.srcKey === activeSourceListe ? baseRow : resolveForeignRow(foreignIdx[c.srcKey], baseRow);
  if (c.kind === "dim") return dimValue(entry, c.mode || defaultModeFor(entry), srcRow);
  if (!srcRow) return "—";
  let v = entry.derive ? entry.derive(srcRow) : srcRow[entry.col];
  if (v === null || v === undefined || v === "") return "—";
  let n = Number(v);
  if (!isNaN(n)) { if (entry.scale) n *= entry.scale; return fmtVal(n, false); }
  return String(v);
}

const LISTE_ROW_CAP = 3000;

function genererListe() {
  const statusEl = document.getElementById("statusListe");
  const setSt = (msg, err) => { statusEl.textContent = msg || ""; statusEl.style.color = err ? "#c0392b" : ""; };
  try {
    const src = SOURCES[activeSourceListe];
    const finessList = selectedFiness();
    const periods = computeSelectedPeriods();
    if (!finessList.length) { setSt("Sélectionnez au moins un établissement.", true); return; }
    if (!periods.length) { setSt("Sélectionnez au moins une année valide pour le mois choisi.", true); return; }
    if (!listeColRows.length) { setSt("Ajoutez au moins une colonne à afficher.", true); return; }

    setSt("Interrogation de la base…");
    const { sql, params } = buildQuery(activeSourceListe, finessList, periods);
    let rows = queryAll(sql, params);
    tagPeriod(rows, activeSourceListe, periods);

    const activeGF = activeGlobalFilters();
    const neededForeign = new Set();
    filterRows.forEach(f => { if (f.srcKey !== activeSourceListe) neededForeign.add(f.srcKey); });
    listeColRows.forEach(c => { if (c.srcKey !== activeSourceListe) neededForeign.add(c.srcKey); });
    activeGF.forEach(f => { if (f.srcKey !== activeSourceListe) neededForeign.add(f.srcKey); });
    const foreignIdx = {};
    neededForeign.forEach(k => { foreignIdx[k] = buildForeignIndex(k, finessList, periods); });

    rows = applyGlobalFilters(rows, activeSourceListe, foreignIdx);

    const activeFilters = filterRows.filter(f => catalogEntry(f.srcKey, f.kind, f.id));
    rows = rows.filter(row => activeFilters.every(f => {
      if (f.srcKey === activeSourceListe) return matchesFilter(f, row);
      const idx = foreignIdx[f.srcKey];
      const candidates = (idx && idx.get(admKey(row.finess_epmsi, row.numero_admin_sejour))) || [];
      return candidates.some(r => matchesFilter(f, r));
    }));

    const total = rows.length;

    // Une ligne = ses valeurs affichées, dans l'ordre des colonnes choisies. On trie sur ces
    // valeurs pour que les lignes identiques sur les premières colonnes soient adjacentes, puis
    // on fusionne verticalement (rowspan) les valeurs répétées, colonne par colonne — même
    // mécanisme (computeMerge) que la fusion des lignes du tableau croisé : une valeur commune
    // n'est présentée qu'une seule fois, pas répétée sur chaque ligne source qui la partage.
    const partsAll = rows.map(row => listeColRows.map(c => listeColValue(c, row, foreignIdx)));
    const order = rows.map((_, i) => i).sort((i, j) => {
      const a = partsAll[i], b = partsAll[j];
      for (let k = 0; k < a.length; k++) {
        if (a[k] !== b[k]) return a[k] < b[k] ? -1 : 1;
      }
      return 0;
    });
    const shownOrder = order.slice(0, LISTE_ROW_CAP);
    const partsList = shownOrder.map(i => partsAll[i]);
    const { show, span } = computeMerge(partsList);

    let html = '<table class="pivot"><thead><tr>';
    listeColRows.forEach(c => { html += `<th>${esc(listeColLabel(c))}</th>`; });
    html += "</tr></thead><tbody>";
    shownOrder.forEach((_, i) => {
      html += "<tr>";
      listeColRows.forEach((c, level) => {
        if (show[i][level]) {
          const cls = level === 0 ? "rowhead" : "rowhead rowhead-nested";
          html += `<td class="${cls}" style="text-align:left" rowspan="${span[i][level]}">${esc(partsList[i][level])}</td>`;
        }
      });
      html += "</tr>";
    });
    html += "</tbody></table>";

    const titleText = `Liste filtrée — ${src.label} — Établissement(s) ${finessList.join(", ")}`;
    const metaText = `Période : ${periods.map(p => p.label).join(", ")} · Filtres globaux : ${activeGF.length} · Filtres liste : ${activeFilters.length} · ` +
      `${total} ligne(s) trouvée(s)${total > LISTE_ROW_CAP ? ` (affichage limité aux ${LISTE_ROW_CAP} premières)` : ""}`;

    document.getElementById("panelResult").style.display = "block";
    document.getElementById("resultMeta").textContent = metaText;
    document.getElementById("resultWrap").innerHTML = html;
    lastResult = { titleText, metaText, tableHtml: html };
    ["btnExportHtml", "btnExportPdf", "btnExportDoc", "btnExportXls"].forEach(id => document.getElementById(id).disabled = false);
    setSt(`${total} ligne(s) trouvée(s)${total > LISTE_ROW_CAP ? `, ${LISTE_ROW_CAP} affichée(s)` : ""}.`);
  } catch (e) {
    setSt("Erreur : " + e.message, true);
    console.error(e);
  }
}

// ---------- Mode "Graphique" ----------
// Réutilise telles quelles les fonctions d'agrégation du tableau croisé (computeMultiPivot,
// dimValue, sourceRowFor, foreignIdx) : l'axe X et la Série sont respectivement l'équivalent des
// "lignes" et "colonnes" du pivot. Les vignettes (petits multiples) sont obtenues en scindant les
// lignes source par valeur(s) de facette puis en recalculant un pivot indépendant par vignette.

const CHART_PALETTE = ["#1a5276", "#c0392b", "#1e8449", "#b9770e", "#7d3c98", "#117864", "#a04000", "#2874a6", "#943126", "#196f3d", "#5d6d7e", "#0e6655"];
const CHART_TYPE_LABELS = {
  barres: "Barres", barres_empilees: "Barres empilées", lignes: "Lignes", aires: "Aires",
  camembert: "Camembert", nuage: "Nuage de points", carte_chaleur: "Carte de chaleur",
  boxplot: "Boîte à moustaches", histogramme: "Histogramme", treemap: "Treemap",
};
// Dimensions "temporelles" au sens large (année/semaine/campagne) : un axe X sur l'une d'elles
// suggère un graphique en lignes plutôt qu'en barres.
const TEMPORAL_DIM_IDS = new Set(["annee_periode", "semaine", "campagne"]);
const GRAPH_FACET_CAP = 12; // nombre max de vignettes générées (évite l'explosion combinatoire)

// ---- Couleurs par anneau (camembert imbriqué) : une teinte de base par anneau (personnalisable
// via un sélecteur couleur), déclinée en dégradé de luminosité pour les valeurs de cet anneau —
// cohérent (même famille de teinte du début à la fin d'un anneau) tout en restant distinguable
// segment par segment.
function hexToHsl(hex) {
  hex = (hex || "#1a5276").replace("#", "");
  const r = parseInt(hex.substr(0, 2), 16) / 255, g = parseInt(hex.substr(2, 2), 16) / 255, b = parseInt(hex.substr(4, 2), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0; const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h /= 6;
  }
  return [h * 360, s * 100, l * 100];
}
function hslToHex(h, s, l) {
  s /= 100; l /= 100;
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = l - c / 2;
  let r, g, b;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  const toHex = v => Math.round((v + m) * 255).toString(16).padStart(2, "0");
  return "#" + toHex(r) + toHex(g) + toHex(b);
}
function shadeForRing(baseHex, index, count) {
  const [h, s] = hexToHsl(baseHex);
  const sat = Math.max(35, Math.min(78, s));
  if (count <= 1) return hslToHex(h, sat, 48);
  const lMin = 28, lMax = 74;
  return hslToHex(h, sat, lMin + (index / (count - 1)) * (lMax - lMin));
}
function syncGraphRingColors() {
  const n = 1 + graphSeriesDimRows.length;
  while (graphRingColors.length < n) graphRingColors.push(CHART_PALETTE[graphRingColors.length % CHART_PALETTE.length]);
  graphRingColors.length = n;
}
function renderRingColorsUI() {
  const field = document.getElementById("ringColorsField");
  const container = document.getElementById("ringColorsList");
  if (!field || !container) return;
  field.style.display = (activeChartType === "camembert" || activeChartType === "treemap") ? "flex" : "none";
  syncGraphRingColors();
  const ringNames = ["Axe X", ...graphSeriesDimRows.map((r, i) => `Série ${i + 1} (${labelForDimRow(r)})`)];
  container.innerHTML = "";
  container.style.cssText = "display:flex;flex-wrap:wrap;gap:14px;align-items:center;";
  ringNames.forEach((name, i) => {
    const wrap = document.createElement("label");
    wrap.style.cssText = "display:flex;align-items:center;gap:6px;font-weight:normal;text-transform:none;letter-spacing:normal;font-size:0.88em;color:var(--texte);";
    const inp = document.createElement("input");
    inp.type = "color";
    inp.value = graphRingColors[i];
    inp.style.cssText = "width:34px;height:26px;padding:0;border:1px solid var(--bordure);border-radius:4px;cursor:pointer;";
    inp.addEventListener("input", () => { graphRingColors[i] = inp.value; });
    wrap.appendChild(inp);
    wrap.appendChild(document.createTextNode(name));
    container.appendChild(wrap);
  });
}

function refreshGraphUI() {
  const src = SOURCES[activeSourceGraph];
  if (!graphXDimRows.length) graphXDimRows = [{ uid: ++uidCounter, srcKey: activeSourceGraph, dimId: src.dims[0].id, mode: defaultModeFor(src.dims[0]) }];
  if (!graphExprRows.length) graphExprRows = [{ uid: ++uidCounter, measureId: src.measures[0].id, aggId: "count", label: "" }];
  renderDimsList("graphXDimsList", graphXDimRows, 1);
  renderDimsList("graphSeriesDimsList", graphSeriesDimRows, 0);
  renderDimsList("graphFacetDimsList", graphFacetDimRows, 0);
  renderExprListGeneric("graphExprList", graphExprRows, activeSourceGraph, 1);
}

function suggestChartType(xDimsCfg, seriesDimsCfg, exprsCfg) {
  const xIsTemporal = xDimsCfg.some(cfg => TEMPORAL_DIM_IDS.has(cfg.dimId));
  if (xIsTemporal) return "lignes";
  if (seriesDimsCfg.length > 0) return "barres";
  if (xDimsCfg.length === 1 && exprsCfg.length === 1) return "camembert";
  return "barres";
}

function splitByFacets(rows, facetDimsCfg, foreignIdx, baseSrcKey) {
  if (!facetDimsCfg.length) return [{ label: null, rows }];
  const groups = new Map();
  for (const row of rows) {
    const parts = facetDimsCfg.map(cfg => dimValue(dimDefOf(cfg), cfg.mode, sourceRowFor(cfg, row, foreignIdx, baseSrcKey)));
    const key = parts.join(" / ");
    if (!groups.has(key)) groups.set(key, { label: key, rows: [] });
    groups.get(key).rows.push(row);
  }
  return [...groups.values()].sort((a, b) => a.label < b.label ? -1 : a.label > b.label ? 1 : 0);
}

// ---- Rendu SVG (aucune dépendance externe : l'application reste 100% locale) ----

function niceCeil(v) {
  if (v <= 0) return 1;
  const exp = Math.floor(Math.log10(v));
  const base = Math.pow(10, exp);
  const frac = v / base;
  const niceFrac = frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 5 ? 5 : 10;
  return niceFrac * base;
}
function fmtAxisNum(v) {
  if (Math.abs(v) >= 1000) return (v / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + "k";
  return v.toLocaleString("fr-FR", { maximumFractionDigits: 1 });
}
function truncLabel(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
function legendHtml(series) {
  if (!series || series.length <= 1) return "";
  return `<div class="chart-legend">${series.map(s => `<span class="legend-item"><span class="legend-swatch" style="background:${s.color}"></span>${esc(s.label)}</span>`).join("")}</div>`;
}

// Regroupe les données d'un pivot (axe X = rowKeys, Série = colKeys) en { categories, series }
// prêtes à tracer : une série par colonne si une Série est définie (1 seule mesure alors utilisée),
// sinon une série par expression (mesure × fonction) choisie.
function chartSeriesData(pivot, seriesDimsCfg, exprsUsed) {
  const categories = pivot.rowKeys.map(rk => pivot.rowPartsByKey.get(rk).join(" / "));
  let series;
  if (seriesDimsCfg.length) {
    const pr = pivot.perExpr[exprsUsed[0].uid];
    series = pivot.colKeys.map((ck, i) => ({
      label: ck,
      color: CHART_PALETTE[i % CHART_PALETTE.length],
      values: pivot.rowKeys.map(rk => pr.grid[rk][ck]),
    }));
  } else {
    // rowTotal (pas grid[rk]["Total"]) : reste correct même quand le pivot sous-jacent a été
    // calculé avec une Série non vide mais qu'on l'ignore ici (ex. camembert), auquel cas les
    // colKeys ne sont pas ["Total"] — rowTotal fait alors la somme sur toute la Série.
    series = exprsUsed.map((e, i) => ({
      label: exprLabelFor(e, activeSourceGraph),
      color: CHART_PALETTE[i % CHART_PALETTE.length],
      values: pivot.rowKeys.map(rk => pivot.perExpr[e.uid].rowTotal[rk]),
    }));
  }
  return { categories, series };
}

function renderBarSvg(categories, series, stacked) {
  const W = 560, H = 320, ML = 54, MR = 16, MT = 16, MB = 78;
  const plotW = W - ML - MR, plotH = H - MT - MB;
  const n = categories.length;
  let maxV = 0;
  if (stacked) {
    for (let i = 0; i < n; i++) {
      let s = 0;
      for (const ser of series) s += Math.max(0, ser.values[i] || 0);
      maxV = Math.max(maxV, s);
    }
  } else {
    for (const ser of series) for (const v of ser.values) maxV = Math.max(maxV, v || 0);
  }
  const niceMax = niceCeil(maxV || 1);
  const y = v => MT + plotH - (v / niceMax) * plotH;
  const groupW = plotW / Math.max(1, n);
  const barGap = groupW * 0.15;
  const barsAreaW = groupW - barGap;
  const barW = stacked ? barsAreaW : barsAreaW / Math.max(1, series.length);

  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;font-family:'Segoe UI',Arial,sans-serif;">`;
  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const v = niceMax * t / ticks, yy = y(v);
    svg += `<line x1="${ML}" y1="${yy.toFixed(1)}" x2="${W - MR}" y2="${yy.toFixed(1)}" stroke="#e5e9ea" stroke-width="1"/>`;
    svg += `<text x="${ML - 6}" y="${(yy + 3).toFixed(1)}" font-size="9" fill="#7f8c8d" text-anchor="end">${esc(fmtAxisNum(v))}</text>`;
  }
  svg += `<line x1="${ML}" y1="${MT}" x2="${ML}" y2="${MT + plotH}" stroke="#aab" stroke-width="1"/>`;
  svg += `<line x1="${ML}" y1="${MT + plotH}" x2="${W - MR}" y2="${MT + plotH}" stroke="#aab" stroke-width="1"/>`;

  categories.forEach((cat, i) => {
    const gx = ML + i * groupW + barGap / 2;
    if (stacked) {
      let cum = 0;
      series.forEach(ser => {
        const v = Math.max(0, ser.values[i] || 0);
        if (!v) return;
        const y0 = y(cum), y1 = y(cum + v);
        svg += `<rect x="${gx.toFixed(1)}" y="${y1.toFixed(1)}" width="${barW.toFixed(1)}" height="${(y0 - y1).toFixed(1)}" fill="${ser.color}"><title>${esc(cat)} — ${esc(ser.label)} : ${esc(fmtVal(v, false))}</title></rect>`;
        cum += v;
      });
    } else {
      series.forEach((ser, si) => {
        const v = ser.values[i];
        if (v === null || v === undefined) return;
        const y0 = MT + plotH, y1 = y(v);
        const bx = gx + si * barW;
        svg += `<rect x="${bx.toFixed(1)}" y="${y1.toFixed(1)}" width="${(barW * 0.9).toFixed(1)}" height="${(y0 - y1).toFixed(1)}" fill="${ser.color}"><title>${esc(cat)} — ${esc(ser.label)} : ${esc(fmtVal(v, false))}</title></rect>`;
      });
    }
    const lx = ML + i * groupW + groupW / 2;
    svg += `<text x="${lx.toFixed(1)}" y="${MT + plotH + 14}" font-size="9" fill="#212f3c" text-anchor="end" transform="rotate(-40 ${lx.toFixed(1)} ${MT + plotH + 14})">${esc(truncLabel(cat, 18))}</text>`;
  });

  svg += "</svg>";
  return svg + legendHtml(series);
}

function renderLineAreaSvg(categories, series, filled) {
  const W = 560, H = 320, ML = 54, MR = 16, MT = 16, MB = 78;
  const plotW = W - ML - MR, plotH = H - MT - MB;
  const n = categories.length;
  let maxV = 0, minV = 0;
  for (const ser of series) for (const v of ser.values) { if (v !== null && v !== undefined) { maxV = Math.max(maxV, v); minV = Math.min(minV, v); } }
  const niceMax = niceCeil(maxV || 1);
  const x = i => n <= 1 ? ML + plotW / 2 : ML + (i / (n - 1)) * plotW;
  const y = v => MT + plotH - ((v - minV) / ((niceMax - minV) || 1)) * plotH;

  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;font-family:'Segoe UI',Arial,sans-serif;">`;
  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const v = niceMax * t / ticks, yy = y(v);
    svg += `<line x1="${ML}" y1="${yy.toFixed(1)}" x2="${W - MR}" y2="${yy.toFixed(1)}" stroke="#e5e9ea" stroke-width="1"/>`;
    svg += `<text x="${ML - 6}" y="${(yy + 3).toFixed(1)}" font-size="9" fill="#7f8c8d" text-anchor="end">${esc(fmtAxisNum(v))}</text>`;
  }
  svg += `<line x1="${ML}" y1="${MT}" x2="${ML}" y2="${MT + plotH}" stroke="#aab" stroke-width="1"/>`;
  svg += `<line x1="${ML}" y1="${MT + plotH}" x2="${W - MR}" y2="${MT + plotH}" stroke="#aab" stroke-width="1"/>`;
  categories.forEach((cat, i) => {
    const lx = x(i);
    svg += `<text x="${lx.toFixed(1)}" y="${MT + plotH + 14}" font-size="9" fill="#212f3c" text-anchor="end" transform="rotate(-40 ${lx.toFixed(1)} ${MT + plotH + 14})">${esc(truncLabel(cat, 18))}</text>`;
  });
  series.forEach(ser => {
    const pts = ser.values.map((v, i) => (v === null || v === undefined) ? null : [x(i), y(v)]).filter(Boolean);
    if (!pts.length) return;
    const pathD = pts.map((p, i) => (i === 0 ? "M" : "L") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
    if (filled && pts.length > 1) {
      const baseY = y(Math.max(minV, 0));
      const areaD = pathD + ` L${pts[pts.length - 1][0].toFixed(1)},${baseY.toFixed(1)} L${pts[0][0].toFixed(1)},${baseY.toFixed(1)} Z`;
      svg += `<path d="${areaD}" fill="${ser.color}" fill-opacity="0.25" stroke="none"/>`;
    }
    if (pts.length > 1) svg += `<path d="${pathD}" fill="none" stroke="${ser.color}" stroke-width="2"/>`;
    pts.forEach((p, i) => {
      svg += `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="${ser.color}"><title>${esc(categories[i])} — ${esc(ser.label)} : ${esc(fmtVal(ser.values[i], false))}</title></circle>`;
    });
  });
  svg += "</svg>";
  return svg + legendHtml(series);
}

function renderPieSvg(categories, values, baseColor) {
  const W = 320, H = 320, cx = W / 2, cy = H / 2 - 10, r = Math.min(W, H) / 2 - 40;
  const total = values.reduce((a, b) => a + (b || 0), 0);
  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:320px;height:auto;font-family:'Segoe UI',Arial,sans-serif;">`;
  if (!total) {
    svg += `<text x="${cx}" y="${cy}" text-anchor="middle" font-size="12" fill="#7f8c8d">Aucune donnée</text></svg>`;
    return svg;
  }
  const colorFor = i => shadeForRing(baseColor || CHART_PALETTE[0], i, categories.length);
  let angle = -Math.PI / 2;
  categories.forEach((cat, i) => {
    const v = values[i] || 0;
    if (!v) return;
    const frac = v / total;
    const a2 = angle + frac * 2 * Math.PI;
    const x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(a2), y2 = cy + r * Math.sin(a2);
    const large = frac > 0.5 ? 1 : 0;
    svg += `<path d="M${cx},${cy} L${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 ${large} 1 ${x2.toFixed(1)},${y2.toFixed(1)} Z" fill="${colorFor(i)}"><title>${esc(cat)} : ${esc(fmtVal(v, false))} (${(frac * 100).toFixed(1)} %)</title></path>`;
    angle = a2;
  });
  svg += "</svg>";
  const legendSeries = categories.map((c, i) => ({ label: `${c} (${fmtVal(values[i] || 0, false)})`, color: colorFor(i) }));
  return svg + legendHtml(legendSeries);
}

// Chemin SVG d'un secteur en couronne (anneau) entre rIn et rOut — dégénère en secteur plein
// (pointe au centre) quand rIn=0, ce qui permet de réutiliser la même fonction pour l'anneau
// intérieur (disque) et l'anneau extérieur (couronne) du camembert imbriqué.
function annulusPath(cx, cy, rIn, rOut, a1, a2) {
  const large = (a2 - a1) > Math.PI ? 1 : 0;
  const x1o = cx + rOut * Math.cos(a1), y1o = cy + rOut * Math.sin(a1);
  const x2o = cx + rOut * Math.cos(a2), y2o = cy + rOut * Math.sin(a2);
  if (rIn <= 0.01) {
    return `M${cx},${cy} L${x1o.toFixed(1)},${y1o.toFixed(1)} A${rOut},${rOut} 0 ${large} 1 ${x2o.toFixed(1)},${y2o.toFixed(1)} Z`;
  }
  const x1i = cx + rIn * Math.cos(a1), y1i = cy + rIn * Math.sin(a1);
  const x2i = cx + rIn * Math.cos(a2), y2i = cy + rIn * Math.sin(a2);
  return `M${x1i.toFixed(1)},${y1i.toFixed(1)} L${x1o.toFixed(1)},${y1o.toFixed(1)} A${rOut},${rOut} 0 ${large} 1 ${x2o.toFixed(1)},${y2o.toFixed(1)} L${x2i.toFixed(1)},${y2i.toFixed(1)} A${rIn},${rIn} 0 ${large} 0 ${x1i.toFixed(1)},${y1i.toFixed(1)} Z`;
}

// Construit l'arbre d'agrégation pour le camembert imbriqué : un niveau par fonction de clé
// (levelKeyFns[0] = axe X combiné, levelKeyFns[1..] = chaque variable de Série PRISE SÉPARÉMENT —
// une variable de Série = un anneau, pas combinée avec les autres dans un même anneau). La valeur
// de chaque nœud (feuille ou intermédiaire) est recalculée directement sur son sous-ensemble de
// lignes via agFn/extractValues (comme le tableau croisé), pas déduite de la somme des enfants —
// correct même pour une agrégation non additive (moyenne, min, max, médiane).
function buildPieHierarchy(rows, levelKeyFns, measure, aggId) {
  const isDistinct = !!measure.distinctKey;
  const nodeValue = rowsSubset => agFn(extractValues(rowsSubset, measure), isDistinct, aggId) || 0;
  function group(rowsSubset, levelIdx) {
    const value = nodeValue(rowsSubset);
    if (levelIdx >= levelKeyFns.length) return { value, children: null };
    const groups = new Map();
    for (const row of rowsSubset) {
      const key = levelKeyFns[levelIdx](row);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(row);
    }
    const children = [...groups.keys()].sort().map(label => {
      const sub = group(groups.get(label), levelIdx + 1);
      return { label, value: sub.value, children: sub.children };
    });
    return { value, children };
  }
  return group(rows, 0);
}

// Recense, pour chaque anneau (profondeur dans l'arbre), l'ensemble des libellés distincts
// rencontrés n'importe où à ce niveau — sert à attribuer une couleur stable par valeur (même
// couleur pour "Sexe = 1" quel que soit sous quelle branche X il apparaît), plutôt qu'une couleur
// qui dépendrait de la position parmi les frères d'un seul nœud.
function collectAllLevelLabels(root, nRings) {
  const levels = Array.from({ length: nRings }, () => new Set());
  function walk(node, ringIdx) {
    if (!node.children || ringIdx >= nRings) return;
    node.children.forEach(c => { levels[ringIdx].add(c.label); walk(c, ringIdx + 1); });
  }
  walk(root, 0);
  return levels.map(s => [...s].sort());
}

// Camembert imbriqué à N anneaux : anneau 0 = axe X, anneaux 1..N = une variable de Série chacun
// (subdivisant, à angle constant, le secteur du niveau parent — vrai "sunburst" hiérarchique).
// Légende affichée à partir de l'anneau 1 (Série) ; l'axe X reste en infobulle seule, pouvant
// compter beaucoup de catégories.
function renderHierPieSvg(root, nRings, ringNames, ringColors) {
  const W = 360, H = 360, cx = W / 2, cy = H / 2 - 6;
  const rOuter = Math.min(W, H) / 2 - 26;
  const rStep = rOuter / nRings;
  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:360px;height:auto;font-family:'Segoe UI',Arial,sans-serif;">`;
  if (!root.value) {
    svg += `<text x="${cx}" y="${cy}" text-anchor="middle" font-size="12" fill="#7f8c8d">Aucune donnée</text></svg>`;
    return svg;
  }
  const levelLabels = collectAllLevelLabels(root, nRings);
  function colorFor(ringIdx, label) {
    const labels = levelLabels[ringIdx];
    const base = ringColors[ringIdx] || CHART_PALETTE[ringIdx % CHART_PALETTE.length];
    return shadeForRing(base, labels.indexOf(label), labels.length);
  }
  function draw(children, ringIdx, a1, a2) {
    const total = children.reduce((s, c) => s + (c.value || 0), 0) || 1;
    let a = a1;
    children.forEach(child => {
      const frac = (child.value || 0) / total;
      if (!frac) return;
      const a2c = a + frac * (a2 - a1);
      const rIn = rStep * ringIdx, rOut = rStep * (ringIdx + 1);
      svg += `<path d="${annulusPath(cx, cy, rIn, rOut, a, a2c)}" fill="${colorFor(ringIdx, child.label)}"><title>${esc(ringNames[ringIdx])} — ${esc(child.label)} : ${esc(fmtVal(child.value, false))}</title></path>`;
      if (child.children) draw(child.children, ringIdx + 1, a, a2c);
      a = a2c;
    });
  }
  draw(root.children, 0, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI);
  svg += "</svg>";
  let extraLegend = "";
  for (let ringIdx = 0; ringIdx < nRings; ringIdx++) {
    const labels = levelLabels[ringIdx];
    if (!labels.length || (ringIdx === 0 && labels.length > 8)) continue; // axe X trop nombreux : infobulle seule
    const series = labels.map(lbl => ({ label: lbl, color: colorFor(ringIdx, lbl) }));
    extraLegend += `<div style="font-size:0.78em;color:var(--gris);margin-top:4px;">${esc(ringNames[ringIdx])}</div>` + legendHtml(series);
  }
  return svg + extraLegend;
}

// Point d'entrée du camembert imbriqué depuis genererGraphique : construit les fonctions de clé
// (une par anneau) et l'arbre, à partir des lignes déjà filtrées d'une vignette.
function renderNestedPieFromRows(rows, foreignIdx, expr, measures) {
  const measure = measures.find(m => m.id === expr.measureId);
  const xKeyFn = row => graphXDimRows.map(cfg => dimValue(dimDefOf(cfg), cfg.mode, sourceRowFor(cfg, row, foreignIdx, activeSourceGraph))).join(" / ");
  const levelKeyFns = [xKeyFn, ...graphSeriesDimRows.map(cfg =>
    row => dimValue(dimDefOf(cfg), cfg.mode, sourceRowFor(cfg, row, foreignIdx, activeSourceGraph))
  )];
  const ringNames = [graphXDimRows.map(r => labelForDimRow(r)).join(" / "), ...graphSeriesDimRows.map(r => labelForDimRow(r))];
  const root = buildPieHierarchy(rows, levelKeyFns, measure, expr.aggId);
  syncGraphRingColors();
  return renderHierPieSvg(root, levelKeyFns.length, ringNames, graphRingColors);
}

function renderScatterSvg(pivot, seriesDimsCfg, exprsUsed) {
  const exX = exprsUsed[0], exY = exprsUsed[1];
  const prX = pivot.perExpr[exX.uid], prY = pivot.perExpr[exY.uid];
  const points = [];
  pivot.rowKeys.forEach(rk => {
    pivot.colKeys.forEach(ck => {
      const vx = prX.grid[rk][ck], vy = prY.grid[rk][ck];
      if (vx !== null && vx !== undefined && vy !== null && vy !== undefined) {
        points.push({ x: vx, y: vy, label: pivot.rowPartsByKey.get(rk).join(" / "), group: seriesDimsCfg.length ? ck : null });
      }
    });
  });
  const W = 560, H = 320, ML = 54, MR = 16, MT = 16, MB = 46;
  const plotW = W - ML - MR, plotH = H - MT - MB;
  if (!points.length) return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg"><text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-size="12" fill="#7f8c8d">Aucune donnée</text></svg>`;
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const xMin = Math.min(0, ...xs), xMax = niceCeil(Math.max(...xs) || 1);
  const yMin = Math.min(0, ...ys), yMax = niceCeil(Math.max(...ys) || 1);
  const px = v => ML + ((v - xMin) / ((xMax - xMin) || 1)) * plotW;
  const py = v => MT + plotH - ((v - yMin) / ((yMax - yMin) || 1)) * plotH;
  const groups = [...new Set(points.map(p => p.group))];
  const colorFor = g => g === null ? CHART_PALETTE[0] : CHART_PALETTE[groups.indexOf(g) % CHART_PALETTE.length];

  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;font-family:'Segoe UI',Arial,sans-serif;">`;
  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const vy = yMin + (yMax - yMin) * t / ticks, yy = py(vy);
    svg += `<line x1="${ML}" y1="${yy.toFixed(1)}" x2="${W - MR}" y2="${yy.toFixed(1)}" stroke="#e5e9ea" stroke-width="1"/>`;
    svg += `<text x="${ML - 6}" y="${(yy + 3).toFixed(1)}" font-size="9" fill="#7f8c8d" text-anchor="end">${esc(fmtAxisNum(vy))}</text>`;
    const vx = xMin + (xMax - xMin) * t / ticks, xx = px(vx);
    svg += `<text x="${xx.toFixed(1)}" y="${MT + plotH + 14}" font-size="9" fill="#7f8c8d" text-anchor="middle">${esc(fmtAxisNum(vx))}</text>`;
  }
  svg += `<line x1="${ML}" y1="${MT}" x2="${ML}" y2="${MT + plotH}" stroke="#aab" stroke-width="1"/>`;
  svg += `<line x1="${ML}" y1="${MT + plotH}" x2="${W - MR}" y2="${MT + plotH}" stroke="#aab" stroke-width="1"/>`;
  svg += `<text x="${(ML + plotW / 2).toFixed(1)}" y="${H - 6}" font-size="10" fill="#212f3c" text-anchor="middle">${esc(exprLabelFor(exX, activeSourceGraph))}</text>`;
  svg += `<text x="12" y="${(MT + plotH / 2).toFixed(1)}" font-size="10" fill="#212f3c" text-anchor="middle" transform="rotate(-90 12 ${(MT + plotH / 2).toFixed(1)})">${esc(exprLabelFor(exY, activeSourceGraph))}</text>`;
  points.forEach(p => {
    svg += `<circle cx="${px(p.x).toFixed(1)}" cy="${py(p.y).toFixed(1)}" r="4" fill="${colorFor(p.group)}" fill-opacity="0.75" stroke="#fff" stroke-width="0.5"><title>${esc(p.label)}${p.group ? ` — ${esc(p.group)}` : ""} : (${esc(fmtVal(p.x, false))}, ${esc(fmtVal(p.y, false))})</title></circle>`;
  });
  svg += "</svg>";
  const legendSeries = groups.length > 1 ? groups.map((g, i) => ({ label: g, color: CHART_PALETTE[i % CHART_PALETTE.length] })) : [];
  return svg + legendHtml(legendSeries);
}

// ---- Carte de chaleur : Axe X en lignes, Série en colonnes, couleur = intensité de la mesure.
// Réutilise directement la grille du pivot (déjà calculée par computeMultiPivot).
function renderHeatmapSvg(pivot, expr) {
  const pr = pivot.perExpr[expr.uid];
  const rowsK = pivot.rowKeys, cols = pivot.colKeys;
  const rowLabels = rowsK.map(rk => pivot.rowPartsByKey.get(rk).join(" / "));
  let vmin = Infinity, vmax = -Infinity;
  rowsK.forEach(rk => cols.forEach(ck => { const v = pr.grid[rk][ck]; if (v !== null && v !== undefined) { vmin = Math.min(vmin, v); vmax = Math.max(vmax, v); } }));
  if (!isFinite(vmin)) { vmin = 0; vmax = 1; }
  const ML = 150, MT = 46, cellW = 56, cellH = 26, MR = 16, MB = 10;
  const W = ML + Math.max(1, cols.length) * cellW + MR, H = MT + Math.max(1, rowsK.length) * cellH + MB;
  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;font-family:'Segoe UI',Arial,sans-serif;">`;
  cols.forEach((ck, ci) => {
    const cx = ML + ci * cellW + cellW / 2;
    svg += `<text x="${cx}" y="${MT - 8}" font-size="9" fill="#212f3c" text-anchor="start" transform="rotate(-35 ${cx} ${MT - 8})">${esc(truncLabel(ck, 16))}</text>`;
  });
  rowsK.forEach((rk, ri) => {
    const ry = MT + ri * cellH;
    svg += `<text x="${ML - 6}" y="${ry + cellH / 2 + 3}" font-size="9" fill="#212f3c" text-anchor="end">${esc(truncLabel(rowLabels[ri], 20))}</text>`;
    cols.forEach((ck, ci) => {
      const v = pr.grid[rk][ck];
      const frac = (v === null || v === undefined) ? null : (vmax > vmin ? (v - vmin) / (vmax - vmin) : 0.5);
      const color = frac === null ? "#f4f6f7" : hslToHex(210, 65, 90 - frac * 60);
      const cx2 = ML + ci * cellW;
      svg += `<rect x="${cx2}" y="${ry}" width="${cellW - 2}" height="${cellH - 2}" fill="${color}"><title>${esc(rowLabels[ri])} — ${esc(ck)} : ${esc(fmtVal(v, false))}</title></rect>`;
      if (v !== null && v !== undefined) {
        svg += `<text x="${cx2 + (cellW - 2) / 2}" y="${ry + cellH / 2 + 3}" font-size="8.5" fill="${frac > 0.55 ? "#fff" : "#212f3c"}" text-anchor="middle">${esc(fmtAxisNum(v))}</text>`;
      }
    });
  });
  svg += "</svg>";
  return svg;
}

// ---- Boîte à moustaches : quartiles/médiane/min-max d'une mesure numérique par catégorie
// d'axe X, avec un groupe de boîtes optionnel par valeur de la 1ère variable de Série (les
// variables de Série suivantes, s'il y en a, sont ignorées — un seul niveau de regroupement a
// un sens visuel pour ce type de graphique, contrairement au camembert imbriqué).
function computeBoxStats(values) {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const q = p => { const idx = p * (s.length - 1), lo = Math.floor(idx), hi = Math.ceil(idx); return s[lo] + (s[hi] - s[lo]) * (idx - lo); };
  return { min: s[0], q1: q(0.25), median: q(0.5), q3: q(0.75), max: s[s.length - 1], n: s.length };
}
function buildBoxplotGroups(rows, xDimsCfg, serieDimCfg, measure, foreignIdx, baseSrcKey) {
  const groups = new Map();
  for (const row of rows) {
    const xKey = xDimsCfg.map(cfg => dimValue(dimDefOf(cfg), cfg.mode, sourceRowFor(cfg, row, foreignIdx, baseSrcKey))).join(" / ");
    const sKey = serieDimCfg ? dimValue(dimDefOf(serieDimCfg), serieDimCfg.mode, sourceRowFor(serieDimCfg, row, foreignIdx, baseSrcKey)) : "Total";
    if (!groups.has(xKey)) groups.set(xKey, new Map());
    const sub = groups.get(xKey);
    if (!sub.has(sKey)) sub.set(sKey, []);
    sub.get(sKey).push(row);
  }
  const categories = [...groups.keys()].sort();
  const serieKeys = serieDimCfg ? [...new Set(categories.flatMap(xk => [...groups.get(xk).keys()]))].sort() : ["Total"];
  const series = serieKeys.map((sk, i) => ({
    label: sk,
    color: CHART_PALETTE[i % CHART_PALETTE.length],
    boxes: categories.map(xk => computeBoxStats(extractValues((groups.get(xk).get(sk)) || [], measure))),
  }));
  return { categories, series };
}
function renderBoxplotSvg(categories, series) {
  const W = 560, H = 320, ML = 54, MR = 16, MT = 16, MB = 78;
  const plotW = W - ML - MR, plotH = H - MT - MB;
  const n = categories.length;
  let maxV = -Infinity, minV = Infinity;
  series.forEach(ser => ser.boxes.forEach(b => { if (b) { maxV = Math.max(maxV, b.max); minV = Math.min(minV, b.min); } }));
  if (!isFinite(maxV)) { maxV = 1; minV = 0; }
  const pad = (maxV - minV) * 0.08 || 1;
  const yMin = minV - pad, yMax = maxV + pad;
  const y = v => MT + plotH - ((v - yMin) / ((yMax - yMin) || 1)) * plotH;
  const groupW = plotW / Math.max(1, n);
  const boxGap = groupW * 0.15, boxAreaW = groupW - boxGap;
  const slotW = boxAreaW / Math.max(1, series.length), boxW = slotW * 0.62;

  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;font-family:'Segoe UI',Arial,sans-serif;">`;
  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const v = yMin + (yMax - yMin) * t / ticks, yy = y(v);
    svg += `<line x1="${ML}" y1="${yy.toFixed(1)}" x2="${W - MR}" y2="${yy.toFixed(1)}" stroke="#e5e9ea" stroke-width="1"/>`;
    svg += `<text x="${ML - 6}" y="${(yy + 3).toFixed(1)}" font-size="9" fill="#7f8c8d" text-anchor="end">${esc(fmtAxisNum(v))}</text>`;
  }
  svg += `<line x1="${ML}" y1="${MT}" x2="${ML}" y2="${MT + plotH}" stroke="#aab" stroke-width="1"/>`;
  svg += `<line x1="${ML}" y1="${MT + plotH}" x2="${W - MR}" y2="${MT + plotH}" stroke="#aab" stroke-width="1"/>`;

  categories.forEach((cat, i) => {
    const gx = ML + i * groupW + boxGap / 2;
    series.forEach((ser, si) => {
      const b = ser.boxes[i];
      if (!b) return;
      const bx = gx + si * slotW + (slotW - boxW) / 2, cxMid = bx + boxW / 2;
      svg += `<line x1="${cxMid.toFixed(1)}" y1="${y(b.min).toFixed(1)}" x2="${cxMid.toFixed(1)}" y2="${y(b.max).toFixed(1)}" stroke="${ser.color}" stroke-width="1.4"/>`;
      svg += `<line x1="${bx.toFixed(1)}" y1="${y(b.min).toFixed(1)}" x2="${(bx + boxW).toFixed(1)}" y2="${y(b.min).toFixed(1)}" stroke="${ser.color}" stroke-width="1.4"/>`;
      svg += `<line x1="${bx.toFixed(1)}" y1="${y(b.max).toFixed(1)}" x2="${(bx + boxW).toFixed(1)}" y2="${y(b.max).toFixed(1)}" stroke="${ser.color}" stroke-width="1.4"/>`;
      svg += `<rect x="${bx.toFixed(1)}" y="${y(b.q3).toFixed(1)}" width="${boxW.toFixed(1)}" height="${(y(b.q1) - y(b.q3)).toFixed(1)}" fill="${ser.color}" fill-opacity="0.35" stroke="${ser.color}" stroke-width="1.4"><title>${esc(cat)} — ${esc(ser.label)} : médiane ${esc(fmtVal(b.median, false))}, Q1 ${esc(fmtVal(b.q1, false))}, Q3 ${esc(fmtVal(b.q3, false))}, min ${esc(fmtVal(b.min, false))}, max ${esc(fmtVal(b.max, false))}, n=${b.n}</title></rect>`;
      svg += `<line x1="${bx.toFixed(1)}" y1="${y(b.median).toFixed(1)}" x2="${(bx + boxW).toFixed(1)}" y2="${y(b.median).toFixed(1)}" stroke="${ser.color}" stroke-width="2.4"/>`;
    });
    const lx = ML + i * groupW + groupW / 2;
    svg += `<text x="${lx.toFixed(1)}" y="${MT + plotH + 14}" font-size="9" fill="#212f3c" text-anchor="end" transform="rotate(-40 ${lx.toFixed(1)} ${MT + plotH + 14})">${esc(truncLabel(cat, 18))}</text>`;
  });
  svg += "</svg>";
  return svg + legendHtml(series.length > 1 ? series : []);
}

// ---- Histogramme : distribution d'une mesure numérique en classes de même largeur (règle de
// Sturges pour le nombre de classes), avec une superposition optionnelle par 1ère variable de
// Série (mêmes classes pour toutes les séries, pour rester comparables).
function computeHistogramBins(values) {
  if (!values.length) return { counts: [], min: 0, max: 0, width: 1, k: 0 };
  const min = Math.min(...values), max = Math.max(...values);
  const span = (max - min) || 1;
  const k = Math.max(5, Math.min(20, Math.ceil(Math.log2(values.length + 1)) + 1));
  const width = span / k;
  const counts = new Array(k).fill(0);
  values.forEach(v => { let idx = Math.floor((v - min) / width); if (idx >= k) idx = k - 1; if (idx < 0) idx = 0; counts[idx]++; });
  return { counts, min, max, width, k };
}
function buildHistogramSeries(rows, serieDimCfg, measure, foreignIdx, baseSrcKey) {
  const allValues = extractValues(rows, measure);
  const bins = computeHistogramBins(allValues);
  if (!serieDimCfg || !bins.k) {
    return { bins, series: [{ label: "Total", color: CHART_PALETTE[0], counts: bins.counts }] };
  }
  const groups = new Map();
  for (const row of rows) {
    const sKey = dimValue(dimDefOf(serieDimCfg), serieDimCfg.mode, sourceRowFor(serieDimCfg, row, foreignIdx, baseSrcKey));
    if (!groups.has(sKey)) groups.set(sKey, []);
    groups.get(sKey).push(row);
  }
  const serieKeys = [...groups.keys()].sort();
  const series = serieKeys.map((sk, i) => {
    const vals = extractValues(groups.get(sk), measure);
    const counts = new Array(bins.k).fill(0);
    vals.forEach(v => { let idx = Math.floor((v - bins.min) / bins.width); if (idx >= bins.k) idx = bins.k - 1; if (idx < 0) idx = 0; counts[idx]++; });
    return { label: sk, color: CHART_PALETTE[i % CHART_PALETTE.length], counts };
  });
  return { bins, series };
}
function renderHistogramSvg(bins, series) {
  const W = 560, H = 320, ML = 54, MR = 16, MT = 16, MB = 46;
  const plotW = W - ML - MR, plotH = H - MT - MB;
  const k = bins.k || 0;
  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;font-family:'Segoe UI',Arial,sans-serif;">`;
  if (!k) { svg += `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-size="12" fill="#7f8c8d">Aucune donnée</text></svg>`; return svg; }
  let maxCount = 0;
  series.forEach(ser => ser.counts.forEach(c => maxCount = Math.max(maxCount, c)));
  const niceMax = niceCeil(maxCount || 1);
  const y = v => MT + plotH - (v / niceMax) * plotH;
  const binW = plotW / k;
  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const v = niceMax * t / ticks, yy = y(v);
    svg += `<line x1="${ML}" y1="${yy.toFixed(1)}" x2="${W - MR}" y2="${yy.toFixed(1)}" stroke="#e5e9ea" stroke-width="1"/>`;
    svg += `<text x="${ML - 6}" y="${(yy + 3).toFixed(1)}" font-size="9" fill="#7f8c8d" text-anchor="end">${esc(fmtAxisNum(v))}</text>`;
  }
  svg += `<line x1="${ML}" y1="${MT}" x2="${ML}" y2="${MT + plotH}" stroke="#aab" stroke-width="1"/>`;
  svg += `<line x1="${ML}" y1="${MT + plotH}" x2="${W - MR}" y2="${MT + plotH}" stroke="#aab" stroke-width="1"/>`;
  for (let i = 0; i < k; i++) {
    const x0 = ML + i * binW;
    const slotW = binW / series.length;
    series.forEach((ser, si) => {
      const c = ser.counts[i] || 0;
      const bx = x0 + si * slotW, y0 = MT + plotH, y1 = y(c);
      svg += `<rect x="${bx.toFixed(1)}" y="${y1.toFixed(1)}" width="${(slotW * 0.92).toFixed(1)}" height="${(y0 - y1).toFixed(1)}" fill="${ser.color}"><title>[${esc(fmtAxisNum(bins.min + i * bins.width))} – ${esc(fmtAxisNum(bins.min + (i + 1) * bins.width))}[ — ${esc(ser.label)} : ${c}</title></rect>`;
    });
    if (k <= 10 || i % Math.ceil(k / 8) === 0) {
      svg += `<text x="${x0.toFixed(1)}" y="${MT + plotH + 14}" font-size="8.5" fill="#7f8c8d" text-anchor="middle">${esc(fmtAxisNum(bins.min + i * bins.width))}</text>`;
    }
  }
  svg += `<text x="${(ML + plotW).toFixed(1)}" y="${MT + plotH + 14}" font-size="8.5" fill="#7f8c8d" text-anchor="middle">${esc(fmtAxisNum(bins.max))}</text>`;
  svg += "</svg>";
  return svg + legendHtml(series.length > 1 ? series : []);
}

// ---- Treemap : mêmes niveaux hiérarchiques que le camembert imbriqué (axe X + une variable de
// Série par niveau) mais en rectangles imbriqués (partition "slice and dice", axe alterné à
// chaque profondeur) plutôt qu'en anneaux — même arbre (buildPieHierarchy), même logique de
// couleur par anneau (graphRingColors + shadeForRing) pour rester cohérent avec le camembert.
function renderTreemapSvg(root, ringNames, ringColors) {
  const W = 560, H = 360;
  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;font-family:'Segoe UI',Arial,sans-serif;">`;
  if (!root.value) {
    svg += `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-size="12" fill="#7f8c8d">Aucune donnée</text></svg>`;
    return svg;
  }
  const levelLabels = collectAllLevelLabels(root, ringNames.length);
  function colorFor(depth, label) {
    const labels = levelLabels[depth];
    const base = ringColors[depth] || CHART_PALETTE[depth % CHART_PALETTE.length];
    return shadeForRing(base, labels.indexOf(label), labels.length);
  }
  function layout(node, x, y, w, h, depth) {
    if (!node.children || !node.children.length) return;
    const horiz = depth % 2 === 0;
    const total = node.children.reduce((s, c) => s + (c.value || 0), 0) || 1;
    let pos = horiz ? x : y;
    node.children.forEach(child => {
      let cx = x, cy = y, cw = w, ch = h;
      const frac = (child.value || 0) / total;
      if (horiz) { cw = w * frac; cx = pos; pos += cw; } else { ch = h * frac; cy = pos; pos += ch; }
      const color = colorFor(depth, child.label);
      svg += `<rect x="${cx.toFixed(1)}" y="${cy.toFixed(1)}" width="${Math.max(0, cw - 1.5).toFixed(1)}" height="${Math.max(0, ch - 1.5).toFixed(1)}" fill="${color}" stroke="#fff" stroke-width="1.5"><title>${esc(ringNames[depth])} — ${esc(child.label)} : ${esc(fmtVal(child.value, false))}</title></rect>`;
      if (cw > 38 && ch > 15) {
        svg += `<text x="${(cx + 4).toFixed(1)}" y="${(cy + 13).toFixed(1)}" font-size="9" fill="#fff" style="pointer-events:none;">${esc(truncLabel(child.label, Math.max(3, Math.floor(cw / 6))))}</text>`;
      }
      layout(child, cx, cy, cw, ch, depth + 1);
    });
  }
  layout(root, 0, 0, W, H, 0);
  svg += "</svg>";
  return svg;
}
function renderTreemapFromRows(rows, foreignIdx, expr, measures) {
  const measure = measures.find(m => m.id === expr.measureId);
  const xKeyFn = row => graphXDimRows.map(cfg => dimValue(dimDefOf(cfg), cfg.mode, sourceRowFor(cfg, row, foreignIdx, activeSourceGraph))).join(" / ");
  const levelKeyFns = [xKeyFn, ...graphSeriesDimRows.map(cfg =>
    row => dimValue(dimDefOf(cfg), cfg.mode, sourceRowFor(cfg, row, foreignIdx, activeSourceGraph))
  )];
  const ringNames = [graphXDimRows.map(r => labelForDimRow(r)).join(" / "), ...graphSeriesDimRows.map(r => labelForDimRow(r))];
  const root = buildPieHierarchy(rows, levelKeyFns, measure, expr.aggId);
  syncGraphRingColors();
  return renderTreemapSvg(root, ringNames, graphRingColors);
}

function renderChartFragment(chartType, pivot, seriesDimsCfg, exprsUsed) {
  if (chartType === "carte_chaleur") {
    return renderHeatmapSvg(pivot, exprsUsed[0]);
  }
  if (chartType === "camembert") {
    // Le camembert imbriqué (Série non vide) est construit directement depuis les lignes brutes
    // (renderNestedPieFromRows, appelé depuis genererGraphique) — un anneau par variable de
    // Série, pas via le pivot qui combinerait les variables de Série en une seule clé.
    const { categories, series } = chartSeriesData(pivot, [], exprsUsed);
    syncGraphRingColors();
    return renderPieSvg(categories, series[0].values, graphRingColors[0]);
  }
  if (chartType === "nuage") {
    return renderScatterSvg(pivot, seriesDimsCfg, exprsUsed);
  }
  const { categories, series } = chartSeriesData(pivot, seriesDimsCfg, exprsUsed);
  if (chartType === "barres_empilees") return renderBarSvg(categories, series, true);
  if (chartType === "lignes") return renderLineAreaSvg(categories, series, false);
  if (chartType === "aires") return renderLineAreaSvg(categories, series, true);
  return renderBarSvg(categories, series, false);
}

function genererGraphique() {
  const statusEl = document.getElementById("statusGraph");
  const setSt = (msg, err) => { statusEl.textContent = msg || ""; statusEl.style.color = err ? "#c0392b" : ""; };
  try {
    const src = SOURCES[activeSourceGraph];
    const finessList = selectedFiness();
    const periods = computeSelectedPeriods();
    if (!finessList.length) { setSt("Sélectionnez au moins un établissement.", true); return; }
    if (!periods.length) { setSt("Sélectionnez au moins une année valide pour le mois choisi.", true); return; }
    if (!graphXDimRows.length) { setSt("Ajoutez au moins une variable en axe X.", true); return; }
    if (!graphExprRows.length) { setSt("Ajoutez au moins une expression (mesure).", true); return; }

    let chartType = activeChartType;
    if (!chartType) {
      chartType = suggestChartType(graphXDimRows, graphSeriesDimRows, graphExprRows);
      activeChartType = chartType;
      document.querySelectorAll("#chartTypeTabs button").forEach(b => b.classList.toggle("active", b.dataset.type === chartType));
      renderRingColorsUI();
    }
    syncGraphRingColors();
    if (chartType === "nuage" && graphExprRows.length < 2) {
      setSt("Le nuage de points nécessite 2 expressions (mesure représentée en X, puis en Y).", true);
      return;
    }
    if (chartType === "boxplot" || chartType === "histogramme") {
      const m = src.measures.find(m => m.id === graphExprRows[0].measureId);
      if (m && m.distinctKey) {
        setSt("Boîte à moustaches / histogramme nécessitent une mesure numérique (pas un comptage de distincts).", true);
        return;
      }
    }

    setSt("Interrogation de la base…");
    const { sql, params } = buildQuery(activeSourceGraph, finessList, periods);
    let rows = queryAll(sql, params);
    tagPeriod(rows, activeSourceGraph, periods);

    const activeGF = activeGlobalFilters();
    const foreignSrcKeys = new Set(
      [...graphXDimRows, ...graphSeriesDimRows, ...graphFacetDimRows].map(r => r.srcKey)
        .concat(activeGF.map(f => f.srcKey))
        .filter(k => k !== activeSourceGraph)
    );
    const foreignIdx = {};
    for (const srcKey of foreignSrcKeys) foreignIdx[srcKey] = buildForeignIndex(srcKey, finessList, periods);

    rows = applyGlobalFilters(rows, activeSourceGraph, foreignIdx);

    const exprsUsed = (chartType === "camembert" || chartType === "boxplot" || chartType === "histogramme") ? graphExprRows.slice(0, 1)
      : chartType === "nuage" ? graphExprRows.slice(0, 2)
      : graphExprRows;

    const facetGroups = splitByFacets(rows, graphFacetDimRows, foreignIdx, activeSourceGraph);
    const facetsShown = facetGroups.slice(0, GRAPH_FACET_CAP);

    const panels = facetsShown.map(g => {
      let fragment;
      if (chartType === "camembert" && graphSeriesDimRows.length) {
        fragment = renderNestedPieFromRows(g.rows, foreignIdx, exprsUsed[0], src.measures);
      } else if (chartType === "treemap") {
        fragment = renderTreemapFromRows(g.rows, foreignIdx, exprsUsed[0], src.measures);
      } else if (chartType === "boxplot") {
        const measure = src.measures.find(m => m.id === exprsUsed[0].measureId);
        const { categories, series } = buildBoxplotGroups(g.rows, graphXDimRows, graphSeriesDimRows[0] || null, measure, foreignIdx, activeSourceGraph);
        fragment = renderBoxplotSvg(categories, series);
      } else if (chartType === "histogramme") {
        const measure = src.measures.find(m => m.id === exprsUsed[0].measureId);
        const { bins, series } = buildHistogramSeries(g.rows, graphSeriesDimRows[0] || null, measure, foreignIdx, activeSourceGraph);
        fragment = renderHistogramSvg(bins, series);
      } else {
        const pivot = computeMultiPivot(g.rows, graphXDimRows, graphSeriesDimRows, exprsUsed, src.measures, foreignIdx, activeSourceGraph);
        fragment = renderChartFragment(chartType, pivot, graphSeriesDimRows, exprsUsed);
      }
      return `<div class="chart-panel">${g.label ? `<h4>${esc(g.label)}</h4>` : ""}${fragment}</div>`;
    });

    document.getElementById("panelGraphResult").style.display = "block";
    const xLabel = graphXDimRows.map(r => labelForDimRow(r)).join(" / ");
    const serieLabel = graphSeriesDimRows.length ? graphSeriesDimRows.map(r => labelForDimRow(r)).join(" / ") : "(aucune)";
    const facetLabel = graphFacetDimRows.length ? graphFacetDimRows.map(r => labelForDimRow(r)).join(" / ") : "(aucune)";
    const metaText = `Type : ${CHART_TYPE_LABELS[chartType]} · Axe X : ${xLabel} · Série : ${serieLabel} · ` +
      `Vignettes : ${facetLabel}${facetGroups.length > 1 ? ` (${facetsShown.length}${facetGroups.length > GRAPH_FACET_CAP ? ` sur ${facetGroups.length}` : ""})` : ""} · ` +
      `Mesure(s) : ${exprsUsed.map(e => exprLabelFor(e, activeSourceGraph)).join(", ")} · Filtres globaux : ${activeGF.length}`;
    document.getElementById("graphResultMeta").textContent = metaText;
    document.getElementById("graphResultWrap").innerHTML = panels.join("");
    setSt(`Graphique généré (${facetsShown.length} vignette(s)).`);
  } catch (e) {
    setSt("Erreur : " + e.message, true);
    console.error(e);
  }
}

// ---------- Mode "Fiche séjour (NDA)" ----------

function populateFicheFiness() {
  const rows = queryAll("SELECT DISTINCT finess_epmsi FROM rhs_groupe ORDER BY 1");
  const sel = document.getElementById("selFicheFiness");
  sel.innerHTML = "";
  rows.forEach(r => {
    const o = document.createElement("option");
    o.value = r.finess_epmsi; o.textContent = r.finess_epmsi;
    sel.appendChild(o);
  });
}

function ficheStatus(msg, err) {
  const el = document.getElementById("statusFiche");
  el.textContent = msg || "";
  el.style.color = err ? "#c0392b" : "";
}

function semaineDates(numero_semaine, jhw, jwe) {
  const week = Number(numero_semaine.slice(0, 2)), year = Number(numero_semaine.slice(2, 6));
  const flags = (jhw || "") + (jwe || "");
  const dates = [];
  for (let wd = 1; wd <= flags.length; wd++) {
    if (flags[wd - 1] === "1") {
      const d = isoWeekDate(year, week, wd);
      if (!isNaN(d)) dates.push(fmtDate(d));
    }
  }
  return dates;
}

function rechercherFiche() {
  const finess = document.getElementById("selFicheFiness").value;
  const ndaRaw = document.getElementById("inpFicheNda").value.trim();
  if (!finess || !ndaRaw) { ficheStatus("Sélectionnez un établissement et saisissez un NDA.", true); return; }
  const ndaNum = Number(ndaRaw);
  if (isNaN(ndaNum)) { ficheStatus("NDA invalide (doit être numérique).", true); return; }
  ficheStatus("Recherche…");
  try {
    const vid = queryAll(
      `SELECT * FROM vid_hosp WHERE finess_epmsi=? AND CAST(numero_admin_sejour AS INTEGER)=?`,
      [finess, ndaNum]
    );
    const rhsRaw = queryAll(
      `SELECT r.*, gme.libelle_long AS lib_gme, gn.libelle_long AS lib_gn,
              err.libelle AS lib_erreur, err.type AS type_erreur,
              dp.libelle_complet AS lib_dp, ae.libelle_complet AS lib_ae
       FROM rhs_groupe r
       LEFT JOIN nomenclature_gme gme ON gme.code = r.code_gme AND gme.kind = 'GME'
       LEFT JOIN nomenclature_gme gn ON gn.code = substr(r.code_gme,1,4) AND gn.kind = 'GN'
       LEFT JOIN nomenclature_gme_erreurs err
              ON err.code = CASE WHEN r.code_retour_groupage GLOB '[0-9]*'
                                  THEN CAST(CAST(r.code_retour_groupage AS INTEGER) AS TEXT)
                                  ELSE r.code_retour_groupage END
       LEFT JOIN nomenclature_diagnostics dp ON dp.code = r.manifestation_morbide_principale
       LEFT JOIN nomenclature_diagnostics ae ON ae.code = r.affection_etiologique
       WHERE r.finess_epmsi=? AND CAST(r.numero_admin_sejour AS INTEGER)=?`,
      [finess, ndaNum]
    );
    rhsRaw.sort((a, b) => {
      const ka = a.numero_semaine.slice(2, 6) + a.numero_semaine.slice(0, 2);
      const kb = b.numero_semaine.slice(2, 6) + b.numero_semaine.slice(0, 2);
      return ka.localeCompare(kb);
    });

    const ids = rhsRaw.map(r => r.id);
    let das = [], csarr = [], csar = [], ccam = [];
    if (ids.length) {
      const ph = ids.map(() => "?").join(",");
      das = queryAll(`SELECT d.*, dp.libelle_complet AS lib_das FROM rhs_groupe_das d
                       LEFT JOIN nomenclature_diagnostics dp ON dp.code = d.code_das
                       WHERE d.parent_id IN (${ph})`, ids);
      csarr = queryAll(`SELECT c.*, nom.libelle AS lib_csarr, interv.libelle AS lib_intervenant
                         FROM rhs_groupe_csarr c
                         LEFT JOIN nomenclature_csarr nom ON nom.code = c.code_principal
                         LEFT JOIN nomenclature_csarr_intervenants interv ON interv.code = c.code_intervenant
                         WHERE c.parent_id IN (${ph})`, ids);
      csar = queryAll(`SELECT c.*, nom.libelle AS lib_csar, interv.libelle AS lib_intervenant
                        FROM rhs_groupe_csar c
                        LEFT JOIN nomenclature_csar nom ON nom.code = c.code_principal
                        LEFT JOIN nomenclature_csar_intervenants interv ON interv.code = c.code_intervenant
                        WHERE c.parent_id IN (${ph})`, ids);
      ccam = queryAll(`SELECT k.*, nom.libelle AS lib_ccam
                        FROM rhs_groupe_ccam k
                        LEFT JOIN nomenclature_ccam nom ON nom.code = k.code_ccam
                        WHERE k.parent_id IN (${ph})`, ids);
    }
    const valo = queryAll(
      `SELECT * FROM valorisation_sejour WHERE finess_epmsi=? AND CAST(numero_admin_sejour AS INTEGER)=? ORDER BY campagne`,
      [finess, ndaNum]
    );

    renderFiche({ finess, nda: ndaRaw, vid, rhsRaw, das, csarr, csar, ccam, valo });
    if (!rhsRaw.length && !vid.length) {
      ficheStatus("Aucune donnée trouvée pour ce NDA sur cet établissement.", true);
    } else {
      ficheStatus(`${rhsRaw.length} semaine(s) RHS · ${vid.length} ligne(s) VID-HOSP · ${valo.length} campagne(s) valorisée(s).`);
    }
  } catch (e) {
    ficheStatus("Erreur : " + e.message, true);
    console.error(e);
  }
}

function renderFiche(d) {
  const panel = document.getElementById("panelFicheResult");
  const v = d.vid[0];

  let html = `<h2>Fiche séjour — NDA ${esc(d.nda)} — Établissement ${esc(d.finess)}</h2>`;

  if (!v) {
    html += `<p><span class="badge err">Aucune ligne VID-HOSP</span> ce séjour n'a pas (ou plus) de dossier VID-HOSP correspondant — vérifier une éventuelle incohérence de clôture.</p>`;
  } else {
    const age = ageAns(v.date_naissance_beneficiaire, v.date_entree);
    html += `<dl class="fiche-header">
      <div><dt>IPP</dt><dd>${esc(normVal(v.numero_ipp))}</dd></div>
      <div><dt>Sexe</dt><dd>${esc(normVal(v.sexe_beneficiaire))}</dd></div>
      <div><dt>Date de naissance</dt><dd>${esc(normVal(v.date_naissance_beneficiaire))}</dd></div>
      <div><dt>Âge à l'entrée</dt><dd>${age != null ? age.toFixed(1) + " ans" : "—"}</dd></div>
      <div><dt>Date d'entrée</dt><dd>${esc(normVal(v.date_entree))}</dd></div>
      <div><dt>Date de sortie</dt><dd>${esc(normVal(v.date_sortie))}</dd></div>
      <div><dt>Régime</dt><dd>${esc(normVal(v.code_grand_regime))}</dd></div>
      <div><dt>Bénéficiaire CMU-C</dt><dd>${esc(normVal(v.patient_beneficiaire_cmu))}</dd></div>
      <div><dt>Établissement transfert</dt><dd>${esc(normVal(v.etablissement_transfert))}</dd></div>
      <div><dt>Établissement retour</dt><dd>${esc(normVal(v.etablissement_retour))}</dd></div>
    </dl>`;
  }

  // ---- Tableau récapitulatif des semaines RHS ----
  const dasByParent = {}, csarrByParent = {}, csarByParent = {}, ccamByParent = {};
  const group = (arr, map) => arr.forEach(r => { (map[r.parent_id] = map[r.parent_id] || []).push(r); });
  group(d.das, dasByParent); group(d.csarr, csarrByParent); group(d.csar, csarByParent); group(d.ccam, ccamByParent);

  html += `<h3>Semaines RHS (${d.rhsRaw.length})</h3>`;
  if (!d.rhsRaw.length) {
    html += `<p style="color:var(--gris)">Aucune ligne RHS pour ce séjour.</p>`;
  } else {
    html += `<table class="semaines"><thead><tr>
      <th>Semaine</th><th>Type</th><th>GME</th><th>Erreur groupage</th>
      <th>AVQ phys.</th><th>AVQ cogn.</th><th>Jours de présence</th><th>DAS / CSARR / CSAR / CCAM</th>
    </tr></thead><tbody>`;
    d.rhsRaw.forEach(r => {
      const semaineLbl = `S${r.numero_semaine.slice(0, 2)}-${r.numero_semaine.slice(2, 6)}`;
      const erreurOk = r.code_retour_groupage === "0" || r.code_retour_groupage === "000" || !r.code_retour_groupage;
      const erreurHtml = erreurOk
        ? "—"
        : `<span class="badge ${r.type_erreur && r.type_erreur.toLowerCase().includes("bloq") ? "err" : ""}">${esc(r.code_retour_groupage)} — ${esc(r.lib_erreur || "?")}</span>`;
      const avqPhys = sumNum(r.dependance_habillage_toilette, r.dependance_deplacement, r.dependance_alimentation, r.dependance_continence);
      const avqCogn = sumNum(r.dependance_comportement, r.dependance_relation);
      const dates = semaineDates(r.numero_semaine, r.jours_hors_weekend, r.jours_weekend);
      const nbActes = (dasByParent[r.id] || []).length + (csarrByParent[r.id] || []).length +
                       (csarByParent[r.id] || []).length + (ccamByParent[r.id] || []).length;
      html += `<tr>
        <td>${esc(semaineLbl)}</td>
        <td>${esc(normVal(r.type_hospitalisation))}</td>
        <td>${esc(r.code_gme)}${r.lib_gme ? " — " + esc(r.lib_gme) : ""}</td>
        <td>${erreurHtml}</td>
        <td>${avqPhys != null ? avqPhys : "—"}</td>
        <td>${avqCogn != null ? avqCogn : "—"}</td>
        <td>${dates.length ? esc(dates.join(", ")) : "—"}</td>
        <td>${(dasByParent[r.id]||[]).length} / ${(csarrByParent[r.id]||[]).length} / ${(csarByParent[r.id]||[]).length} / ${(ccamByParent[r.id]||[]).length}</td>
      </tr>`;
    });
    html += "</tbody></table>";

    html += `<h3>Détail par semaine</h3>`;
    d.rhsRaw.forEach(r => {
      const semaineLbl = `S${r.numero_semaine.slice(0, 2)}-${r.numero_semaine.slice(2, 6)}`;
      html += `<details class="semaine-detail"><summary>${esc(semaineLbl)} — GME ${esc(r.code_gme)}${r.lib_gme ? " (" + esc(r.lib_gme) + ")" : ""}</summary><div class="semaine-body">`;
      html += `<p><strong>Diagnostic principal :</strong> ${esc(normVal(r.manifestation_morbide_principale))}${r.lib_dp ? " — " + esc(r.lib_dp) : ""}<br>`;
      html += `<strong>Affection étiologique :</strong> ${esc(normVal(r.affection_etiologique))}${r.lib_ae ? " — " + esc(r.lib_ae) : ""}</p>`;

      const das = dasByParent[r.id] || [];
      if (das.length) {
        html += `<table class="actes-mini"><thead><tr><th>DAS</th><th>Libellé</th></tr></thead><tbody>`;
        das.forEach(x => { html += `<tr><td>${esc(x.code_das)}</td><td>${esc(x.lib_das || "")}</td></tr>`; });
        html += "</tbody></table>";
      }
      const actesTable = (arr, cols) => {
        if (!arr.length) return "";
        let t = `<table class="actes-mini"><thead><tr>${cols.map(c => `<th>${esc(c[0])}</th>`).join("")}</tr></thead><tbody>`;
        arr.forEach(x => { t += `<tr>${cols.map(c => `<td>${esc(normVal(c[1](x)))}</td>`).join("")}</tr>`; });
        return t + "</tbody></table>";
      };
      const csarrRows = csarrByParent[r.id] || [];
      if (csarrRows.length) {
        html += `<p><strong>Actes CSARR</strong></p>` + actesTable(csarrRows, [
          ["Code", x => x.code_principal], ["Libellé", x => x.lib_csarr], ["Intervenant", x => x.lib_intervenant || x.code_intervenant], ["Réalisations", x => x.nombre_realisations],
        ]);
      }
      const csarRows = csarByParent[r.id] || [];
      if (csarRows.length) {
        html += `<p><strong>Actes CSAR</strong></p>` + actesTable(csarRows, [
          ["Code", x => x.code_principal], ["Libellé", x => x.lib_csar], ["Intervenant", x => x.lib_intervenant || x.code_intervenant], ["Réalisations", x => x.nombre_realisations],
        ]);
      }
      const ccamRows = ccamByParent[r.id] || [];
      if (ccamRows.length) {
        html += `<p><strong>Actes CCAM</strong></p>` + actesTable(ccamRows, [
          ["Code", x => x.code_ccam], ["Libellé", x => x.lib_ccam], ["Réalisations", x => x.nombre_realisations],
        ]);
      }
      if (!das.length && !csarrRows.length && !csarRows.length && !ccamRows.length) {
        html += `<p style="color:var(--gris)">Aucun diagnostic associé ni acte enregistré cette semaine.</p>`;
      }
      html += "</div></details>";
    });
  }

  // ---- Valorisation ----
  html += `<h3>Valorisation (${d.valo.length} campagne(s))</h3>`;
  if (!d.valo.length) {
    html += `<p style="color:var(--gris)">Aucune ligne de valorisation pour ce séjour.</p>`;
  } else {
    html += `<table class="semaines"><thead><tr>
      <th>Campagne</th><th>GME</th><th>Montant BR total</th><th>Montant AM total</th>
      <th>Jours GMT (≤90j)</th><th>Jours GMTH (&gt;90j)</th><th>Score RR</th><th>Score RR spé.</th>
    </tr></thead><tbody>`;
    d.valo.forEach(x => {
      html += `<tr>
        <td>${esc(normVal(x.campagne))}</td>
        <td>${esc(normVal(x.code_gme))}</td>
        <td>${x.montant_br_tot != null ? Number(x.montant_br_tot).toLocaleString("fr-FR", { minimumFractionDigits: 2 }) + " €" : "—"}</td>
        <td>${x.montant_am_tot != null ? Number(x.montant_am_tot).toLocaleString("fr-FR", { minimumFractionDigits: 2 }) + " €" : "—"}</td>
        <td>${esc(normVal(x.nb_jours_valorises_gmt))}</td>
        <td>${esc(normVal(x.nb_jours_valorises_gmth))}</td>
        <td>${esc(normVal(x.score_rr))}</td>
        <td>${esc(normVal(x.score_rr_spe))}</td>
      </tr>`;
    });
    html += "</tbody></table>";
  }

  html += `<div class="export-bar"><button class="secondary" id="btnExportFiche">Exporter / Imprimer en PDF</button></div>`;

  panel.innerHTML = html;
  panel.style.display = "block";
  document.getElementById("btnExportFiche").addEventListener("click", () => {
    document.getElementById("printExport").innerHTML = html.replace(/<div class="export-bar">.*<\/div>/s, "");
    window.print();
  });
}

// ---------- Exports ----------

function download(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function exportHtml() {
  if (!lastResult) return;
  const html = `<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><title>${esc(lastResult.titleText)}</title>
<style>
body{font-family:Arial,sans-serif;color:#212f3c;margin:24px;}
h1{color:#1a5276;font-size:1.2em;}
p{color:#7f8c8d;font-size:0.9em;}
table{border-collapse:collapse;width:100%;font-size:0.9em;}
th,td{border:1px solid #d5dbdb;padding:6px 10px;text-align:right;}
td:first-child,th:first-child{text-align:left;}
th{background:#eaf2f8;}
tr:last-child td{background:#eaf2f8;font-weight:700;}
</style></head><body>
<h1>${esc(lastResult.titleText)}</h1><p>${esc(lastResult.metaText)}</p>
${lastResult.tableHtml}
</body></html>`;
  download("tdb_export.html", html, "text/html;charset=utf-8");
}

function exportPdf() {
  if (!lastResult) return;
  document.getElementById("printExport").innerHTML =
    `<h2>${esc(lastResult.titleText)}</h2><p>${esc(lastResult.metaText)}</p>${lastResult.tableHtml}`;
  window.print();
}

function exportXls() {
  if (!lastResult) return;
  const xlsHtml = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="utf-8"><title>${esc(lastResult.titleText)}</title>
<!--[if gte mso 9]><xml><x:ExcelWorkbook><x:ExcelWorksheets><x:ExcelWorksheet>
<x:Name>TDB</x:Name><x:WorksheetOptions><x:DisplayGridlines/></x:WorksheetOptions>
</x:ExcelWorksheet></x:ExcelWorksheets></x:ExcelWorkbook></xml><![endif]-->
<style>
table{border-collapse:collapse;} td,th{border:1px solid #999;padding:4px 9px;} th{background:#eaf2f8;font-weight:bold;}
tr:last-child td{background:#eaf2f8;font-weight:bold;}
</style></head>
<body><table><tr><td colspan="2"><b>${esc(lastResult.titleText)}</b></td></tr><tr><td colspan="2">${esc(lastResult.metaText)}</td></tr><tr><td></td></tr></table>${lastResult.tableHtml}</body></html>`;
  download("tdb_export.xls", xlsHtml, "application/vnd.ms-excel");
}

function exportDoc() {
  if (!lastResult) return;
  const docHtml = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="utf-8"><title>${esc(lastResult.titleText)}</title>
<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View><w:Zoom>100</w:Zoom></w:WordDocument></xml><![endif]-->
<style>
body{font-family:Calibri,Arial,sans-serif;color:#212f3c;}
h2{color:#1a5276;} p{color:#555;font-size:0.9em;}
table{border-collapse:collapse;} td,th{border:1px solid #999;padding:4px 9px;} th{background:#eaf2f8;}
tr:last-child td{background:#eaf2f8;font-weight:bold;}
</style></head>
<body><h2>${esc(lastResult.titleText)}</h2><p>${esc(lastResult.metaText)}</p>${lastResult.tableHtml}</body></html>`;
  download("tdb_export.doc", docHtml, "application/msword");
}

// ---------- Câblage évènements ----------

function wireEvents() {
  document.getElementById("checksAnnees").addEventListener("change", () => { updateRecap(); renderGlobalFilterList(); });
  document.getElementById("selMois").addEventListener("change", () => { updateRecap(); renderGlobalFilterList(); });

  document.querySelectorAll("#sourceTabs button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#sourceTabs button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeSource = btn.dataset.src;
      // Changer d'onglet ne change que la table de mesures (expressions) : les variables déjà
      // choisies en lignes/colonnes, qui peuvent venir de n'importe quel fichier, sont conservées.
      const src = SOURCES[activeSource];
      exprRows = [{ uid: ++uidCounter, measureId: src.measures[0].id, aggId: "count", label: "" }];
      renderExprList();
      renderDimsList("rowDimsList", rowDimRows, 1);
      renderDimsList("colDimsList", colDimRows, 0);
      updateRecap();
    });
  });

  document.getElementById("btnAddRowDim").addEventListener("click", () => {
    const src = SOURCES[activeSource];
    rowDimRows.push({ uid: ++uidCounter, srcKey: activeSource, dimId: src.dims[0].id, mode: defaultModeFor(src.dims[0]) });
    renderDimsList("rowDimsList", rowDimRows, 1);
    updateRecap();
  });
  document.getElementById("btnAddColDim").addEventListener("click", () => {
    const src = SOURCES[activeSource];
    colDimRows.push({ uid: ++uidCounter, srcKey: activeSource, dimId: src.dims[0].id, mode: defaultModeFor(src.dims[0]) });
    renderDimsList("colDimsList", colDimRows, 0);
    updateRecap();
  });
  document.getElementById("btnAddExpr").addEventListener("click", () => {
    const src = SOURCES[activeSource];
    exprRows.push({ uid: ++uidCounter, measureId: src.measures[0].id, aggId: "count", label: "" });
    renderExprList();
    updateRecap();
  });

  document.getElementById("btnGenerer").addEventListener("click", generer);
  document.getElementById("btnExportHtml").addEventListener("click", exportHtml);
  document.getElementById("btnExportPdf").addEventListener("click", exportPdf);
  document.getElementById("btnExportDoc").addEventListener("click", exportDoc);
  document.getElementById("btnExportXls").addEventListener("click", exportXls);

  // ---- Mode "Liste filtrée" ----
  document.querySelectorAll("#sourceTabsListe button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#sourceTabsListe button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeSourceListe = btn.dataset.src;
      refreshListeUI();
    });
  });
  document.getElementById("btnAddFilter").addEventListener("click", () => {
    const src = SOURCES[activeSourceListe];
    filterRows.push({ uid: ++uidCounter, srcKey: activeSourceListe, kind: "dim", id: src.dims[0].id, op: "eq", val: "", val2: "" });
    renderFilterList();
  });
  document.getElementById("btnAddListeCol").addEventListener("click", () => {
    const src = SOURCES[activeSourceListe];
    const d = src.dims[0];
    listeColRows.push({ uid: ++uidCounter, srcKey: activeSourceListe, kind: "dim", id: d.id, mode: defaultModeFor(d) });
    renderListeColsList();
  });
  document.getElementById("btnGenererListe").addEventListener("click", genererListe);

  // ---- Mode "Fiche séjour (NDA)" ----
  document.getElementById("btnRechercherFiche").addEventListener("click", rechercherFiche);
  document.getElementById("inpFicheNda").addEventListener("keydown", e => { if (e.key === "Enter") rechercherFiche(); });

  // ---- Choix du parcours (écran d'entrée) ----
  function goToEntry() {
    activeParcours = null;
    document.getElementById("panelEntry").style.display = "block";
    document.getElementById("flowRequetes").style.display = "none";
    document.getElementById("flowDossier").style.display = "none";
  }
  function goToParcours(p) {
    activeParcours = p;
    document.getElementById("panelEntry").style.display = "none";
    document.getElementById("flowRequetes").style.display = p === "requetes" ? "block" : "none";
    document.getElementById("flowDossier").style.display = p === "dossier" ? "block" : "none";
    if (p === "requetes") goToSortieChoice();
  }
  document.querySelectorAll("#panelEntry .entry-choice").forEach(btn => {
    btn.addEventListener("click", () => goToParcours(btn.dataset.parcours));
  });
  document.getElementById("btnBackFromRequetes").addEventListener("click", e => { e.preventDefault(); goToEntry(); });
  document.getElementById("btnBackFromDossier").addEventListener("click", e => { e.preventDefault(); goToEntry(); });
  goToEntry();

  // ---- Choix de sortie, dans "Requêtes sur mesure" (Tableaux / Graphique) ----
  function goToSortieChoice() {
    activeSortie = null;
    document.getElementById("panelSortieChoice").style.display = "block";
    document.getElementById("flowTableaux").style.display = "none";
    document.getElementById("flowGraphique").style.display = "none";
  }
  function goToSortie(s) {
    activeSortie = s;
    document.getElementById("panelSortieChoice").style.display = "none";
    document.getElementById("flowTableaux").style.display = s === "tableaux" ? "block" : "none";
    document.getElementById("flowGraphique").style.display = s === "graphique" ? "block" : "none";
    if (s === "graphique") refreshGraphUI();
  }
  document.querySelectorAll("#panelSortieChoice .entry-choice").forEach(btn => {
    btn.addEventListener("click", () => goToSortie(btn.dataset.sortie));
  });
  document.getElementById("btnBackFromTableaux").addEventListener("click", e => { e.preventDefault(); goToSortieChoice(); });
  document.getElementById("btnBackFromGraphique").addEventListener("click", e => { e.preventDefault(); goToSortieChoice(); });

  // ---- Bascule de mode (sous-onglets de "Tableaux") ----
  document.querySelectorAll("#modeTabs button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#modeTabs button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeMode = btn.dataset.mode;
      document.getElementById("modePivot").style.display = activeMode === "pivot" ? "" : "none";
      document.getElementById("modeListe").style.display = activeMode === "liste" ? "" : "none";
      document.getElementById("panelResult").style.display = "none";
    });
  });

  // ---- Filtres globaux (section "1. Filtres") ----
  document.getElementById("btnAddGlobalFilter").addEventListener("click", () => {
    const srcKey = SOURCE_ORDER[0];
    const src = SOURCES[srcKey];
    globalFilterRows.push({ uid: ++uidCounter, srcKey, kind: "dim", id: src.dims[0].id, values: [], op: "between", val: "", val2: "" });
    renderGlobalFilterList();
  });

  // ---- Mode "Graphique" ----
  document.querySelectorAll("#sourceTabsGraph button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#sourceTabsGraph button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeSourceGraph = btn.dataset.src;
      const src = SOURCES[activeSourceGraph];
      graphExprRows = [{ uid: ++uidCounter, measureId: src.measures[0].id, aggId: "count", label: "" }];
      renderExprListGeneric("graphExprList", graphExprRows, activeSourceGraph, 1);
    });
  });
  document.getElementById("btnAddGraphXDim").addEventListener("click", () => {
    if (graphXDimRows.length >= 3) return;
    const src = SOURCES[activeSourceGraph];
    graphXDimRows.push({ uid: ++uidCounter, srcKey: activeSourceGraph, dimId: src.dims[0].id, mode: defaultModeFor(src.dims[0]) });
    renderDimsList("graphXDimsList", graphXDimRows, 1);
  });
  document.getElementById("btnAddGraphSeriesDim").addEventListener("click", () => {
    if (graphSeriesDimRows.length >= 3) return;
    const src = SOURCES[activeSourceGraph];
    graphSeriesDimRows.push({ uid: ++uidCounter, srcKey: activeSourceGraph, dimId: src.dims[0].id, mode: defaultModeFor(src.dims[0]) });
    renderDimsList("graphSeriesDimsList", graphSeriesDimRows, 0);
  });
  document.getElementById("btnAddGraphFacetDim").addEventListener("click", () => {
    if (graphFacetDimRows.length >= 3) return;
    const src = SOURCES[activeSourceGraph];
    graphFacetDimRows.push({ uid: ++uidCounter, srcKey: activeSourceGraph, dimId: src.dims[0].id, mode: defaultModeFor(src.dims[0]) });
    renderDimsList("graphFacetDimsList", graphFacetDimRows, 0);
  });
  document.getElementById("btnAddGraphExpr").addEventListener("click", () => {
    const src = SOURCES[activeSourceGraph];
    graphExprRows.push({ uid: ++uidCounter, measureId: src.measures[0].id, aggId: "count", label: "" });
    renderExprListGeneric("graphExprList", graphExprRows, activeSourceGraph, 1);
  });
  document.querySelectorAll("#chartTypeTabs button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#chartTypeTabs button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeChartType = btn.dataset.type;
      renderRingColorsUI();
    });
  });
  document.getElementById("btnGenererGraph").addEventListener("click", genererGraphique);

  refreshDimUI();
}

init();
