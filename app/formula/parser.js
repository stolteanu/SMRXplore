// Formula.parse — tokens (tokenizer.js) -> arbre syntaxique. Descente récursive classique,
// priorités (du plus lâche au plus serré) : or > and > not > comparaison > + - > * / > unaire.
window.Formula = window.Formula || {};
(function (Formula) {
  "use strict";

  const CMP_OPS = new Set(["=", "<>", "<", ">", "<=", ">="]);
  const MODIFIER_KWS = new Set(["total", "distinct"]);

  function Parser(tokens) {
    this.tokens = tokens;
    this.i = 0;
  }
  Parser.prototype.peek = function () { return this.tokens[this.i]; };
  Parser.prototype.next = function () { return this.tokens[this.i++]; };
  Parser.prototype.check = function (type, value) {
    const t = this.peek();
    return t.type === type && (value === undefined || String(t.value).toLowerCase() === value);
  };
  Parser.prototype.expectOp = function (op) {
    const t = this.peek();
    if (t.type !== "op" || t.value !== op) Formula.fail("UNEXPECTED_TOKEN", t.pos, t.value ?? "fin de formule");
    return this.next();
  };

  Parser.prototype.parseExpr = function () { return this.parseOr(); };

  Parser.prototype.parseOr = function () {
    let left = this.parseAnd();
    while (this.check("kw", "or")) { this.next(); left = { type: "logical", op: "or", left, right: this.parseAnd() }; }
    return left;
  };
  Parser.prototype.parseAnd = function () {
    let left = this.parseNot();
    while (this.check("kw", "and")) { this.next(); left = { type: "logical", op: "and", left, right: this.parseNot() }; }
    return left;
  };
  Parser.prototype.parseNot = function () {
    if (this.check("kw", "not")) { this.next(); return { type: "not", arg: this.parseNot() }; }
    return this.parseCmp();
  };
  Parser.prototype.parseCmp = function () {
    let left = this.parseAdd();
    const t = this.peek();
    if (t.type === "op" && CMP_OPS.has(t.value)) {
      this.next();
      return { type: "compare", op: t.value, left, right: this.parseAdd() };
    }
    return left;
  };
  Parser.prototype.parseAdd = function () {
    let left = this.parseMul();
    while (this.check("op", "+") || this.check("op", "-")) {
      const op = this.next().value;
      left = { type: "binary", op, left, right: this.parseMul() };
    }
    return left;
  };
  Parser.prototype.parseMul = function () {
    let left = this.parseUnary();
    while (this.check("op", "*") || this.check("op", "/")) {
      const op = this.next().value;
      left = { type: "binary", op, left, right: this.parseUnary() };
    }
    return left;
  };
  Parser.prototype.parseUnary = function () {
    if (this.check("op", "-")) { this.next(); return { type: "unary", op: "-", arg: this.parseUnary() }; }
    return this.parsePrimary();
  };

  Parser.prototype.parsePrimary = function () {
    const t = this.peek();

    if (t.type === "num") { this.next(); return { type: "num", value: t.value, pos: t.pos }; }
    if (t.type === "str") { this.next(); return { type: "str", value: t.value, pos: t.pos }; }

    if (t.type === "field") {
      this.next();
      // Qualifié ? [table].[champ]
      if (this.check("op", ".") && this.tokens[this.i + 1] && this.tokens[this.i + 1].type === "field") {
        this.next(); // '.'
        const fieldTok = this.next();
        return { type: "field", table: t.value, name: fieldTok.value, pos: t.pos };
      }
      return { type: "field", table: null, name: t.value, pos: t.pos };
    }

    if (t.type === "op" && t.value === "(") {
      this.next();
      const inner = this.parseExpr();
      this.expectOp(")");
      return inner;
    }

    if (t.type === "ident") {
      return this.parseCall();
    }

    if (t.type === "eof") Formula.fail("UNEXPECTED_END", t.pos);
    Formula.fail("UNEXPECTED_TOKEN", t.pos, t.value);
  };

  Parser.prototype.parseCall = function () {
    const nameTok = this.next(); // ident
    if (!this.check("op", "(")) Formula.fail("UNEXPECTED_TOKEN", this.peek().pos, this.peek().value ?? "(");
    this.next(); // '('

    let total = false, distinct = false;
    while (this.peek().type === "kw" && MODIFIER_KWS.has(String(this.peek().value).toLowerCase())) {
      const kw = this.next().value.toLowerCase();
      if (kw === "total") total = true; else distinct = true;
    }

    const args = [];
    if (!this.check("op", ")")) {
      args.push(this.parseExpr());
      while (this.check("op", ",")) { this.next(); args.push(this.parseExpr()); }
    }
    if (!this.check("op", ")")) Formula.fail("UNCLOSED_PAREN", nameTok.pos);
    this.next(); // ')'

    return { type: "call", name: nameTok.value, args, total, distinct, pos: nameTok.pos };
  };

  Formula.parse = function (src) {
    const tokens = Formula.tokenize(src);
    const p = new Parser(tokens);
    const ast = p.parseExpr();
    if (p.peek().type !== "eof") Formula.fail("UNEXPECTED_TOKEN", p.peek().pos, p.peek().value);
    return ast;
  };

  // Parcourt l'arbre et renvoie l'ensemble des tables explicitement qualifiées
  // (sert à Formula.resolveFieldRef pour juger de l'ambiguïté d'un champ non qualifié).
  Formula.collectTables = function (ast) {
    const tables = new Set();
    (function walk(node) {
      if (!node || typeof node !== "object") return;
      if (node.type === "field" && node.table) tables.add(node.table);
      for (const key of ["left", "right", "arg"]) if (node[key]) walk(node[key]);
      if (node.args) node.args.forEach(walk);
    })(ast);
    return tables;
  };
})(window.Formula);
