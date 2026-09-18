"""Assemble un schéma de parsing final à partir :
  - du schéma déjà validé le plus proche (existing_schema),
  - du rapport de rapprochement (ce qui est inchangé / nouveau / disparu),
  - des résolutions apportées par l'utilisateur (via l'assistant interactif
    tools/incorporer_format.py) pour chaque point ambigu.

Ce module ne pose aucune question lui-même (pas d'input()) — il ne fait que
construire des structures de données à partir de réponses déjà connues, ce qui
le rend testable indépendamment de l'interaction terminal.
"""
from __future__ import annotations

from typing import Any

from src.formats.spec_reconcile import ReconcileReport, slugify


def guess_type(type_raw: str | None) -> str:
    """Suggestion par défaut à partir de la colonne 'Type de données' du xlsx
    quand elle existe (RHS groupé). N'est qu'une proposition — l'utilisateur
    peut toujours la corriger."""
    if not type_raw:
        return "A"
    t = type_raw.strip().lower()
    if t.startswith("date"):
        return "Date"
    if t.startswith("n") or t.startswith("entier"):
        return "N"
    return "A"


def group_contiguous(fields: list[dict]) -> list[list[dict]]:
    """Regroupe les champs 'nouveaux' dont les positions sont contiguës —
    signe probable qu'ils forment ensemble un seul champ composite (cf. le cas
    code_gme) plutôt que plusieurs champs indépendants. L'utilisateur tranche
    ensuite (fusion ou séparation) pour chaque groupe."""
    if not fields:
        return []
    ordered = sorted(fields, key=lambda f: f["start"])
    groups: list[list[dict]] = [[ordered[0]]]
    for f in ordered[1:]:
        if f["start"] == groups[-1][-1]["end"] + 1:
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


def build_schema(
    existing_schema: dict,
    report: ReconcileReport,
    disparus_resolutions: dict[str, dict],
    nouveaux_champs: list[dict],
    blocks_resolus: list[dict],
    version_codes: list[str],
    source_note: str,
) -> dict:
    """Construit le schéma final.

    disparus_resolutions : {nom_champ_existant: {"action": "supprime"} ou
                             {"action": "deplace", "start":.., "end":..}}
    nouveaux_champs       : [{"name":.., "start":.., "end":.., "type":..}, ...]
                            (un par champ final résolu — un groupe fusionné ne
                            donne qu'une seule entrée)
    blocks_resolus        : liste de blocs déjà entièrement résolus, forme :
                            {"name":.., "counter_field":.., "block_len":..,
                             "fields":[{"name","start","end","len","type"}, ...]}
    """
    inchanges_names = {f["name"] for f in report.fixed_inchanges}

    fixed: list[dict] = []
    for ex in existing_schema.get("fixed_block", []):
        name = ex["name"]
        if name in inchanges_names:
            fixed.append(dict(ex))
            continue
        resolution = disparus_resolutions.get(name)
        if resolution is None:
            continue  # ni inchangé, ni dans les disparus résolus : absent du nouveau format
        if resolution["action"] == "supprime":
            continue
        if resolution["action"] == "deplace":
            moved = dict(ex)
            moved["start"] = resolution["start"]
            moved["end"] = resolution["end"]
            moved["len"] = resolution["end"] - resolution["start"] + 1
            fixed.append(moved)

    for nf in nouveaux_champs:
        fixed.append({
            "name": nf["name"], "start": nf["start"], "end": nf["end"],
            "len": nf["end"] - nf["start"] + 1, "type": nf["type"],
        })

    fixed.sort(key=lambda f: f["start"])

    base_len = fixed[-1]["end"] if fixed else 0
    formula_terms = " + ".join(f"{b['block_len']}*{b['counter_field']}" for b in blocks_resolus)
    formula = f"{base_len}" + (f" + {formula_terms}" if formula_terms else "")

    version_field = dict(existing_schema.get("version_field", {}))
    version_field["values"] = version_codes

    schema: dict[str, Any] = {
        "format": existing_schema["format"],
        "spec_source": source_note,
        "record_length_formula": formula,
        "natural_key": existing_schema.get("natural_key"),
        "version_field": version_field,
        "fixed_block": fixed,
        "repeated_blocks": [
            {
                "name": b["name"], "counter_field": b["counter_field"], "block_len": b["block_len"],
                "fields": [
                    {"name": f["name"], "start": f["start"], "end": f["end"], "len": f["len"], "type": f["type"]}
                    for f in b["fields"]
                ],
            }
            for b in blocks_resolus
        ],
        "validation_notes": [
            f"Schéma construit par l'assistant interactif ({source_note}). "
            f"Aucune donnée réelle avec ce code de version n'a été vérifiée automatiquement — "
            f"à confirmer via les erreurs de longueur d'enregistrement au prochain traitement "
            f"de fichiers réels (python run.py)."
        ],
    }
    if "required_codes" in existing_schema:
        schema["required_codes"] = existing_schema["required_codes"]

    return schema
