"""Extraction du fichier complémentaire CSARR (xlsx ATIH).

Le fichier (feuille "CSARR_2026_avec_infos") mélange sur des lignes de nature
différente (colonne "TypeLigne" : T=titre, NT/NT2/N/N2=notes, LV=ligne vide,
L=libellé) les titres de subdivision et les libellés d'actes — même principe
que le fichier CCAM, mais en plus simple :
- colonne "CodeHier" : le numéro de subdivision hiérarchique pointé (ex.
  "07.01.01.02"), présent sur TOUTES les lignes (titres ET actes) ;
- colonne "CodeActe" : le code de l'acte CSARR (ex. "ALQ+183"), rempli
  uniquement sur les lignes d'acte.

Contrairement à CCAM, le fichier ne fournit pas de colonnes séparées
"N°/Titre 1e à 4e subdivision" par ligne d'acte : c'est la ligne "T" (titre)
correspondant à chaque CodeHier qui porte le libellé de ce niveau de
hiérarchie. On ne garde que les colonnes utiles (code, libellé, code
hiérarchique parent) — pas les modulateurs, gestes complémentaires, dates de
validité, consignes de codage, etc.

La feuille "codes supprimés" du classeur (codes retirés d'une version
antérieure) n'est pas chargée : conformément à la politique
dernier-libellé-gagne déjà appliquée à CIM-10 et CCAM, on ne charge que la
version en vigueur.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

SHEET_NAME = "CSARR_2026_avec_infos"

COL_CODEHIER = 1
COL_CODEACTE = 2
COL_LIBELLE = 3
COL_TYPO = 9

_KIND_BY_DEPTH = {1: "chapitre", 2: "sous_chapitre", 3: "paragraphe", 4: "sous_paragraphe"}


def _rows(path: str | Path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[SHEET_NAME]
    it = ws.iter_rows(values_only=True)
    next(it)  # header
    yield from it
    wb.close()


def load_flat_from_xlsx(path: str | Path) -> list[dict]:
    out = []
    for r in _rows(path):
        if r[COL_TYPO] == "L" and r[COL_CODEACTE]:
            out.append(
                {
                    "code": str(r[COL_CODEACTE]).strip(),
                    "libelle": (r[COL_LIBELLE] or "").strip(),
                    "parent_code": str(r[COL_CODEHIER]).strip() if r[COL_CODEHIER] else None,
                }
            )
    return out


def load_hierarchie_from_xlsx(path: str | Path) -> list[dict]:
    out = []
    for r in _rows(path):
        if r[COL_TYPO] != "T" or not r[COL_CODEHIER]:
            continue
        code = str(r[COL_CODEHIER]).strip()
        parts = code.split(".")
        depth = len(parts)
        parent_code = ".".join(parts[:-1]) if depth > 1 else None
        out.append(
            {
                "code": code,
                "kind": _KIND_BY_DEPTH.get(depth, f"niveau_{depth}"),
                "parent_code": parent_code,
                "libelle": (r[COL_LIBELLE] or "").strip(),
            }
        )
    return out
