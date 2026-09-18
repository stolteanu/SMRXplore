"""Extraction de la nomenclature des intervenants CSAR.

Contrairement aux autres nomenclatures, cette liste (code à 2 chiffres +
libellé de la profession) n'existe dans aucun fichier structuré du fichier
associé CSAR : elle ne figure que dans le guide de codage
(guide_csar_version_n1_2026.pdf, §2.4.1 "Liste des intervenants", Tableau 3).
Plutôt que de la coder en dur en Python (comme pour les libellés de
chapitre CSAR), elle a été retranscrite une fois dans
input/nomenclatures/csar/intervenants/intervenants_csar_2026.csv (code,libelle)
pour rester versionnée comme un vrai fichier source, chargeable via le même
mécanisme générique que les autres nomenclatures.
"""
from __future__ import annotations

import csv
from pathlib import Path


def load_from_csv(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [{"code": row["code"].strip(), "libelle": row["libelle"].strip()} for row in reader]
