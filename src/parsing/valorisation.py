"""Parsing des fichiers CSV de restitution ATIH VISUAL VALO Séjours.

Contrairement au RHS groupé / VID-HOSP (positions fixes, version détectée par
un code à position fixe dans la ligne), ce format est un CSV auto-descriptif
(en-tête = noms de colonnes) délimité par ';' — le mapping se fait donc par
NOM d'en-tête (schema['columns'][i]['csv_aliases']), pas par position. Cela
absorbe naturellement les deux structures de colonnes constatées (2024/2025
vs 2026, cf. note_versions du schéma) sans registre de version séparé.

Une particularité du fichier source, dans les deux structures : l'en-tête
contient deux colonnes nommées littéralement NUMSEMAINE (une renseignée en
HC, l'autre en HP). Le mapping par nom seul ne peut pas les distinguer — on
désambiguïse par ORDRE D'APPARITION dans l'en-tête : la k-ième colonne du
schéma déclarant un alias donné reçoit la k-ième occurrence de ce nom dans
le fichier.
"""
from __future__ import annotations

import csv
from pathlib import Path

NULL_TOKENS = {"", "."}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return None if v in NULL_TOKENS else v


def _header_mapping(header: list[str], columns: list[dict]) -> tuple[list[str | None], list[str]]:
    """Retourne (mapping, noms_inconnus) où mapping[i] est le nom de champ
    canonique correspondant à header[i] (ou None si l'en-tête contient une
    colonne non déclarée dans le schéma)."""
    alias_candidates: dict[str, list[str]] = {}
    for col in columns:
        for alias in col["csv_aliases"]:
            alias_candidates.setdefault(alias, []).append(col["name"])

    consumed: dict[str, int] = {}
    mapping: list[str | None] = []
    unknown: list[str] = []
    for raw in header:
        candidates = alias_candidates.get(raw)
        k = consumed.get(raw, 0)
        consumed[raw] = k + 1
        if candidates and k < len(candidates):
            mapping.append(candidates[k])
        else:
            mapping.append(None)
            unknown.append(raw)
    return mapping, unknown


def load_from_csv(path: str | Path, schema: dict) -> list[dict]:
    """Lit un fichier VISUAL VALO Séjours et retourne une liste de dicts
    clé = nom de champ canonique (schema['columns'][i]['name']). Les champs
    du schéma absents de l'en-tête de CE fichier (structure plus ancienne ou
    plus récente) valent None pour toutes les lignes."""
    columns = schema["columns"]
    all_names = [c["name"] for c in columns]
    with open(path, encoding="cp1252", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        header = next(reader)
        mapping, unknown = _header_mapping(header, columns)
        if unknown:
            raise ValueError(f"{path}: colonne(s) inconnue(s) du schéma : {unknown}")

        rows = []
        for raw in reader:
            if not raw or all(not c.strip() for c in raw):
                continue
            row = dict.fromkeys(all_names)
            for field_name, value in zip(mapping, raw):
                if field_name is not None:
                    row[field_name] = _clean(value)
            rows.append(row)
    return rows
