"""Chargement de la grille tarifaire GMT (input/tarifs/tarifs_qv.xlsx).

Fichier compilé et maintenu à jour par l'utilisateur lui-même, pas une
restitution ATIH — il a 3 feuilles qui partagent la même trame de colonnes
(Sheet1 = GMT standard <=90j, GMT_en_8 = HC Réadaptation spécialisée,
GMT_en_7 = GMTH journées au-delà du 90e jour), chacune un historique
versionné par tarif (DDEB/DFIN) plutôt qu'un instantané dernier-gagne.

Comme pour la valorisation (src/parsing/valorisation.py), le mapping se fait
PAR NOM d'en-tête (schema['columns'][i]['xlsx_header']), pas par position :
l'utilisateur a dit vouloir simplement ajouter des lignes années après
années dans le même fichier/mêmes feuilles, donc tant que les en-têtes ne
changent pas, aucune modification de schéma n'est nécessaire pour une
nouvelle année. Si un en-tête inconnu apparaît (colonne ajoutée/renommée),
le chargement de la feuille concernée échoue explicitement plutôt que
d'ignorer silencieusement la colonne.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import openpyxl

SHEETS = ["Sheet1", "GMT_en_8", "GMT_en_7"]


def _to_iso_date(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def _header_mapping(header: list, columns: list[dict]) -> tuple[list[str | None], list[str]]:
    by_header = {c["xlsx_header"]: c["name"] for c in columns if c["xlsx_header"] is not None}
    mapping = []
    unknown = []
    for raw in header:
        name = by_header.get(raw)
        mapping.append(name)
        if name is None:
            unknown.append(raw)
    return mapping, unknown


def load_from_xlsx(path: str | Path, schema: dict) -> list[dict]:
    columns = schema["columns"]
    all_names = [c["name"] for c in columns]
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows: list[dict] = []
    for sheet_name in SHEETS:
        ws = wb[sheet_name]
        it = ws.iter_rows(values_only=True)
        header = list(next(it))
        mapping, unknown = _header_mapping(header, columns)
        if unknown:
            raise ValueError(f"{path} [{sheet_name}]: colonne(s) inconnue(s) du schéma : {unknown}")
        for raw in it:
            if raw[0] is None:
                continue
            row = dict.fromkeys(all_names)
            row["feuille_source"] = sheet_name
            for field_name, value in zip(mapping, raw):
                if field_name is None:
                    continue
                if field_name in ("date_debut", "date_fin"):
                    value = _to_iso_date(value)
                row[field_name] = value
            rows.append(row)
    wb.close()
    return rows
