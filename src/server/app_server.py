"""Serveur local minimal (bibliothèque standard uniquement) pour piloter le
tableau de bord PMSI-SMR depuis un navigateur : sert app/ en statique et
expose des endpoints JSON pour la page "TDB choix" (app/tdb-choix.html) et
la page d'accueil (app/index.html) :

  GET  /api/meta      -> établissements + années disponibles
  POST /api/generate  -> génère le(s) TDB demandé(s), renvoie leurs URLs
  POST /api/exporter   -> copie une sélection de TDB déjà générés (app/generated/)
                          vers un dossier choisi via un sélecteur natif OS
                          (tkinter, cf. _choisir_dossier_export), 2026-09-16
  POST /api/charger    -> parse input/ -> pmsi.db (run.py) puis republie la
                          copie pour l'explorateur (tools/publier_explorateur.py) ;
                          déclenché SEULEMENT par un clic utilisateur ("Mettre
                          à jour les données"), jamais automatiquement au
                          démarrage (décision utilisateur explicite 2026-08-05)

Aucune dépendance externe (http.server de la bibliothèque standard) : le
même interpréteur Python que run.py suffit, aucune installation ni droit
administrateur requis sur la machine qui l'exécute — voir launch.py à la
racine du projet pour le point d'entrée utilisateur.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if not getattr(sys, "frozen", False):
    # Nécessaire uniquement en exécution depuis les sources (`python
    # launch.py`) pour que `from src...` résolve quel que soit le cwd — une
    # fois empaqueté (PyInstaller), les modules src.* sont déjà accessibles
    # via le mécanisme d'import interne au .exe, pas besoin de sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.util.paths import project_root, resource_root  # noqa: E402
from src.server import upload as upload_mod  # noqa: E402

ROOT = project_root()
APP_DIR = (ROOT / "app").resolve()
GENERATED_DIR = APP_DIR / "generated"

# app/ mélange des fichiers SOURCE (interface, statiques, jamais modifiés à
# l'exécution) et des artefacts GÉNÉRÉS à partir de données patients réelles
# (tableaux de bord, app/generated/, app/data/pmsi.db) — cf. .gitignore à la
# racine du projet, qui distingue déjà les deux avec la même liste. Une fois
# empaqueté, les fichiers source sont déployés dans bin/app/ (remplaçable
# lors d'une mise à jour) tandis que le reste continue de vivre sous
# project_root()/app (bac à sable, jamais écrasé) — voir resource_root().
BIN_APP_DIR = (resource_root() / "app").resolve()
_SOURCE_APP_FILES = {
    "index.html",
    "admin.html",
    "tdb-choix.html",
    "explorateur.html",
    "catalogue.js",
    "app.js",
    "plotly_viewer.html",
    "theme.js",
}
_SOURCE_APP_DIRS = {"lib", "formula", "explorer"}

MAX_ANNEES = 3

_FINESS_RE = re.compile(r"^\d{9}$")
_ANNEE_RE = re.compile(r"^\d{4}$")
# Couleurs "apparence" insérées TELLES QUELLES dans un <style> du TDB généré
# (voir render_dashboard._apparence_style) — validation stricte au format hex
# obligatoire ici, sinon une valeur arbitraire du payload JSON s'injecterait
# directement dans le CSS/HTML du fichier produit.
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _load_meta() -> dict:
    from src.viz.tableau_de_bord import connect, list_finess, years_disponibles

    conn = connect()
    finess_list = list_finess(conn)
    years_by_finess = {f: years_disponibles(conn, f) for f in finess_list}
    conn.close()
    return {"finess": finess_list, "years_by_finess": years_by_finess}


def _generate(
    finess_list: list[str],
    years: list[str],
    axis: str,
    mois_fin: int | None = None,
    groupes_uf: dict[str, dict[str, list[str]]] | None = None,
    selection_uf: dict[str, list[str]] | None = None,
    signalisation_couleur: bool = False,
    apparence: dict | None = None,
) -> list[dict]:
    from src.viz.render_dashboard import generate_axis_reports, render, render_annexe, render_journal
    from src.viz.tableau_de_bord import build

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "-".join(years) if years else "toutes"
    if mois_fin:
        suffix += f"-M{mois_fin:02d}"
    reports = []
    for finess in finess_list:
        data = build(finess, years or None, mois_fin=mois_fin)
        if not data["years"]:
            raise ValueError(f"Aucune donnée pour le FINESS {finess} sur les années demandées.")
        base = f"{finess}_{suffix}"

        tdb_path = GENERATED_DIR / f"tableau_de_bord_{base}.html"
        tdb_path.write_text(
            render(data, signalisation_couleur=signalisation_couleur, apparence=apparence), encoding="utf-8"
        )

        annexe_path = GENERATED_DIR / f"annexe_{base}.html"
        annexe_path.write_text(render_annexe(data), encoding="utf-8")

        journal_path = GENERATED_DIR / f"journal_{base}.html"
        journal_path.write_text(render_journal(data), encoding="utf-8")

        report = {
            "finess": finess,
            "annees": data["years"],
            "tdb": f"/generated/{tdb_path.name}",
            "annexe": f"/generated/{annexe_path.name}",
            "journal": f"/generated/{journal_path.name}",
        }

        if axis in ("uf", "type_hospitalisation"):
            # Un TDB complet PAR valeur d'axe (pas une section résumé en
            # plus du TDB principal, cf. generate_axis_reports). Pour "uf",
            # `groupes_uf[finess]` (optionnel) regroupe plusieurs UF en
            # "service" défini par l'utilisateur, et `selection_uf[finess]`
            # (optionnel, 2026-08-25) restreint les UF individuelles
            # générées — voir generate_axis_reports.
            groupes = (groupes_uf or {}).get(finess) if axis == "uf" else None
            selection = (selection_uf or {}).get(finess) if axis == "uf" else None
            report["secondaires"] = generate_axis_reports(
                finess, years or None, axis, mois_fin, groupes, selection, signalisation_couleur, apparence
            )

        reports.append(report)
    return reports


_EXPORT_DIALOG_LOCK = threading.Lock()


def _choisir_dossier_export(initial: Path) -> str | None:
    """Ouvre un sélecteur de DOSSIER natif de l'OS (Explorateur Windows, Finder
    macOS, sélecteur GTK/KDE sous Linux) via tkinter — bibliothèque standard
    déjà embarquée avec Python, donc "sans dépendance externe" comme le reste
    du serveur (cf. docstring du module). Renvoie None si l'utilisateur annule.

    Import différé (comme les autres imports lourds de ce module) : évite le
    coût au démarrage du serveur pour une fonctionnalité utilisée seulement au
    clic sur "Exporter". Sérialisé par `_EXPORT_DIALOG_LOCK` : le serveur est
    un `ThreadingHTTPServer` (un thread par requête), et Tcl/Tk n'est pas
    prévu pour faire coexister deux interpréteurs `Tk()` sur deux threads en
    parallèle (deux clics "Exporter" presque simultanés, ex. deux onglets) —
    audit 2026-09-18, vérifié fonctionnel en usage normal (un seul dialogue à
    la fois, y compris depuis launch.exe empaqueté) mais ce verrou évite la
    course dans le cas concurrent."""
    import tkinter as tk
    from tkinter import filedialog

    with _EXPORT_DIALOG_LOCK:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            chosen = filedialog.askdirectory(
                title="Choisir où enregistrer les tableaux de bord",
                initialdir=str(initial),
                mustexist=True,
            )
        finally:
            root.destroy()
    return chosen or None


def _exporter(fichiers: list) -> dict:
    """Copie une sélection de fichiers déjà générés dans app/generated/ (TDB,
    Annexe, Journal, TDB secondaires — tous générés à plat dans ce dossier,
    voir _generate() et generate_axis_reports()) vers un dossier choisi par
    l'utilisateur via un sélecteur natif (voir _choisir_dossier_export).

    `fichiers` : URLs telles que renvoyées par /api/generate (ex.
    "/generated/tableau_de_bord_680000973_2026.html") — seul le nom de
    fichier est retenu, jamais le chemin fourni tel quel, pour ne jamais
    sortir de GENERATED_DIR quoi que contienne le payload JSON. Même
    principe resolve()+startswith() que Handler._resolve_static (audit
    2026-09-18 : harmonisé avec ce garde-fou déjà éprouvé plutôt qu'un
    second mécanisme divergent basé sur os.path.basename seul, dont le
    découpage de séparateurs dépend de la plateforme)."""
    import shutil

    if not isinstance(fichiers, list) or not fichiers:
        raise ValueError("Aucun tableau sélectionné.")

    base = GENERATED_DIR.resolve()
    sources = []
    for rel in fichiers:
        if not isinstance(rel, str):
            raise ValueError("Fichier invalide.")
        nom = os.path.basename(rel)
        target = (GENERATED_DIR / nom).resolve()
        if target != base and not str(target).startswith(str(base) + os.sep):
            raise ValueError(f"Fichier invalide : {nom}")
        if not target.is_file():
            raise ValueError(f"Fichier introuvable : {nom}")
        sources.append(target)

    destination = _choisir_dossier_export(GENERATED_DIR)
    if destination is None:
        return {"cancelled": True}

    dest_dir = Path(destination)
    copies, erreurs = [], []
    for src in sources:
        try:
            shutil.copy2(src, dest_dir / src.name)
            copies.append(src.name)
        except OSError as exc:
            erreurs.append(f"{src.name} : {exc}")

    return {"destination": str(dest_dir), "copies": copies, "erreurs": erreurs}


def _supprimer_et_publier(finess: str, avec_fichiers_source: bool) -> dict:
    """Exécute tools/supprimer_etablissement.executer() puis republie la copie
    pour l'explorateur (même enchaînement que _charger_et_publier), pour que
    la suppression déclenchée depuis la page admin soit immédiatement visible
    sans étape manuelle supplémentaire."""
    from tools.supprimer_etablissement import executer
    from tools.publier_explorateur import main as publier_main

    resultat = executer(finess, avec_fichiers_source)
    publier_main()
    return resultat


def _charger_et_publier() -> str:
    """Enchaîne run.py (parse input/ -> data/processed/pmsi.db) puis
    tools/publier_explorateur.py (recopie pour l'explorateur, qui lit sa
    propre copie app/data/pmsi.db plutôt que la base source — voir
    docstring de publier_explorateur.py). Capture toute la sortie texte des
    deux étapes (le résumé fichier-par-fichier de run.py, le OK final de la
    publication) pour l'afficher dans la page d'accueil plutôt que de la
    perdre dans la console — l'utilisateur qui a lancé le .exe n'a
    généralement pas de terminal visible."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        import run

        run.main()

        from tools.publier_explorateur import main as publier_main

        publier_main()
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "PMSI-SMR/1.0"

    def log_message(self, fmt, *args):  # noqa: A003 - signature imposée par BaseHTTPRequestHandler
        sys.stderr.write("[server] " + (fmt % args) + "\n")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404, "Fichier introuvable")
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _resolve_static(self, url_path: str) -> Path | None:
        """Traduit une URL en chemin sous app/ (source, bin/app/ une fois
        empaqueté) ou sous le app/ du bac à sable (artefacts générés),
        en refusant toute sortie du dossier (../, chemins absolus, etc.)."""
        if url_path == "/":
            url_path = "/index.html"
        rel = url_path.lstrip("/")
        top = rel.split("/", 1)[0]
        base = BIN_APP_DIR if (rel in _SOURCE_APP_FILES or top in _SOURCE_APP_DIRS) else APP_DIR
        target = (base / rel).resolve()
        if target != base and not str(target).startswith(str(base) + os.sep):
            return None
        return target

    def do_GET(self) -> None:
        from urllib.parse import parse_qs, urlsplit

        parsed = urlsplit(self.path)
        if parsed.path == "/api/meta":
            try:
                self._send_json(_load_meta())
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
            return

        if parsed.path == "/api/uf-list":
            try:
                qs = parse_qs(parsed.query)
                finess = (qs.get("finess") or [""])[0]
                if not _FINESS_RE.match(finess):
                    raise ValueError("FINESS invalide.")
                from src.viz.tableau_de_bord import connect, valeurs_axe

                conn = connect()
                values = valeurs_axe(conn, [], finess, "numero_unite_medicale")
                conn.close()
                self._send_json({"uf": values})
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return

        if parsed.path == "/api/upload/etat":
            try:
                self._send_json(upload_mod.list_staged())
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
            return

        target = self._resolve_static(parsed.path)
        if target is None:
            self.send_error(403, "Interdit")
            return
        self._send_file(target)

    def do_POST(self) -> None:
        if self.path == "/api/charger":
            try:
                output = _charger_et_publier()
                self._send_json({"output": output})
            except Exception as exc:
                self._send_json({"error": str(exc), "output": str(exc)}, status=500)
            return

        if self.path == "/api/upload":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                content_type = self.headers.get("Content-Type", "")
                fields, files = upload_mod.parse_multipart(content_type, body)
                categorie = fields.get("categorie", "")
                if not files:
                    raise upload_mod.ErreurUpload("Aucun fichier reçu.")
                f = files[0]
                meta = upload_mod.stage_file(categorie, f["filename"], f["content"])
                self._send_json(meta)
            except upload_mod.ErreurUpload as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
            return

        if self.path == "/api/upload/meta":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                meta = upload_mod.set_meta(
                    payload.get("categorie", ""),
                    payload.get("id", ""),
                    str(payload.get("finess", "")),
                    int(payload.get("annee", 0)),
                    int(payload.get("mois", 0)),
                )
                self._send_json(meta)
            except upload_mod.ErreurUpload as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return

        if self.path == "/api/upload/confirmer-ecrasement":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                meta = upload_mod.confirmer_ecrasement(payload.get("categorie", ""), payload.get("id", ""))
                self._send_json(meta)
            except upload_mod.ErreurUpload as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return

        if self.path == "/api/upload/confirmer-malgre-erreurs":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                meta = upload_mod.confirmer_malgre_erreurs(payload.get("categorie", ""), payload.get("id", ""))
                self._send_json(meta)
            except upload_mod.ErreurUpload as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return

        if self.path == "/api/upload/retirer":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                upload_mod.remove_staged(payload.get("categorie", ""), payload.get("id", ""))
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return

        if self.path == "/api/upload/controler":
            try:
                self._send_json(upload_mod.controler())
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
            return

        if self.path == "/api/supprimer/apercu":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                finess = str(payload.get("finess", ""))
                if not _FINESS_RE.match(finess):
                    raise ValueError("FINESS invalide (9 chiffres attendus).")
                avec_fichiers_source = bool(payload.get("fichiers_source"))

                from tools.supprimer_etablissement import apercu

                self._send_json(apercu(finess, avec_fichiers_source))
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return

        if self.path == "/api/supprimer/executer":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                finess = str(payload.get("finess", ""))
                if not _FINESS_RE.match(finess):
                    raise ValueError("FINESS invalide (9 chiffres attendus).")
                avec_fichiers_source = bool(payload.get("fichiers_source"))

                self._send_json(_supprimer_et_publier(finess, avec_fichiers_source))
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
            return

        if self.path == "/api/exporter":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                self._send_json(_exporter(payload.get("fichiers") or []))
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return

        if self.path != "/api/generate":
            self.send_error(404, "Route inconnue")
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            finess_list = payload.get("finess") or []
            years = payload.get("years") or []
            axis = payload.get("axis") or "none"
            mois_fin = payload.get("mois_fin")
            groupes_uf = payload.get("groupes_uf") or {}
            selection_uf = payload.get("selection_uf") or {}

            if not finess_list:
                raise ValueError("Choisissez au moins un établissement.")
            if not all(_FINESS_RE.match(f) for f in finess_list):
                raise ValueError("FINESS invalide.")
            if len(years) > MAX_ANNEES:
                raise ValueError(f"3 années maximum (reçu {len(years)}).")
            if not all(_ANNEE_RE.match(y) for y in years):
                raise ValueError("Année invalide.")
            if axis not in ("none", "uf", "type_hospitalisation"):
                raise ValueError("Axe secondaire invalide.")
            if mois_fin is not None:
                if not isinstance(mois_fin, int) or not (1 <= mois_fin <= 12):
                    raise ValueError("Mois de fin invalide (1 à 12).")
            if not isinstance(groupes_uf, dict):
                raise ValueError("groupes_uf invalide.")
            for f, groupes in groupes_uf.items():
                if f not in finess_list or not isinstance(groupes, dict):
                    raise ValueError("groupes_uf invalide.")
                for nom, ufs in groupes.items():
                    if not isinstance(nom, str) or not isinstance(ufs, list) or not all(isinstance(u, str) for u in ufs):
                        raise ValueError("groupes_uf invalide.")
            if not isinstance(selection_uf, dict):
                raise ValueError("selection_uf invalide.")
            for f, ufs in selection_uf.items():
                if f not in finess_list or not isinstance(ufs, list) or not all(isinstance(u, str) for u in ufs):
                    raise ValueError("selection_uf invalide.")

            signalisation_couleur = bool(payload.get("signalisation_couleur"))
            apparence_raw = payload.get("apparence") or {}
            if not isinstance(apparence_raw, dict):
                raise ValueError("apparence invalide.")
            apparence: dict[str, str] = {}
            for key in ("fond", "contenu", "cadre"):
                v = apparence_raw.get(key)
                if v:
                    if not isinstance(v, str) or not _HEX_COLOR_RE.match(v):
                        raise ValueError(f"Couleur \"{key}\" invalide (format #rrggbb attendu).")
                    apparence[key] = v
            police = apparence_raw.get("police")
            if police:
                from src.viz.render_dashboard import FONT_CHOICES

                if police not in FONT_CHOICES:
                    raise ValueError("Police invalide.")
                apparence["police"] = police

            reports = _generate(
                finess_list, years, axis, mois_fin, groupes_uf, selection_uf, signalisation_couleur, apparence
            )
            self._send_json({"reports": reports})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)


def serve(port: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    import webbrowser

    # Crée l'arborescence du bac à sable (input/, data/, app/generated, ...) dès
    # le démarrage plutôt qu'au premier clic sur "Mettre à jour les données" :
    # sinon /api/meta plante au tout premier lancement sur un dossier neuf
    # (data/processed/ absent -> sqlite3.connect échoue, il ne crée pas les
    # dossiers parents).
    from run import ensure_arborescence

    ensure_arborescence()

    # Port fixe (plutôt que 0 = port aléatoire choisi par l'OS) : l'URL reste identique d'un
    # lancement à l'autre, sinon chaque relance de launch.exe change d'origine (127.0.0.1:PORT)
    # et fait perdre tout ce que l'explorateur mémorise côté navigateur (localStorage), comme la
    # dernière sélection de filtres — constaté par l'utilisateur. Repli sur un port aléatoire
    # seulement si le port fixe est déjà occupé (ex. une autre instance déjà lancée), pour ne
    # jamais empêcher le démarrage.
    DEFAULT_PORT = 8743
    try:
        httpd = serve(DEFAULT_PORT)
    except OSError:
        httpd = serve(0)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"Serveur PMSI-SMR démarré : {url}")
    print("Ctrl+C pour arrêter.")
    webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
