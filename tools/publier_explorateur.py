"""Recopie data/processed/pmsi.db vers app/data/pmsi.db pour l'explorateur TDB interactif.

À relancer après chaque exécution de run.py (nouvelle transmission chargée), avant de
rouvrir app/explorateur.html ou de redistribuer le dossier app/ tel quel.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.util.paths import project_root  # noqa: E402

ROOT = project_root()
SRC = ROOT / "data/processed/pmsi.db"
DST = ROOT / "app/data/pmsi.db"


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"Base introuvable : {SRC}")
    DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC, DST)
    print(f"OK — {SRC} -> {DST} ({DST.stat().st_size / 1_000_000:.1f} Mo)")


if __name__ == "__main__":
    main()
