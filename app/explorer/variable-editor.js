// VariableEditor — le dialogue "Créer une variable calculée". Ne parle qu'à Formula.* et
// SessionVars.*, jamais directement à SOURCES en écriture (SessionVars est le seul point
// d'injection). Un seul module, injecté une fois dans le document au premier open().
window.VariableEditor = (function () {
  "use strict";

  let built = false;
  let els = {};
  let onSaveCb = null;

  function build() {
    if (built) return;
    built = true;

    const style = document.createElement("style");
    style.textContent = `
      .ve-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.35); display: none;
        align-items: flex-start; justify-content: center; z-index: 9999; padding: 6vh 16px; }
      .ve-overlay.open { display: flex; }
      .ve-modal { background: var(--surface); color: var(--texte); border: 1px solid var(--bordure);
        border-radius: 8px; width: 640px; max-width: 100%; box-shadow: 0 12px 40px rgba(0,0,0,.25);
        font-family: "Segoe UI", Arial, sans-serif; }
      .ve-head { padding: 14px 20px; border-bottom: 1px solid var(--bordure); font-weight: 600;
        color: var(--bleu); display: flex; justify-content: space-between; align-items: center; }
      .ve-head .ve-close { cursor: pointer; color: var(--gris); font-size: 1.2em; line-height: 1; border: none; background: none; }
      .ve-body { padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
      .ve-row { display: flex; gap: 12px; }
      .ve-field { display: flex; flex-direction: column; gap: 4px; flex: 1; }
      .ve-field label { font-size: .78em; color: var(--gris); font-weight: 600; text-transform: uppercase; letter-spacing: .03em; }
      .ve-field input[type=text], .ve-field select { padding: 7px 9px; border: 1px solid var(--bordure);
        border-radius: 4px; background: var(--surface); color: var(--texte); font-size: .95em; }
      .ve-formula-wrap { position: relative; }
      .ve-formula { width: 100%; min-height: 76px; padding: 10px 12px; border: 1px solid var(--bordure);
        border-radius: 6px; background: var(--surface-alt); color: var(--texte); font-family: "Cascadia Code","Consolas",monospace;
        font-size: .92em; resize: vertical; }
      .ve-formula:focus { outline: 2px solid var(--bleu-clair); border-color: var(--bleu); }
      .ve-autocomplete { position: absolute; left: 0; right: 0; top: 100%; margin-top: 4px; background: var(--surface);
        border: 1px solid var(--bordure); border-radius: 6px; box-shadow: 0 8px 24px rgba(0,0,0,.18);
        max-height: 220px; overflow-y: auto; z-index: 10; display: none; }
      .ve-autocomplete.open { display: block; }
      .ve-ac-row { padding: 6px 10px; display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: .88em; }
      .ve-ac-row:hover, .ve-ac-row.hi { background: var(--bleu-clair); }
      .ve-ac-badge { flex: none; width: 16px; height: 16px; border-radius: 4px; display: flex; align-items: center;
        justify-content: center; font-size: 10px; font-weight: 700; }
      .ve-ac-badge.fn { background: color-mix(in srgb, #93641c 20%, transparent); color: #93641c; }
      .ve-ac-badge.fld { background: var(--bleu-clair); color: var(--bleu); }
      .ve-ac-name { flex: 1; font-family: "Cascadia Code","Consolas",monospace; }
      .ve-ac-tag { font-size: .75em; color: var(--gris); }
      .ve-status { font-size: .85em; padding: 8px 10px; border-radius: 5px; font-family: "Cascadia Code","Consolas",monospace; }
      .ve-status.ok { background: var(--surface-subtotal); color: var(--vert); }
      .ve-status.err { background: var(--surface-danger); color: var(--danger); border: 1px solid var(--danger-border); }
      .ve-status.idle { color: var(--gris); }
      .ve-foot { padding: 14px 20px; border-top: 1px solid var(--bordure); display: flex; justify-content: flex-end; gap: 10px; }
    `;
    document.head.appendChild(style);

    const overlay = document.createElement("div");
    overlay.className = "ve-overlay";
    overlay.innerHTML = `
      <div class="ve-modal" role="dialog" aria-modal="true">
        <div class="ve-head"><span>➕ Créer une variable calculée</span><button class="ve-close" type="button">✕</button></div>
        <div class="ve-body">
          <div class="ve-row">
            <div class="ve-field"><label>Nom</label><input type="text" class="ve-name" placeholder="ex. Valo par jour de présence"></div>
            <div class="ve-field"><label>Source de base</label><select class="ve-src"></select></div>
          </div>
          <div class="ve-field">
            <label>Formule</label>
            <div class="ve-formula-wrap">
              <textarea class="ve-formula" spellcheck="false" placeholder="Sum([valo].[montant_br_tot]) / Sum([nb_journees])"></textarea>
              <div class="ve-autocomplete"></div>
            </div>
          </div>
          <div class="ve-status idle">Écrivez une formule pour la valider.</div>
        </div>
        <div class="ve-foot">
          <button type="button" class="secondary ve-cancel">Annuler</button>
          <button type="button" class="primary ve-save" disabled>Créer</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    els = {
      overlay,
      close: overlay.querySelector(".ve-close"),
      cancel: overlay.querySelector(".ve-cancel"),
      save: overlay.querySelector(".ve-save"),
      name: overlay.querySelector(".ve-name"),
      src: overlay.querySelector(".ve-src"),
      formula: overlay.querySelector(".ve-formula"),
      ac: overlay.querySelector(".ve-autocomplete"),
      status: overlay.querySelector(".ve-status"),
    };

    els.close.addEventListener("click", close);
    els.cancel.addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    els.formula.addEventListener("input", () => { renderAutocomplete(); validateNow(); });
    els.formula.addEventListener("keydown", onFormulaKeydown);
    els.formula.addEventListener("blur", () => setTimeout(() => hideAutocomplete(), 150));
    els.src.addEventListener("change", () => { renderAutocomplete(); validateNow(); });
    els.name.addEventListener("input", validateNow);
    els.save.addEventListener("click", doSave);
  }

  function close() { els.overlay.classList.remove("open"); }

  function currentWord() {
    const ta = els.formula, v = ta.value, pos = ta.selectionStart;
    let start = pos;
    while (start > 0 && /[A-Za-z0-9_#\[\]]/.test(v[start - 1])) start--;
    return { text: v.slice(start, pos), start, end: pos };
  }

  function fieldCandidates(srcKey) {
    const src = SOURCES[srcKey];
    if (!src) return [];
    const out = [];
    const add = (list) => (list || []).forEach((e) => { if (!e.distinctKey) out.push(e); });
    add(src.dims); add(src.measures);
    return out;
  }

  let acIndex = -1, acItems = [];

  function renderAutocomplete() {
    const word = currentWord();
    const srcKey = els.src.value;
    const bareWord = word.text.replace(/^\[/, "").replace(/\]$/, "");
    if (!bareWord) { hideAutocomplete(); return; }

    const lower = bareWord.toLowerCase();
    const fnMatches = Object.values(Formula.Registry)
      .filter((f) => f.name.toLowerCase().includes(lower))
      .map((f) => ({ kind: "fn", name: f.name, tag: f.category }));
    const fldMatches = fieldCandidates(srcKey)
      .filter((e) => e.id.toLowerCase().includes(lower) || e.label.toLowerCase().includes(lower))
      .map((e) => ({ kind: "fld", name: e.id, label: e.label, tag: srcKey }));

    acItems = [...fldMatches.slice(0, 8), ...fnMatches.slice(0, 8)];
    acIndex = acItems.length ? 0 : -1;
    if (!acItems.length) { hideAutocomplete(); return; }

    els.ac.innerHTML = acItems.map((it, i) => `
      <div class="ve-ac-row${i === acIndex ? " hi" : ""}" data-i="${i}">
        <span class="ve-ac-badge ${it.kind === "fn" ? "fn" : "fld"}">${it.kind === "fn" ? "ƒ" : "▮"}</span>
        <span class="ve-ac-name">${it.kind === "fn" ? it.name + "()" : "[" + it.name + "]"}</span>
        <span class="ve-ac-tag">${it.kind === "fn" ? it.tag : it.label}</span>
      </div>`).join("");
    els.ac.querySelectorAll(".ve-ac-row").forEach((row) => {
      row.addEventListener("mousedown", (e) => { e.preventDefault(); insertItem(acItems[+row.dataset.i]); });
    });
    els.ac.classList.add("open");
  }

  function hideAutocomplete() { els.ac.classList.remove("open"); acItems = []; acIndex = -1; }

  function insertItem(item) {
    const ta = els.formula, word = currentWord();
    const insertText = item.kind === "fn" ? `${item.name}()` : `[${item.name}]`;
    const before = ta.value.slice(0, word.start), after = ta.value.slice(word.end);
    ta.value = before + insertText + after;
    const caret = before.length + (item.kind === "fn" ? insertText.length - 1 : insertText.length);
    ta.focus(); ta.setSelectionRange(caret, caret);
    hideAutocomplete();
    validateNow();
  }

  function onFormulaKeydown(e) {
    if (!els.ac.classList.contains("open")) return;
    if (e.key === "ArrowDown") { e.preventDefault(); acIndex = Math.min(acIndex + 1, acItems.length - 1); refreshHi(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); acIndex = Math.max(acIndex - 1, 0); refreshHi(); }
    else if (e.key === "Tab" || e.key === "Enter") { if (acItems[acIndex]) { e.preventDefault(); insertItem(acItems[acIndex]); } }
    else if (e.key === "Escape") { hideAutocomplete(); }
  }
  function refreshHi() {
    els.ac.querySelectorAll(".ve-ac-row").forEach((row, i) => row.classList.toggle("hi", i === acIndex));
  }

  function validateNow() {
    const formula = els.formula.value.trim();
    const name = els.name.value.trim();
    if (!formula) { setStatus("idle", "Écrivez une formule pour la valider."); els.save.disabled = true; return; }
    try {
      const ast = Formula.parse(formula);
      Formula.validate(ast, els.src.value);
      setStatus("ok", "Formule valide.");
      els.save.disabled = !name;
    } catch (e) {
      setStatus("err", (e instanceof Formula.FormulaError) ? e.message : String(e.message || e));
      els.save.disabled = true;
    }
  }

  function setStatus(kind, msg) { els.status.className = "ve-status " + kind; els.status.textContent = msg; }

  let editingId = null;

  function doSave() {
    try {
      const args = { name: els.name.value.trim(), formula: els.formula.value.trim(), srcKey: els.src.value };
      const entry = editingId ? SessionVars.updateMeasure(editingId, args) : SessionVars.createMeasure(args);
      close();
      if (onSaveCb) onSaveCb(entry);
    } catch (e) {
      setStatus("err", (e instanceof Formula.FormulaError) ? e.message : String(e.message || e));
    }
  }

  // opts: { defaultSrcKey, onSave(entry), editId } — editId : ouvre en mode modification,
  // préremplit depuis SessionVars.get(editId), et le clic sur "Enregistrer" appelle
  // updateMeasure() au lieu de createMeasure() (même id conservé).
  function open(opts) {
    build();
    opts = opts || {};
    onSaveCb = opts.onSave || null;
    editingId = opts.editId || null;
    const existing = editingId ? SessionVars.get(editingId) : null;

    els.overlay.querySelector(".ve-head span").textContent = existing ? "✎ Modifier la variable calculée" : "➕ Créer une variable calculée";
    els.save.textContent = existing ? "Enregistrer" : "Créer";
    els.name.value = existing ? existing.name : "";
    els.formula.value = existing ? existing.formula : "";
    setStatus("idle", "Écrivez une formule pour la valider.");
    els.save.disabled = true;
    hideAutocomplete();

    els.src.innerHTML = "";
    SOURCE_ORDER.forEach((k) => {
      const o = document.createElement("option");
      o.value = k; o.textContent = SOURCES[k].label;
      if (k === (existing ? existing.srcKey : (opts.defaultSrcKey || SOURCE_ORDER[0]))) o.selected = true;
      els.src.appendChild(o);
    });

    if (existing) validateNow();
    els.overlay.classList.add("open");
    setTimeout(() => els.name.focus(), 30);
  }

  // ---------- Gestionnaire (liste, modifier, supprimer) ----------

  let mgrBuilt = false, mgrEls = {}, onChangeCb = null;

  function buildManager() {
    if (mgrBuilt) return;
    mgrBuilt = true;
    const style = document.createElement("style");
    style.textContent = `
      .vem-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.35); display: none;
        align-items: flex-start; justify-content: center; z-index: 9998; padding: 6vh 16px; }
      .vem-overlay.open { display: flex; }
      .vem-modal { background: var(--surface); color: var(--texte); border: 1px solid var(--bordure);
        border-radius: 8px; width: 620px; max-width: 100%; box-shadow: 0 12px 40px rgba(0,0,0,.25);
        font-family: "Segoe UI", Arial, sans-serif; }
      .vem-head { padding: 14px 20px; border-bottom: 1px solid var(--bordure); font-weight: 600;
        color: var(--bleu); display: flex; justify-content: space-between; align-items: center; }
      .vem-head .vem-close { cursor: pointer; color: var(--gris); font-size: 1.2em; line-height: 1; border: none; background: none; }
      .vem-body { padding: 10px 20px; max-height: 50vh; overflow-y: auto; }
      .vem-empty { padding: 20px 0; color: var(--gris); font-size: .9em; text-align: center; }
      .vem-row { padding: 10px 0; border-bottom: 1px solid var(--bordure); display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
      .vem-row:last-child { border-bottom: none; }
      .vem-row .vem-name { font-weight: 600; }
      .vem-row .vem-meta { font-size: .78em; color: var(--gris); margin-top: 2px; }
      .vem-row .vem-formula { font-family: "Cascadia Code","Consolas",monospace; font-size: .82em; color: var(--texte);
        background: var(--surface-alt); border-radius: 4px; padding: 4px 7px; margin-top: 4px; display: inline-block; }
      .vem-row .vem-actions { flex: none; display: flex; gap: 6px; }
      .vem-row .vem-actions button { font-size: .82em; padding: 4px 10px; }
      .vem-foot { padding: 14px 20px; border-top: 1px solid var(--bordure); display: flex; justify-content: space-between; gap: 10px; }
    `;
    document.head.appendChild(style);

    const overlay = document.createElement("div");
    overlay.className = "vem-overlay";
    overlay.innerHTML = `
      <div class="vem-modal" role="dialog" aria-modal="true">
        <div class="vem-head"><span>🛠 Variables calculées (session)</span><button class="vem-close" type="button">✕</button></div>
        <div class="vem-body"><div class="vem-list"></div></div>
        <div class="vem-foot">
          <button type="button" class="secondary vem-new">➕ Nouvelle variable</button>
          <button type="button" class="secondary vem-done">Fermer</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    mgrEls = { overlay, close: overlay.querySelector(".vem-close"), done: overlay.querySelector(".vem-done"),
      list: overlay.querySelector(".vem-list"), newBtn: overlay.querySelector(".vem-new") };
    mgrEls.close.addEventListener("click", closeManager);
    mgrEls.done.addEventListener("click", closeManager);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) closeManager(); });
    mgrEls.newBtn.addEventListener("click", () => { closeManager(); open({ onSave: onChangeCb }); });
  }

  function closeManager() { mgrEls.overlay.classList.remove("open"); }

  function renderManagerList() {
    const items = SessionVars.list();
    if (!items.length) { mgrEls.list.innerHTML = '<div class="vem-empty">Aucune variable calculée créée dans cette session.</div>'; return; }
    mgrEls.list.innerHTML = items.map((it) => `
      <div class="vem-row" data-id="${it.id}">
        <div>
          <div class="vem-name">${it.name}</div>
          <div class="vem-meta">Source : ${(SOURCES[it.srcKey] && SOURCES[it.srcKey].label) || it.srcKey}</div>
          <div class="vem-formula">${it.formula}</div>
        </div>
        <div class="vem-actions">
          <button type="button" class="secondary vem-edit">✎ Modifier</button>
          <button type="button" class="secondary vem-del">🗑 Supprimer</button>
        </div>
      </div>`).join("");
    mgrEls.list.querySelectorAll(".vem-row").forEach((row) => {
      const id = row.dataset.id;
      row.querySelector(".vem-edit").addEventListener("click", () => { closeManager(); open({ editId: id, onSave: onChangeCb }); });
      row.querySelector(".vem-del").addEventListener("click", () => {
        if (!confirm(`Supprimer la variable "${SessionVars.get(id).name}" ? Les tableaux qui l'utilisent perdront cette mesure.`)) return;
        SessionVars.remove(id);
        renderManagerList();
        if (onChangeCb) onChangeCb(null);
      });
    });
  }

  // opts: { onChange() } — appelé après chaque suppression et après fermeture (pour que
  // l'appelant rafraîchisse les sélecteurs qui listent les mesures).
  function openManager(opts) {
    buildManager();
    onChangeCb = (opts && opts.onChange) || null;
    renderManagerList();
    mgrEls.overlay.classList.add("open");
  }

  return { open, openManager };
})();
