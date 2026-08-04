#!/usr/bin/env python3
"""Point d'entrée utilisateur final du projet PMSI-SMR.

Démarre un serveur local (aucune dépendance externe, aucun droit
administrateur requis) et ouvre le navigateur sur la page de lancement, qui
propose deux entrées :
  - Tableaux de bord simples : choix d'années (max 3), d'établissements et
    d'un TDB secondaire (par UF ou par type d'hospitalisation HC/HTP) ;
  - Explorateur : requêtage libre existant (sql.js, 100% navigateur).

Contrairement à run.py (pipeline de PARSING des fichiers source, à relancer
par le mainteneur à chaque nouvelle transmission), ce script sert la
RESTITUTION à l'utilisateur final à partir de data/processed/pmsi.db déjà
construit.

Usage :
    python launch.py
"""
from __future__ import annotations

from src.server.app_server import main

if __name__ == "__main__":
    main()
