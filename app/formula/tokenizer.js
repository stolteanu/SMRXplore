// Formula.tokenize — texte de formule -> liste de tokens.
// Seule source de vérité pour la découpe en tokens : alimente à la fois le parseur
// (parser.js) et la colorisation syntaxique de l'éditeur (même rôles qu'app/formula/README).
window.Formula = window.Formula || {};
(function (Formula) {
  "use strict";

  // Rôles alignés sur la Grammaire des formules : fn, field, kw, num, str, op.
  const KEYWORDS = new Set(["total", "distinct", "and", "or", "not"]);

  const TWO_CHAR_OPS = ["<=", ">=", "<>"];
  const ONE_CHAR_OPS = "+-*/(),.=<>";

  function isDigit(c) { return c >= "0" && c <= "9"; }
  function isIdentStart(c) { return /[A-Za-zÀ-ÿ_#]/.test(c); }
  function isIdentPart(c) { return /[A-Za-zÀ-ÿ0-9_#]/.test(c); }

  function tokenize(src) {
    const tokens = [];
    let i = 0;
    const n = src.length;

    function push(type, value, start) {
      tokens.push({ type, value, pos: start, end: i });
    }

    while (i < n) {
      const c = src[i];

      if (c === " " || c === "\t" || c === "\n" || c === "\r") { i++; continue; }

      // Référence de champ : [nom_technique]
      if (c === "[") {
        const start = i;
        i++;
        let name = "";
        while (i < n && src[i] !== "]") { name += src[i]; i++; }
        if (i >= n) Formula.fail("UNCLOSED_PAREN", start);
        i++; // consomme ]
        push("field", name.trim(), start);
        continue;
      }

      // Chaîne littérale : 'texte'
      if (c === "'") {
        const start = i;
        i++;
        let str = "";
        while (i < n && src[i] !== "'") { str += src[i]; i++; }
        if (i >= n) Formula.fail("UNCLOSED_PAREN", start);
        i++;
        push("str", str, start);
        continue;
      }

      // Nombre : 123, 12.5
      if (isDigit(c) || (c === "." && isDigit(src[i + 1]))) {
        const start = i;
        let num = "";
        while (i < n && (isDigit(src[i]) || src[i] === ".")) { num += src[i]; i++; }
        push("num", parseFloat(num), start);
        continue;
      }

      // Opérateurs à deux caractères
      const two = src.substr(i, 2);
      if (TWO_CHAR_OPS.includes(two)) { push("op", two, i); i += 2; continue; }

      // Opérateurs à un caractère
      if (ONE_CHAR_OPS.includes(c)) { push("op", c, i); i++; continue; }

      // Identifiant : nom de fonction ou mot-clé (TOTAL, DISTINCT, and, or, not)
      if (isIdentStart(c)) {
        const start = i;
        let ident = "";
        while (i < n && isIdentPart(src[i])) { ident += src[i]; i++; }
        const lower = ident.toLowerCase();
        push(KEYWORDS.has(lower) ? "kw" : "ident", ident, start);
        continue;
      }

      Formula.fail("UNEXPECTED_TOKEN", i, c);
    }

    tokens.push({ type: "eof", value: null, pos: n, end: n });
    return tokens;
  }

  Formula.tokenize = tokenize;
})(window.Formula);
