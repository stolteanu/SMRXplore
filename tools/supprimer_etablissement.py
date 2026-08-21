#!/usr/bin/env python3
"""Supprime complètement un établissement (par FINESS) : base + artefacts générés,
et en option ses fichiers source dans input/.

Contrairement à "charger" (qui ne fait qu'AJOUTER ce qui est déposé dans
input/ — retirer les fichiers d'un établissement du dossier ne le retire PAS
de la base), cet outil purge explicitement toute trace du FINESS donné :
  1. Base pmsi.db :
       - rhs_groupe (+ tables enfants rhs_groupe_* via ON DELETE CASCADE)
       - vid_hosp   (+ tables enfants vid_hosp_* via ON DELETE CASCADE)
       - valorisation_sejour
       - parse_errors (lignes rattachées à ses fichiers source)
  2. Artefacts générés dans app/ (tableaux de bord, annexes, journaux HTML déjà
     produits pour ce FINESS) — toujours purgés : ce sont des sous-produits de
     la base, jamais une source de vérité.
  3. (option --fichiers-source) fichiers source déposés dans input/rhs,
     input/vdh, input/valorisation dont le nom commence par "<FINESS>." —
     PAS supprimés par défaut car ce sont les seuls fichiers non
     régénérables ; il faut le demander explicitement.

tarifs_gmt n'est PAS concerné : c'est une grille tarifaire nationale, commune
à tous les établissements, pas une donnée par FINESS.

Usage :
    python tools/supprimer_etablissement.py <FINESS>
    python tools/supprimer_etablissement.py <FINESS> --fichiers-source
    python tools/supprimer_etablissement.py <FINESS> --oui              (sans confirmation)

Après suppression, il faut relancer :
    python pmsi.py publier
pour répercuter la suppression dans l'explorateur (app/data/pmsi.db).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.util.paths import project_root  # noqa: E402

ROOT = project_root()
DB_PATH = ROOT / "data/processed/pmsi.db"

# Tables portant une colonne finess_epmsi. Les tables enfants (rhs_groupe_das,
# vid_hosp_..., etc.) sont retirées automatiquement par ON DELETE CASCADE —
# cf. sqlite_store.build_create_table_statements.
TABLES_PAR_FINESS = ["rhs_groupe", "vid_hosp", "valorisation_sejour"]

# Dossiers input/ dont les fichiers sont nommés "<FINESS>.<AAAA>.<MM>...." —
# cf. convention décrite dans run.py. input/tarifs exclu : grille nationale,
# pas de FINESS dans le nom.
DOSSIERS_SOURCE = ["input/rhs", "input/vdh", "input/valorisation"]

# app/ : artefacts générés par render_dashboard.py, nommés avec le FINESS.
GLOBS_GENERES = [
    ("app", "tableau_de_bord_{finess}.html"),
    ("app", "annexe_{finess}.html"),
    ("app", "journal_{finess}.html"),
    ("app/generated", "tableau_de_bord_{finess}_*.html"),
]


def compter(conn: sqlite3.Connection, finess: str) -> dict[str, int]:
    counts = {}
    for table in TABLES_PAR_FINESS:
        (n,) = conn.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE finess_epmsi = ?', (finess,)
        ).fetchone()
        counts[table] = n
    return counts


def lister_fichiers_generes(finess: str) -> list[Path]:
    fichiers = []
    for sous_dossier, motif in GLOBS_GENERES:
        dossier = ROOT / sous_dossier
        if dossier.exists():
            fichiers.extend(sorted(dossier.glob(motif.format(finess=finess))))
    return fichiers


def lister_fichiers_source(finess: str) -> list[Path]:
    fichiers = []
    for sous_dossier in DOSSIERS_SOURCE:
        dossier = ROOT / sous_dossier
        if dossier.exists():
            fichiers.extend(sorted(p for p in dossier.iterdir() if p.is_file() and p.name.startswith(f"{finess}.")))
    return fichiers


def supprimer_base(conn: sqlite3.Connection, finess: str) -> dict[str, int]:
    counts = {}
    for table in TABLES_PAR_FINESS:
        cur = conn.execute(f'DELETE FROM "{table}" WHERE finess_epmsi = ?', (finess,))
        counts[table] = cur.rowcount
    conn.execute('DELETE FROM parse_errors WHERE source_file LIKE ?', (f"{finess}.%",))
    conn.commit()
    return counts


def supprimer_fichiers(fichiers: list[Path]) -> int:
    n = 0
    for f in fichiers:
        f.unlink(missing_ok=True)
        n += 1
    return n


def apercu(finess: str, avec_fichiers_source: bool) -> dict:
    """Calcule ce qui serait supprimé pour `finess`, sans rien toucher —
    utilisé par la CLI (avant confirmation) et par l'endpoint web
    /api/supprimer/apercu (même logique, deux présentations)."""
    if not DB_PATH.exists():
        raise SystemExit(f"Base introuvable : {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        lignes = compter(conn, finess)
    finally:
        conn.close()
    fichiers_generes = lister_fichiers_generes(finess)
    fichiers_source = lister_fichiers_source(finess) if avec_fichiers_source else []

    return {
        "finess": finess,
        "avec_fichiers_source": avec_fichiers_source,
        "lignes": lignes,
        "fichiers_generes": [str(f.relative_to(ROOT)) for f in fichiers_generes],
        "fichiers_source": [str(f.relative_to(ROOT)) for f in fichiers_source],
        "rien_a_supprimer": not any(lignes.values()) and not fichiers_generes and not fichiers_source,
    }


def executer(finess: str, avec_fichiers_source: bool) -> dict:
    """Exécute la suppression pour de bon — à n'appeler qu'après confirmation
    explicite (CLI : réponse "o" ; web : deuxième appel après apercu())."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    lignes = supprimer_base(conn, finess)
    conn.close()

    n_generes = supprimer_fichiers(lister_fichiers_generes(finess))
    n_source = supprimer_fichiers(lister_fichiers_source(finess)) if avec_fichiers_source else 0

    return {
        "finess": finess,
        "lignes": lignes,
        "fichiers_generes": n_generes,
        "fichiers_source": n_source,
    }


