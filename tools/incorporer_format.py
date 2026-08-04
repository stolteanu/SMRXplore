#!/usr/bin/env python3
"""Assistant interactif : incorpore un nouveau format ATIH (xlsx) dans le
projet, tout seul, sans intervention extérieure.

Contrairement à tools/xlsx_vers_schema.py (qui ne fait que RAPPORTER les
différences), cet outil pose les questions nécessaires pour les résoudre et
écrit lui-même :
  - un nouveau fichier config/formats/<format>_<version>.schema.json
  - la mise à jour de config/formats/registry.json (pour que run.py le
    reconnaisse dès le prochain lancement)

S'il ne reste plus rien de nouveau à intégrer (le xlsx correspond déjà
exactement à un format connu), l'outil le dit et s'arrête sans rien demander.

Usage :
    python tools/incorporer_format.py <chemin_vers_xlsx>
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    # certains terminaux Windows utilisent un encodage (cp1252) qui ne supporte
    # pas les caractères ✅/⚠ utilisés dans les messages — on force l'UTF-8 en
    # sortie pour que ça ne plante jamais, quel que soit le terminal.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.formats.xlsx_extract import extraire_feuille_vers_csv, FeuilleIntrouvable  # noqa: E402
from src.formats.spec_reconcile import parse_raw_csv, build_draft, reconcile, slugify, MiseEnPageInattendue  # noqa: E402
from src.formats.schema_builder import guess_type, group_contiguous, build_schema  # noqa: E402

FEUILLES = {
    "RHS groupé": ("rhs_groupe", "RHS_groupe"),
    "VID-HOSP": ("vid_hosp", "VDH"),
}

REGISTRY_PATH = ROOT / "config/formats/registry.json"


def _annee_depuis_nom(xlsx_path: Path) -> str:
    m = re.search(r"(20\d{2})", xlsx_path.stem)
    return m.group(1) if m else "annee_inconnue"


def _score(report) -> int:
    return (
        len(report.fixed_nouveaux) + len(report.fixed_disparus)
        + len(report.blocks_nouveaux) + (1 if report.anomalie_nb_blocs else 0)
    )


def ask(question: str, default: str | None = None, ask_fn=input) -> str:
    suffix = f" [{default}]" if default else ""
    reponse = ask_fn(f"{question}{suffix} : ").strip()
    return reponse if reponse else (default or "")


def ask_oui_non(question: str, defaut_oui: bool, ask_fn=input) -> bool:
    defaut = "o" if defaut_oui else "n"
    reponse = ask(question + " (o/n)", defaut, ask_fn=ask_fn).strip().lower()
    return reponse.startswith("o")


TYPES_VALIDES = {"a": "A", "n": "N", "date": "Date"}


def ask_type(question: str, defaut: str, ask_fn=input) -> str:
    """Redemande tant que la réponse n'est pas A/N/Date (insensible à la casse) —
    un type non reconnu serait sinon silencieusement traité comme du texte brut
    par le parseur (pas de conversion date/nombre), sans aucun avertissement."""
    while True:
        reponse = ask(question, defaut, ask_fn=ask_fn).strip().lower()
        if reponse in TYPES_VALIDES:
            return TYPES_VALIDES[reponse]
        print(f"  -> type non reconnu {reponse!r}, réponds A, N ou Date.")


def resoudre_disparus_et_nouveaux(report, ask_fn=input) -> tuple[dict[str, dict], list[dict]]:
    """Traite ensemble les champs 'disparus' et les lignes de champs 'nouveaux' :
    un champ qui a simplement changé de position apparaît sinon dans LES DEUX
    listes indépendamment (l'ancienne position en 'disparu', la nouvelle en
    'nouveau'), ce qui, si on les résout séparément, crée un champ EN DOUBLE à
    la même position (constaté empiriquement). Ici, on demande explicitement
    quelle(s) ligne(s) nouvelle(s) correspond(ent) à chaque champ disparu —
    une fois réclamée(s), elle(s) ne sont plus proposées comme champ vraiment
    nouveau ensuite. On réclame ligne par ligne (pas un groupe entier d'un
    coup) car plusieurs champs disparus distincts peuvent se retrouver
    accolés dans le nouveau fichier (constaté : n4_nb_ccam + 4 champs suivants
    tous décalés ensemble par l'insertion du bloc CSAR en 2025)."""
    rows = sorted(report.fixed_nouveaux, key=lambda f: f["start"])
    disponibles = list(range(len(rows)))  # index des lignes pas encore réclamées
    disparus_resolutions: dict[str, dict] = {}

    for d in report.fixed_disparus:
        taille_attendue = d["end"] - d["start"] + 1
        print(f"\nLe champ connu {d['name']!r} (attendu {d['start']}-{d['end']}, {taille_attendue} car.) est introuvable tel quel.")
        if disponibles:
            print("  A-t-il simplement changé de position ? Choisis la/les ligne(s) qui lui correspondent :")
            print("  0. Non — ce champ a disparu")
            for i in disponibles:
                f = rows[i]
                print(f"  {i + 1}. positions {f['start']}-{f['end']} ({f['len']} car.) — {f['label']}")
            while True:
                choix = ask(
                    "  Numéro(s) (virgule si le champ est réparti sur plusieurs lignes)", "0", ask_fn=ask_fn
                ).strip()
                if choix == "0":
                    picked: list[int] = []
                    break
                try:
                    picked = [int(c.strip()) - 1 for c in choix.split(",") if c.strip()]
                except ValueError:
                    picked = []
                if picked and all(p in disponibles for p in picked):
                    break
                print("  -> réponds 0, ou un/des numéro(s) affichés séparés par une virgule.")
        else:
            picked = []

        if not picked:
            disparus_resolutions[d["name"]] = {"action": "supprime"}
        else:
            picked_rows = sorted((rows[p] for p in picked), key=lambda f: f["start"])
            disparus_resolutions[d["name"]] = {
                "action": "deplace", "start": picked_rows[0]["start"], "end": picked_rows[-1]["end"],
            }
            for p in picked:
                disponibles.remove(p)

    groupes = group_contiguous([rows[i] for i in disponibles])
    nouveaux_champs: list[dict] = []
    for g in groupes:
        print(f"\nChamp(s) vraiment nouveau(x), positions {g[0]['start']}-{g[-1]['end']} :")
        for f in g:
            print(f"   - ligne {f['row']} : {f['start']}-{f['end']} ({f['len']} car.) — {f['label']}")
        if len(g) > 1:
            fusionner = ask_oui_non(
                "Fusionner ces lignes en un seul champ atomique (plutôt que les garder séparées) ?",
                True, ask_fn,
            )
        else:
            fusionner = True

        if fusionner:
            defaut_nom = slugify(g[0]["label"])
            nom = ask("Nom du champ (identifiant)", defaut_nom, ask_fn)
            type_ = ask_type("Type [A/N/Date]", guess_type(g[0].get("type_raw")), ask_fn)
            nouveaux_champs.append({"name": nom, "start": g[0]["start"], "end": g[-1]["end"], "type": type_})
        else:
            for f in g:
                defaut_nom = slugify(f["label"])
                nom = ask(f"Nom du champ pour {f['start']}-{f['end']}", defaut_nom, ask_fn)
                type_ = ask_type("Type [A/N/Date]", guess_type(f.get("type_raw")), ask_fn)
                nouveaux_champs.append({"name": nom, "start": f["start"], "end": f["end"], "type": type_})

    return disparus_resolutions, nouveaux_champs


def resoudre_blocks(report, existing_schema, noms_champs_valides: set[str], ask_fn=input) -> list[dict]:
    resolus: list[dict] = []

    for bi in report.blocks_inchanges:
        existing_block = next(b for b in existing_schema.get("repeated_blocks", []) if b["name"] == bi["name"])
        resolus.append(dict(existing_block))

    for bn in report.blocks_nouveaux:
        print(f"\nBloc répété nouveau/modifié — déclencheur {bn['trigger_label']!r}, longueur {bn['block_len']} :")
        for i, f in enumerate(bn["fields"], start=1):
            print(f"   {i}. {f['label']} ({f['len']} car.)")
        nom_bloc = ask("Nom de ce bloc (identifiant court, ex. DMT/CSARR)", slugify(bn["trigger_label"]).upper(), ask_fn)
        champs_finaux = []
        offset = 1
        for f in bn["fields"]:
            defaut_nom = slugify(f["label"])
            nom = ask(f"  Nom du champ ({f['label']}, {f['len']} car.)", defaut_nom, ask_fn)
            type_ = ask_type("  Type [A/N/Date]", guess_type(f.get("type_raw")), ask_fn)
            champs_finaux.append({"name": nom, "start": offset, "end": offset + f["len"] - 1, "len": f["len"], "type": type_})
            offset += f["len"]

        print(f"  Champs déjà connus pouvant compter les répétitions : {sorted(noms_champs_valides)}")
        while True:
            counter_field = ask("  Nom du champ qui compte les répétitions de ce bloc", ask_fn=ask_fn).strip()
            if counter_field in noms_champs_valides:
                break
            print(f"  -> {counter_field!r} n'est pas un champ connu/résolu — choisis-en un dans la liste ci-dessus.")

        resolus.append({
            "name": nom_bloc, "counter_field": counter_field, "block_len": bn["block_len"], "fields": champs_finaux,
        })

    return resolus


def incorporer_format(xlsx_path: Path, ask_fn=input) -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    annee = _annee_depuis_nom(xlsx_path)
    extraits_dir = ROOT / "input/formats/extraits"

    for sheet_name, (fmt, prefixe) in FEUILLES.items():
        print(f"\n=== {sheet_name} ({annee}) ===")
        csv_out = extraits_dir / f"{prefixe}_{annee}.csv"
        try:
            extraire_feuille_vers_csv(xlsx_path, sheet_name, csv_out)
        except FeuilleIntrouvable as e:
            print(f"ÉCHEC (extraction) : {e}")
            continue

        try:
            raw_rows = parse_raw_csv(csv_out)
            draft = build_draft(raw_rows)
        except MiseEnPageInattendue as e:
            print(f"ÉCHEC (lecture) : {e}")
            continue

        entry = registry[fmt]
        candidats = []
        for version_code, rel in entry["variants"].items():
            schema_path = ROOT / "config/formats" / rel
            if not schema_path.exists():
                continue
            existing_schema = json.loads(schema_path.read_text(encoding="utf-8"))
            report = reconcile(draft, existing_schema)
            candidats.append((version_code, rel, existing_schema, report))

        version_code, rel, existing_schema, report = min(candidats, key=lambda c: _score(c[3]))

        if report.tout_connu:
            print(f"✅ Rien de nouveau — ce format correspond déjà à {rel} (version {version_code}). Rien à faire.")
            continue

        print(f"Ce format diffère de tout ce qui est connu (le plus proche : {rel}, version {version_code}).")
        print("Quelques questions pour l'incorporer :\n")

        nouveaux_codes = ask_fn(
            f"Quel(s) code(s) de version ce fichier décrit-il pour {fmt} (séparés par une virgule si plusieurs) : "
        ).strip()
        version_codes = [c.strip() for c in nouveaux_codes.split(",") if c.strip()]
        if not version_codes:
            print("Aucun code de version fourni — abandon pour ce format.")
            continue

        disparus_resolutions, nouveaux_champs = resoudre_disparus_et_nouveaux(report, ask_fn)

        noms_valides = {f["name"] for f in report.fixed_inchanges}
        noms_valides |= {r["name"] for r in nouveaux_champs}
        for nom_champ, resolution in disparus_resolutions.items():
            if resolution["action"] == "deplace":
                noms_valides.add(nom_champ)

        blocks_resolus = resoudre_blocks(report, existing_schema, noms_valides, ask_fn)

        source_note = (
            f"Assistant interactif tools/incorporer_format.py, {dt.date.today().isoformat()}, "
            f"à partir de {xlsx_path.name} (base de comparaison : {rel})"
        )
        nouveau_schema = build_schema(
            existing_schema, report, disparus_resolutions, nouveaux_champs, blocks_resolus, version_codes, source_note,
        )

        nom_fichier = f"{fmt}_{version_codes[0].lower()}.schema.json"
        out_path = ROOT / "config/formats" / nom_fichier
        out_path.write_text(json.dumps(nouveau_schema, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSchéma écrit : {out_path.relative_to(ROOT)}")

        for code in version_codes:
            registry[fmt]["variants"][code] = nom_fichier
        REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Registre mis à jour ({REGISTRY_PATH.relative_to(ROOT)}) : {version_codes} -> {nom_fichier}")
        print("Ce format sera reconnu au prochain lancement de python run.py.")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage : python tools/incorporer_format.py <chemin_vers_xlsx>")
        sys.exit(1)
    xlsx_path = Path(sys.argv[1])
    if not xlsx_path.is_absolute():
        xlsx_path = ROOT / xlsx_path
    incorporer_format(xlsx_path)


if __name__ == "__main__":
    main()
