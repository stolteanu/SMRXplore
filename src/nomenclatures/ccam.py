"""Extraction du fichier complémentaire CCAM descriptive à usage PMSI (xlsx ATIH).

Le fichier (feuille "CCAM_Final_2026") est une liste analytique de 49+ colonnes
mêlant, sur des lignes de nature différente (colonne "Typo ligne libellé" :
T=titre, NT=note de titre, LV=ligne vide, L=libellé, N=note de libellé), les
titres de subdivision et les libellés d'actes. On ne garde que les lignes
Typo == "L" (un acte ou un modificateur + son libellé), et seulement les
colonnes nécessaires : code, libellé, et les 4 niveaux de hiérarchie
(chapitre / sous-chapitre / paragraphe / sous-paragraphe) que le fichier
fournit déjà, en clair, sur chaque ligne d'acte (pas de préfixe à deviner
comme pour CIM-10 : colonnes "N°/Titre 1e à 4e subdivision").

Deux quirks de la source à connaître :
- Les colonnes numéro-de-chapitre et numéro-de-sous-chapitre (ex-colonnes 42
  et 44) sont mal typées sur 2 lignes / 8850 (int/float au lieu de texte,
  ex. 9.03 au lieu de "09.03") — on les ignore et on dérive systématiquement
  chapitre/sous-chapitre par troncature du code "paragraphe" (colonne 46,
  toujours une chaîne bien zéro-paddée du type "01.01.01"), qui est fiable
  à 100% sur les 8850 lignes.
- Un même code peut apparaître plusieurs fois avec un libellé différent
  (le fichier garde l'historique des libellés successifs, identifiable par
  "Date de début de validité" croissante) — ex. DAQL006, ou les
  modificateurs U/P/S/F. On trie par date de début de validité croissante
  avant de renvoyer les lignes : le chargeur (INSERT OR REPLACE, même
  logique que les autres nomenclatures) fait gagner le libellé le plus
  récent, cohérent avec la politique dernier-libellé-gagne.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import openpyxl

SHEET_NAME = "CCAM_Final_2026"

COL_CODE = 2  # "Code à 7 caractères (et extension PMSI)"
COL_TYPO = 10  # "Typo ligne libellé"
COL_LIBELLE = 5  # "Texte : titre-libellés-notes"
COL_CHAP_LIBELLE = 43
COL_SCHAP_LIBELLE = 45
COL_PARAGRAPHE = 46  # "N° 3e subdivision : paragraphe", ex. "01.01.01"
COL_PARAGRAPHE_LIBELLE = 47
COL_SOUS_PARAGRAPHE = 48
COL_SOUS_PARAGRAPHE_LIBELLE = 49
COL_DATE_DEBUT = 50


def _rows_l(path: str | Path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[SHEET_NAME]
    it = ws.iter_rows(values_only=True)
    next(it)  # header
    for r in it:
        if r[COL_TYPO] == "L":
            yield r
    wb.close()


def _sort_key(row) -> dt.datetime:
    d = row[COL_DATE_DEBUT]
    return d if isinstance(d, dt.datetime) else dt.datetime.min


def load_flat_from_xlsx(path: str | Path) -> list[dict]:
    rows = sorted(_rows_l(path), key=_sort_key)
    out = []
    for r in rows:
        if r[COL_CODE] is None:
            continue
        sous_paragraphe = r[COL_SOUS_PARAGRAPHE]
        paragraphe = r[COL_PARAGRAPHE]
        parent_code = str(sous_paragraphe) if sous_paragraphe else (str(paragraphe) if paragraphe else None)
        out.append(
            {
                "code": str(r[COL_CODE]).strip(),
                "libelle": (r[COL_LIBELLE] or "").strip(),
                "parent_code": parent_code,
            }
        )
    return out


def load_hierarchie_from_xlsx(path: str | Path) -> list[dict]:
    rows = sorted(_rows_l(path), key=_sort_key)
    out: dict[str, dict] = {}
    for r in rows:
        paragraphe = r[COL_PARAGRAPHE]
        if not paragraphe:
            continue
        parts = str(paragraphe).split(".")
        chap_code = parts[0]
        schap_code = ".".join(parts[:2])
        out[chap_code] = {
            "code": chap_code, "kind": "chapitre", "parent_code": None,
            "libelle": (r[COL_CHAP_LIBELLE] or "").strip(),
        }
        out[schap_code] = {
            "code": schap_code, "kind": "sous_chapitre", "parent_code": chap_code,
            "libelle": (r[COL_SCHAP_LIBELLE] or "").strip(),
        }
        out[str(paragraphe)] = {
            "code": str(paragraphe), "kind": "paragraphe", "parent_code": schap_code,
            "libelle": (r[COL_PARAGRAPHE_LIBELLE] or "").strip(),
        }
        sous_paragraphe = r[COL_SOUS_PARAGRAPHE]
        if sous_paragraphe:
            out[str(sous_paragraphe)] = {
                "code": str(sous_paragraphe), "kind": "sous_paragraphe",
                "parent_code": str(paragraphe),
                "libelle": (r[COL_SOUS_PARAGRAPHE_LIBELLE] or "").strip(),
            }
    return list(out.values())
