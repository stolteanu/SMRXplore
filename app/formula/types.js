// Formula.resolveField — résout une référence [table].[champ] contre le catalogue
// existant (SOURCES de catalogue.js). Seule source de vérité pour le typage : on ne
// déclare jamais un type en dur ici en double d'une info déjà dans catalogue.js.
//
// Convention (à respecter pour toute nouvelle entrée de catalogue) :
//   - measures : numérique par défaut, sauf `numeric:false` explicite ou colonne de date.
//   - dims     : texte par défaut, sauf `numeric:true` explicite ou colonne de date.
//   - une entrée à `distinctKey` n'est PAS une valeur de ligne — non référençable
//     directement dans une formule (utiliser Count(Distinct [champ_brut]) à la place).
window.Formula = window.Formula || {};
(function (Formula) {
  "use strict";

  // Colonnes connues comme dates dans le schéma pmsi.db (RHS, Valo, VID-HOSP + enfants).
  const DATE_COLUMNS = new Set([
    "date_debut_sejour", "date_fin_sejour", "date_naissance",
    "date_entree_um", "date_sortie_um", "date_intervention_chirurgicale",
    "date_realisation", "date_naissance_beneficiaire", "date_hospitalisation",
    "date_entree", "date_sortie", "date_debut_sejour_dmt", "date_fin_sejour_dmt",
    "_date_sortie_sej",
  ]);

  Formula.toDate = function (v) {
    if (!v) return null;
    if (typeof parseDateStr === "function") return parseDateStr(v);
    const d = new Date(v);
    return isNaN(d) ? null : d;
  };

  function entryType(entry, col) {
    if (col && DATE_COLUMNS.has(col)) return "date";
    if (entry.__from === "measure") return entry.numeric === false ? "text" : "numeric";
    return entry.numeric === true ? "numeric" : "text";
  }

  function indexSource(srcKey) {
    const src = (typeof SOURCES !== "undefined") ? SOURCES[srcKey] : null;
    if (!src) return null;
    const index = new Map();
    const addAll = (list, from) => {
      for (const entry of list || []) {
        if (entry.distinctKey) continue; // pas une valeur de ligne, exclue des formules
        const tagged = Object.assign({ __from: from }, entry);
        index.set(entry.id, tagged);
        if (entry.col && !index.has(entry.col)) index.set(entry.col, tagged);
      }
    };
    addAll(src.dims, "dim");
    addAll(src.measures, "measure");
    return index;
  }

  const _cache = new Map();
  function sourceIndex(srcKey) {
    if (!_cache.has(srcKey)) _cache.set(srcKey, indexSource(srcKey));
    return _cache.get(srcKey);
  }
  Formula.clearFieldCache = () => _cache.clear(); // à appeler si SOURCES est modifié à chaud

  Formula.listSourceKeys = function () {
    return (typeof SOURCES !== "undefined") ? Object.keys(SOURCES) : [];
  };

  // Cherche `fieldName` dans une source précise. Renvoie null si absent (pas une erreur ici :
  // l'appelant décide — champ inconnu vs à chercher ailleurs).
  Formula.lookupInSource = function (srcKey, fieldName) {
    const idx = sourceIndex(srcKey);
    if (!idx) return null;
    const entry = idx.get(fieldName);
    if (!entry) return null;
    const col = entry.col || null;
    return {
      srcKey, fieldName, entry, col,
      type: entryType(entry, col),
      get: (row) => (entry.derive ? entry.derive(row) : row[col]),
    };
  };

  // Résout [champ] (non qualifié) ou [table].[champ] (qualifié). `referencedTables` est
  // l'ensemble des sources déjà qualifiées ailleurs DANS CETTE FORMULE (baseSrcKey y est
  // toujours implicitement inclus) — l'ambiguïté ne se juge que par rapport à ces sources-là,
  // jamais contre la totalité du catalogue (sinon presque tout deviendrait ambigu : "id",
  // "code", "finess_epmsi" existent dans une dizaine de tables sans rapport avec la formule).
  // - non qualifié + trouvé dans 1 seule source pertinente -> résolu.
  // - non qualifié + trouvé dans >1 -> Formula.fail("AMBIGUOUS_FIELD", ...).
  // - introuvable partout -> Formula.fail("UNKNOWN_FIELD", ...).
  Formula.resolveFieldRef = function (baseSrcKey, table, fieldName, pos, referencedTables) {
    if (table) {
      const r = Formula.lookupInSource(table, fieldName);
      if (!r) Formula.fail("UNKNOWN_FIELD", pos, `${table}].[${fieldName}`);
      return r;
    }
    const pool = new Set([baseSrcKey, ...(referencedTables || [])]);
    const candidates = [];
    for (const key of pool) {
      const r = Formula.lookupInSource(key, fieldName);
      if (r) candidates.push(r);
    }
    if (!candidates.length) Formula.fail("UNKNOWN_FIELD", pos, fieldName);
    if (candidates.length > 1) {
      Formula.fail("AMBIGUOUS_FIELD", pos, fieldName, candidates.map((c) => c.srcKey));
    }
    return candidates[0];
  };
})(window.Formula);
