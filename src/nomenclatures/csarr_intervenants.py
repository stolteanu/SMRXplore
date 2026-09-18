"""Extraction de la nomenclature des intervenants CSARR.

Comme pour CSAR, cette liste (code à 2 chiffres + libellé de la profession)
n'a pas de source structurée ATIH connue et a été fournie par l'utilisateur
(transcrite d'un guide/annexe CSARR). Elle est retranscrite dans
input/nomenclatures/csarr/intervenants/intervenants_csarr_2026.csv
(code,libelle) pour rester versionnée comme un vrai fichier source.
"""
from __future__ import annotations

import csv
from pathlib import Path


def load_from_csv(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [{"code": row["code"].strip(), "libelle": row["libelle"].strip()} for row in reader]
