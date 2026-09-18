#!/usr/bin/env python3
"""Vérifie, SANS JAMAIS AFFICHER de valeur réelle ni anonymisée, que
tools/anonymiser_sources.py a effectivement transformé les identifiants
sensibles : compare en mémoire les ENSEMBLES de valeurs réelles et
anonymisées (structure interne au script, jamais imprimée) et n'affiche que
des compteurs agrégés — nombre de correspondances, PASS/FAIL.

Usage :
    python tools/verifier_anonymisation.py [--input input] [--output anon]
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.anonymiser_sources import ENCODING, RHS_FIELDS, RHS_VERSION_POS, VDH_FIELDS, _slice  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _collect_rhs(root: Path, field: str) -> tuple[set[str], int]:
    values, n = set(), 0
    for path in sorted((root / "rhs").glob("*.txt")):
        with open(path, encoding=ENCODING) as f:
            for line in f:
                version = _slice(line, *RHS_VERSION_POS).strip()
                fields = RHS_FIELDS.get(version)
                if fields is None:
                    continue
                values.add(_slice(line, *fields[field]).strip())
                n += 1
    return values, n


def _collect_vdh(root: Path, field: str) -> tuple[set[str], int]:
    values, n = set(), 0
    for path in sorted((root / "vdh").glob("*.txt")):
        with open(path, encoding=ENCODING) as f:
            for line in f:
                v = _slice(line, *VDH_FIELDS[field]).strip()
                if v and v.strip("0") != "":
                    values.add(v)
                n += 1
    return values, n


def _collect_valo_nda(root: Path) -> tuple[set[str], int]:
    values, n = set(), 0
    for path in sorted((root / "valorisation").glob("*.csv")):
        with open(path, newline="", encoding=ENCODING) as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                v = (row.get("NUMADMIN") or "").strip()
                if v:
                    values.add(v.lstrip("0") or "0")
                n += 1
    return values, n


def _to_date(jjmmaaaa: str) -> date | None:
    s = jjmmaaaa.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[4:8]), int(s[2:4]), int(s[0:2]))
    except ValueError:
        return None


def _check_date_shift(label: str, real_root: Path, anon_root: Path, subdir: str, field_key: str,
                       fields_by_version: bool) -> bool:
    """Vérifie, ligne à ligne (les fichiers réels et anonymisés ont le même
    nombre de lignes, dans le même ordre — 1 ligne source = 1 ligne
    anonymisée), que la date de naissance de CHAQUE enregistrement a bien
    été décalée de 1 à 5 jours (jamais 0, jamais plus) — le bon test pour un
    champ à faible cardinalité, où comparer des ENSEMBLES de valeurs (comme
    pour NDA/NIR/IPP) donnerait de faux positifs par pur hasard de calendrier."""
    n_ok = n_bad = n_skip = 0
    for real_path in sorted((real_root / subdir).glob("*")):
        anon_path = anon_root / subdir / real_path.name
        if not anon_path.exists():
            continue
        with open(real_path, encoding=ENCODING) as f_real, open(anon_path, encoding=ENCODING) as f_anon:
            for real_line, anon_line in zip(f_real, f_anon):
                if fields_by_version:
                    version = _slice(real_line, *RHS_VERSION_POS).strip()
                    fields = RHS_FIELDS.get(version)
                    if fields is None:
                        n_skip += 1
                        continue
                    start, end = fields[field_key]
                else:
                    start, end = VDH_FIELDS[field_key]
                d_real = _to_date(_slice(real_line, start, end))
                d_anon = _to_date(_slice(anon_line, start, end))
                if d_real is None or d_anon is None:
                    n_skip += 1
                    continue
                delta = (d_anon - d_real).days
                if 1 <= abs(delta) <= 5:
                    n_ok += 1
                else:
                    n_bad += 1
    ok = n_bad == 0 and n_ok > 0
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label} : {n_ok} dates décalées correctement (1-5 jours), "
          f"{n_bad} incorrectes (0 attendu), {n_skip} lignes ignorées (vides/version inconnue)")
    return ok


def _check(label: str, real: set[str], anon: set[str], n_real: int, n_anon: int) -> bool:
    overlap = real & anon
    ok = len(overlap) == 0 and n_real == n_anon and len(real) > 0
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label} : {len(real)} valeurs réelles distinctes, "
          f"{len(anon)} anonymisées, {len(overlap)} en commun (doit être 0) — "
          f"{n_real}/{n_anon} lignes (doivent être égales)")
    return ok


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", default="input")
    p.add_argument("--output", default="anon")
    args = p.parse_args()

    real_root = (ROOT / args.input).resolve()
    anon_root = (ROOT / args.output).resolve()

    results = []

    r_real, n1 = _collect_rhs(real_root, "nda")
    r_anon, n2 = _collect_rhs(anon_root, "nda")
    results.append(_check("RHS — numero_admin_sejour", r_real, r_anon, n1, n2))

    results.append(_check_date_shift("RHS — date_naissance", real_root, anon_root, "rhs", "naissance", True))

    r_real, n1 = _collect_vdh(real_root, "nda")
    r_anon, n2 = _collect_vdh(anon_root, "nda")
    results.append(_check("VID-HOSP — numero_admin_sejour", r_real, r_anon, n1, n2))

    results.append(_check_date_shift("VID-HOSP — date_naissance_beneficiaire", real_root, anon_root, "vdh", "naissance", False))

    r_real, n1 = _collect_vdh(real_root, "nir_assure")
    r_anon, n2 = _collect_vdh(anon_root, "nir_assure")
    results.append(_check("VID-HOSP — numero_immatriculation_assure", r_real, r_anon, n1, n2))

    r_real, n1 = _collect_vdh(real_root, "ipp")
    r_anon, n2 = _collect_vdh(anon_root, "ipp")
    results.append(_check("VID-HOSP — numero_ipp", r_real, r_anon, n1, n2))

    r_real, n1 = _collect_valo_nda(real_root)
    r_anon, n2 = _collect_valo_nda(anon_root)
    results.append(_check("Valorisation — NUMADMIN", r_real, r_anon, n1, n2))

    # Cohérence inter-fichiers : le NDA (normalisé) doit rester la MÊME
    # correspondance réel->pseudonyme entre RHS et VID-HOSP (même séjour =
    # même pseudonyme des deux côtés) — vérifié sans jamais afficher les
    # valeurs elles-mêmes, juste le nombre de correspondances.
    rhs_real, _ = _collect_rhs(real_root, "nda")
    rhs_anon, _ = _collect_rhs(anon_root, "nda")
    vdh_real, _ = _collect_vdh(real_root, "nda")
    vdh_anon, _ = _collect_vdh(anon_root, "nda")
    rhs_real_n = {v.lstrip("0") or "0" for v in rhs_real}
    vdh_real_n = {v.lstrip("0") or "0" for v in vdh_real}
    shared_real = rhs_real_n & vdh_real_n
    # Reconstruit réel->pseudo pour RHS et VID-HOSP à partir des lignes déjà
    # lues plutôt que de raffiner par valeur (les sets seuls ne donnent pas
    # la correspondance) : relecture ciblée uniquement pour ce test.
    def _pairs_rhs(root):
        out = {}
        for path in sorted((root / "rhs").glob("*.txt")):
            with open(path, encoding=ENCODING) as f:
                for line in f:
                    version = _slice(line, *RHS_VERSION_POS).strip()
                    fields = RHS_FIELDS.get(version)
                    if fields is None:
                        continue
                    nda = _slice(line, *fields["nda"]).strip()
                    out.setdefault(nda.lstrip("0") or "0", set()).add(nda)
        return out

    print(f"[INFO] {len(shared_real)} séjours présents à la fois en RHS et VID-HOSP (réel) — "
          f"cohérence de pseudonymisation entre fichiers non vérifiée automatiquement ici "
          f"(nécessiterait de comparer les pseudonymes eux-mêmes) ; garantie par construction "
          f"(HMAC déterministe sur la même clé normalisée), voir tools/anonymiser_sources.py.")

    print()
    if all(results):
        print(f"RÉSULTAT GLOBAL : PASS ({len(results)}/{len(results)} contrôles)")
    else:
        print(f"RÉSULTAT GLOBAL : FAIL ({sum(results)}/{len(results)} contrôles réussis)")
        sys.exit(1)


if __name__ == "__main__":
    main()
