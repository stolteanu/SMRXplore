"""Extraction mécanique de feuilles xlsx ATIH vers CSV.

Aucune interprétation ici : on recopie tel quel le contenu des cellules.
Cette étape ne peut pas se tromper silencieusement — si la feuille demandée
n'existe pas, on échoue bruyamment en listant les feuilles réellement
présentes dans le classeur.
"""
from __future__ import annotations

import csv
from pathlib import Path

import openpyxl


class FeuilleIntrouvable(Exception):
    pass


def extraire_feuille_vers_csv(xlsx_path: str | Path, nom_feuille: str, csv_out: str | Path) -> Path:
    xlsx_path = Path(xlsx_path)
    csv_out = Path(csv_out)

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    if nom_feuille not in wb.sheetnames:
        raise FeuilleIntrouvable(
            f"Feuille {nom_feuille!r} introuvable dans {xlsx_path.name}. "
            f"Feuilles disponibles : {wb.sheetnames}. "
            f"La mise en page ATIH a peut-être changé de nom de feuille — à vérifier manuellement."
        )

    ws = wb[nom_feuille]
    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_out, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for row in ws.iter_rows(values_only=True):
            writer.writerow(["" if v is None else v for v in row])

    return csv_out
