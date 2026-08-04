"""Extraction de la hiérarchie de groupage SMR (CM -> GN -> GR -> GL -> GME).

Le fichier (feuille "libelles") est une table plate à 4 colonnes : "quoi"
(le niveau : CM/GN/GR/GL/GME), "code", "lib_court", "lib_long". Contrairement
à CSARR/CSAR, il n'y a ici qu'une seule feuille pour toute la hiérarchie
(pas de distinction fichier flat / fichier hiérarchie) — chaque niveau EST
un nœud de hiérarchie, avec son propre libellé.

Comme pour CIM-10 et CCAM, le code d'un niveau est un préfixe du code du
niveau enfant, mais ici la longueur du code est fixe et connue par niveau
(CM=2, GN=4, GR=5, GL=6, GME=7 caractères) — le code parent s'obtient donc
en tronquant le code enfant à la longueur du niveau parent, plutôt qu'en
retirant un nombre fixe de caractères. Vérifié empiriquement : les 2559
lignes de la source (16 CM, 92 GN, 392 GR, 745 GL, 1314 GME) ont des codes
de longueur strictement constante par niveau, et les 2543 codes non-CM ont
tous un préfixe qui correspond exactement à un code réel du niveau parent
(0 lien de parenté manquant).

Le niveau GME (7 caractères) est le code_gme atomique déjà stocké tel quel
dans les RHS groupé (positions 55-61, cf. rhs_groupe.schema.json) — cette
table permet enfin de résoudre son libellé et sa hiérarchie complète.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

SHEET_NAME = "libelles"

_KIND_LENGTHS = {"CM": 2, "GN": 4, "GR": 5, "GL": 6, "GME": 7}
_PARENT_KIND = {"GN": "CM", "GR": "GN", "GL": "GR", "GME": "GL"}


def load_from_xlsx(path: str | Path) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[SHEET_NAME]
    it = ws.iter_rows(values_only=True)
    next(it)  # header
    rows = []
    for r in it:
        if not r[0]:
            continue
        kind, code = r[0].strip(), r[1].strip()
        parent_kind = _PARENT_KIND.get(kind)
        parent_code = code[: _KIND_LENGTHS[parent_kind]] if parent_kind else None
        rows.append(
            {
                "code": code,
                "kind": kind,
                "parent_code": parent_code,
                "libelle_court": (r[2] or "").strip(),
                "libelle_long": (r[3] or "").strip(),
            }
        )
    wb.close()
    return rows
