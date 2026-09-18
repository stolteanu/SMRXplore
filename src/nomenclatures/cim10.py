"""Extraction du kit de nomenclature CIM-10 (ATIH).

Le kit est distribué en zip et contient 3 fichiers texte : LIBCIM10MULTI.TXT
(l'ensemble complet des codes) et deux sous-ensembles redondants,
LIBCIM10MULTI_ch20.TXT et LIBCIM10MULTI_saufch20.TXT (chapitre 20 / hors
chapitre 20). Seul le fichier complet est chargé.

Format (cf. cim.pdf du kit) : fichier séquentiel, encodé ANSI/cp1252,
une ligne par code, 6 champs séparés par '|' : code, type_mco_had,
profil_smr, type_psy, libelle_court, libelle_complet. Les 4 premiers champs
sont de longueur fixe (6/1/3/1) mais on découpe sur '|' plutôt que sur la
position, car les deux derniers champs (libellés) sont de longueur variable.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

_MAIN_FILE_RE = re.compile(r"^LIBCIM10(MULTI)?\.TXT$", re.IGNORECASE)


def _find_main_member(zf: zipfile.ZipFile) -> str:
    candidates = [
        n for n in zf.namelist()
        if _MAIN_FILE_RE.match(Path(n).name)
        and "ch20" not in Path(n).stem.lower()
        and "saufch20" not in Path(n).stem.lower()
    ]
    if not candidates:
        raise ValueError(
            f"Aucun fichier LIBCIM10(MULTI).TXT complet trouvé dans {zf.filename} "
            f"(contenu du zip: {zf.namelist()})"
        )
    return candidates[0]


def parse_line(raw: str) -> dict:
    fields = raw.split("|")
    if len(fields) != 6:
        raise ValueError(
            f"Ligne CIM-10 mal formée (attendu 6 champs séparés par '|', trouvé {len(fields)}): {raw!r}"
        )
    code, type_mco_had, profil_smr, type_psy, libelle_court, libelle_complet = fields
    return {
        "code": code.strip(),
        "type_mco_had": int(type_mco_had) if type_mco_had.strip() else None,
        "profil_smr": profil_smr.strip(),
        "type_psy": int(type_psy) if type_psy.strip() else None,
        "libelle_court": libelle_court,
        "libelle_complet": libelle_complet,
    }


def load_from_zip(zip_path: str | Path) -> list[dict]:
    with zipfile.ZipFile(zip_path) as zf:
        member = _find_main_member(zf)
        raw_bytes = zf.read(member)
    text = raw_bytes.decode("cp1252")
    rows = []
    for line in text.splitlines():
        line = line.rstrip("\r\n")
        if not line:
            continue
        rows.append(parse_line(line))
    return rows
