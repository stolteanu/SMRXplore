"""Racine du projet, indépendante du mode d'exécution.

En exécution normale (`python launch.py`), la racine se déduit du fichier
source (remonter jusqu'à C:\\claude). Une fois empaqueté en .exe autonome
(PyInstaller, voir README de build) le module tourne depuis un dossier
d'extraction TEMPORAIRE — `__file__` ne pointe plus vers le dossier où
l'utilisateur a réellement copié le projet. PyInstaller expose alors
`sys.frozen` : dans ce cas, la racine est le dossier qui contient l'exécutable
lui-même (`sys.executable`), là où l'utilisateur a copié app/ et
data/processed/ à côté du .exe.
"""
from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Convention : tout appelant vit à src/<sous-paquet>/<fichier>.py,
    # donc parents[2] remonte à la racine du dépôt.
    return Path(__file__).resolve().parents[2]
