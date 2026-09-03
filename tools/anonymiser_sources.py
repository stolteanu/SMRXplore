#!/usr/bin/env python3
"""Anonymise une copie des fichiers source PMSI-SMR réels (RHS groupé,
VID-HOSP, VisualValoSéjours) — NDA/NIR/IPP régénérés via des pseudonymes
cohérents entre les 3 familles de fichiers (même identifiant réel -> même
pseudonyme partout, dérivé par HMAC d'une seed locale secrète, jamais par
une table de correspondance à conserver), date de naissance décalée d'un
nombre de jours aléatoire (mais stable par séjour) entre -5 et +5 (jamais
0), commune de résidence randomisée en conservant le département (2
premiers caractères du code postal).

**STRICTEMENT EN LECTURE SEULE sur les fichiers source** : ce script ne
modifie, ne déplace ni ne supprime jamais rien sous `input/` — il écrit
uniquement une COPIE anonymisée dans un dossier de sortie séparé (`anon/`
par défaut, jamais versionné, voir `.gitignore`).

Champs touchés (positions issues de config/formats/*.schema.json) :
- RHS groupé (M1D/M1C/M1B) : numero_admin_sejour, date_naissance,
  code_postal_residence.
- VID-HOSP (canonique + V015) : numero_immatriculation_assure,
  numero_immatriculation_individuel (si renseigné), date_naissance_beneficiaire,
  numero_admin_sejour, numero_admin_sejour_mere (si renseigné), numero_ipp,
  nom_medecin_traitant/prenom_medecin_traitant (vidés, tiers non concerné
  par la demande d'anonymisation mais nominatifs).
- VisualValoSéjours (CSV) : colonne NUMADMIN.

`anon/_seed.secret.json` (créé au premier lancement, jamais versionné) est
la seule clé qui permette de reproduire/inverser la correspondance
réel -> pseudonyme : à protéger comme un secret.

Usage :
    python tools/anonymiser_sources.py [--input input] [--output anon]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import re
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENCODING = "latin-1"


def _slice(line: str, start: int, end: int) -> str:
    """Positions 1-based incluses, comme src/parsing/fixed_width.py::_slice."""
    if start - 1 >= len(line):
        return ""
    return line[start - 1:end]


def _splice(line: str, start: int, end: int, replacement: str) -> str:
    """Remplace line[start-1:end] par `replacement` (complété/tronqué à la
    largeur du champ), en préservant tout le reste de la ligne à l'identique
    — y compris sa longueur totale."""
    width = end - start + 1
    replacement = replacement[:width].ljust(width) if len(replacement) < width else replacement[:width]
    return line[:start - 1] + replacement + line[end:]


class Anonymiseur:
    """Dérive des pseudonymes STABLES (même entrée -> même sortie, à seed
    constante) sans jamais avoir besoin de conserver de table de
    correspondance grandissante — seule la seed doit être protégée."""

    def __init__(self, seed: bytes):
        self._seed = seed

    def _hmac_int(self, namespace: str, value: str, digits: int) -> int:
        digest = hmac.new(self._seed, f"{namespace}:{value}".encode("utf-8"), hashlib.sha256).digest()
        return int.from_bytes(digest, "big") % (10 ** digits)

    def pseudo_numeric_id(self, namespace: str, real_value: str, width: int) -> str:
        """Pseudonyme pour un identifiant numérique zero-paddable (NDA/IPP/NIR) —
        `real_value` normalisé (sans zéros de tête) sert de clé, pour que la
        même personne/le même séjour donne le même pseudonyme quel que soit
        le padding du fichier d'origine (cf. piège numero_admin_sejour, RHS/
        VID-HOSP zero-paddent, Valo non)."""
        canonical = real_value.strip().lstrip("0") or "0"
        n = self._hmac_int(namespace, canonical, width)
        return str(n).zfill(width)

    def pseudo_alnum_id(self, namespace: str, real_value: str, width: int) -> str:
        """Pseudonyme pour un identifiant potentiellement alphanumérique, de
        même longueur que l'original (padding à droite par espaces, comme le
        format source)."""
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        digest = hmac.new(self._seed, f"{namespace}:{real_value.strip()}".encode("utf-8"), hashlib.sha256).digest()
        n = int.from_bytes(digest, "big")
        out = []
        for _ in range(width):
            out.append(alphabet[n % len(alphabet)])
            n //= len(alphabet)
        return "".join(out)

    def pseudo_id_auto(self, namespace: str, real_value: str, width: int) -> str:
        s = real_value.strip()
        if s != "" and s.lstrip("0").isdigit() or s == "0" * len(s):
            return self.pseudo_numeric_id(namespace, s, width)
        return self.pseudo_alnum_id(namespace, s, width)

    def pseudo_date_naissance(self, seance_key: str, jjmmaaaa: str) -> str:
        """Décale une date JJMMAAAA d'un nombre de jours aléatoire mais
        STABLE (dérivé de `seance_key`, typiquement le NDA du séjour — donc
        identique sur toutes les lignes RHS hebdomadaires d'un même séjour
        et cohérent avec le VID-HOSP correspondant), entre -5 et +5 jours,
        jamais 0 (la date doit toujours changer)."""
        raw = self._hmac_int(f"dob:{seance_key}", jjmmaaaa, 1) % 10  # 0-9
        offset = (raw - 5) if raw < 5 else (raw - 4)  # -5..-1, 1..5 — jamais 0
        try:
            d = date(int(jjmmaaaa[4:8]), int(jjmmaaaa[2:4]), int(jjmmaaaa[0:2]))
        except ValueError:
            return jjmmaaaa  # date invalide/vide dans la source : inchangée
        d2 = d + timedelta(days=offset)
        return f"{d2.day:02d}{d2.month:02d}{d2.year:04d}"

    def pseudo_code_postal(self, seance_key: str, code_postal: str) -> str:
        """Randomise un code postal en conservant les 2 premiers caractères
        (département, approximation retenue explicitement — les DOM-TOM à
        préfixe 3 chiffres restent donc rattachés à un département voisin
        de la même dizaine, limite connue et acceptée pour cet usage)."""
        cp = code_postal.strip()
        if len(cp) < 5 or not cp.isdigit():
            return code_postal
        n = self._hmac_int(f"cp:{seance_key}", cp, 3)
        return cp[:2] + f"{n:03d}"


# ---------- RHS groupé ----------

RHS_VERSION_POS = (11, 13)
RHS_FIELDS = {  # version_format_rhs_groupe -> positions (1-based incluses)
    "M1D": {"nda": (33, 52), "naissance": (82, 89), "cp": (91, 95)},
    "M1C": {"nda": (33, 52), "naissance": (82, 89), "cp": (91, 95)},
    "M1B": {"nda": (33, 52), "naissance": (81, 88), "cp": (90, 94)},
}


def anonymiser_rhs_ligne(line: str, anon: Anonymiseur) -> str:
    version = _slice(line, *RHS_VERSION_POS).strip()
    fields = RHS_FIELDS.get(version)
    if fields is None:
        return line  # version inconnue : ne touche à rien plutôt que de corrompre
    nda_real = _slice(line, *fields["nda"])
    nda_pseudo = anon.pseudo_id_auto("nda", nda_real, fields["nda"][1] - fields["nda"][0] + 1)
    line = _splice(line, *fields["nda"], nda_pseudo)
    naissance_real = _slice(line, *fields["naissance"])
    naissance_pseudo = anon.pseudo_date_naissance(nda_real.strip(), naissance_real)
    line = _splice(line, *fields["naissance"], naissance_pseudo)
    cp_real = _slice(line, *fields["cp"])
    cp_pseudo = anon.pseudo_code_postal(nda_real.strip(), cp_real)
    line = _splice(line, *fields["cp"], cp_pseudo)
    return line


# ---------- VID-HOSP (canonique + V015 : mêmes positions pour ces champs) ----------

VDH_FIELDS = {
    "nir_assure": (1, 13),
    "naissance": (20, 27),
    "nda": (29, 48),
    "nir_individuel": (62, 74),
    "nda_mere": (140, 159),
    "ipp": (354, 373),
    "nom_medecin": (397, 421),
    "prenom_medecin": (422, 436),
}


def _is_blank(s: str) -> bool:
    return s.strip() == "" or s.strip("0") == ""


def anonymiser_vdh_ligne(line: str, anon: Anonymiseur) -> str:
    nda_real = _slice(line, *VDH_FIELDS["nda"])
    nda_key = nda_real.strip()
    nda_pseudo = anon.pseudo_id_auto("nda", nda_real, VDH_FIELDS["nda"][1] - VDH_FIELDS["nda"][0] + 1)
    line = _splice(line, *VDH_FIELDS["nda"], nda_pseudo)

    nir_a = _slice(line, *VDH_FIELDS["nir_assure"])
    if not _is_blank(nir_a):
        line = _splice(line, *VDH_FIELDS["nir_assure"], anon.pseudo_numeric_id("nir", nir_a, 13))

    nir_i = _slice(line, *VDH_FIELDS["nir_individuel"])
    if not _is_blank(nir_i):
        line = _splice(line, *VDH_FIELDS["nir_individuel"], anon.pseudo_numeric_id("nir", nir_i, 13))

    naissance = _slice(line, *VDH_FIELDS["naissance"])
    line = _splice(line, *VDH_FIELDS["naissance"], anon.pseudo_date_naissance(nda_key, naissance))

    nda_mere = _slice(line, *VDH_FIELDS["nda_mere"])
    if not _is_blank(nda_mere):
        # Même espace de noms "nda" que numero_admin_sejour : si la mère est
        # elle-même un séjour de la base, son pseudonyme est déjà cohérent.
        line = _splice(line, *VDH_FIELDS["nda_mere"],
                        anon.pseudo_id_auto("nda", nda_mere, VDH_FIELDS["nda_mere"][1] - VDH_FIELDS["nda_mere"][0] + 1))

    ipp = _slice(line, *VDH_FIELDS["ipp"])
    if not _is_blank(ipp):
        line = _splice(line, *VDH_FIELDS["ipp"], anon.pseudo_id_auto("ipp", ipp, VDH_FIELDS["ipp"][1] - VDH_FIELDS["ipp"][0] + 1))

    # Nom/prénom du médecin traitant : tiers non listé dans la demande mais
    # nominatif — vidé plutôt qu'inventé (champ facultatif, un blanc est une
    # valeur valide du format).
    line = _splice(line, *VDH_FIELDS["nom_medecin"], "")
    line = _splice(line, *VDH_FIELDS["prenom_medecin"], "")
    return line


# ---------- VisualValoSéjours (CSV) ----------

def anonymiser_valo_fichier(src: Path, dst: Path, anon: Anonymiseur) -> int:
    with open(src, newline="", encoding=ENCODING) as f_in:
        reader = csv.reader(f_in, delimiter=";")
        rows = list(reader)
    if not rows:
        dst.write_text("", encoding=ENCODING)
        return 0
    header = rows[0]
    try:
        idx = header.index("NUMADMIN")
    except ValueError:
        idx = None
    n = 0
    with open(dst, "w", newline="", encoding=ENCODING) as f_out:
        writer = csv.writer(f_out, delimiter=";")
        writer.writerow(header)
        for row in rows[1:]:
            if idx is not None and idx < len(row) and row[idx].strip():
                real = row[idx]
                pseudo = anon.pseudo_id_auto("nda", real, 20)
                # Valo n'est pas zero-paddé (contrairement à RHS/VID-HOSP, cf.
                # docstring module) : ne retire les zéros de tête que si le
                # pseudonyme est purement numérique — un pseudonyme
                # alphanumérique se garde tel quel.
                row[idx] = str(int(pseudo)) if pseudo.isdigit() else pseudo
            writer.writerow(row)
            n += 1
    return n


# ---------- Orchestration ----------

def _load_or_create_seed(output_dir: Path) -> bytes:
    seed_path = output_dir / "_seed.secret.json"
    if seed_path.exists():
        return bytes.fromhex(json.loads(seed_path.read_text())["seed_hex"])
    output_dir.mkdir(parents=True, exist_ok=True)
    seed = secrets.token_bytes(32)
    seed_path.write_text(json.dumps({"seed_hex": seed.hex()}, indent=2))
    return seed


def anonymiser_dossier(input_root: Path, output_root: Path) -> dict:
    anon = Anonymiseur(_load_or_create_seed(output_root))
    stats = {"rhs": 0, "vdh": 0, "valo": 0}

    for src in sorted((input_root / "rhs").glob("*.txt")):
        dst = output_root / "rhs" / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(src, encoding=ENCODING) as f_in, open(dst, "w", encoding=ENCODING) as f_out:
            for line in f_in:
                eol = "\n" if line.endswith("\n") else ""
                f_out.write(anonymiser_rhs_ligne(line.rstrip("\n"), anon) + eol)
                stats["rhs"] += 1

    for src in sorted((input_root / "vdh").glob("*.txt")):
        dst = output_root / "vdh" / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(src, encoding=ENCODING) as f_in, open(dst, "w", encoding=ENCODING) as f_out:
            for line in f_in:
                eol = "\n" if line.endswith("\n") else ""
                f_out.write(anonymiser_vdh_ligne(line.rstrip("\n"), anon) + eol)
                stats["vdh"] += 1

    for src in sorted((input_root / "valorisation").glob("*.csv")):
        dst = output_root / "valorisation" / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        stats["valo"] += anonymiser_valo_fichier(src, dst, anon)

    return stats


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", default="input", help="Dossier source réel (lecture seule) — défaut: input/")
    p.add_argument("--output", default="anon", help="Dossier de sortie anonymisé — défaut: anon/")
    args = p.parse_args()

    input_root = (ROOT / args.input).resolve()
    output_root = (ROOT / args.output).resolve()
    if input_root == output_root or str(input_root) == str(ROOT):
        sys.exit("Le dossier de sortie ne peut pas être le dossier source (ou la racine du projet).")

    stats = anonymiser_dossier(input_root, output_root)
    print(f"OK — {output_root}")
    print(f"  RHS groupé     : {stats['rhs']} lignes")
    print(f"  VID-HOSP       : {stats['vdh']} lignes")
    print(f"  Valorisation   : {stats['valo']} lignes")


if __name__ == "__main__":
    main()
