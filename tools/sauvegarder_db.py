#!/usr/bin/env python3
"""Sauvegarde de data/processed/pmsi.db avant toute opération qui la modifie
(charger, supprimer) — filet de sécurité indépendant de la vigilance humaine,
suite à l'écrasement accidentel d'une copie de cette base le 2026-08-28.

Rotation automatique : ne garde que les GARDER dernières sauvegardes pour ne
pas saturer le disque (chaque copie peut peser plusieurs dizaines de Mo).

Usage :
    python tools/sauvegarder_db.py     sauvegarde manuelle (ex. avant une manip risquée)
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.util.paths import project_root  # noqa: E402

ROOT = project_root()
DB_PATH = ROOT / "data/processed/pmsi.db"
BACKUPS_DIR = ROOT / "backups"
GARDER = 5


def sauvegarder(garder: int = GARDER) -> Path | None:
    """Copie DB_PATH vers backups/pmsi_AAAAMMJJ-HHMMSS.db puis supprime les
    plus anciennes au-delà de `garder`. Ne fait rien (retourne None) si la
    base n'existe pas encore (premier lancement, rien à sauvegarder)."""
    if not DB_PATH.exists():
        return None
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUPS_DIR / f"pmsi_{horodatage}.db"
    shutil.copy2(DB_PATH, dest)

    sauvegardes = sorted(BACKUPS_DIR.glob("pmsi_*.db"))
    for ancienne in sauvegardes[:-garder]:
        ancienne.unlink()
    return dest


def main() -> None:
    dest = sauvegarder()
    if dest is None:
        print(f"Rien à sauvegarder : {DB_PATH} n'existe pas encore.")
        return
    print(f"OK — sauvegarde créée : {dest} ({dest.stat().st_size / 1_000_000:.1f} Mo)")


if __name__ == "__main__":
    main()
