// Explorateur TDB PMSI-SMR — logique applicative (sql.js, 100% navigateur, aucun serveur).

let db = null;
let activeSource = "rhs";
let lastResult = null; // { titleText, metaText, tableHtml }
let uidCounter = 0;

let rowDimRows = [];  // { uid, dimId, mode: 'code'|'libelle'|'both' }
let colDimRows = [];
let exprRows = [];    // { uid, measureId, aggId, label }

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
  document.getElementById("panelPivot").style.display = "block";
  refreshDimUI();
}

// ---------- Listes dynamiques : lignes / colonnes / expressions ----------

function defaultModeFor(dim) {
  return (dim && (dim.libCol || dim.libDerive)) ? "libelle" : "code";
}

function refreshDimUI() {
  const src = SOURCES[activeSource];
  rowDimRows = [{ uid: ++uidCounter, dimId: src.dims[0].id, mode: defaultModeFor(src.dims[0]) }];
  colDimRows = [];
  exprRows = [{ uid: ++uidCounter, measureId: src.measures[0].id, aggId: "count", label: "" }];
  renderDimsList("rowDimsList", rowDimRows, src.dims, 1);
  renderDimsList("colDimsList", colDimRows, src.dims, 0);
  renderExprList();
  updateRecap();
}

function renderDimsList(containerId, arr, dims, minCount) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  arr.forEach(row => {
    const div = document.createElement("div");
    div.className = "var-row";

    const sel = document.createElement("select");
    dims.forEach(d => {
      const o = document.createElement("option");
      o.value = d.id; o.textContent = d.label;
      if (d.id === row.dimId) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener("change", () => {
      row.dimId = sel.value;
      row.mode = defaultModeFor(dims.find(x => x.id === row.dimId));
      renderDimsList(containerId, arr, dims, minCount);
      updateRecap();
    });
    div.appendChild(sel);

    const d = dims.find(x => x.id === row.dimId);
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
      renderDimsList(containerId, arr, dims, minCount);
      updateRecap();
    });
    div.appendChild(rm);

    container.appendChild(div);
  });
}

function renderExprList() {
  const container = document.getElementById("exprList");
  const src = SOURCES[activeSource];
  container.innerHTML = "";
  exprRows.forEach(row => {
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
    rm.disabled = exprRows.length <= 1;
    rm.addEventListener("click", () => {
      if (exprRows.length <= 1) return;
      const idx = exprRows.indexOf(row);
      if (idx >= 0) exprRows.splice(idx, 1);
      renderExprList();
      updateRecap();
    });

    div.appendChild(measSel); div.appendChild(aggSel); div.appendChild(labelInput); div.appendChild(rm);
    container.appendChild(div);
  });
}

function labelForDimRow(row, dims) {
  const d = dims.find(x => x.id === row.dimId);
  if (!d) return "?";
  if (d.libCol || d.libDerive) {
    const modeLabel = row.mode === "code" ? "code" : row.mode === "both" ? "code + libellé" : "libellé";
    return `${d.label} (${modeLabel})`;
  }
  return d.label;
}

function exprLabel(expr) {
  const src = SOURCES[activeSource];
  const measure = src.measures.find(m => m.id === expr.measureId);
  const agg = AGG_DEFS.find(a => a.id === expr.aggId);
  if (expr.label && expr.label.trim()) return expr.label.trim();
  return `${agg ? agg.short : expr.aggId} — ${measure ? measure.label : expr.measureId}`;
}

