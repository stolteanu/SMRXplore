#!/usr/bin/env python3
"""Point d'entrée unique du projet PMSI-SMR — une seule commande à retenir.

Usage :
    python pmsi.py                    affiche cette aide
    python pmsi.py nomenclatures      charge/actualise les nomenclatures (rare : nouvelle
                                       version ATIH annuelle — CIM-10, CCAM, CSARR, CSAR, GME...)
    python pmsi.py charger            crée pmsi.db si besoin et charge les nouveaux fichiers
                                       RHS/VID-HOSP/Valorisation/Tarifs déposés dans input/
                                       (mensuel, à chaque nouvelle transmission)
    python pmsi.py dashboard [FINESS] génère le tableau de bord HTML pour un établissement
                                       (par défaut : le premier établissement trouvé en base)
    python pmsi.py publier            republie une copie de pmsi.db pour l'explorateur interactif
                                       (app/explorateur.html) — à relancer après chaque "charger"
    python pmsi.py supprimer <FINESS> purge un établissement de pmsi.db + artefacts générés (app/)
                                       (retirer ses fichiers de input/ ne suffit pas : "charger"
                                       n'ajoute que ce qu'il trouve, il ne supprime jamais rien) ;
                                       ajouter --fichiers-source pour aussi effacer ses fichiers
                                       source dans input/ (définitif, non régénérable — pas
                                       supprimé par défaut)
    python pmsi.py sauvegarder        copie pmsi.db vers backups/ (horodatée, 5 dernières gardées) ;
                                       déclenchée automatiquement avant "charger" et "supprimer",
                                       inutile en usage normal — utile avant une manip risquée
    python pmsi.py tout               enchaîne nomenclatures + charger + dashboard (tous les
                                       établissements) + publier, dans le bon ordre — la commande
                                       à utiliser au quotidien

Remarque : il n'y a pas de commande "init" séparée — "charger" crée la base et ses tables
tout seul si elles n'existent pas encore (relancer "charger" plus tard ne les recrée pas,
sans danger).
"""
from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def cmd_nomenclatures(args: list[str]) -> None:
    from tools.charger_nomenclatures import main as charger_nomenclatures_main

    charger_nomenclatures_main()


def cmd_charger(args: list[str]) -> None:
    from run import main as charger_main

    charger_main()


def cmd_dashboard(args: list[str]) -> None:
    from src.viz.render_dashboard import main as dashboard_main

    finess = args[0] if args else None
    dashboard_main(finess)


def cmd_publier(args: list[str]) -> None:
    from tools.publier_explorateur import main as publier_main

    publier_main()


def cmd_supprimer(args: list[str]) -> None:
    from tools.supprimer_etablissement import main as supprimer_main

    supprimer_main(args)


def cmd_sauvegarder(args: list[str]) -> None:
    from tools.sauvegarder_db import main as sauvegarder_main

    sauvegarder_main()


def cmd_tout(args: list[str]) -> None:
    from src.viz.tableau_de_bord import connect, list_finess
    from src.util.progress import print_progress

    print("=== 1/4 nomenclatures ===")
    cmd_nomenclatures([])

    print("\n=== 2/4 charger ===")
    cmd_charger([])

    print("\n=== 3/4 dashboard (tous les établissements) ===")
    conn = connect()
    finess_list = list_finess(conn)
    conn.close()
    for i, finess in enumerate(finess_list, start=1):
        cmd_dashboard([finess])
        print_progress(i, len(finess_list), "Dashboards", detail=finess)

    print("\n=== 4/4 publier ===")
    cmd_publier([])


COMMANDS = {
    "nomenclatures": cmd_nomenclatures,
    "charger": cmd_charger,
    "dashboard": cmd_dashboard,
    "publier": cmd_publier,
    "supprimer": cmd_supprimer,
    "sauvegarder": cmd_sauvegarder,
    "tout": cmd_tout,
}


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return

    cmd, rest = argv[0], argv[1:]
    if cmd not in COMMANDS:
        print(f"Commande inconnue : {cmd!r}\n")
        print(__doc__)
        raise SystemExit(1)

    COMMANDS[cmd](rest)


if __name__ == "__main__":
    main()
