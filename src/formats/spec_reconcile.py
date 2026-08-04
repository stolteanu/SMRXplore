"""Convertit un CSV brut (extrait d'un xlsx ATIH) en schéma de parsing, en
comparant chaque position au schéma déjà validé plutôt qu'en réinterprétant
la sémantique de chaque ligne à chaque nouvelle version.

Principe (voir discussion projet) : les positions/tailles lues dans le xlsx
sont fiables et mécaniques. Le sens d'un libellé, en revanche, peut être
ambigu (ex. un champ composite éclaté sur plusieurs lignes du xlsx). Plutôt
que de deviner, on regarde si l'octet-range correspond exactement à un champ
déjà connu et validé du schéma canonique en vigueur :
  - si oui -> repris tel quel (nom, type, notes hérités), aucune ressaisie ;
  - si non -> signalé comme nouveau/modifié pour une décision humaine,
    exactement comme on l'a fait pour code_gme au départ.

Rien n'est jamais écrasé automatiquement dans config/formats/*.schema.json :
ce module ne fait que produire un rapport + un schéma "candidat" séparé.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class MiseEnPageInattendue(Exception):
    """Levée quand une hypothèse structurelle (colonnes attendues, etc.)
    n'est pas vérifiée — on préfère planter avec un message clair plutôt que
    de deviner et produire un schéma silencieusement faux."""


def slugify(label: str) -> str:
    label = label.replace("\xa0", " ").strip()
    normalized = unicodedata.normalize("NFKD", label)
    ascii_ = "".join(c for c in normalized if not unicodedata.combining(c))
    ascii_ = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_).strip("_").lower()
    return ascii_ or "champ_sans_nom"


def _to_int(raw: Any) -> int | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "" or not s.lstrip("-").isdigit():
        return None
    return int(s)


@dataclass
class RawRow:
    row_no: int
    label_cells: list[str]          # cellules des colonnes "libellé", dans l'ordre
    taille_raw: str
    debut: int | None
    fin: int | None
    obligatoire: str | None
    type_raw: str | None

    @property
    def taille(self) -> int | None:
        return _to_int(self.taille_raw)

    @property
    def label_non_empty(self) -> list[str]:
        return [c for c in self.label_cells if c.strip()]

    @property
    def best_label(self) -> str:
        """Label le plus probable pour usage dans un rapport lisible — PAS utilisé
        pour décider automatiquement d'une correspondance (voir reconcile())."""
        cells = self.label_non_empty
        return cells[-1] if cells else ""


def _tokens(c: str) -> list[str]:
    return c.split("_")


def _find_header(rows: list[list[str]]) -> tuple[int, list[str]]:
    """Cherche la ligne d'en-tête (contient les mots 'taille', 'debut', 'fin' —
    éventuellement au sein d'un intitulé composé comme 'Position début') et
    renvoie (index_ligne, colonnes_normalisées). La recherche est basée sur les
    mots (tokens séparés par '_') et non sur l'intitulé entier, pour tolérer
    les variantes de libellé d'une année sur l'autre (ex. 'Début' vs 'Position
    début') sans se laisser piéger par un mot qui contiendrait 'fin' sans être
    ce mot (ex. 'FINESS')."""
    for i, row in enumerate(rows):
        normalized = [slugify(str(c)) for c in row]
        has_taille = any("taille" in _tokens(c) for c in normalized)
        has_debut = any("debut" in _tokens(c) for c in normalized)
        has_fin = any("fin" in _tokens(c) for c in normalized)
        if has_taille and has_debut and has_fin:
            return i, normalized
    raise MiseEnPageInattendue(
        "Impossible de trouver la ligne d'en-tête (colonnes 'Taille'/'Début'/'Fin' "
        "attendues, même sous une forme composée comme 'Position début') — "
        "la mise en page ATIH a peut-être changé."
    )


def parse_raw_csv(csv_path: str | Path) -> list[RawRow]:
    with open(csv_path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))

    header_idx, normalized = _find_header(rows)
    taille_col = next(idx for idx, c in enumerate(normalized) if "taille" in _tokens(c))
    debut_col = next(idx for idx, c in enumerate(normalized) if "debut" in _tokens(c))
    fin_col = next(idx for idx, c in enumerate(normalized) if "fin" in _tokens(c))
    obligatoire_col = next((idx for idx, c in enumerate(normalized) if "obligatoire" in _tokens(c)), None)
    type_col = next(
        (idx for idx, c in enumerate(normalized) if "type" in _tokens(c) and "norme" not in _tokens(c)), None
    )
    label_cols = list(range(0, taille_col))

    raw_rows: list[RawRow] = []
    for i in range(header_idx + 1, len(rows)):
        row = rows[i]
        if len(row) <= max(taille_col, debut_col, fin_col):
            continue
        label_cells = [row[c] if c < len(row) else "" for c in label_cols]
        taille_raw = row[taille_col] if taille_col < len(row) else ""
        debut = _to_int(row[debut_col]) if debut_col < len(row) else None
        fin = _to_int(row[fin_col]) if fin_col < len(row) else None
        obligatoire = (row[obligatoire_col].strip() or None) if obligatoire_col is not None and obligatoire_col < len(row) else None
        type_raw = (row[type_col].strip() or None) if type_col is not None and type_col < len(row) else None
        raw_rows.append(RawRow(i + 1, label_cells, taille_raw, debut, fin, obligatoire, type_raw))

    return raw_rows


