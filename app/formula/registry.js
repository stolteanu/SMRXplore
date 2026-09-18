// Formula.Registry — LE registre des fonctions. Ajouter une fonction = une entrée ici,
// jamais un nouveau cas dans le parseur ou l'évaluateur. Voir Grammaire des formules
// pour la doc utilisateur ; chaque entrée ci-dessous doit avoir sa ligne miroir là-bas.
//
// kind: "aggregate" — l'argument est évalué ligne par ligne sur la case du tableau,
//                      puis réduit par `reduce` (Sum, Count, Mode, Only…).
//       "scalar"     — opère sur des valeurs déjà résolues, en mode ligne (imbriqué
//                      dans un agrégat, ex. If() dans Sum(If(...))) ou en mode case
//                      (appliqué au résultat d'un agrégat, ex. Round(Sum(...))).
//
// argTypes: type attendu par position ("numeric" | "text" | "date" | "any"),
// dernier élément répété si variadic (RangeSum).
window.Formula = window.Formula || {};
(function (Formula) {
  "use strict";

  function toNum(v) {
    if (v === null || v === undefined || v === "") return null;
    const n = typeof v === "number" ? v : parseFloat(v);
    return Number.isFinite(n) ? n : null;
  }

  function nonEmpty(values) {
    // "" traité comme absent (piège des colonnes texte PMSI), jamais coercé en 0.
    return values.filter((v) => v !== null && v !== undefined && v !== "");
  }

  const REGISTRY = {};

  function reg(entry) { REGISTRY[entry.name.toLowerCase()] = entry; }

  // ---------- Agrégation ----------
  reg({
    name: "Sum", category: "Agrégation", kind: "aggregate",
    argType: "numeric", allowDistinct: true, allowTotal: true,
    reduce: (values) => {
      const nums = nonEmpty(values).map(toNum).filter((v) => v !== null);
      return nums.length ? nums.reduce((a, b) => a + b, 0) : 0;
    },
  });
  reg({
    name: "Avg", category: "Agrégation", kind: "aggregate",
    argType: "numeric", allowDistinct: true, allowTotal: true,
    reduce: (values) => {
      const nums = nonEmpty(values).map(toNum).filter((v) => v !== null);
      return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
    },
  });
  reg({
    name: "Count", category: "Agrégation", kind: "aggregate",
    argType: "any", returnType: "numeric", allowDistinct: true, allowTotal: true,
    reduce: (values, distinct) => {
      const vals = nonEmpty(values);
      return distinct ? new Set(vals).size : vals.length;
    },
  });
  reg({
    name: "Min", category: "Agrégation", kind: "aggregate",
    argType: "any", allowTotal: true,
    reduce: (values) => {
      const vals = nonEmpty(values);
      return vals.length ? vals.reduce((a, b) => (b < a ? b : a)) : null;
    },
  });
  reg({
    name: "Max", category: "Agrégation", kind: "aggregate",
    argType: "any", allowTotal: true,
    reduce: (values) => {
      const vals = nonEmpty(values);
      return vals.length ? vals.reduce((a, b) => (b > a ? b : a)) : null;
    },
  });
  reg({
    name: "Median", category: "Agrégation", kind: "aggregate",
    argType: "numeric", allowTotal: true,
    reduce: (values) => {
      const nums = nonEmpty(values).map(toNum).filter((v) => v !== null).sort((a, b) => a - b);
      if (!nums.length) return null;
      const mid = Math.floor(nums.length / 2);
      return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
    },
  });
  reg({
    name: "Mode", category: "Agrégation", kind: "aggregate",
    argType: "any", allowTotal: true,
    reduce: (values) => {
      const vals = nonEmpty(values);
      if (!vals.length) return null;
      const counts = new Map();
      for (const v of vals) counts.set(v, (counts.get(v) || 0) + 1);
      let best = vals[0], bestN = 0;
      for (const [v, n] of counts) if (n > bestN) { best = v; bestN = n; }
      return best;
    },
  });
  reg({
    name: "Only", category: "Agrégation", kind: "aggregate",
    argType: "any", allowTotal: true,
    reduce: (values) => {
      const distinct = new Set(nonEmpty(values));
      return distinct.size === 1 ? [...distinct][0] : null;
    },
  });

  // ---------- Conditionnel & logique ----------
  reg({
    name: "If", category: "Conditionnel", kind: "scalar",
    argTypes: ["any", "any", "any"], minArgs: 2, maxArgs: 3, returnType: "any",
    impl: (cond, then, els) => (cond ? then : (els === undefined ? null : els)),
  });
  reg({
    name: "IsNull", category: "Conditionnel", kind: "scalar",
    argTypes: ["any"], minArgs: 1, maxArgs: 1, returnType: "any",
    impl: (v) => v === null || v === undefined || v === "",
  });

  // ---------- Numérique général ----------
  reg({
    name: "Round", category: "Numérique", kind: "scalar",
    argTypes: ["numeric", "numeric"], minArgs: 1, maxArgs: 2, returnType: "numeric",
    impl: (x, step) => {
      const n = toNum(x); if (n === null) return null;
      const s = step ? toNum(step) : 1;
      return Math.round(n / s) * s;
    },
  });
  reg({
    name: "Abs", category: "Numérique", kind: "scalar",
    argTypes: ["numeric"], minArgs: 1, maxArgs: 1, returnType: "numeric",
    impl: (x) => { const n = toNum(x); return n === null ? null : Math.abs(n); },
  });
  reg({
    name: "Mod", category: "Numérique", kind: "scalar",
    argTypes: ["numeric", "numeric"], minArgs: 2, maxArgs: 2, returnType: "numeric",
    impl: (x, y) => { const a = toNum(x), b = toNum(y); return (a === null || !b) ? null : a % b; },
  });

  // ---------- Texte ----------
  reg({
    name: "Left", category: "Texte", kind: "scalar",
    argTypes: ["text", "numeric"], minArgs: 2, maxArgs: 2, returnType: "text",
    impl: (s, n) => String(s ?? "").slice(0, toNum(n) ?? 0),
  });
  reg({
    name: "Right", category: "Texte", kind: "scalar",
    argTypes: ["text", "numeric"], minArgs: 2, maxArgs: 2, returnType: "text",
    impl: (s, n) => { const str = String(s ?? ""); const k = toNum(n) ?? 0; return str.slice(str.length - k); },
  });
  reg({
    name: "Len", category: "Texte", kind: "scalar",
    argTypes: ["text"], minArgs: 1, maxArgs: 1, returnType: "numeric",
    impl: (s) => String(s ?? "").length,
  });
  reg({
    name: "Trim", category: "Texte", kind: "scalar",
    argTypes: ["text"], minArgs: 1, maxArgs: 1, returnType: "text",
    impl: (s) => String(s ?? "").trim(),
  });
  reg({
    name: "Upper", category: "Texte", kind: "scalar",
    argTypes: ["text"], minArgs: 1, maxArgs: 1, returnType: "text",
    impl: (s) => String(s ?? "").toUpperCase(),
  });
  reg({
    name: "Lower", category: "Texte", kind: "scalar",
    argTypes: ["text"], minArgs: 1, maxArgs: 1, returnType: "text",
    impl: (s) => String(s ?? "").toLowerCase(),
  });

  // ---------- Date et heure ----------
  reg({
    name: "Year", category: "Date", kind: "scalar",
    argTypes: ["date"], minArgs: 1, maxArgs: 1, returnType: "numeric",
    impl: (d) => { const dt = Formula.toDate(d); return dt ? dt.getFullYear() : null; },
  });
  reg({
    name: "Month", category: "Date", kind: "scalar",
    argTypes: ["date"], minArgs: 1, maxArgs: 1, returnType: "numeric",
    impl: (d) => { const dt = Formula.toDate(d); return dt ? dt.getMonth() + 1 : null; },
  });

  // ---------- Intervalle (Range) — combine plusieurs champs d'UNE MÊME ligne ----------
  reg({
    name: "RangeSum", category: "Range", kind: "scalar",
    argTypes: ["numeric"], minArgs: 1, maxArgs: Infinity, returnType: "numeric",
    impl: (...vals) => {
      const nums = nonEmpty(vals).map(toNum).filter((v) => v !== null);
      return nums.length ? nums.reduce((a, b) => a + b, 0) : 0;
    },
  });

  // ---------- Conversion de type — la seule façon explicite de changer de type ----------
  reg({
    name: "Num#", category: "Conversion", kind: "scalar",
    argTypes: ["text"], minArgs: 1, maxArgs: 2, returnType: "numeric",
    impl: (s) => toNum(s),
  });
  reg({
    name: "Text", category: "Conversion", kind: "scalar",
    argTypes: ["any"], minArgs: 1, maxArgs: 1, returnType: "text",
    impl: (v) => (v === null || v === undefined) ? "" : String(v),
  });

  Formula.Registry = REGISTRY;
  Formula.lookupFunction = (name) => REGISTRY[String(name).toLowerCase()];
})(window.Formula);
