"""Stockage SQLite des nomenclatures (diagnostics CIM-10, CM/GM, CSARR, CSAR, CCAM...).

Une table par nomenclature, clé = natural_key du schéma canonique (config/nomenclatures/*.schema.json).
Chargement en INSERT OR REPLACE : en chargeant les fichiers sources dans l'ordre
chronologique (année dans le nom de fichier), la dernière année écrase la précédente
sur les codes en commun — dernier-libellé-gagne, décision utilisateur du 2026-07-29.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def init_nomenclature_table(conn: sqlite3.Connection, schema: dict) -> None:
    table = schema["table"]
    cols = [f"{_quote(c['name'])} TEXT" for c in schema["columns"]]
    cols.append("source_annee INTEGER")
    cols.append("source_file TEXT")
    cols.append(f"UNIQUE({', '.join(_quote(k) for k in schema['natural_key'])})")
    conn.execute(f"CREATE TABLE IF NOT EXISTS {_quote(table)} (\n  " + ",\n  ".join(cols) + "\n)")
    conn.commit()


def upsert_rows(
    conn: sqlite3.Connection,
    schema: dict,
    rows: list[dict],
    source_annee: int,
    source_file: str,
) -> int:
    table = schema["table"]
    col_names = [c["name"] for c in schema["columns"]]
    col_list = ", ".join(_quote(c) for c in col_names)
    placeholders = ", ".join(["?"] * (len(col_names) + 2))
    conn.executemany(
        f"INSERT OR REPLACE INTO {_quote(table)} ({col_list}, source_annee, source_file) "
        f"VALUES ({placeholders})",
        [
            [row.get(c) for c in col_names] + [source_annee, source_file]
            for row in rows
        ],
    )
    conn.commit()
    return len(rows)
