"""Extraction de la hiérarchie CIM-10 (format ClaML — Classification Markup Language).

Contrairement au kit LIBCIM10MULTI.TXT (plat, un code + libellé par ligne),
le fichier ClaML porte la hiérarchie chapitre -> bloc (sous-chapitre) ->
catégorie -> sous-catégorie de façon EXPLICITE : chaque <Class> a un
attribut `kind` (chapter/block/category) et un <SuperClass code="..."/>
donnant le code du parent directement (pas de dérivation par préfixe à faire
nous-mêmes pour chapitre/bloc, contrairement à ce qui avait été supposé).

Normalisation des codes : ClaML note les catégories avec un point
(ex. "A00.0"), alors que le kit LIBCIM10MULTI.TXT et les RHS utilisent la
notation sans point (ex. "A000"). On retire simplement le point partout
(y compris dans les codes "dague/astérisque" du type "B24.+0" -> "B24+0")
pour que `code` soit directement joignable avec `nomenclature_diagnostics.code`.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

_KEPT_KINDS = {"chapter", "block", "category"}


def _normalize(code: str) -> str:
    return code.replace(".", "")


def _preferred_label(class_el: ET.Element) -> str | None:
    for rubric in class_el.findall("Rubric"):
        if rubric.get("kind") == "preferred":
            label = rubric.find("Label")
            if label is not None:
                return "".join(label.itertext()).strip()
    return None


def load_from_xml(path: str | Path) -> list[dict]:
    tree = ET.parse(path)
    root = tree.getroot()
    rows = []
    for class_el in root.findall("Class"):
        kind = class_el.get("kind")
        if kind not in _KEPT_KINDS:
            continue
        code = _normalize(class_el.get("code"))
        superclass = class_el.find("SuperClass")
        parent_code = _normalize(superclass.get("code")) if superclass is not None else None
        rows.append(
            {
                "code": code,
                "kind": kind,
                "parent_code": parent_code,
                "libelle": _preferred_label(class_el),
            }
        )
    return rows