_ELLIPSIS_RE = re.compile(r"^[\s .…�]*$")
_BLOCK_START_RE = re.compile(r"n°\s*1(?!\d)")


@dataclass
class DraftField:
    row_no: int
    start: int | None   # None pour un champ de bloc répété (position relative alors)
    end: int | None
    len_: int
    label_display: str  # tous les libellés non vides concaténés, pour le rapport uniquement
    type_raw: str | None = None  # valeur brute de la colonne "type" si présente (suggestion, non fiable pour VID-HOSP)


@dataclass
class DraftBlock:
    trigger_label: str
    fields: list[DraftField]

    @property
    def block_len(self) -> int:
        return sum(f.len_ for f in self.fields)


@dataclass
class Draft:
    fixed_fields: list[DraftField]
    blocks: list[DraftBlock]


def build_draft(raw_rows: list[RawRow]) -> Draft:
    fixed_fields: list[DraftField] = []
    blocks: list[DraftBlock] = []
    current_block: DraftBlock | None = None
    mode = "collecting"

    for r in raw_rows:
        trigger_hit = next((c for c in r.label_non_empty if _BLOCK_START_RE.search(c)), None)
        label_display = " / ".join(r.label_non_empty)

        if trigger_hit is not None:
            # déclencheur de bloc répété — certaines années (ex. 2026) donnent des
            # positions absolues pour la 1ère occurrence (exemple calculé avec N=1),
            # d'autres (2024/2025) les laissent vides : on ignore début/fin ici dans
            # les deux cas, seule la taille compte pour un champ de bloc répété.
            if current_block is not None:
                blocks.append(current_block)
            current_block = DraftBlock(trigger_label=label_display, fields=[])
            mode = "collecting"
            if r.taille is not None:
                current_block.fields.append(DraftField(r.row_no, None, None, r.taille, label_display, r.type_raw))
            continue

        if mode == "collecting" and current_block is not None:
            # toujours à l'intérieur d'un bloc déclenché : seule une VRAIE marque de
            # séparation ("...", "…") le clôt. Une ligne sans taille mais qui n'est
            # pas cette marque (ex. une note/commentaire isolée sur sa propre ligne,
            # vu en 2023) est ignorée sans clore le bloc — sinon le bloc est coupé
            # bien avant la fin (constaté empiriquement sur formats_ssr2023_0.xlsx :
            # le bloc CCAM se retrouvait tronqué à 1 champ au lieu de 7).
            est_separateur = any(_ELLIPSIS_RE.fullmatch(c.strip()) for c in r.label_non_empty if c.strip())
            if est_separateur:
                blocks.append(current_block)
                current_block = None
                mode = "skipping"
                continue
            if r.taille is None:
                continue  # ligne note/annotation isolée : ignorée, le bloc reste ouvert
            current_block.fields.append(DraftField(r.row_no, None, None, r.taille, label_display, r.type_raw))
            continue

        if r.debut is not None and r.fin is not None:
            fixed_fields.append(DraftField(r.row_no, r.debut, r.fin, r.fin - r.debut + 1, label_display, r.type_raw))
            mode = "collecting"
            continue

        if r.taille is None:
            mode = "skipping"
            continue
        # sinon (mode == "skipping", ou aucun bloc en cours sans trigger reconnu) :
        # ligne ignorée — probable "dernière occurrence" documentaire (n° nX)

    if current_block is not None:
        blocks.append(current_block)

    return Draft(fixed_fields=fixed_fields, blocks=blocks)


def _counter_fields_in_order(existing_schema: dict) -> list[str]:
    """Trouve les champs compteurs (n1, n2, ...) dans le schéma existant, dans
    l'ordre de leur position, en s'appuyant sur record_length_formula si
    présente, sinon sur les counter_field des repeated_blocks (déjà dans
    l'ordre du fichier)."""
    return [b["counter_field"] for b in existing_schema.get("repeated_blocks", [])]


@dataclass
class ReconcileReport:
    format_name: str
    fixed_inchanges: list[dict] = field(default_factory=list)
    fixed_nouveaux: list[dict] = field(default_factory=list)
    fixed_disparus: list[dict] = field(default_factory=list)
    blocks_inchanges: list[dict] = field(default_factory=list)
    blocks_nouveaux: list[dict] = field(default_factory=list)
    anomalie_nb_blocs: str | None = None

    @property
    def tout_connu(self) -> bool:
        return not (self.fixed_nouveaux or self.fixed_disparus or self.blocks_nouveaux or self.anomalie_nb_blocs)


