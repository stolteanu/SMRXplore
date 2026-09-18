#!/usr/bin/env python3
"""Convertit un fichier CSV standardisé (voir input/formats/standard/REGLES.md)
en schéma de parsing config/formats/*.schema.json, et enregistre le(s) code(s)
de version correspondant(s) dans config/formats/registry.json.

Contrairement à l'assistant xlsx (tools/incorporer_format.py), ce convertisseur
est entièrement mécanique : le CSV standard a une forme fixe et connue (mêmes
colonnes, noms de champs stables d'une année à l'autre), donc il n'y a aucune
interprétation à faire — juste à valider que les positions d'un bloc se
tiennent bien de bout en bout et que chaque bloc a un compteur.

Usage :
    python tools/csv_standard_vers_schema.py <csv> <code_version>[,<code_version>...]
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent

COLONNES_ATTENDUES = [
    "format", "bloc", "nom_champ", "position_debut", "position_fin",
    "taille", "type", "compteur_de_bloc", "obligatoire", "note",
]


class CsvStandardInvalide(Exception):
    pass


def lire_csv_standard(csv_path: Path) -> dict:
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLONNES_ATTENDUES:
            raise CsvStandardInvalide(
                f"Colonnes inattendues : {reader.fieldnames}. "
                f"Attendu exactement : {COLONNES_ATTENDUES} (voir input/formats/standard/REGLES.md)."
            )
        lignes = list(reader)

    if not lignes:
        raise CsvStandardInvalide("Le fichier est vide.")

    formats_presents = {l["format"] for l in lignes}
    if len(formats_presents) != 1:
        raise CsvStandardInvalide(f"Plusieurs formats mélangés dans un seul fichier : {formats_presents}")
    format_nom = formats_presents.pop()

    fixed_rows = [l for l in lignes if not l["bloc"]]
    block_rows = [l for l in lignes if l["bloc"]]

    fixed_block = []
    counter_by_block: dict[str, str] = {}
    for l in fixed_rows:
        entry = {
            "name": l["nom_champ"],
            "start": int(l["position_debut"]),
            "end": int(l["position_fin"]),
            "len": int(l["taille"]),
            "type": l["type"] or "A",
        }
        if l["obligatoire"]:
            entry["required"] = l["obligatoire"]
        if l["note"]:
            entry["note"] = l["note"]
        fixed_block.append(entry)
        if l["compteur_de_bloc"]:
            counter_by_block[l["compteur_de_bloc"]] = l["nom_champ"]

    fixed_block.sort(key=lambda f: f["start"])
    for a, b in zip(fixed_block, fixed_block[1:]):
        if a["end"] >= b["start"]:
            raise CsvStandardInvalide(
                f"Chevauchement de positions dans le bloc fixe entre {a['name']!r} "
                f"({a['start']}-{a['end']}) et {b['name']!r} ({b['start']}-{b['end']})."
            )

    blocs: dict[str, list[dict]] = {}
    for l in block_rows:
        blocs.setdefault(l["bloc"], []).append(l)

    repeated_blocks = []
    for nom_bloc, rows in blocs.items():
        if nom_bloc not in counter_by_block:
            raise CsvStandardInvalide(
                f"Le bloc {nom_bloc!r} n'a aucun champ fixe avec 'compteur_de_bloc' = {nom_bloc!r} "
                f"— impossible de savoir combien de fois il se répète."
            )
        rows_sorted = sorted(rows, key=lambda l: int(l["position_debut"]))
        fields = []
        cursor = 1
        for l in rows_sorted:
            start, end = int(l["position_debut"]), int(l["position_fin"])
            if start != cursor:
                raise CsvStandardInvalide(
                    f"Bloc {nom_bloc!r} : trou ou chevauchement de position — "
                    f"attendu de commencer à {cursor}, trouvé {start} pour {l['nom_champ']!r}."
                )
            entry = {
                "name": l["nom_champ"], "start": start, "end": end, "len": int(l["taille"]),
                "type": l["type"] or "A",
            }
            if l["obligatoire"]:
                entry["required"] = l["obligatoire"]
            if l["note"]:
                entry["note"] = l["note"]
            fields.append(entry)
            cursor = end + 1

        repeated_blocks.append({
            "name": nom_bloc, "counter_field": counter_by_block[nom_bloc],
            "block_len": cursor - 1, "fields": fields,
        })

    base_len = fixed_block[-1]["end"] if fixed_block else 0
    formula = f"{base_len}" + "".join(f" + {b['block_len']}*{b['counter_field']}" for b in repeated_blocks)

    return {
        "format": format_nom,
        "fixed_block": fixed_block,
        "repeated_blocks": repeated_blocks,
        "record_length_formula": formula,
    }


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage : python tools/csv_standard_vers_schema.py <csv> <code_version>[,<code_version>...]")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    version_codes = [c.strip() for c in sys.argv[2].split(",") if c.strip()]
    if not csv_path.is_absolute():
        csv_path = ROOT / csv_path

    try:
        contenu = lire_csv_standard(csv_path)
    except CsvStandardInvalide as e:
        print(f"ÉCHEC : {e}")
        sys.exit(1)

    fmt_key = contenu["format"].lower()
    registry_path = ROOT / "config/formats/registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if fmt_key not in registry:
        print(f"ÉCHEC : format {fmt_key!r} inconnu dans registry.json.")
        sys.exit(1)

    version_slice = registry[fmt_key]["version_slice"]
    contenu["version_field"] = {"start": version_slice[0], "end": version_slice[1], "values": version_codes}

    nom_fichier = f"{fmt_key}_{version_codes[0].lower()}.schema.json"
    out_path = ROOT / "config/formats" / nom_fichier
    out_path.write_text(json.dumps(contenu, ensure_ascii=False, indent=2), encoding="utf-8")

    for code in version_codes:
        registry[fmt_key]["variants"][code] = nom_fichier
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Schéma écrit : {out_path.relative_to(ROOT)}")
    print(f"{len(contenu['fixed_block'])} champ(s) fixe(s), {len(contenu['repeated_blocks'])} bloc(s) répété(s) :")
    for b in contenu["repeated_blocks"]:
        print(f"  - {b['name']} : {b['block_len']} car., compteur {b['counter_field']}")
    print(f"Registre mis à jour : {version_codes} -> {nom_fichier}")
    print("Reconnu au prochain lancement de python run.py.")


if __name__ == "__main__":
    main()