def _afficher_apercu(a: dict) -> None:
    print(f"Établissement {a['finess']} — à supprimer :")
    print("  Base pmsi.db :")
    for table, n in a["lignes"].items():
        print(f"    {table:<20} {n:>8} ligne(s)")
    print(f"  Artefacts générés (app/) : {len(a['fichiers_generes'])} fichier(s)")
    for f in a["fichiers_generes"]:
        print(f"    {f}")
    if a["avec_fichiers_source"]:
        print(f"  Fichiers source (input/) : {len(a['fichiers_source'])} fichier(s) — SUPPRESSION DÉFINITIVE, non régénérable")
        for f in a["fichiers_source"]:
            print(f"    {f}")
    else:
        print("  Fichiers source (input/) : conservés (relancer avec --fichiers-source pour les supprimer aussi)")


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return

    finess = argv[0]
    options = argv[1:]
    confirme = "--oui" in options or "-y" in options
    avec_fichiers_source = "--fichiers-source" in options

    a = apercu(finess, avec_fichiers_source)
    if a["rien_a_supprimer"]:
        print(f"Aucune trace trouvée pour le FINESS {finess!r} — rien à supprimer.")
        return

    _afficher_apercu(a)

    if not confirme:
        reponse = input(f"\nConfirmer la suppression définitive de {finess} ? [o/N] ").strip().lower()
        if reponse not in ("o", "oui", "y", "yes"):
            print("Annulé.")
            return

    resultat = executer(finess, avec_fichiers_source)

    print(f"\nSupprimé pour {finess} :")
    for table, n in resultat["lignes"].items():
        print(f"  {table:<20} {n:>8} ligne(s)")
    print(f"  Artefacts générés  : {resultat['fichiers_generes']} fichier(s)")
    if avec_fichiers_source:
        print(f"  Fichiers source    : {resultat['fichiers_source']} fichier(s)")
    print(
        "\nPenser à relancer 'python pmsi.py publier' pour répercuter la suppression "
        "dans l'explorateur (app/data/pmsi.db)."
    )


if __name__ == "__main__":
    main()
