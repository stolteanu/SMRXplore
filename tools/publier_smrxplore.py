#!/usr/bin/env python3
"""Publie l'état courant de ce dépôt sur le dépôt public SMRXplore
(github.com/stolteanu/SMRXplore) en UN SEUL commit — l'historique de
développement complet (commits incrémentaux, itérations, correctifs
successifs) reste uniquement en local, jamais exposé publiquement
(décision utilisateur 2026-09-18).

Adapte 3 fichiers pour la version publiée, sans toucher aux fichiers
locaux (l'arbre Git local n'est jamais modifié, seul un commit isolé
est construit puis poussé en force sur origin/master) :
- CHANGELOG.md : ne garde que la dernière entrée de version (pas
  l'historique complet reconstruit depuis 0.1.0).
- PROJECT_HISTORY.md : retiré entièrement (document de planification
  interne, pas destiné à un utilisateur du produit).
- README.md : retire les références à PROJECT_HISTORY.md et à la
  section "Dette..." du CHANGELOG (absente de la version publiée).

Usage :
    python tools/publier_smrxplore.py
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REMOTE = "origin"
BRANCH = "master"

# Fichiers/dossiers internes au développement (config Claude Code locale,
# chemins/identifiants dans settings.local.json, prompt de démarrage) —
# jamais publiés (décision utilisateur 2026-09-18, même logique que
# PROJECT_HISTORY.md ci-dessous).
EXCLUDED_PATHS = {".claude", "PROJECT_HISTORY.md", "PROMPT_DEMARRAGE_CLAUDE_CODE.md"}


def _run(*args: str, input_bytes: bytes | None = None) -> str:
    # `input_bytes`, jamais `input=str`+`text=True` : sous Windows, le mode
    # texte de subprocess traduit chaque \n en \r\n à l'écriture — corrompt
    # silencieusement les noms de fichiers passés à `git mktree` (un \r
    # parasite s'accroche à la fin de chaque chemin). Écrit dans un fichier
    # temporaire ouvert en binaire plutôt que via `input=` pour être sûr
    # qu'aucune traduction n'a lieu, quelle que soit la plateforme.
    stdin_arg = None
    tmp_path = None
    if input_bytes is not None:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(input_bytes)
            tmp_path = tmp.name
        stdin_arg = open(tmp_path, "rb")
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            stdin=stdin_arg,
            capture_output=True,
            check=True,
        )
    finally:
        if stdin_arg is not None:
            stdin_arg.close()
        if tmp_path is not None:
            Path(tmp_path).unlink()
    return result.stdout.decode("utf-8")


def _hash_object(content: str) -> str:
    return _run("hash-object", "-w", "--stdin", input_bytes=content.encode("utf-8")).strip()


def extract_latest_changelog_entry(changelog: str) -> str:
    matches = list(re.finditer(r"^### (\d+\.\d+\.\d+[^\n]*)$", changelog, re.M))
    if not matches:
        raise SystemExit("Aucune entrée de version (### x.y.z) trouvée dans CHANGELOG.md")
    last = matches[-1]
    tail = changelog[last.start():]
    end_match = re.search(r"^---\s*$", tail, re.M)
    entry = tail[: end_match.start()] if end_match else tail
    # Retire la ligne de hash de commit ("`abc1234` (date) — ...") : une fois
    # l'historique squashé en un seul commit public, ce hash ne correspond
    # plus à rien sur le dépôt publié — laisserait croire à un historique
    # consultable qui n'existe pas côté public.
    entry = re.sub(r"^`[0-9a-f]{7,40}`[^\n]*\n", "", entry, flags=re.M)
    return entry.rstrip() + "\n"


def build_public_changelog(changelog_path: Path) -> tuple[str, str]:
    changelog = changelog_path.read_text(encoding="utf-8")
    entry = extract_latest_changelog_entry(changelog)
    version = re.match(r"### (\d+\.\d+\.\d+)", entry).group(1)
    content = (
        "# CHANGELOG — SMRXplore\n\n"
        "> Notes de la version publiée. L'historique de développement complet\n"
        "> n'est pas publié sur ce dépôt.\n\n"
        "---\n\n"
        f"{entry}"
    )
    return content, version


def build_public_readme(readme_path: Path) -> str:
    readme = readme_path.read_text(encoding="utf-8")
    old_intro = (
        "supposé correct — voir [CHANGELOG.md](CHANGELOG.md) pour l'historique\n"
        "détaillé des vérifications et [PROJECT_HISTORY.md](PROJECT_HISTORY.md) pour\n"
        "l'architecture complète."
    )
    new_intro = "supposé correct — voir [CHANGELOG.md](CHANGELOG.md) pour les notes de la version actuelle."
    if old_intro not in readme:
        raise SystemExit("build_public_readme : texte d'intro attendu introuvable — README.md a changé, ajuster ce script.")
    readme = readme.replace(old_intro, new_intro)

    old_etat = (
        'contre les documents de référence ATIH (voir [CHANGELOG.md](CHANGELOG.md),\n'
        'section "Dette et périmètre explicitement hors scope" pour le détail des\n'
        "limites connues)."
    )
    new_etat = "contre les documents de référence ATIH."
    if old_etat not in readme:
        raise SystemExit("build_public_readme : texte 'État du projet' attendu introuvable — README.md a changé, ajuster ce script.")
    readme = readme.replace(old_etat, new_etat)

    if "PROJECT_HISTORY.md" in readme:
        raise SystemExit("build_public_readme : référence à PROJECT_HISTORY.md encore présente après nettoyage — ajuster ce script.")
    return readme


def main() -> None:
    _run("fetch", REMOTE, BRANCH)
    head_tree = _run("rev-parse", f"{BRANCH}^{{tree}}").strip()

    changelog_content, version = build_public_changelog(ROOT / "CHANGELOG.md")
    readme_content = build_public_readme(ROOT / "README.md")
    changelog_blob = _hash_object(changelog_content)
    readme_blob = _hash_object(readme_content)

    entries = []
    for line in _run("ls-tree", head_tree).splitlines():
        meta, name = line.split("\t")
        if name in EXCLUDED_PATHS:
            continue
        mode, kind, sha = meta.split()
        if name == "CHANGELOG.md":
            sha = changelog_blob
        elif name == "README.md":
            sha = readme_blob
        entries.append(f"{mode} {kind} {sha}\t{name}")

    new_tree = _run("mktree", input_bytes=("\n".join(entries) + "\n").encode("utf-8")).strip()

    message = (
        f"SMRXplore — état courant ({version})\n\n"
        "Historique de développement condensé en un seul commit : l'historique\n"
        "incrémental complet (mise au point, correctifs successifs, itérations)\n"
        "reste en local, ce dépôt public n'expose que l'état actuel du produit.\n\n"
        "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
    )
    new_commit = _run("commit-tree", new_tree, "-m", message).strip()

    _run("push", REMOTE, f"{new_commit}:refs/heads/{BRANCH}", "--force")
    print(f"Publié : {new_commit} (version {version})")


if __name__ == "__main__":
    main()
