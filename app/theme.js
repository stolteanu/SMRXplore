// Bascule clair/sombre/système, partagée par toutes les pages d'interaction de l'app (Explorateur,
// pages de choix/admin, visualiseur Plotly). Le Tableau de bord généré (tableau_de_bord_*.html,
// annexe_*.html, journal_*.html) n'y touche pas : thème vert pâle fixe, décision assumée séparément.
//
// Ce fichier doit être chargé le plus tôt possible dans <head> (avant tout <style> si possible) :
// apply() s'exécute immédiatement à l'évaluation du script, donc avant le premier rendu — la page
// n'a jamais besoin d'être repeinte après coup (pas de flash de l'autre thème).
(function () {
  var KEY = "pmsi_theme_mode"; // "light" | "dark" | "system"

  function load() {
    try { return localStorage.getItem(KEY) || "system"; } catch (e) { return "system"; }
  }
  function save(mode) {
    try { localStorage.setItem(KEY, mode); } catch (e) {}
  }
  function apply(mode) {
    var root = document.documentElement;
    if (mode === "light" || mode === "dark") root.setAttribute("data-theme", mode);
    else root.removeAttribute("data-theme");
  }

  apply(load());

  var api = {
    get: load,
    set: function (mode) {
      save(mode);
      apply(mode);
      if (api._sync) api._sync();
    },
  };
  window.PmsiTheme = api;

  var STYLE_ID = "pmsi-theme-toggle-style";
  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = document.createElement("style");
    style.id = STYLE_ID;
    // Couleurs neutres semi-transparentes (pas de dépendance aux variables CSS propres à chaque
    // page, qui diffèrent d'une page à l'autre) : le composant s'intègre correctement quel que
    // soit le fond clair ou sombre sur lequel il est posé.
    style.textContent =
      ".pmsi-theme-toggle{display:inline-flex;border-radius:999px;overflow:hidden;" +
      "border:1px solid rgba(127,127,127,0.4);font-family:inherit;}" +
      ".pmsi-theme-toggle button{font:inherit;font-size:0.78em;padding:5px 12px;border:none;" +
      "background:transparent;color:inherit;cursor:pointer;opacity:0.7;}" +
      ".pmsi-theme-toggle button+button{border-left:1px solid rgba(127,127,127,0.4);}" +
      ".pmsi-theme-toggle button:hover{opacity:1;}" +
      ".pmsi-theme-toggle button.active{opacity:1;font-weight:700;background:rgba(127,127,127,0.22);}";
    document.head.appendChild(style);
  }

  // Insère le sélecteur dans `container` s'il est fourni, sinon crée un conteneur flottant en haut
  // à droite de la page — utilisé par les pages sans emplacement dédié dans leur en-tête.
  api.mount = function (container) {
    ensureStyle();
    var el = container;
    if (!el) {
      el = document.createElement("div");
      el.style.cssText = "position:fixed;top:10px;right:12px;z-index:1000;";
      document.body.appendChild(el);
    }
    el.className = (el.className ? el.className + " " : "") + "pmsi-theme-toggle";
    el.setAttribute("role", "group");
    el.setAttribute("aria-label", "Thème de l'application");
    el.innerHTML = "";
    var modes = [["light", "Clair"], ["dark", "Sombre"], ["system", "Système"]];
    var buttons = modes.map(function (entry) {
      var value = entry[0], label = entry[1];
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.dataset.value = value;
      b.addEventListener("click", function () { api.set(value); });
      el.appendChild(b);
      return b;
    });
    function sync() {
      var current = load();
      buttons.forEach(function (b) { b.classList.toggle("active", b.dataset.value === current); });
    }
    api._sync = sync;
    sync();
    return el;
  };
})();
