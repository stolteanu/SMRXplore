#!/usr/bin/env python3
"""Charge les nomenclatures (diagnostics CIM-10, et futures CM/GM, CSARR, CSAR, CCAM)
dans data/processed/pmsi.db.

Convention : un sous-dossier par nomenclature sous input/nomenclatures/ (ex.
diagnostics/), un fichier par année, nommé avec l'année dedans (ex.
cim10_2026.zip). Les fichiers sont chargés dans l'ordre chronologique de
l'année trouvée dans leur nom ; INSERT OR REPLACE fait gagner le libellé de
la dernière année sur les codes en commun (dernier-libellé-gagne, décision
utilisateur du 2026-07-29).

Usage :
    python tools/charger_nomenclatures.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.nomenclatures import (  # noqa: E402
    actes_specialises,
    ccam,
    cim10,
    cim10_claml,
    csar,
    csar_intervenants,
    csar_ponderation,
    csarr,
    csarr_intervenants,
    gme,
    gme_erreurs,
    ponderation,
)
from src.storage.nomenclature_store import init_nomenclature_table, upsert_rows  # noqa: E402
from src.util.progress import print_progress  # noqa: E402

REGISTRY_PATH = ROOT / "config/nomenclatures/registry.json"

LOADERS = {
    "cim10": cim10.load_from_zip,
    "cim10_claml": cim10_claml.load_from_xml,
    "ccam_flat": ccam.load_flat_from_xlsx,
    "ccam_hierarchie": ccam.load_hierarchie_from_xlsx,
    "csarr_flat": csarr.load_flat_from_xlsx,
    "csarr_hierarchie": csarr.load_hierarchie_from_xlsx,
    "csar_flat": csar.load_flat_from_xlsx,
    "csar_hierarchie": csar.load_hierarchie_from_xlsx,
    "csar_transcodage": csar.load_transcodage_from_xlsx,
    "csar_intervenants": csar_intervenants.load_from_csv,
    "csar_transcodage_detail": csar_ponderation.load_transcodage_detail_from_xlsx,
    "csar_ponderation_temps": csar_ponderation.load_ponderation_temps_from_xlsx,
    "csar_majoration_lieu": csar_ponderation.load_majoration_lieu_from_xlsx,
    "csarr_intervenants": csarr_intervenants.load_from_csv,
    "gme": gme.load_from_xlsx,
    "gme_erreurs": gme_erreurs.load_erreurs_from_txt,
    "gme_erreurs_actes_concernes": gme_erreurs.load_actes_concernes_from_txt,
    "ponderation_actes": ponderation.load_actes_from_xlsx,
    "ponderation_modulateurs": ponderation.load_modulateurs_from_xlsx,
    "actes_specialises": actes_specialises.load_from_xlsx,
}

YEAR_RE = re.compile(r"(20\d{2})")


def year_of(path: Path) -> int:
    m = YEAR_RE.search(path.stem)
    if not m:
        raise ValueError(f"Pas d'année (20xx) trouvée dans le nom de fichier : {path.name}")
    return int(m.group(1))


def main() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    db_path = ROOT / "data/processed/pmsi.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)

    total = len(registry)
    for i, (nom, entry) in enumerate(registry.items(), start=1):
        schema = json.loads((ROOT / "config/nomenclatures" / entry["schema"]).read_text(encoding="utf-8"))
        init_nomenclature_table(conn, schema)

        loader = LOADERS[entry["loader"]]
        input_dir = ROOT / entry["input_dir"]
        files = sorted(
            (
                p
                for p in input_dir.glob(entry.get("file_glob", "*"))
                if p.is_file() and not p.name.startswith("~$")
            ),
            key=year_of,
        )
        for path in files:
            annee = year_of(path)
            rows = loader(path)
            n = upsert_rows(conn, schema, rows, source_annee=annee, source_file=path.name)
            print(f"\n{nom:<15} {path.name:<30} annee={annee:<6} {n:>6} lignes")
        print_progress(i, total, "Nomenclatures", detail=nom)

    conn.close()
    print(f"Base SQLite : {db_path}")


if __name__ == "__main__":
    main()
