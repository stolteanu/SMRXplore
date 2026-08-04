"""Stockage SQLite de la grille tarifaire GMT (tarifs_gmt).

Même patron que valorisation_store.py : table plate typée depuis
schema['columns'], PAS de dernier-gagne — chaque version tarifaire (par
feuille/GMT/GME/date_debut, cf. natural_key du schéma) garde sa propre ligne,
INSERT OR REPLACE ne fait donc que dédupliquer un rechargement du même
fichier."""
from __future__ import annotations

import sqlite3


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def init_table(conn: sqlite3.Connection, schema: dict) -> None:
    table = schema["format"]
    cols = ["id INTEGER PRIMARY KEY AUTOINCREMENT", "source_file TEXT NOT NULL"]
    for c in schema["columns"]:
        cols.append(f"{_quote(c['name'])} {c['type']}")
    cols.append(f"UNIQUE({', '.join(_quote(k) for k in schema['natural_key'])})")
    conn.execute(f"CREATE TABLE IF NOT EXISTS {_quote(table)} (\n  " + ",\n  ".join(cols) + "\n)")
    conn.commit()


def insert_rows(conn: sqlite3.Connection, schema: dict, rows: list[dict], source_file: str) -> int:
    table = schema["format"]
    col_names = [c["name"] for c in schema["columns"]]
    col_list = ", ".join(_quote(c) for c in col_names)
    placeholders = ", ".join(["?"] * (len(col_names) + 1))
    conn.executemany(
        f"INSERT OR REPLACE INTO {_quote(table)} (source_file, {col_list}) VALUES ({placeholders})",
        [[source_file] + [row.get(c) for c in col_names] for row in rows],
    )
    conn.commit()
    return len(rows)
