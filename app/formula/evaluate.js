// Formula.validate / Formula.evaluate — vérification de type (avant tout calcul) puis
// exécution réelle. Deux modes de marche sur l'arbre :
//   "row"  — expression évaluée sur UNE ligne (l'intérieur d'un agrégat, ex. If(...) dans
//            Sum(If(...))).
//   "cell" — expression évaluée sur LA CASE du tableau (le résultat scalaire final,
//            obtenu en sortie d'un ou plusieurs appels d'agrégat combinés par + - * /).
// Une formule ne peut jamais rester en mode "row" au sommet : un champ non agrégé ne peut
// pas se combiner directement avec une mesure de case (cf. Grammaire des formules, erreur
// "doit être agrégé").
window.Formula = window.Formula || {};
(function (Formula) {
  "use strict";

  // ---------- validate() : vérification de type, aucune donnée lue ----------

  function widen(a, b) {
    // Combine deux "modes" (row prime sur cell/const ; cell prime sur const).
    if (a === "row" || b === "row") return "row";
    if (a === "cell" || b === "cell") return "cell";
    return "const";
  }

  function checkArgType(fnName, expected, got, fieldName, pos) {
    if (expected === "any" || got === "any" || expected === got) return;
    Formula.fail("TYPE_MISMATCH", pos, fnName, expected, fieldName || "?", got);
  }

  function check(node, ctx) {
    switch (node.type) {
      case "num": return { mode: "const", type: "numeric" };
      case "str": return { mode: "const", type: "text" };

      case "field": {
        const r = Formula.resolveFieldRef(ctx.baseSrcKey, node.table, node.name, node.pos, ctx.referencedTables);
        if (!ctx.firstRowField) ctx.firstRowField = node.name;
        return { mode: "row", type: r.type, fieldName: node.name };
      }

      case "call": {
        const fn = Formula.lookupFunction(node.name);
        if (!fn) Formula.fail("UNKNOWN_FUNCTION", node.pos, node.name);

        if (fn.kind === "aggregate") {
          if (node.args.length !== 1) Formula.fail("ARITY", node.pos, fn.name, 1, 1);
          const arg = check(node.args[0], ctx);
          if (arg.mode === "cell") Formula.fail("NESTED_AGGREGATE" in Formula.Errors ? "NESTED_AGGREGATE" : "UNEXPECTED_TOKEN", node.pos, fn.name);
          checkArgType(fn.name, fn.argType, arg.type, arg.fieldName, node.pos);
          if (node.distinct && !fn.allowDistinct) Formula.fail("ARITY", node.pos, `${fn.name}(DISTINCT …) non supporté`, 1, 1);
          if (node.total && !fn.allowTotal) Formula.fail("ARITY", node.pos, `${fn.name}(TOTAL …) non supporté`, 1, 1);
          return { mode: "cell", type: fn.returnType || arg.type };
        }

        // Fonction scalaire : arité, puis mode/type de chaque argument.
        if (node.args.length < fn.minArgs || node.args.length > fn.maxArgs) {
          Formula.fail("ARITY", node.pos, fn.name, fn.minArgs, fn.maxArgs);
        }
        const infos = node.args.map((a) => check(a, ctx));
        const hasRow = infos.some((i) => i.mode === "row");
        const hasCell = infos.some((i) => i.mode === "cell");
        if (hasRow && hasCell) Formula.fail("UNAGGREGATED", node.pos, ctx.firstRowField || "?");
        infos.forEach((info, i) => {
          const expected = fn.argTypes[Math.min(i, fn.argTypes.length - 1)];
          checkArgType(fn.name, expected, info.type, info.fieldName, node.pos);
        });
        return { mode: hasRow ? "row" : (hasCell ? "cell" : "const"), type: fn.returnType };
      }

      case "unary": {
        const a = check(node.arg, ctx);
        checkArgType("(unaire -)", "numeric", a.type, a.fieldName, node.pos);
        return { mode: a.mode, type: "numeric" };
      }

      case "binary": {
        const l = check(node.left, ctx), r = check(node.right, ctx);
        checkArgType(node.op, "numeric", l.type, l.fieldName, node.pos);
        checkArgType(node.op, "numeric", r.type, r.fieldName, node.pos);
        const mode = widen(l.mode, r.mode);
        if (l.mode !== r.mode && l.mode !== "const" && r.mode !== "const") {
          Formula.fail("UNAGGREGATED", node.pos, ctx.firstRowField || "?");
        }
        return { mode, type: "numeric" };
      }

      case "compare": {
        const l = check(node.left, ctx), r = check(node.right, ctx);
        return { mode: widen(l.mode, r.mode), type: "boolean" };
      }
      case "logical": {
        const l = check(node.left, ctx), r = check(node.right, ctx);
        return { mode: widen(l.mode, r.mode), type: "boolean" };
      }
      case "not": {
        const a = check(node.arg, ctx);
        return { mode: a.mode, type: "boolean" };
      }

      default:
        Formula.fail("UNEXPECTED_TOKEN", node.pos, node.type);
    }
  }

  // Ajoute le code d'erreur manquant utilisé ci-dessus (module chargé après errors.js).
  if (!Formula.Errors.NESTED_AGGREGATE) {
    Formula.Errors.NESTED_AGGREGATE = (fn) => `${fn}() ne peut pas contenir un autre agrégat imbriqué`;
  }

  // Valide une formule déjà parsée. Lève une FormulaError au premier problème trouvé ;
  // renvoie {type, mode} de haut niveau si tout est correct — `mode` doit être "cell" ou
  // "const" (jamais "row" au sommet, cf. en-tête du fichier).
  Formula.validate = function (ast, baseSrcKey) {
    const ctx = { baseSrcKey, referencedTables: Formula.collectTables(ast) };
    const top = check(ast, ctx);
    if (top.mode === "row") Formula.fail("UNAGGREGATED", ast.pos, ctx.firstRowField || "?");
    return top;
  };

  // ---------- evaluate() : exécution réelle sur des lignes déjà chargées ----------

  function getRowValue(node, row, ctx) {
    const r = Formula.resolveFieldRef(ctx.baseSrcKey, node.table, node.name, node.pos, ctx.referencedTables);
    let srcRow = row;
    if (r.srcKey !== ctx.baseSrcKey) {
      if (typeof sourceRowFor !== "function") Formula.fail("INCOMPATIBLE_SOURCE", node.pos, node.name);
      srcRow = sourceRowFor({ srcKey: r.srcKey }, row, ctx.foreignIdx, ctx.baseSrcKey);
    }
    return srcRow ? r.get(srcRow) : null;
  }

  function evalRow(node, row, ctx) {
    switch (node.type) {
      case "num": return node.value;
      case "str": return node.value;
      case "field": return getRowValue(node, row, ctx);
      case "call": {
        const fn = Formula.lookupFunction(node.name);
        const args = node.args.map((a) => evalRow(a, row, ctx));
        return fn.impl(...args);
      }
      case "unary": { const v = evalRow(node.arg, row, ctx); return v === null || v === undefined ? null : -v; }
      case "binary": return arith(node.op, evalRow(node.left, row, ctx), evalRow(node.right, row, ctx));
      case "compare": return compare(node.op, evalRow(node.left, row, ctx), evalRow(node.right, row, ctx));
      case "logical": return logical(node.op, () => evalRow(node.left, row, ctx), () => evalRow(node.right, row, ctx));
      case "not": return !evalRow(node.arg, row, ctx);
    }
  }

  // Collecte les valeurs par ligne pour un agrégat, en dédoublonnant les lignes croisées :
  // même principe que extractValues() dans app.js pour une mesure croisée — une ligne d'une
  // autre source (ex. Valo, grain séjour) référencée par plusieurs lignes de la source de
  // base (ex. RHS, plusieurs semaines par séjour) ne doit compter qu'UNE fois, sinon Sum()
  // la multiplierait par le nombre de lignes qui pointent dessus (le bug de fan-out déjà
  // rencontré ailleurs sur ce projet). Limite connue : ne dédoublonne que si l'agrégat
  // référence une seule autre source explicitement qualifiée — suffisant pour les cas
  // validés (croisement à deux sources) ; un agrégat mêlant plusieurs sources croisées à la
  // fois est un cas plus rare, à traiter séparément si le besoin se présente.
  function collectAggregateValues(node, rows, ctx) {
    const crossTables = [...Formula.collectTables(node.args[0])].filter((t) => t !== ctx.baseSrcKey);
    if (crossTables.length !== 1) return rows.map((row) => evalRow(node.args[0], row, ctx));
    if (typeof sourceRowFor !== "function") return rows.map((row) => evalRow(node.args[0], row, ctx));
    const seen = new Set();
    const values = [];
    for (const row of rows) {
      const target = sourceRowFor({ srcKey: crossTables[0] }, row, ctx.foreignIdx, ctx.baseSrcKey);
      if (target) {
        if (seen.has(target)) continue;
        seen.add(target);
      }
      values.push(evalRow(node.args[0], row, ctx));
    }
    return values;
  }

  function evalCell(node, ctx) {
    switch (node.type) {
      case "num": return node.value;
      case "str": return node.value;
      case "field": Formula.fail("UNAGGREGATED", node.pos, node.name); break;
      case "call": {
        const fn = Formula.lookupFunction(node.name);
        if (fn.kind === "aggregate") {
          const rows = node.total ? (ctx.allRows || Formula.fail("UNAGGREGATED", node.pos, "TOTAL")) : ctx.cellRows;
          const values = collectAggregateValues(node, rows, ctx);
          return fn.reduce(values, node.distinct);
        }
        const args = node.args.map((a) => evalCell(a, ctx));
        return fn.impl(...args);
      }
      case "unary": { const v = evalCell(node.arg, ctx); return v === null || v === undefined ? null : -v; }
      case "binary": return arith(node.op, evalCell(node.left, ctx), evalCell(node.right, ctx));
      case "compare": return compare(node.op, evalCell(node.left, ctx), evalCell(node.right, ctx));
      case "logical": return logical(node.op, () => evalCell(node.left, ctx), () => evalCell(node.right, ctx));
      case "not": return !evalCell(node.arg, ctx);
    }
  }

  function num(v) { const n = typeof v === "number" ? v : parseFloat(v); return Number.isFinite(n) ? n : null; }

  function arith(op, l, r) {
    const a = num(l), b = num(r);
    if (a === null || b === null) return null;
    switch (op) {
      case "+": return a + b;
      case "-": return a - b;
      case "*": return a * b;
      case "/": return b === 0 ? null : a / b; // division par zéro : résultat vide, pas une erreur bloquante
    }
  }

  function compare(op, l, r) {
    if (l === null || l === undefined || r === null || r === undefined) return null;
    switch (op) {
      case "=": return l == r || String(l) === String(r);
      case "<>": return !(l == r || String(l) === String(r));
      case "<": return num(l) < num(r);
      case ">": return num(l) > num(r);
      case "<=": return num(l) <= num(r);
      case ">=": return num(l) >= num(r);
    }
  }

  function logical(op, leftFn, rightFn) {
    if (op === "and") { const l = leftFn(); return l ? !!rightFn() : false; }
    return leftFn() ? true : !!rightFn(); // "or"
  }

  Formula.evaluate = function (ast, ctx) { return evalCell(ast, ctx); };

  // Point d'entrée pratique : texte -> {ok, value} ou {ok:false, error}. N'expose jamais
  // une exception JS brute à l'appelant UI, toujours une FormulaError structurée.
  Formula.run = function (src, ctx) {
    try {
      const ast = Formula.parse(src);
      Formula.validate(ast, ctx.baseSrcKey);
      // referencedTables (tables qualifiées explicitement dans la formule) est nécessaire à
      // getRowValue() pour résoudre un champ non qualifié — validate() le calcule dans son
      // propre contexte local et ne le renvoie pas, on le recalcule ici pour evaluate().
      const runCtx = Object.assign({ referencedTables: Formula.collectTables(ast) }, ctx);
      const value = Formula.evaluate(ast, runCtx);
      return { ok: true, value };
    } catch (e) {
      if (e instanceof Formula.FormulaError) return { ok: false, error: e };
      throw e;
    }
  };
})(window.Formula);
