"""Extraction des codes d'erreur de la fonction de groupage (FG) SMR.

Le fichier (FG_erreurs*.TXT, encodé cp1252, un peu à la manière du kit
CIM-10) mélange deux choses :

1. La table principale, pipe-delimited : `code|libellé|Bloquant/Non-bloquant`
   — 184 codes, correspond au champ `code_retour_groupage` du RHS groupé
   (positions 62-64). Les codes ne sont PAS zéro-paddés dans ce fichier
   (ex. "72", pas "072"), alors que la valeur réellement stockée dans les
   RHS peut l'être ("072") ou non ("28") — la normalisation (strip des
   zéros de tête) doit donc se faire au moment du lookup/affichage, pas au
   chargement (les tables de faits gardent leurs codes bruts, comme
   toujours dans ce projet). Le code "0"/"000" observé dans les RHS réels
   n'existe pas dans cette table : il signifie "groupage réussi, pas
   d'erreur", pas un code à résoudre.
2. Deux annexes en texte libre plus loin dans le même fichier
   ("Erreur 162 : liste des actes concernés", "Erreur 163 : actes
   concernés"), chacune une simple liste `code_acte<TAB>libellé_acte`
   (des actes CSARR) : les actes CSARR concernés par ces deux erreurs
   précises. Structurellement différent du reste du fichier (pas de
   pipe, séparateur tabulation), extrait séparément dans une seconde
   table.
"""
from __future__ import annotations

from pathlib import Path


def _read_lines(path: str | Path) -> list[str]:
    return Path(path).read_text(encoding="cp1252").splitlines()


def load_erreurs_from_txt(path: str | Path) -> list[dict]:
    rows = []
    for line in _read_lines(path):
        if "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        code, libelle, type_ = parts
        rows.append({"code": code.strip(), "libelle": libelle.strip(), "type": type_.strip()})
    return rows


def load_actes_concernes_from_txt(path: str | Path) -> list[dict]:
    rows = []
    current_error = None
    for line in _read_lines(path):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Erreur"):
            current_error = stripped.split()[1].rstrip("\xa0:").rstrip(":")
            continue
        if "\t" in line and current_error:
            code, libelle = line.split("\t", 1)
            rows.append(
                {
                    "code_erreur": current_error,
                    "code_acte": code.strip(),
                    "libelle_acte": libelle.strip(),
                }
            )
    return rows
