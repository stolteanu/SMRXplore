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

Voir aussi tools/build_launch.py (même logique --add-data, cf.
tools/_build_common.py, mais produit C:\\claude\\launch.exe pour un usage
interne sur cette machine plutôt qu'un déploiement portable ailleurs).

Usage :
    python tools/deployer_smrxplore.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools._build_common import ROOT, add_data_args, build_nomenclatures_seed, check_warn_file, hidden_import_args  # noqa: E402

DEPLOY_DIR = ROOT / "SMRXPLORE"
DEPLOY_BUILD_DIR = DEPLOY_DIR / "_build"


def build_exe(nomenclatures_seed):
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
            *add_data_args(nomenclatures_seed),
            *hidden_import_args(),
            *(["--log-level", "DEBUG"] if os.environ.get("PYI_DEBUG") else []),
            str(ROOT / "launch.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    return DEPLOY_DIR / "SMRXplore.exe"


def main() -> None:
    DEPLOY_DIR.mkdir(exist_ok=True)
    nomenclatures_seed = build_nomenclatures_seed(DEPLOY_BUILD_DIR)
    exe_path = build_exe(nomenclatures_seed)
    check_warn_file(DEPLOY_BUILD_DIR, "SMRXplore")
    shutil.rmtree(DEPLOY_BUILD_DIR, ignore_errors=True)
    print(f"\nOK — {exe_path} à jour (fichier unique, bac à sable non touché).")


if __name__ == "__main__":
    main()
