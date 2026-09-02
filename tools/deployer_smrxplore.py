#!/usr/bin/env python3
"""Met à jour le déploiement portable SMRXplore (C:\\claude\\SMRXPLORE) avec les
dernières modifications de ce dépôt — sur demande uniquement, jamais automatique.

Produit UN SEUL fichier : SMRXPLORE\\SMRXplore.exe. Les ressources statiques
(app/ source, config/) sont EMBARQUÉES dans l'exécutable via PyInstaller
--add-data (extraites à chaque lancement dans un dossier temporaire, cf.
src/util/paths.resource_root()) — aucun dossier annexe à côté de l'exe qui
pourrait se perdre lors d'une copie/déplacement. Seul le bac à sable
(input/, data/, output/, backups/, app/generated, app/data — données
patients réelles) est créé à côté de l'exe, à l'exécution, et n'est jamais
touché par ce script.

Usage :
    python tools/deployer_smrxplore.py
"""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = ROOT / "SMRXPLORE"
DEPLOY_BUILD_DIR = DEPLOY_DIR / "_build"
NOMENCLATURES_SEED = DEPLOY_BUILD_DIR / "nomenclatures_seed.db"

# Doit rester synchronisé avec la liste "source" du .gitignore (app/*) et de
# src/server/app_server.py (_SOURCE_APP_FILES / _SOURCE_APP_DIRS) — ce sont
# les seuls fichiers app/ qui ne sont pas des artefacts générés à partir de
# données patients réelles (jamais à embarquer dans l'exe).
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


def build_nomenclatures_seed() -> None:
    """Extrait les seules tables nomenclature_* (référence ATIH quasi-statique :
    CIM-10, CCAM, CSARR, CSAR, GME...) de data/processed/pmsi.db vers un petit
    fichier à part, embarqué dans l'exe — jamais les tables de données
    patients (rhs_groupe, vid_hosp, valorisation_sejour...). Permet à un
    déploiement neuf de générer des tableaux de bord sans avoir à relancer
    `python pmsi.py nomenclatures` (maintenance interne, fichiers sources
    ATIH bruts non embarqués) — cf. run.seed_nomenclatures()."""
    source_db = ROOT / "data" / "processed" / "pmsi.db"
    if not source_db.exists():
        print("(pas de data/processed/pmsi.db local — seed nomenclatures ignoré)")
        return

    DEPLOY_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    NOMENCLATURES_SEED.unlink(missing_ok=True)

    conn = sqlite3.connect(NOMENCLATURES_SEED)
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
            return
        for t in tables:
            conn.execute(f'CREATE TABLE "{t}" AS SELECT * FROM src."{t}"')
        conn.commit()
        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()
    print(f"Seed nomenclatures : {NOMENCLATURES_SEED} ({len(tables)} table(s))")


def add_data_args() -> list[str]:
    args = []
    for name in SOURCE_APP_FILES:
        args += ["--add-data", f"{ROOT / 'app' / name};app"]
    args += ["--add-data", f"{ROOT / 'app' / 'lib'};app/lib"]
    args += ["--add-data", f"{ROOT / 'config' / 'formats'};config/formats"]
    args += ["--add-data", f"{ROOT / 'config' / 'nomenclatures'};config/nomenclatures"]
    if NOMENCLATURES_SEED.exists():
        args += ["--add-data", f"{NOMENCLATURES_SEED};data"]
    return args


def build_exe() -> Path:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--name",
            "SMRXplore",
            "--distpath",
            str(DEPLOY_DIR),
            "--workpath",
            str(DEPLOY_BUILD_DIR),
            "--specpath",
            str(DEPLOY_BUILD_DIR),
            *add_data_args(),
            str(ROOT / "launch.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    return DEPLOY_DIR / "SMRXplore.exe"


def main() -> None:
    DEPLOY_DIR.mkdir(exist_ok=True)
    build_nomenclatures_seed()
    exe_path = build_exe()
    shutil.rmtree(DEPLOY_BUILD_DIR, ignore_errors=True)
    print(f"\nOK — {exe_path} à jour (fichier unique, bac à sable non touché).")


if __name__ == "__main__":
    main()
