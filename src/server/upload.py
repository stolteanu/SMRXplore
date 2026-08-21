"""Zone de dépôt + contrôle pour les fichiers source (RHS, VID-HOSP,
VisualValoSejours) uploadés depuis la fenêtre d'administration de l'app
(app/admin.html), pour que l'utilisateur n'ait plus jamais à copier de
fichier lui-même dans input/.

Cycle de vie d'un fichier déposé :

  1. stage_file()   — reçu depuis /api/upload, écrit dans data/staging/<categorie>/
                       avec un identifiant unique + un fichier .meta.json à côté
                       (établissement/année/mois détectés depuis le nom si possible).
  2. set_meta()      — si l'établissement/année/mois n'ont pas pu être détectés,
                       l'UI les redemande via un petit formulaire ; complète le
                       .meta.json correspondant.
  3. controler()     — relit TOUS les fichiers actuellement en zone de dépôt (toutes
                       catégories confondues), fait un essai de parsing (sans écrire
                       dans la base) pour vérifier le format, et — SEULEMENT si tout
                       est correct — déplace chaque fichier vers son dossier final
                       (input/rhs, input/vdh, input/valorisation) avec le nom
                       standard. En cas d'erreur BLOQUANTE sur au moins un fichier,
                       rien n'est déplacé.

Deux catégories d'anomalies pour RHS/VID-HOSP (_valider_rhs_vdh) :
  - BLOQUANTES, jamais contournables : code de version non reconnu, longueur
    d'enregistrement incorrecte, champ de liaison manquant (finess_epmsi,
    numero_admin_sejour, numero_semaine, numero_unite_medicale — la clé
    naturelle qui rattache RHS/VID-HOSP/valorisation entre eux dans pmsi.db).
  - AVERTISSEMENTS, contournables via confirmer_malgre_erreurs() (bouton
    "Mettre à jour quand même" dans l'UI) : toute autre anomalie de champ,
    ex. numéro de sécurité sociale absent/non numérique — n'entre dans
    aucune clé de rattachement, et run.py charge de toute façon
    l'enregistrement en journalisant l'anomalie (cf. process_file).

Rien ici ne touche à data/processed/pmsi.db : le chargement effectif reste
/api/charger (run.py), déclenché par le bouton "Mettre à jour" une fois le
contrôle passé avec succès.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.util.paths import project_root

ROOT = project_root()
STAGING_ROOT = ROOT / "data/staging"

_FINESS_ANNEE_MOIS_RE = re.compile(r"^(\d{9})[._-](\d{4})[._-](\d{1,2})\b")
_FINESS_RE = re.compile(r"^\d{9}$")


@dataclass(frozen=True)
class Categorie:
    cle: str
    label: str
    extensions: tuple[str, ...]
    dossier_final: str

    @property
    def dossier_staging(self) -> Path:
        return STAGING_ROOT / self.cle


CATEGORIES: dict[str, Categorie] = {
    "rhs": Categorie("rhs", "RHS groupé", (".txt",), "input/rhs"),
    "vdh": Categorie("vdh", "VID-HOSP", (".txt",), "input/vdh"),
    "valorisation": Categorie("valorisation", "VisualValoSejours", (".csv",), "input/valorisation"),
}


class ErreurUpload(Exception):
    pass


def parse_multipart(content_type: str, body: bytes) -> tuple[dict[str, str], list[dict]]:
    """Parseur minimal de multipart/form-data (aucune dépendance externe, le
    module cgi étant déprécié/supprimé selon les versions de Python). Ne gère
    que ce dont l'app a besoin : champs texte simples + fichiers uploadés une
    fois chacun. Retourne (champs_texte, [{"name":..., "filename":..., "content": bytes}])."""
    m = re.search(r'boundary="?([^";]+)"?', content_type)
    if not m:
        raise ErreurUpload("Requête multipart sans boundary.")
    boundary = ("--" + m.group(1)).encode("utf-8")

    fields: dict[str, str] = {}
    files: list[dict] = []

    parts = body.split(boundary)
    for part in parts:
        if not part or part in (b"--", b"\r\n") or part.startswith(b"--"):
            continue
        # Chaque segment commence par le CRLF qui suit la ligne de boundary —
        # à retirer précisément (PAS bytes.strip(), qui mangerait aussi les
        # \r/\n réels de fin de fichier s'ils sont adjacents : c'est le bug
        # constaté empiriquement le 2026-08-20, une ligne finale de fichier
        # perdue au réupload d'un VisualValoSejours réel).
        if part.startswith(b"\r\n"):
            part = part[2:]
        elif part.startswith(b"\n"):
            part = part[1:]

        header_end = part.find(b"\r\n\r\n")
        if header_end == -1:
            continue
        raw_headers = part[:header_end].decode("utf-8", errors="replace")
        content = part[header_end + 4:]
        # Le CRLF séparant le contenu du prochain boundary est TOUJOURS
        # exactement 2 octets (RFC 2046) — retirer seulement ceux-là, jamais
        # en boucle, pour ne jamais toucher au contenu réel du fichier.
        if content.endswith(b"\r\n"):
            content = content[:-2]
        elif content.endswith(b"\n"):
            content = content[:-1]

        disposition = ""
        for line in raw_headers.split("\r\n"):
            if line.lower().startswith("content-disposition:"):
                disposition = line
                break
        name_m = re.search(r'name="([^"]*)"', disposition)
        filename_m = re.search(r'filename="([^"]*)"', disposition)
        if not name_m:
            continue
        name = name_m.group(1)
        if filename_m:
            files.append({"name": name, "filename": filename_m.group(1), "content": content})
        else:
            fields[name] = content.decode("utf-8", errors="replace")

    return fields, files


def _safe_stem(original_name: str) -> str:
    name = Path(original_name).name  # retire tout chemin éventuel
    return name or "fichier"


def _meta_path(categorie: str, file_id: str) -> Path:
    return CATEGORIES[categorie].dossier_staging / f"{file_id}.meta.json"


def _data_path(categorie: str, file_id: str, original_name: str) -> Path:
    return CATEGORIES[categorie].dossier_staging / f"{file_id}__{original_name}"


def _read_meta(meta_path: Path) -> dict:
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _write_meta(meta_path: Path, meta: dict) -> None:
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def stage_file(categorie: str, original_name: str, content: bytes) -> dict:
    if categorie not in CATEGORIES:
        raise ErreurUpload(f"Catégorie inconnue : {categorie!r}")
    cat = CATEGORIES[categorie]
    cat.dossier_staging.mkdir(parents=True, exist_ok=True)

    original_name = _safe_stem(original_name)
    ext = Path(original_name).suffix.lower()
    if ext not in cat.extensions:
        raise ErreurUpload(
            f"{original_name} : extension {ext or '(aucune)'} inattendue pour {cat.label} "
            f"(attendu : {', '.join(cat.extensions)})."
        )

    file_id = uuid.uuid4().hex[:12]
    data_path = _data_path(categorie, file_id, original_name)
    data_path.write_bytes(content)

    m = _FINESS_ANNEE_MOIS_RE.match(original_name)
    finess = m.group(1) if m else None
    annee = int(m.group(2)) if m else None
    mois = int(m.group(3)) if m else None
    if mois is not None and not (1 <= mois <= 12):
        finess = annee = mois = None  # nom trompeur (ex. faux positif) : on redemande

    meta = {
        "id": file_id,
        "categorie": categorie,
        "original_name": original_name,
        "finess": finess,
        "annee": annee,
        "mois": mois,
        "detecte": finess is not None,
        "confirme_ecrasement": False,
        "confirme_malgre_erreurs": False,
    }
    _write_meta(_meta_path(categorie, file_id), meta)
    return meta


def set_meta(categorie: str, file_id: str, finess: str, annee: int, mois: int) -> dict:
    meta_path = _meta_path(categorie, file_id)
    if not meta_path.exists():
        raise ErreurUpload("Fichier introuvable en zone de dépôt (a-t-il déjà été traité ?).")
    if not _FINESS_RE.match(finess):
        raise ErreurUpload("FINESS invalide (9 chiffres attendus).")
    if not (2000 <= annee <= 2100):
        raise ErreurUpload("Année invalide.")
    if not (1 <= mois <= 12):
        raise ErreurUpload("Mois invalide (1 à 12).")

    meta = _read_meta(meta_path)
    meta.update({"finess": finess, "annee": annee, "mois": mois, "detecte": False})
    _write_meta(meta_path, meta)
    return meta


def remove_staged(categorie: str, file_id: str) -> None:
    if categorie not in CATEGORIES:
        raise ErreurUpload(f"Catégorie inconnue : {categorie!r}")
    meta_path = _meta_path(categorie, file_id)
    if not meta_path.exists():
        return
    meta = _read_meta(meta_path)
    data_path = _data_path(categorie, file_id, meta["original_name"])
    data_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)


def list_staged() -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {cle: [] for cle in CATEGORIES}
    for cle, cat in CATEGORIES.items():
        if not cat.dossier_staging.is_dir():
            continue
        for meta_path in sorted(cat.dossier_staging.glob("*.meta.json")):
            result[cle].append(_read_meta(meta_path))
    return result


# Champs de liaison (natural_key, en tête d'enregistrement) sans lesquels un
# RHS/VID-HOSP ne peut pas être rattaché aux deux autres fichiers d'une même
# transmission — un enregistrement qui en manque un reste BLOQUANT (avec la
# longueur d'enregistrement et le code de version), quoi qu'il arrive : ça
# casserait le rattachement dans la base, aucun bouton "quand même" ne doit
# pouvoir le contourner.
_CHAMPS_LIAISON = {
    "rhs_groupe": ["finess_epmsi", "numero_admin_sejour", "numero_semaine", "numero_unite_medicale"],
    "vid_hosp": ["finess_epmsi", "numero_admin_sejour"],
}
# Numéro de sécurité sociale (VID-HOSP uniquement) : n'entre PAS dans la clé
# naturelle ni dans le rattachement entre tables de pmsi.db (seul finess_epmsi
# + numero_admin_sejour y comptent) — une anomalie dessus est donc un simple
# AVERTISSEMENT, pas un blocage (retour utilisateur 2026-08-21 : un fichier
# réel avec NIR="XXXX" sur certaines lignes était rejeté en bloc alors que le
# reste du fichier, et notamment les champs de liaison, étaient corrects).
_CHAMP_SECU = {"vid_hosp": "numero_immatriculation_assure"}


def _erreur_liaison(fmt: str, fixed: dict) -> str | None:
    for champ in _CHAMPS_LIAISON.get(fmt, []):
        valeur = fixed.get(champ)
        if valeur in (None, ""):
            return f"champ de liaison {champ!r} manquant (empêche le rattachement aux autres fichiers)"
    return None


def _avertissement_secu(fmt: str, fixed: dict) -> str | None:
    champ = _CHAMP_SECU.get(fmt)
    if not champ:
        return None
    valeur = fixed.get(champ)
    if valeur in (None, ""):
        return "numéro de sécurité sociale absent"
    if not str(valeur).strip().isdigit():
        return f"numéro de sécurité sociale non numérique ({valeur!r})"
    return None


def _valider_rhs_vdh(fmt: str, path: Path) -> dict:
    """Retourne {"bloquant": bool, "message": str, "avertissement_count": int}.
    bloquant=True ne peut JAMAIS être contourné (mauvais fichier/format, ou
    perte du rattachement entre tables) ; avertissement_count>0 peut l'être
    via confirmer_malgre_erreurs() — cf. docstring module."""
    import run as run_module  # import tardif : évite tout cycle au chargement du serveur

    registry = run_module.load_registry()
    if fmt not in registry:
        return {"bloquant": True, "message": f"format {fmt!r} absent de config/formats/registry.json", "avertissement_count": 0}
    entry = registry[fmt]
    version_slice = tuple(entry["version_slice"])

    from src.parsing.fixed_width import load_schema, parse_file_multi

    schemas_by_version = {v: load_schema(ROOT / "config/formats" / rel) for v, rel in entry["variants"].items()}

    total = 0
    ok = 0
    version_inconnue = 0
    with_avertissement = 0
    bloquant_count = 0
    premier_message_bloquant: str | None = None
    premier_message_avertissement: str | None = None
    for line_no, _raw, version, parsed in parse_file_multi(path, schemas_by_version, version_slice):
        total += 1
        if parsed is None:
            version_inconnue += 1
            continue

        if parsed["actual_length"] != parsed["expected_length"]:
            bloquant_count += 1
            if premier_message_bloquant is None:
                premier_message_bloquant = (
                    f"ligne {line_no} : longueur d'enregistrement incorrecte "
                    f"(attendue={parsed['expected_length']}, réelle={parsed['actual_length']})"
                )
            continue
        erreur_liaison = _erreur_liaison(fmt, parsed["fixed"])
        if erreur_liaison:
            bloquant_count += 1
            if premier_message_bloquant is None:
                premier_message_bloquant = f"ligne {line_no} : {erreur_liaison}"
            continue

        avert_secu = _avertissement_secu(fmt, parsed["fixed"])
        if avert_secu or parsed["errors"]:
            with_avertissement += 1
            if premier_message_avertissement is None:
                premier_message_avertissement = f"ligne {line_no} : " + (avert_secu or parsed["errors"][0])
        else:
            ok += 1

    if total == 0:
        return {"bloquant": True, "message": "fichier vide.", "avertissement_count": 0}
    if ok == 0 and with_avertissement == 0 and bloquant_count == 0:
        return {
            "bloquant": True,
            "message": (
                f"aucune ligne avec un code de version reconnu — mauvais fichier déposé dans cette zone, "
                f"ou format non encore incorporé au projet ({total} ligne(s) ignorée(s))."
            ),
            "avertissement_count": 0,
        }
    if bloquant_count:
        return {
            "bloquant": True,
            "message": f"{bloquant_count}/{total} ligne(s) avec un format/champ de liaison invalide, ex. {premier_message_bloquant}.",
            "avertissement_count": 0,
        }

    # Non bloquant : longueur et champs de liaison sont corrects sur toutes
    # les lignes. Une anomalie sur un autre champ (NIR, sous-champ DMT type
    # sentinelle ATIH...) n'empêche pas run.py de charger l'enregistrement —
    # seulement journalisée (cf. process_file) — donc n'empêche pas non plus
    # l'upload, moyennant confirmation explicite si des lignes sont concernées.
    message = f"{ok}/{total} ligne(s) conformes."
    if with_avertissement:
        message += f" {with_avertissement} ligne(s) avec anomalie(s) mineure(s) (seront journalisées à la mise à jour) — ex. {premier_message_avertissement}."
    if version_inconnue:
        message += f" {version_inconnue} ligne(s) à code de version inconnu, ignorée(s)."
    return {"bloquant": False, "message": message, "avertissement_count": with_avertissement}


def _valider_valorisation(path: Path) -> dict:
    schema = json.loads((ROOT / "config/formats/valorisation_sejour.schema.json").read_text(encoding="utf-8"))
    from src.parsing.valorisation import load_from_csv

    try:
        rows = load_from_csv(path, schema)
    except ValueError as exc:
        return {"bloquant": True, "message": str(exc), "avertissement_count": 0}
    if not rows:
        return {"bloquant": False, "message": "0 ligne dans le fichier (fichier accepté mais vide).", "avertissement_count": 0}
    return {"bloquant": False, "message": f"{len(rows)} ligne(s) conformes.", "avertissement_count": 0}


def _nom_final(categorie: str, meta: dict) -> str:
    finess, annee, mois = meta["finess"], meta["annee"], meta["mois"]
    if categorie == "valorisation":
        return f"{finess}.{annee}.{mois:02d}.SMR.VisualValoSejours.csv"
    horodatage = meta.get("id", uuid.uuid4().hex[:10])
    return f"{finess}.{annee}.{mois:02d}.{categorie}.{horodatage}.txt"


def _finaliser(categorie: str, meta: dict, path: Path) -> None:
    cat = CATEGORIES[categorie]
    final_dir = ROOT / cat.dossier_final
    final_dir.mkdir(parents=True, exist_ok=True)
    cible = final_dir / _nom_final(categorie, meta)
    path.replace(cible)


def confirmer_ecrasement(categorie: str, file_id: str) -> dict:
    """Marque explicitement qu'un fichier déjà présent (aucune sauvegarde
    possible, input/ n'étant pas versionné) peut être remplacé. Appelé
    UNIQUEMENT sur clic explicite de l'utilisateur dans l'UI — jamais
    automatiquement, quel que soit le mode (décision utilisateur 2026-08-20,
    suite à un fichier réel écrasé par erreur pendant un test)."""
    meta_path = _meta_path(categorie, file_id)
    if not meta_path.exists():
        raise ErreurUpload("Fichier introuvable en zone de dépôt.")
    meta = _read_meta(meta_path)
    meta["confirme_ecrasement"] = True
    _write_meta(meta_path, meta)
    return meta


def confirmer_malgre_erreurs(categorie: str, file_id: str) -> dict:
    """Marque explicitement qu'un fichier avec des anomalies NON bloquantes
    (cf. _valider_rhs_vdh : format/longueur/champs de liaison corrects, mais
    au moins une autre anomalie comme un NIR invalide) doit quand même être
    téléversé. Appelé UNIQUEMENT sur clic explicite ("Mettre à jour quand
    même") — jamais automatiquement (même logique que confirmer_ecrasement)."""
    meta_path = _meta_path(categorie, file_id)
    if not meta_path.exists():
        raise ErreurUpload("Fichier introuvable en zone de dépôt.")
    meta = _read_meta(meta_path)
    meta["confirme_malgre_erreurs"] = True
    _write_meta(meta_path, meta)
    return meta


def controler() -> dict:
    staged = list_staged()
    total_fichiers = sum(len(v) for v in staged.values())
    if total_fichiers == 0:
        return {"pret": False, "resultats": [], "erreur_globale": "Aucun fichier déposé."}

    resultats: list[dict] = []
    tout_ok = True

    for categorie, items in staged.items():
        cat = CATEGORIES[categorie]
        for meta in items:
            data_path = _data_path(categorie, meta["id"], meta["original_name"])
            entry = {
                "id": meta["id"],
                "categorie": categorie,
                "categorie_label": cat.label,
                "original_name": meta["original_name"],
            }
            if meta["finess"] is None or meta["annee"] is None or meta["mois"] is None:
                entry["ok"] = False
                entry["message"] = "établissement/année/mois manquants — à compléter ci-dessus."
                tout_ok = False
                resultats.append(entry)
                continue

            if categorie in ("rhs", "vdh"):
                fmt = "rhs_groupe" if categorie == "rhs" else "vid_hosp"
                validation = _valider_rhs_vdh(fmt, data_path)
            else:
                validation = _valider_valorisation(data_path)

            if validation["bloquant"]:
                entry["ok"] = False
                entry["message"] = validation["message"]
                tout_ok = False
                resultats.append(entry)
                continue

            ok = True
            message = validation["message"]

            if validation["avertissement_count"] and not meta.get("confirme_malgre_erreurs"):
                ok = False
                entry["confirmation_erreurs_requise"] = True

            if ok:
                cible = ROOT / cat.dossier_final / _nom_final(categorie, meta)
                if cible.exists() and not meta.get("confirme_ecrasement"):
                    ok = False
                    entry["ecrasement_requis"] = True
                    entry["cible"] = str(cible.relative_to(ROOT))
                    message = (
                        f"remplace un fichier déjà présent ({cible.name}), sans sauvegarde possible "
                        f"(input/ non versionné) — confirmation explicite requise avant remplacement."
                    )

            entry["ok"] = ok
            entry["message"] = message
            if not ok:
                tout_ok = False
            resultats.append(entry)

    if not tout_ok:
        return {"pret": False, "resultats": resultats}

    for categorie, items in staged.items():
        for meta in items:
            data_path = _data_path(categorie, meta["id"], meta["original_name"])
            _finaliser(categorie, meta, data_path)
            _meta_path(categorie, meta["id"]).unlink(missing_ok=True)

    return {"pret": True, "resultats": resultats}
