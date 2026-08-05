#!/usr/bin/env python3
"""Point d'entrée unique du projet PMSI-SMR.

Sans installation manuelle : au premier lancement, crée toute l'arborescence
attendue (input/, data/, config/, src/, app/) si elle n'existe pas encore, puis
parse tous les fichiers déposés dans input/rhs/ et input/vdh/ et les charge
dans data/processed/pmsi.db.

Format d'entrée attendu :

    input/
      rhs/      <FINESS>.<AAAA>.<MM>.rhs.*.txt   (RHS groupé — un ou plusieurs fichiers)
      vdh/      <FINESS>.<AAAA>.<MM>.vdh.*.txt   (VID-HOSP — un ou plusieurs fichiers)
      formats/  specs ATIH brutes (xlsx multi-feuilles ATIH, ou CSV déjà extraits)
                — dépose un nouveau xlsx ATIH ici puis lance :
                  python tools/incorporer_format.py input/formats/<fichier>.xlsx
                Si le format est déjà connu, l'outil le confirme et ne fait rien.
                S'il diffère, il pose les questions nécessaires (nom des
                nouveaux champs, code de version...) et met à jour lui-même
                config/formats/registry.json — aucune intervention manuelle
                dans le code n'est nécessaire.

Le dossier (rhs/ ou vdh/) dans lequel un fichier est déposé détermine son
format à traiter — c'est la convention la plus simple et la plus fiable (pas
de dépendance au nom de fichier). Le FINESS de chaque enregistrement est de
toute façon relu dans le contenu de la ligne, jamais dans le nom du fichier.

Usage :
    python run.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.util.paths import project_root  # noqa: E402
from src.parsing.fixed_width import load_schema, parse_file_multi  # noqa: E402
from src.parsing.valorisation import load_from_csv  # noqa: E402
from src.storage.sqlite_store import init_db, insert_record  # noqa: E402
from src.storage.valorisation_store import init_table as init_valorisation_table  # noqa: E402
from src.storage.valorisation_store import insert_rows as insert_valorisation_rows  # noqa: E402
from src.tarifs.gmt import load_from_xlsx as load_tarifs_gmt  # noqa: E402
from src.storage.tarifs_store import init_table as init_tarifs_table  # noqa: E402
from src.storage.tarifs_store import insert_rows as insert_tarifs_rows  # noqa: E402
from src.util.progress import print_progress  # noqa: E402

ROOT = project_root()

DIRS = [
    "input/rhs",
    "input/vdh",
    "input/valorisation",
    "input/tarifs",
    "input/formats",
    "data/processed",
    "data/logs",
    "config/formats",
    "src/parsing",
    "src/storage",
    "src/viz",
    "app",
]

VALORISATION_SCHEMA_PATH = "config/formats/valorisation_sejour.schema.json"
TARIFS_GMT_SCHEMA_PATH = "config/formats/tarifs_gmt.schema.json"

# Dossier d'entrée -> format traité. C'est la seule chose qui détermine le
# format d'un fichier : où il est rangé.
INPUT_DIRS = {
    "input/rhs": "rhs_groupe",
    "input/vdh": "vid_hosp",
}

REGISTRY_PATH = "config/formats/registry.json"


def load_registry() -> dict:
    """Charge config/formats/registry.json : pour chaque format, le schéma
    canonique (le plus récent), la position du code de version dans la ligne,
    et la table code-de-version -> fichier de schéma de PARSING à utiliser.
    Ce fichier est celui que tools/incorporer_format.py met à jour tout seul
    quand un nouveau format ATIH est incorporé — run.py ne fait que le lire."""
    return json.loads((ROOT / REGISTRY_PATH).read_text(encoding="utf-8"))


def ensure_arborescence() -> None:
    for d in DIRS:
        (ROOT / d).mkdir(parents=True, exist_ok=True)


def merge_schemas_for_format(canonical: dict, variants: dict[str, dict]) -> dict:
    """Fusionne le schéma canonique et TOUTES les variantes d'un format en un
    schéma unique qui sert à créer les colonnes de la table et à insérer les
    lignes. Sans cette fusion, un champ ou un bloc introduit par une variante
    mais absent du canonique serait silencieusement ignoré à l'insertion
    (aucune colonne pour le recevoir) — constaté empiriquement avec un bloc
    CSAR nommé différemment du canonique lors d'un test de l'assistant
    d'incorporation. La fusion est par NOM (premier schéma qui définit un nom
    donné l'emporte pour le type/notes ; seule la PRÉSENCE du nom compte pour
    la création de colonne)."""
    merged = dict(canonical)

    fixed_by_name = {f["name"]: f for f in canonical.get("fixed_block", [])}
    for variant in variants.values():
        for f in variant.get("fixed_block", []):
            fixed_by_name.setdefault(f["name"], f)
    merged["fixed_block"] = list(fixed_by_name.values())

    blocks: dict[str, dict] = {}
    for b in canonical.get("repeated_blocks", []):
        blocks[b["name"]] = {**b, "fields": {f["name"]: f for f in b["fields"]}}
    for variant in variants.values():
        for b in variant.get("repeated_blocks", []):
            if b["name"] not in blocks:
                blocks[b["name"]] = {**b, "fields": {f["name"]: f for f in b["fields"]}}
            else:
                for f in b["fields"]:
                    blocks[b["name"]]["fields"].setdefault(f["name"], f)
    merged["repeated_blocks"] = [{**b, "fields": list(b["fields"].values())} for b in blocks.values()]

    return merged


def process_file(
    path: Path,
    fmt: str,
    merged_schemas: dict[str, dict],
    schemas_by_version: dict[str, dict[str, dict]],
    version_slices: dict[str, tuple[int, int]],
    conn,
    log_lines: list[str],
) -> tuple[str, int, int]:
    merged_schema = merged_schemas[fmt]
    version_slice = version_slices[fmt]
    version_registry = schemas_by_version[fmt]

    ok, ko = 0, 0
    for line_no, _raw_line, version, parsed in parse_file_multi(path, version_registry, version_slice):
        if parsed is None:
            ko += 1
            log_lines.append(
                f"[{fmt}] {path.name}:{line_no} — version de format inconnue {version!r}, ligne ignorée"
            )
            continue
        insert_record(conn, merged_schema, parsed, path.name, line_no)
        if parsed["errors"]:
            ko += 1
            for msg in parsed["errors"]:
                log_lines.append(f"[{fmt}] {path.name}:{line_no} (v={version}) — {msg}")
        else:
            ok += 1
    conn.commit()
    return fmt, ok, ko


def main() -> None:
    ensure_arborescence()

    registry = load_registry()
    canonical_schemas = {
        fmt: load_schema(ROOT / "config/formats" / entry["canonical"]) for fmt, entry in registry.items()
    }
    version_slices = {fmt: tuple(entry["version_slice"]) for fmt, entry in registry.items()}
    schemas_by_version = {
        fmt: {v: load_schema(ROOT / "config/formats" / rel) for v, rel in entry["variants"].items()}
        for fmt, entry in registry.items()
    }
    merged_schemas = {
        fmt: merge_schemas_for_format(canonical_schemas[fmt], schemas_by_version[fmt]) for fmt in canonical_schemas
    }

    db_path = ROOT / "data/processed/pmsi.db"
    conn = init_db(db_path, list(merged_schemas.values()))

    log_lines: list[str] = []
    summary = []

    rhs_vdh_files = [
        (input_dir, fmt, path)
        for input_dir, fmt in INPUT_DIRS.items()
        for path in sorted(p for p in (ROOT / input_dir).iterdir() if p.is_file())
    ]
    valorisation_dir = ROOT / "input/valorisation"
    valorisation_files = sorted(
        p for p in valorisation_dir.iterdir() if p.is_file() and p.suffix.lower() == ".csv"
    )
    tarifs_dir = ROOT / "input/tarifs"
    tarifs_files = sorted(
        p for p in tarifs_dir.iterdir() if p.is_file() and p.suffix.lower() == ".xlsx" and not p.name.startswith("~$")
    )
    total_files = len(rhs_vdh_files) + len(valorisation_files) + len(tarifs_files)
    done_files = 0

    for input_dir, fmt, path in rhs_vdh_files:
        fmt_out, ok, ko = process_file(
            path, fmt, merged_schemas, schemas_by_version, version_slices, conn, log_lines
        )
        summary.append((f"{input_dir}/{path.name}", fmt_out, ok, ko))
        done_files += 1
        print_progress(done_files, total_files, "Chargement fichiers", detail=path.name)

    valorisation_schema = json.loads((ROOT / VALORISATION_SCHEMA_PATH).read_text(encoding="utf-8"))
    init_valorisation_table(conn, valorisation_schema)
    for path in valorisation_files:
        # <FINESS>.<AAAA>.<MM>.SMR.VisualValoSejours.csv — l'année de la campagne
        # de transmission fait partie de la clé naturelle (cf. valorisation_sejour.schema.json :
        # la valorisation ATIH est incrémentale par campagne, pas dernier-gagne).
        campagne = int(path.name.split(".")[1])
        try:
            rows = load_from_csv(path, valorisation_schema)
        except ValueError as exc:
            log_lines.append(f"[valorisation_sejour] {exc}")
            summary.append((f"input/valorisation/{path.name}", "valorisation_sejour", 0, 1))
            done_files += 1
            print_progress(done_files, total_files, "Chargement fichiers", detail=path.name)
            continue
        n = insert_valorisation_rows(conn, valorisation_schema, rows, path.name, campagne)
        summary.append((f"input/valorisation/{path.name}", "valorisation_sejour", n, 0))
        done_files += 1
        print_progress(done_files, total_files, "Chargement fichiers", detail=path.name)

    tarifs_schema = json.loads((ROOT / TARIFS_GMT_SCHEMA_PATH).read_text(encoding="utf-8"))
    init_tarifs_table(conn, tarifs_schema)
    for path in tarifs_files:
        try:
            rows = load_tarifs_gmt(path, tarifs_schema)
        except ValueError as exc:
            log_lines.append(f"[tarifs_gmt] {exc}")
            summary.append((f"input/tarifs/{path.name}", "tarifs_gmt", 0, 1))
            done_files += 1
            print_progress(done_files, total_files, "Chargement fichiers", detail=path.name)
            continue
        n = insert_tarifs_rows(conn, tarifs_schema, rows, path.name)
        summary.append((f"input/tarifs/{path.name}", "tarifs_gmt", n, 0))
        done_files += 1
        print_progress(done_files, total_files, "Chargement fichiers", detail=path.name)

    conn.close()

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = ROOT / f"data/logs/parse_{timestamp}.log"
    log_path.write_text("\n".join(log_lines) + ("\n" if log_lines else ""), encoding="utf-8")

    print(f"Base SQLite : {db_path}")
    print(f"{'Fichier':<55} {'Format':<12} {'OK':>6} {'Erreurs':>8}")
    for name, fmt, ok, ko in summary:
        print(f"{name:<55} {fmt:<12} {ok:>6} {ko:>8}")
    print(f"Log détaillé : {log_path} ({len(log_lines)} ligne(s))")


if __name__ == "__main__":
    main()
