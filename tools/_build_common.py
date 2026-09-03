"""Logique partagée par les scripts de build PyInstaller (`build_launch.py`,
`deployer_smrxplore.py`) : liste des fichiers `app/` à embarquer et
constitution des arguments `--add-data`.

Ne PAS dupliquer `SOURCE_APP_FILES` ailleurs — doit rester synchronisé avec
la liste "source" du `.gitignore` (`app/*`) et avec
`src/server/app_server.py::_SOURCE_APP_FILES`/`_SOURCE_APP_DIRS` : ce sont
les seuls fichiers `app/` qui ne sont pas des artefacts générés à partir de
données patients réelles (les seuls à embarquer dans un exécutable).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCE_APP_FILES = [
    "index.html",
    "admin.html",
    "tdb-choix.html",
    "explorateur.html",
    "catalogue.js",
    "app.js",
    "plotly_viewer.html",
    "theme.js",
]

# Modules importés uniquement à l'intérieur de fonctions dans
# src/server/app_server.py (routes déclenchées à la demande, jamais au
# démarrage du serveur) — l'analyse statique de PyInstaller les détecte en
# général sans aide, mais s'est montrée peu fiable au moins une fois en CI
# (src.viz.render_dashboard absent du build v3.7.3 alors qu'il l'était bien
# dans deux reconstructions locales identiques, même version de PyInstaller
# 6.22.2 — seule différence connue : Python 3.11 en CI vs 3.12 en local).
# Déclarés ici en --hidden-import pour ne plus dépendre de cette détection :
# la génération des tableaux de bord (`_generate`, route /api/tableaux) et
# la suppression d'établissement plantaient sinon avec "No module named ...".
HIDDEN_IMPORTS = [
    "run",
    "src.viz.render_dashboard",
    "tools.publier_explorateur",
    "tools.supprimer_etablissement",
]


def hidden_import_args() -> list[str]:
    args = []
    for name in HIDDEN_IMPORTS:
        args += ["--hidden-import", name]
    return args


def check_warn_file(build_dir: Path, exe_name: str) -> None:
    """Affiche toute ligne du fichier warn-<exe_name>.txt de PyInstaller
    mentionnant un des HIDDEN_IMPORTS — diagnostic ajouté le 2026-09-03 après
    un cas où src.viz.render_dashboard manquait du binaire malgré
    --hidden-import (échec constaté seulement en CI, jamais reproduit en
    local ni dans un venv minimal identique) : ce fichier, jusque-là
    supprimé avec build_dir sans être lu, aurait donné la vraie raison
    (ImportError sous-jacent ?) au lieu de deviner. Ne fait rien si le
    fichier n'existe pas (ex. nom différent selon la structure de build)."""
    warn_path = build_dir / exe_name / f"warn-{exe_name}.txt"
    if not warn_path.exists():
        return
    hits = [
        line
        for line in warn_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if any(m in line for m in HIDDEN_IMPORTS)
    ]
    if hits:
        print(f"\n--- Avertissements PyInstaller concernant HIDDEN_IMPORTS ({warn_path}) ---")
        for line in hits:
            print(line)
        print("---")


COMMITTED_SEED = ROOT / "config" / "nomenclatures" / "nomenclatures_seed.db"


def build_nomenclatures_seed(build_dir: Path) -> Path | None:
    """Extrait les seules tables nomenclature_* (référence ATIH quasi-statique,
    données PUBLIQUES — pas la propriété de l'ATIH, voir mémoire projet du
    2026-09-03 : CIM-10, CCAM, CSARR, CSAR, GME...) de data/processed/pmsi.db
    vers un petit fichier à part, embarquable dans un exe — jamais les
    tables de données patients (rhs_groupe, vid_hosp, valorisation_sejour...).
    Permet à un déploiement neuf de générer des tableaux de bord sans avoir
    à relancer `python pmsi.py nomenclatures` (maintenance interne, fichiers
    sources ATIH bruts non embarqués) — cf. run.seed_nomenclatures().

    Si data/processed/pmsi.db est absent localement (cas d'un build CI, qui
    n'a jamais cette base — voir .gitignore) : repli sur COMMITTED_SEED, un
    seed déjà extrait et committé dans le dépôt, pour que les binaires
    publiés (GitHub Actions) restent fonctionnels dès le téléchargement.
    Régénérer ce fichier committé à la main après toute mise à jour des
    nomenclatures (voir README, section build)."""
    source_db = ROOT / "data" / "processed" / "pmsi.db"
    if not source_db.exists():
        if COMMITTED_SEED.exists():
            print(f"(pas de data/processed/pmsi.db local — repli sur {COMMITTED_SEED})")
            return COMMITTED_SEED
        print("(pas de data/processed/pmsi.db local, ni de seed committé — seed nomenclatures ignoré)")
        return None

    build_dir.mkdir(parents=True, exist_ok=True)
    seed_path = build_dir / "nomenclatures_seed.db"
    seed_path.unlink(missing_ok=True)

    conn = sqlite3.connect(seed_path)
    try:
        conn.execute("ATTACH DATABASE ? AS src", (str(source_db),))
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM src.sqlite_master WHERE type='table' AND name LIKE 'nomenclature_%'"
            )
        ]
        if not tables:
            print("(aucune table nomenclature_* dans data/processed/pmsi.db — seed ignoré)")
            return None
        for t in tables:
            conn.execute(f'CREATE TABLE "{t}" AS SELECT * FROM src."{t}"')
        conn.commit()
        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()
    print(f"Seed nomenclatures : {seed_path} ({len(tables)} table(s))")
    return seed_path


def add_data_args(nomenclatures_seed: Path | None) -> list[str]:
    """Arguments `--add-data` PyInstaller pour embarquer les fichiers source
    `app/` (interface, jamais les artefacts générés) + `config/formats` et
    `config/nomenclatures` — indispensable pour tout exécutable onefile
    consommé par `src/server/app_server.py`, qui résout ces fichiers via
    `src/util/paths.py::resource_root()` (=`sys._MEIPASS` une fois figé,
    donc introuvables si non embarqués via cette fonction).

    Le séparateur SRC/DEST de --add-data est ';' sous Windows et ':' partout
    ailleurs (doc PyInstaller) — os.pathsep le donne déjà correctement."""
    sep = os.pathsep
    args = []
    for name in SOURCE_APP_FILES:
        args += ["--add-data", f"{ROOT / 'app' / name}{sep}app"]
    args += ["--add-data", f"{ROOT / 'app' / 'lib'}{sep}app/lib"]
    args += ["--add-data", f"{ROOT / 'config' / 'formats'}{sep}config/formats"]
    args += ["--add-data", f"{ROOT / 'config' / 'nomenclatures'}{sep}config/nomenclatures"]
    if nomenclatures_seed is not None:
        args += ["--add-data", f"{nomenclatures_seed}{sep}data"]
    return args
