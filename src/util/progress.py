"""Barre de progression texte minimale, sans dépendance externe.

Affiche une ligne qui se réécrit sur elle-même (\\r) tant qu'on n'est pas
au dernier élément, puis se fige avec un retour à la ligne — pas de
bibliothèque tierce (type tqdm) à installer, cohérent avec le choix du
projet de rester en bibliothèque standard.
"""
from __future__ import annotations

BAR_WIDTH = 30


def print_progress(current: int, total: int, label: str, detail: str = "") -> None:
    if total <= 0:
        return
    current = min(current, total)
    filled = BAR_WIDTH * current // total
    bar = "#" * filled + "-" * (BAR_WIDTH - filled)
    pct = current * 100 // total
    suffix = f" — {detail}" if detail else ""
    end = "\n" if current >= total else ""
    print(f"\r{label} [{bar}] {current}/{total} ({pct:>3}%){suffix}" + " " * 10, end=end, flush=True)