function updateRecap() {
  const src = SOURCES[activeSource];
  const finessList = selectedFiness();
  const periods = computeSelectedPeriods();
  const box = document.getElementById("recapBox");
  box.innerHTML = `<dl>
    <dt>Établissement(s)</dt><dd>${finessList.length ? esc(finessList.join(", ")) : '<span style="color:#c0392b">aucun sélectionné</span>'}</dd>
    <dt>Période</dt><dd>${periods.length ? esc(periods.map(p => p.label).join(", ")) : '<span style="color:#c0392b">aucune période valide</span>'}</dd>
    <dt>Table source</dt><dd>${esc(src.label)}</dd>
    <dt>Lignes</dt><dd>${rowDimRows.map(r => esc(labelForDimRow(r, src.dims))).join(" / ") || "—"}</dd>
    <dt>Colonnes</dt><dd>${colDimRows.length ? colDimRows.map(r => esc(labelForDimRow(r, src.dims))).join(" / ") : "(aucune)"}</dd>
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

function dimValue(dim, mode, row) {
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

function computeMultiPivot(rows, rowDimsCfg, colDimsCfg, exprsCfg, dims, measures) {
  function rowKeyOf(row) { return rowDimsCfg.map(r => dimValue(dims.find(d => d.id === r.dimId), r.mode, row)).join(" | "); }
  function colKeyOf(row) { return colDimsCfg.length ? colDimsCfg.map(r => dimValue(dims.find(d => d.id === r.dimId), r.mode, row)).join(" | ") : "Total"; }

  const cells = new Map();
  const rowKeysSet = new Set(), colKeysSet = new Set();
  for (const row of rows) {
    const rk = rowKeyOf(row), ck = colKeyOf(row);
    rowKeysSet.add(rk); colKeysSet.add(ck);
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

  return { rowKeys, colKeys, perExpr };
}

function fmtVal(v, isPct) {
  if (v === null || v === undefined || (typeof v === "number" && isNaN(v))) return "—";
  if (isPct) return v.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " %";
  return v.toLocaleString("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function renderMultiPivotTable(pivot, rowLabel, exprsCfg) {
  const n = exprsCfg.length;
  let html = '<table class="pivot"><thead><tr><th rowspan="2">' + esc(rowLabel || "—") + "</th>";
  for (const ck of pivot.colKeys) html += `<th colspan="${n}">${esc(ck)}</th>`;
  html += `<th colspan="${n}" class="totalcol">Total</th></tr><tr>`;
  for (const ck of pivot.colKeys) for (const e of exprsCfg) html += `<th class="exprhead">${esc(exprLabel(e))}</th>`;
  for (const e of exprsCfg) html += `<th class="exprhead totalcol">${esc(exprLabel(e))}</th>`;
  html += "</tr></thead><tbody>";

  for (const rk of pivot.rowKeys) {
    html += '<tr><td class="rowhead">' + esc(rk) + "</td>";
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
  }

  html += '<tr class="totalrow"><td class="rowhead">Total</td>';
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
    const rows = queryAll(sql, params);
    tagPeriod(rows, activeSource, periods);

    const pivot = computeMultiPivot(rows, rowDimRows, colDimRows, exprRows, src.dims, src.measures);
    const rowLabel = rowDimRows.map(r => labelForDimRow(r, src.dims)).join(" / ");
    const tableHtml = renderMultiPivotTable(pivot, rowLabel, exprRows);

    const titleText = `TDB PMSI-SMR — ${src.label} — Établissement(s) ${finessList.join(", ")}`;
    const metaText = `Période : ${periods.map(p => p.label).join(", ")} · Lignes : ${rowLabel} · ` +
      `Colonnes : ${colDimRows.length ? colDimRows.map(r => labelForDimRow(r, src.dims)).join(" / ") : "(aucune)"} · ` +
      `Expressions : ${exprRows.map(e => exprLabel(e)).join(", ")} · ${rows.length} ligne(s) source analysée(s)`;

    document.getElementById("panelResult").style.display = "block";
    document.getElementById("resultMeta").textContent = metaText;
    document.getElementById("resultWrap").innerHTML = tableHtml;
    lastResult = { titleText, metaText, tableHtml };
    ["btnExportHtml", "btnExportPdf", "btnExportDoc"].forEach(id => document.getElementById(id).disabled = false);
    status(`Tableau généré (${pivot.rowKeys.length} ligne(s) × ${pivot.colKeys.length} colonne(s) × ${exprRows.length} expression(s)).`);
  } catch (e) {
    status("Erreur : " + e.message, true);
    console.error(e);
  }
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
  document.getElementById("checksAnnees").addEventListener("change", updateRecap);
  document.getElementById("selMois").addEventListener("change", updateRecap);

  document.querySelectorAll("#sourceTabs button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#sourceTabs button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeSource = btn.dataset.src;
      refreshDimUI();
    });
  });

  document.getElementById("btnAddRowDim").addEventListener("click", () => {
    const src = SOURCES[activeSource];
    rowDimRows.push({ uid: ++uidCounter, dimId: src.dims[0].id, mode: defaultModeFor(src.dims[0]) });
    renderDimsList("rowDimsList", rowDimRows, src.dims, 1);
    updateRecap();
  });
  document.getElementById("btnAddColDim").addEventListener("click", () => {
    const src = SOURCES[activeSource];
    colDimRows.push({ uid: ++uidCounter, dimId: src.dims[0].id, mode: defaultModeFor(src.dims[0]) });
    renderDimsList("colDimsList", colDimRows, src.dims, 0);
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

  refreshDimUI();
}

init();
