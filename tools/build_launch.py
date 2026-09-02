#!/usr/bin/env python3
"""Reconstruit C:\\claude\\launch.exe (usage interne, sur cette machine) — sur
demande uniquement, jamais automatique.

Depuis l'ajout de src/util/paths.py::resource_root() (résolution des
fichiers app/ via sys._MEIPASS une fois figé), un simple `pyinstaller
--onefile launch.py` SANS --add-data produit un exe qui ne retrouve plus
explorateur.html/app.js/etc. au lancement (BIN_APP_DIR introuvable, cf.
src/server/app_server.py) — d'où ce script, qui embarque les mêmes
fichiers source app/ + config/ que tools/deployer_smrxplore.py (voir
tools/_build_common.py, seule source de vérité pour cette liste).

Différence avec tools/deployer_smrxplore.py : celui-ci produit
SMRXPLORE\\SMRXplore.exe (déploiement portable, redistribuable ailleurs) ;
celui-ci reconstruit launch.exe à la racine du dépôt, à utiliser sur cette
machine (à relancer après toute modification d'un fichier app/ embarqué —
cf. _build_common.SOURCE_APP_FILES — si l'on teste via launch.exe plutôt
que `python launch.py`, qui lit toujours les fichiers directement sur
disque et n'a donc pas besoin d'être reconstruit).

Usage :
    python tools/build_launch.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools._build_common import ROOT, add_data_args, build_nomenclatures_seed  # noqa: E402

BUILD_DIR = ROOT / "build"


def build_exe(nomenclatures_seed):
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--name",
            "launch",
            "--distpath",
            str(ROOT),
            "--workpath",
            str(BUILD_DIR),
            "--specpath",
            str(BUILD_DIR),
            *add_data_args(nomenclatures_seed),
            str(ROOT / "launch.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    return ROOT / "launch.exe"


def main() -> None:
    nomenclatures_seed = build_nomenclatures_seed(BUILD_DIR)
    exe_path = build_exe(nomenclatures_seed)
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    print(f"\nOK — {exe_path} à jour.")


if __name__ == "__main__":
    main()
