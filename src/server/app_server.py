"""Serveur local minimal (bibliothèque standard uniquement) pour piloter le
tableau de bord PMSI-SMR depuis un navigateur : sert app/ en statique et
expose des endpoints JSON pour la page "TDB choix" (app/tdb-choix.html) et
la page d'accueil (app/index.html) :

  GET  /api/meta      -> établissements + années disponibles
  POST /api/generate  -> génère le(s) TDB demandé(s), renvoie leurs URLs
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if not getattr(sys, "frozen", False):
    # Nécessaire uniquement en exécution depuis les sources (`python
    # launch.py`) pour que `from src...` résolve quel que soit le cwd — une
    # fois empaqueté (PyInstaller), les modules src.* sont déjà accessibles
    # via le mécanisme d'import interne au .exe, pas besoin de sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.util.paths import project_root  # noqa: E402

ROOT = project_root()
APP_DIR = (ROOT / "app").resolve()
GENERATED_DIR = APP_DIR / "generated"

MAX_ANNEES = 3

_FINESS_RE = re.compile(r"^\d{9}$")
_ANNEE_RE = re.compile(r"^\d{4}$")


def _load_meta() -> dict:
    from src.viz.tableau_de_bord import connect, list_finess, years_disponibles

    conn = connect()
    finess_list = list_finess(conn)
    years_by_finess = {f: years_disponibles(conn, f) for f in finess_list}
    conn.close()
    return {"finess": finess_list, "years_by_finess": years_by_finess}


def _generate(finess_list: list[str], years: list[str], axis: str) -> list[dict]:
    from src.viz.render_dashboard import generate_axis_reports, render, render_annexe, render_journal
    from src.viz.tableau_de_bord import build

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "-".join(years) if years else "toutes"
    reports = []
    for finess in finess_list:
        data = build(finess, years or None)
        if not data["years"]:
            raise ValueError(f"Aucune donnée pour le FINESS {finess} sur les années demandées.")
        base = f"{finess}_{suffix}"

        tdb_path = GENERATED_DIR / f"tableau_de_bord_{base}.html"
        tdb_path.write_text(render(data), encoding="utf-8")

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
            # plus du TDB principal, cf. generate_axis_reports).
            report["secondaires"] = generate_axis_reports(finess, years or None, axis)

        reports.append(report)
    return reports


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
        """Traduit une URL en chemin sous app/, en refusant toute sortie du
        dossier (../, chemins absolus, etc.)."""
        if url_path == "/":
            url_path = "/index.html"
        rel = url_path.lstrip("/")
        target = (APP_DIR / rel).resolve()
        if target != APP_DIR and not str(target).startswith(str(APP_DIR) + os.sep):
            return None
        return target

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/api/meta":
            try:
                self._send_json(_load_meta())
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
            return

        target = self._resolve_static(self.path.split("?", 1)[0])
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

        if self.path != "/api/generate":
            self.send_error(404, "Route inconnue")
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            finess_list = payload.get("finess") or []
            years = payload.get("years") or []
            axis = payload.get("axis") or "none"

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

            reports = _generate(finess_list, years, axis)
            self._send_json({"reports": reports})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)


def serve(port: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    import webbrowser

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
