#!/usr/bin/env python3
"""Exporte un schéma de parsing (config/formats/*.schema.json) déjà validé
vers le format CSV standardisé (une ligne par champ, colonnes identiques
d'une année à l'autre) — voir input/formats/standard/REGLES.md pour la
convention complète.

Usage :
    python tools/schema_vers_csv.py <schema.json> <sortie.csv>
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COLONNES = [
    "format", "bloc", "nom_champ", "position_debut", "position_fin",
    "taille", "type", "compteur_de_bloc", "obligatoire", "note",
]


def schema_vers_lignes(schema: dict) -> list[dict]:
    fmt = schema["format"]
    lignes = []

    counter_fields = {b["counter_field"] for b in schema.get("repeated_blocks", [])}

    for f in schema.get("fixed_block", []):
        lignes.append({
            "format": fmt,
            "bloc": "",
            "nom_champ": f["name"],
            "position_debut": f["start"],
            "position_fin": f["end"],
            "taille": f["len"],
            "type": f.get("type", "A"),
            "compteur_de_bloc": "",
            "obligatoire": f.get("required", ""),
            "note": f.get("note", ""),
        })

    # deuxième passe : indiquer sur le champ compteur quel bloc il gouverne
    for ligne in lignes:
        if ligne["nom_champ"] in counter_fields:
            bloc = next(b for b in schema["repeated_blocks"] if b["counter_field"] == ligne["nom_champ"])
            ligne["compteur_de_bloc"] = bloc["name"]

    for b in schema.get("repeated_blocks", []):
        for f in b["fields"]:
            lignes.append({
                "format": fmt,
                "bloc": b["name"],
                "nom_champ": f["name"],
                "position_debut": f["start"],
                "position_fin": f["end"],
                "taille": f["len"],
                "type": f.get("type", "A"),
                "compteur_de_bloc": "",
                "obligatoire": f.get("required", ""),
                "note": f.get("note", ""),
            })

    return lignes


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage : python tools/schema_vers_csv.py <schema.json> <sortie.csv>")
        sys.exit(1)

    schema_path = Path(sys.argv[1])
    csv_out = Path(sys.argv[2])

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    lignes = schema_vers_lignes(schema)

    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLONNES)
        writer.writeheader()
        writer.writerows(lignes)

    print(f"Écrit : {csv_out} ({len(lignes)} lignes)")


if __name__ == "__main__":
    main()
