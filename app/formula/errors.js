// Formula.Errors — catalogue central des messages d'erreur du moteur de formules.
// Une entrée par code ; UI et évaluateur lisent ce fichier, jamais de message en dur ailleurs.
window.Formula = window.Formula || {};
(function (Formula) {
  "use strict";

  class FormulaError extends Error {
    constructor(code, message, pos) {
      super(message);
      this.name = "FormulaError";
      this.code = code;
      this.pos = pos; // index dans la chaîne source, pour souligner le bon token
    }
  }

  const Errors = {
    UNKNOWN_FIELD: (f) => `Champ inconnu : [${f}]`,
    AMBIGUOUS_FIELD: (f, tables) =>
      `[${f}] ambigu — qualifiez avec ${tables.map((t) => `[${t}].`).join(" ou ")}`,
    UNCLOSED_PAREN: () => `Parenthèse non fermée`,
    UNEXPECTED_TOKEN: (t) => `Symbole inattendu : "${t}"`,
    UNEXPECTED_END: () => `Formule incomplète`,
    UNKNOWN_FUNCTION: (n) => `Fonction inconnue : ${n}()`,
    ARITY: (n, min, max) =>
      `${n}() attend ${min === max ? min : `${min} à ${max}`} argument(s)`,
    TYPE_MISMATCH: (fn, expected, field, actual) =>
      `${fn}() attend un champ ${expected}, [${field}] est ${actual}`,
    UNAGGREGATED: (f) =>
      `[${f}] doit être agrégé (Sum, Avg, Count…) avant d'être combiné à d'autres mesures`,
    INCOMPATIBLE_SOURCE: (f) =>
      `[${f}] n'a ni clé NDA ni clé RHS_ID commune avec la source de base — jointure impossible`,
    UNKNOWN_TABLE: (t) => `Source inconnue : [${t}]`,
  };

  Formula.FormulaError = FormulaError;
  Formula.Errors = Errors;

  Formula.fail = function (code, pos, ...args) {
    const build = Errors[code];
    if (!build) throw new FormulaError("INTERNAL", `Erreur inconnue : ${code}`, pos);
    throw new FormulaError(code, build(...args), pos);
  };
})(window.Formula);
