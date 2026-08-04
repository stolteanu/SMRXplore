"""Stockage SQLite de la restitution ATIH VISUAL VALO Séjours (valorisation_sejour).

Contrairement à sqlite_store.py (RHS/VID-HOSP, colonnes décrites par
fixed_block/repeated_blocks), ce format est une table plate à une seule
liste de colonnes (schema['columns']) — pas de bloc répété.

PAS de dernier-gagne ici (contrairement à RHS/VID-HOSP) : la valorisation
ATIH est incrémentale par campagne (cf. note_natural_key du schéma), donc
chaque campagne (année civile de la transmission, PAS une colonne du CSV —
ajoutée ici par le loader) garde sa propre ligne. natural_key inclut
"campagne" et INSERT OR REPLACE ne fait donc que dédupliquer un rechargement
du MÊME fichier, jamais écraser une campagne différente par une autre."""
from __future__ import annotations

import sqlite3


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table(schema: dict) -> str:
    return schema["format"]


def init_table(conn: sqlite3.Connection, schema: dict) -> None:
    table = _table(schema)
    cols = ["id INTEGER PRIMARY KEY AUTOINCREMENT", "source_file TEXT NOT NULL", "campagne INTEGER NOT NULL"]
    for c in schema["columns"]:
        cols.append(f"{_quote(c['name'])} {c['type']}")
    cols.append(f"UNIQUE({', '.join(_quote(k) for k in schema['natural_key'])})")
    conn.execute(f"CREATE TABLE IF NOT EXISTS {_quote(table)} (\n  " + ",\n  ".join(cols) + "\n)")
    conn.commit()


def insert_rows(
    conn: sqlite3.Connection, schema: dict, rows: list[dict], source_file: str, campagne: int
) -> int:
    table = _table(schema)
    col_names = [c["name"] for c in schema["columns"]]
    col_list = ", ".join(_quote(c) for c in col_names)
    placeholders = ", ".join(["?"] * (len(col_names) + 2))
    conn.executemany(
        f"INSERT OR REPLACE INTO {_quote(table)} (source_file, campagne, {col_list}) "
        f"VALUES ({placeholders})",
        [[source_file, campagne] + [row.get(c) for c in col_names] for row in rows],
    )
    conn.commit()
    return len(rows)
