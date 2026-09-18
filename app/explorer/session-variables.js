// SessionVars — registre des variables calculées ad-hoc (portée session navigateur,
// jamais écrites sur disque). Un seul point d'injection dans le catalogue (SOURCES) :
// une fois créée, une variable apparaît partout où SOURCES[srcKey].measures est lu —
// aucun autre fichier n'a besoin de connaître son existence.
//
// Portée actuelle : MESURES uniquement (formule en mode "cell", ex. Sum(...)/Sum(...)).
// Le mode DIMENSION (formule en mode "row", ex. Class([montant],500) sans agrégat) n'est
// pas encore branché ici — Formula.validate() rejette aujourd'hui tout formule qui reste
// en mode "row" au sommet. Extension prévue, pas un oubli silencieux.
window.SessionVars = (function () {
  "use strict";

  const store = new Map(); // id -> entry
  let seq = 0;

  // Id stable, indépendant du nom (un renommage ne doit jamais faire perdre les
  // sélections déjà faites ailleurs dans le tableau, cf. updateMeasure).
  function nextId() { return "calc_" + (++seq); }

  function buildCatalogueEntry(entry) {
    return {
      id: entry.id,
      label: `${entry.name} (calculée)`,
      isFormula: true,
      formula: entry.formula,
      srcKey: entry.srcKey,
      crossSources: entry.crossSources,
      numeric: true,
    };
  }

  function inject(entry) {
    SOURCES[entry.srcKey].measures.push(buildCatalogueEntry(entry));
    Formula.clearFieldCache();
  }

  function uninject(entry) {
    const src = SOURCES[entry.srcKey];
    if (src) src.measures = src.measures.filter((m) => m.id !== entry.id);
    Formula.clearFieldCache();
  }

  // Valide une formule et calcule les sources croisées qu'elle référence en plus de srcKey
  // (ex. [valo].[...] dans une formule de base "rhs") — app.js ne construit un foreignIdx
  // que pour les sources visibles dans la config du tableau ; une formule cache sa propre
  // référence croisée dans du texte qu'il ne parse pas, on la lui rend visible ici.
  function validateAndDescribe({ name, formula, srcKey }) {
    if (!name || !name.trim()) throw new Formula.FormulaError("EMPTY_NAME", "Le nom de la variable est vide");
    if (!SOURCES[srcKey]) Formula.fail("UNKNOWN_TABLE", 0, srcKey);
    const ast = Formula.parse(formula);
    Formula.validate(ast, srcKey); // lève si mode "row" au sommet, type incompatible, etc.
    const crossSources = [...Formula.collectTables(ast)].filter((t) => t !== srcKey);
    return { name: name.trim(), formula, srcKey, crossSources };
  }

  function createMeasure({ name, formula, srcKey }) {
    const desc = validateAndDescribe({ name, formula, srcKey });
    const entry = Object.assign({ id: nextId(), createdAt: Date.now() }, desc);
    store.set(entry.id, entry);
    inject(entry);
    return entry;
  }

  // Remplace la formule/nom/source d'une variable existante EN GARDANT SON ID — une
  // sélection déjà faite ailleurs (ligne d'expression pointant sur cet id) reste valide
  // après modification, seule sa définition change.
  function updateMeasure(id, { name, formula, srcKey }) {
    const old = store.get(id);
    if (!old) throw new Formula.FormulaError("UNKNOWN_VAR", `Variable inconnue : ${id}`);
    const desc = validateAndDescribe({ name, formula, srcKey });
    uninject(old);
    const entry = Object.assign({ id, createdAt: old.createdAt, updatedAt: Date.now() }, desc);
    store.set(id, entry);
    inject(entry);
    return entry;
  }

  function remove(id) {
    const entry = store.get(id);
    if (!entry) return false;
    uninject(entry);
    store.delete(id);
    return true;
  }

  function list() { return [...store.values()]; }
  function get(id) { return store.get(id) || null; }

  return { createMeasure, updateMeasure, remove, list, get };
})();