def reconcile(draft: Draft, existing_schema: dict) -> ReconcileReport:
    format_name = existing_schema.get("format", "?")
    report = ReconcileReport(format_name=format_name)

    existing_fixed = existing_schema.get("fixed_block", [])
    covered_existing_ids: set[int] = set()

    for ex in existing_fixed:
        ex_start, ex_end = ex["start"], ex["end"]
        # les lignes brutes qui tombent entièrement dans [ex_start, ex_end]
        inside = [f for f in draft.fixed_fields if f.start is not None and ex_start <= f.start and f.end <= ex_end]
        covered_span = sum(f.len_ for f in inside)
        exact_tiling = (
            inside
            and min(f.start for f in inside) == ex_start
            and max(f.end for f in inside) == ex_end
            and covered_span == (ex_end - ex_start + 1)
        )
        if exact_tiling:
            report.fixed_inchanges.append({"name": ex["name"], "start": ex_start, "end": ex_end})
            for f in inside:
                covered_existing_ids.add(f.row_no)
        else:
            report.fixed_disparus.append({"name": ex["name"], "start": ex_start, "end": ex_end})

    for f in draft.fixed_fields:
        if f.row_no not in covered_existing_ids:
            report.fixed_nouveaux.append(
                {"row": f.row_no, "start": f.start, "end": f.end, "len": f.len_,
                 "label": f.label_display, "type_raw": f.type_raw}
            )

    existing_blocks = existing_schema.get("repeated_blocks", [])
    if len(existing_blocks) != len(draft.blocks):
        report.anomalie_nb_blocs = (
            f"{len(draft.blocks)} bloc(s) répété(s) détecté(s) dans le nouveau fichier, "
            f"contre {len(existing_blocks)} attendu(s) d'après le schéma actuel "
            f"({[b['name'] for b in existing_blocks]}) — à vérifier manuellement, "
            f"la convention de mise en page a peut-être changé."
        )

    # Comparaison par longueur de bloc (pas par position dans la liste) : un bloc
    # inséré au milieu des autres (ex. CSAR entre CSARR et CCAM en 2025) décale
    # sinon les index et fait croire à tort que tout ce qui suit a changé.
    used = [False] * len(existing_blocks)
    for draft_block in draft.blocks:
        match_idx = next(
            (i for i, eb in enumerate(existing_blocks) if not used[i] and eb["block_len"] == draft_block.block_len),
            None,
        )
        if match_idx is not None:
            used[match_idx] = True
            report.blocks_inchanges.append(
                {"name": existing_blocks[match_idx]["name"], "block_len": draft_block.block_len,
                 "counter_field": existing_blocks[match_idx]["counter_field"]}
            )
        else:
            report.blocks_nouveaux.append(
                {"trigger_label": draft_block.trigger_label, "block_len": draft_block.block_len,
                 "fields": [{"label": fl.label_display, "len": fl.len_, "type_raw": fl.type_raw}
                            for fl in draft_block.fields]}
            )

    return report


def render_report(report: ReconcileReport) -> str:
    lines = [f"=== Rapport de rapprochement — format {report.format_name} ===", ""]

    if report.tout_connu:
        lines.append(
            f"✅ Rien de nouveau : {len(report.fixed_inchanges)} champ(s) fixe(s) et "
            f"{len(report.blocks_inchanges)} bloc(s) répété(s) correspondent exactement "
            f"au schéma déjà validé. Aucune action requise."
        )
        return "\n".join(lines)

    lines.append(f"{len(report.fixed_inchanges)} champ(s) fixe(s) inchangé(s), repris automatiquement.")
    lines.append(f"{len(report.blocks_inchanges)} bloc(s) répété(s) inchangé(s), repris automatiquement.")
    lines.append("")

    if report.anomalie_nb_blocs:
        lines.append(f"⚠ {report.anomalie_nb_blocs}")
        lines.append("")

    if report.fixed_disparus:
        lines.append(f"⚠ {len(report.fixed_disparus)} champ(s) connu(s) introuvable(s) tel quel dans le nouveau fichier :")
        for d in report.fixed_disparus:
            lines.append(f"   - {d['name']} (attendu {d['start']}-{d['end']}) — position déplacée ou supprimée ?")
        lines.append("")

    if report.fixed_nouveaux:
        lines.append(f"⚠ {len(report.fixed_nouveaux)} champ(s) nouveau(x)/modifié(s), à valider ensemble :")
        for n in report.fixed_nouveaux:
            lines.append(f"   - ligne {n['row']} : positions {n['start']}-{n['end']} ({n['len']} car.) — libellé(s) : {n['label']}")
        lines.append("")

    if report.blocks_nouveaux:
        lines.append(f"⚠ {len(report.blocks_nouveaux)} bloc(s) répété(s) nouveau(x)/modifié(s), à valider ensemble :")
        for b in report.blocks_nouveaux:
            lines.append(f"   - déclencheur {b['trigger_label']!r}, longueur totale {b['block_len']} :")
            for fl in b["fields"]:
                lines.append(f"       · {fl['label']} ({fl['len']} car.)")
        lines.append("")

    return "\n".join(lines)
