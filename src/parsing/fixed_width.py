"""Parseur générique pour fichiers texte à largeur fixe (RHS groupé, VID-HOSP).

Le schéma (config/formats/*.schema.json) décrit un bloc fixe et, optionnellement,
des blocs répétés dont le nombre de répétitions est lu dans un champ du bloc fixe
(ex. n1 = nombre de DAS). Chaque bloc répété est rejoué en boucle juste après le
bloc précédent, avec un offset calculé dynamiquement pour CETTE ligne précise.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


def load_schema(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _slice(line: str, start: int, end: int) -> str:
    """Extrait line[start-1:end] (positions 1-based incluses), tolérant aux lignes trop courtes."""
    if start - 1 >= len(line):
        return ""
    return line[start - 1:end]


def _cast(raw: str, type_: str) -> tuple[Any, str | None]:
    """Retourne (valeur_castée, message_erreur_ou_None). Ne lève jamais d'exception."""
    if type_ == "N":
        stripped = raw.strip()
        if stripped == "":
            return None, None
        if stripped.lstrip("-").isdigit():
            return int(stripped), None
        return raw, "valeur non numérique pour un champ de type N"

    if type_ == "Date":
        stripped = raw.strip()
        if stripped == "" or stripped == "0" * len(stripped):
            return None, None
        if len(stripped) == 8 and stripped.isdigit():
            jj, mm, aaaa = stripped[0:2], stripped[2:4], stripped[4:8]
            return f"{aaaa}-{mm}-{jj}", None
        return raw, "format de date inattendu (JJMMAAAA attendu)"

    stripped = raw.strip()
    return (stripped if stripped != "" else None), None


def parse_record(line: str, schema: dict) -> dict:
    """Parse une ligne (un enregistrement) selon le schéma. Ne lève jamais d'exception :
    les anomalies sont accumulées dans result['errors'] pour permettre un traitement
    tolérant (ligne journalisée mais pas bloquante pour le reste du fichier)."""
    errors: list[str] = []
    fixed: dict[str, Any] = {}

    for f in schema["fixed_block"]:
        raw = _slice(line, f["start"], f["end"])
        value, err = _cast(raw, f.get("type", "A"))
        fixed[f["name"]] = value
        if err:
            errors.append(f"{f['name']}: {err} (brut={raw!r})")

    result: dict[str, Any] = {"fixed": fixed, "errors": errors}

    offset = schema["fixed_block"][-1]["end"]
    for block in schema.get("repeated_blocks", []):
        counter_name = block["counter_field"]
        count = fixed.get(counter_name)
        if not isinstance(count, int) or count < 0:
            if count not in (None, 0):
                errors.append(
                    f"compteur {counter_name} invalide ({count!r}), bloc {block['name']} ignoré"
                )
            count = 0

        block_len = block["block_len"]
        items = []
        for i in range(count):
            base = offset + i * block_len
            item: dict[str, Any] = {}
            for bf in block["fields"]:
                raw = _slice(line, base + bf["start"], base + bf["end"])
                value, err = _cast(raw, bf.get("type", "A"))
                item[bf["name"]] = value
                if err:
                    errors.append(
                        f"{block['name']}[{i + 1}].{bf['name']}: {err} (brut={raw!r})"
                    )
            items.append(item)

        result[block["name"]] = items
        offset += count * block_len

    result["expected_length"] = offset
    result["actual_length"] = len(line)
    if len(line) != offset:
        errors.append(
            f"longueur d'enregistrement attendue={offset} caractères, réelle={len(line)}"
        )

    return result


def parse_file_multi(
    path: str | Path,
    schemas_by_version: dict[str, dict],
    version_slice: tuple[int, int],
    encoding: str = "latin-1",
) -> Iterator[tuple[int, str, str, dict | None]]:
    """Comme parse_file, mais choisit le schéma de PARSING ligne par ligne selon le
    code de version lu à version_slice=(start, end) (positions 1-based incluses),
    ex. (11, 13) pour version_format_rhs_groupe. Génère
    (numéro_ligne, ligne_brute, code_version, résultat_parse_ou_None).
    résultat = None si le code de version ne correspond à aucun schéma connu
    (ligne à journaliser et ignorer, plutôt que de deviner un format)."""
    start, end = version_slice
    with open(path, encoding=encoding, newline="") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.rstrip("\r\n")
            if line == "":
                continue
            version = line[start - 1:end]
            parsing_schema = schemas_by_version.get(version)
            if parsing_schema is None:
                yield line_no, line, version, None
                continue
            yield line_no, line, version, parse_record(line, parsing_schema)


def parse_file(path: str | Path, schema: dict, encoding: str = "latin-1") -> Iterator[tuple[int, str, dict]]:
    """Génère (numéro_ligne, ligne_brute, résultat_parse) pour chaque ligne non vide du fichier."""
    with open(path, encoding=encoding, newline="") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.rstrip("\r\n")
            if line == "":
                continue
            yield line_no, line, parse_record(line, schema)
