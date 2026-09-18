#!/usr/bin/env python3
"""Convertit un xlsx ATIH (classeur multi-feuilles, ex. formats_smr_AAAA.xlsx)
déposé dans input/formats/ en rapport de rapprochement avec les schémas de
parsing déjà validés (config/formats/*.schema.json — canonique + variantes
historiques connues).

Ne modifie JAMAIS les schémas en production : produit uniquement
  - une copie CSV lisible de chaque feuille extraite, nommée
    RHS_groupe_<année>.csv / VDH_<année>.csv (input/formats/extraits/) —
    pour repérer visuellement une éventuelle erreur de transcription en la
    comparant au xlsx d'origine.
  - un rapport en français par format (input/formats/rapports/).

Usage :
    python tools/xlsx_vers_schema.py <chemin_vers_xlsx>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    # certains terminaux Windows utilisent un encodage (cp1252) qui ne supporte
    # pas les caractères ✅/⚠ utilisés dans les rapports — on force l'UTF-8 en
    # sortie pour que ça ne plante jamais, quel que soit le terminal.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.formats.xlsx_extract import extraire_feuille_vers_csv, FeuilleIntrouvable  # noqa: E402
from src.formats.spec_reconcile import parse_raw_csv, build_draft, reconcile, render_report, MiseEnPageInattendue  # noqa: E402

# feuille du classeur ATIH -> (nom du format interne, préfixe de fichier, liste des
# schémas déjà validés à essayer — canonique en premier, puis variantes historiques)
FEUILLES = {
    "RHS groupé": (
        "rhs_groupe", "RHS_groupe",
        ["config/formats/rhs_groupe.schema.json", "config/formats/rhs_groupe_m1c.schema.json"],
    ),
    "VID-HOSP": (
        "vid_hosp", "VDH",
        ["config/formats/vid_hosp.schema.json", "config/formats/vid_hosp_v015.schema.json", "config/formats/vid_hosp_v014.schema.json"],
    ),
}


def _score(report) -> int:
    """Plus petit = meilleure correspondance."""
    return (
        len(report.fixed_nouveaux) + len(report.fixed_disparus)
        + len(report.blocks_nouveaux) + (1 if report.anomalie_nb_blocs else 0)
    )


def _annee_depuis_nom(xlsx_path: Path) -> str:
    m = re.search(r"(20\d{2})", xlsx_path.stem)
    return m.group(1) if m else "annee_inconnue"


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage : python tools/xlsx_vers_schema.py <chemin_vers_xlsx>")
        sys.exit(1)

    xlsx_path = Path(sys.argv[1])
    if not xlsx_path.is_absolute():
        xlsx_path = ROOT / xlsx_path

    annee = _annee_depuis_nom(xlsx_path)
    extraits_dir = ROOT / "input/formats/extraits"
    rapports_dir = ROOT / "input/formats/rapports"

    for sheet_name, (fmt, prefixe, schema_candidates) in FEUILLES.items():
        print(f"\n--- {sheet_name} ({annee}) ---")
        csv_out = extraits_dir / f"{prefixe}_{annee}.csv"
        try:
            extraire_feuille_vers_csv(xlsx_path, sheet_name, csv_out)
        except FeuilleIntrouvable as e:
            print(f"ÉCHEC (extraction) : {e}")
            continue
        print(f"Extrait (à comparer visuellement au xlsx si besoin) : {csv_out.relative_to(ROOT)}")

        try:
            raw_rows = parse_raw_csv(csv_out)
            draft = build_draft(raw_rows)
        except MiseEnPageInattendue as e:
            print(f"ÉCHEC (lecture) : {e}")
            continue

        candidats = []
        for schema_rel in schema_candidates:
            schema_path = ROOT / schema_rel
            if not schema_path.exists():
                continue
            existing_schema = json.loads(schema_path.read_text(encoding="utf-8"))
            report = reconcile(draft, existing_schema)
            candidats.append((schema_rel, existing_schema, report))

        if not candidats:
            print("ÉCHEC : aucun schéma de référence trouvé pour ce format.")
            continue

        schema_rel, existing_schema, report = min(candidats, key=lambda c: _score(c[2]))
        version_note = existing_schema.get("version_field", {}).get("values", ["?"])
        print(f"Meilleure correspondance : {schema_rel} (version(s) {version_note})")

        text = render_report(report)
        print(text)

        rapport_path = rapports_dir / f"{prefixe}_{annee}.txt"
        rapport_path.parent.mkdir(parents=True, exist_ok=True)
        rapport_path.write_text(f"Comparé à : {schema_rel} (version(s) {version_note})\n\n{text}", encoding="utf-8")
        print(f"Rapport enregistré : {rapport_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
