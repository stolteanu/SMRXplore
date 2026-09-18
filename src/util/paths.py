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


def resource_root() -> Path:
    """Racine des ressources statiques embarquées dans l'exécutable (app/
    hors artefacts générés, config/) — distincte de project_root().

    En exécution depuis les sources, confondue avec project_root() (tout
    vit au même endroit dans le dépôt). Une fois empaqueté en .exe onefile
    (PyInstaller --add-data, voir tools/deployer_smrxplore.py), ces
    ressources sont EMBARQUÉES dans le binaire lui-même plutôt que copiées
    à côté : PyInstaller les extrait à chaque lancement dans un dossier
    temporaire exposé via sys._MEIPASS. Aucun dossier annexe à côté de
    l'exe ne peut donc se perdre — seul le bac à sable (input/, data/,
    output/, backups/, app/generated, app/data, contenant les données
    patients réelles) est créé à côté, à l'exécution."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return project_root()
