"""Stockage SQLite des enregistrements parsés (RHS groupé / VID-HOSP).

Les tables sont générées dynamiquement à partir du schéma JSON (config/formats/*.schema.json) :
une table principale par format, plus une table enfant par bloc répété, reliée par
clé étrangère + numéro de séquence. Cela évite de dupliquer à la main la liste des
~70 colonnes et garde le schéma JSON comme unique source de vérité.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _col_type(field: dict) -> str:
    return "INTEGER" if field.get("type") == "N" else "TEXT"


def _main_table(schema: dict) -> str:
    return schema["format"].lower()


def _child_table(schema: dict, block_name: str) -> str:
    return f"{_main_table(schema)}_{block_name.lower()}"


def build_create_table_statements(schema: dict) -> list[str]:
    main_table = _main_table(schema)
    cols = [
        "id INTEGER PRIMARY KEY AUTOINCREMENT",
        "source_file TEXT NOT NULL",
        "line_no INTEGER NOT NULL",
    ]
    for f in schema["fixed_block"]:
        cols.append(f"{_quote(f['name'])} {_col_type(f)}")
    cols.append("parse_errors TEXT")

    natural_key = schema.get("natural_key")
    if natural_key:
        # une transmission peut renvoyer le séjour complet (semaines déjà vues dans
        # une transmission précédente) : la clé naturelle + INSERT OR REPLACE fait
        # gagner la dernière transmission traitée, sans compter deux fois la même semaine.
        cols.append(f"UNIQUE({', '.join(_quote(c) for c in natural_key)})")
    else:
        cols.append("UNIQUE(source_file, line_no)")
    stmts = [f"CREATE TABLE IF NOT EXISTS {_quote(main_table)} (\n  " + ",\n  ".join(cols) + "\n)"]

    for block in schema.get("repeated_blocks", []):
        child_table = _child_table(schema, block["name"])
        child_cols = [
            "id INTEGER PRIMARY KEY AUTOINCREMENT",
            f"parent_id INTEGER NOT NULL REFERENCES {_quote(main_table)}(id) ON DELETE CASCADE",
            "seq INTEGER NOT NULL",
        ]
        for f in block["fields"]:
            child_cols.append(f"{_quote(f['name'])} {_col_type(f)}")
        stmts.append(
            f"CREATE TABLE IF NOT EXISTS {_quote(child_table)} (\n  " + ",\n  ".join(child_cols) + "\n)"
        )
    return stmts


def init_db(db_path: str | Path, schemas: list[dict]) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS parse_errors ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " format TEXT NOT NULL,"
        " source_file TEXT NOT NULL,"
        " line_no INTEGER NOT NULL,"
        " message TEXT NOT NULL"
        ")"
    )
    for schema in schemas:
        for stmt in build_create_table_statements(schema):
            conn.execute(stmt)
    conn.commit()
    return conn


def insert_record(
    conn: sqlite3.Connection,
    schema: dict,
    parsed: dict,
    source_file: str,
    line_no: int,
) -> int:
    main_table = _main_table(schema)
    fixed = parsed["fixed"]
    col_names = [f["name"] for f in schema["fixed_block"]]
    col_list = ", ".join(_quote(c) for c in col_names)
    placeholders = ", ".join(["?"] * (len(col_names) + 3))
    errors_json = json.dumps(parsed["errors"], ensure_ascii=False) if parsed["errors"] else None
    verb = "INSERT OR REPLACE" if schema.get("natural_key") else "INSERT"

    cur = conn.execute(
        f'{verb} INTO {_quote(main_table)} (source_file, line_no, {col_list}, parse_errors) '
        f"VALUES ({placeholders})",
        [source_file, line_no, *(fixed.get(c) for c in col_names), errors_json],
    )
    parent_id = cur.lastrowid

    for block in schema.get("repeated_blocks", []):
        child_table = _child_table(schema, block["name"])
        bcol_names = [f["name"] for f in block["fields"]]
        bcol_list = ", ".join(_quote(c) for c in bcol_names)
        bplaceholders = ", ".join(["?"] * (len(bcol_names) + 2))
        for seq, item in enumerate(parsed.get(block["name"], []), start=1):
            conn.execute(
                f'INSERT INTO {_quote(child_table)} (parent_id, seq, {bcol_list}) '
                f"VALUES ({bplaceholders})",
                [parent_id, seq, *(item.get(c) for c in bcol_names)],
            )

    if parsed["errors"]:
        conn.executemany(
            "INSERT INTO parse_errors (format, source_file, line_no, message) VALUES (?, ?, ?, ?)",
            [(schema["format"], source_file, line_no, msg) for msg in parsed["errors"]],
        )

    return parent_id
