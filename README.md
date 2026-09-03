# SMRXplore

**SMRXplore** est le produit portable de ce dépôt : un unique exécutable
autonome (Windows, Linux ou macOS — aucune installation, aucun Python
requis) qui transforme les fichiers de transmission PMSI-SMR (RHS groupé,
VID-HOSP, VisualValoSéjours) en tableaux de bord fiables et en exploration
de données libre, sans dépendance cloud ni serveur externe.

Ce dépôt contient le **code source** — pipeline de traitement, interface,
outils de build. `SMRXplore.exe` est produit à partir de ce code via
`tools/deployer_smrxplore.py` (voir [Obtenir SMRXplore](#obtenir-smrxplore)
ci-dessous) ; c'est ce binaire, pas le dépôt lui-même, qui est destiné à un
utilisateur final.

Développé pour un usage concret en établissement de santé (SSR/SMR),
chaque calcul étant validé contre les documents de référence ATIH plutôt
que supposé correct — voir [CHANGELOG.md](CHANGELOG.md) pour l'historique
détaillé des vérifications et [PROJECT_HISTORY.md](PROJECT_HISTORY.md) pour
l'architecture complète.

## Ce que ça fait

- **Ingestion** multi-version, multi-établissement, multi-campagne des 3
  familles de fichiers source PMSI-SMR (formats largeur fixe + CSV,
  spécifiés par schéma JSON, jamais codés en dur).
- **Valorisation** exacte, répartie au jour de présence, robuste à tout
  regroupement — vérifiée au centime près contre des références ATIH
  externes.
- **Tableau de bord officiel** (9 sections, HTML), figé et versionné comme
  référence, + un second tableau de bord ventilé par unité fonctionnelle ou
  type d'hospitalisation.
- **Explorateur interactif** (tableau croisé, listes filtrées, fiche séjour,
  graphiques — 10+ types) tournant **100 % dans le navigateur** via sql.js
  (WebAssembly), aucun serveur nécessaire une fois les données chargées.
- **Administration web** (upload de fichiers, suppression d'un
  établissement) sans passer par la ligne de commande.

## Confidentialité des données

Aucune donnée patient ne quitte jamais la machine locale : pas d'appel
réseau, pas de service cloud, aucune bibliothèque chargée depuis un CDN
(tout est embarqué localement, voir [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md)).
Les fichiers source et la base SQLite générée restent sur disque, sous
votre contrôle exclusif — voir `.gitignore` pour la liste de ce qui n'est
jamais versionné (données patients réelles, bases générées, sauvegardes).

## Obtenir SMRXplore

`SMRXplore` (`SMRXplore.exe` sous Windows, `SMRXplore` sous Linux/macOS)
embarque tout le nécessaire (interface, bibliothèques, schémas de
référentiels) en un seul fichier — voir `tools/deployer_smrxplore.py` pour
le détail (PyInstaller `--add-data`, aucune dépendance externe conservée à
côté de l'exécutable). Le projet est **multiplateforme** : même code
source, un binaire natif par plateforme (pas de compilation croisée
possible avec PyInstaller — chaque binaire doit être construit sur son OS
cible).

- **Via une version publiée** (Releases GitHub, quand disponible) :
  télécharger le binaire correspondant à votre plateforme et à la version
  souhaitée.
- **Via GitHub Actions** ([`.github/workflows/build-smrxplore.yml`](.github/workflows/build-smrxplore.yml)) :
  déclenchement manuel (onglet *Actions* → *Run workflow*) ou sur un tag
  `vX.Y.Z`, construit les 3 binaires (Windows, Linux, macOS) en parallèle
  et les attache au run en artefacts téléchargeables.
- **En le construisant vous-même**, depuis ce dépôt (sur la plateforme
  cible — Windows pour `SMRXplore.exe`, Linux/macOS pour `SMRXplore`) :
  ```bash
  python -m pip install -r requirements-dev.txt
  python tools/deployer_smrxplore.py
  ```
  Produit `SMRXPLORE/SMRXplore(.exe)`, reconstruit à partir de l'état
  courant du code source (`app/`, `src/`, `config/`) — chaque publication
  est rebuilée à la demande depuis la dernière version de travail validée,
  jamais un binaire archivé séparément du code qui l'a produit.

Au premier lancement, `SMRXplore` crée à côté de lui son propre bac à
sable (`input/`, `data/`, `output/`, `backups/`) — rien n'est écrit
ailleurs sur la machine.

## Développement (contribuer au code source)

Point d'entrée unique côté source (voir `python pmsi.py` sans argument pour
l'aide complète) :

```bash
python pmsi.py tout          # nomenclatures + chargement + tableaux de bord + publication — usage quotidien
python pmsi.py dashboard     # régénère le tableau de bord d'un établissement
python launch.py             # lance le serveur local depuis les sources (sans passer par un exe)
```

Aucune dépendance externe requise pour le pipeline (bibliothèque standard
Python uniquement — voir `requirements.txt`, portable Windows/Linux/macOS).
`requirements-dev.txt` n'est nécessaire que pour construire un exécutable
(`SMRXplore(.exe)` via `tools/deployer_smrxplore.py`, ou `launch(.exe)` —
variante interne pour tester sur cette machine sans passer par
`python launch.py`, jamais publiée — via `tools/build_launch.py`).

## Prérequis

Aucun — les référentiels ATIH (CIM-10, CCAM, CSARR, CSAR, GME) sont des
données **publiques** et sont embarqués directement dans `SMRXplore` (voir
[THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md)). Pour la maintenance du
dépôt (mise à jour d'une nomenclature), voir `python pmsi.py nomenclatures`
et `config/nomenclatures/seed.db`.

## Licence

Copyright (C) 2026 D3f1ant — distribué sous licence [GPL-3.0](LICENSE)
(nom d'auteur repris de l'identité Git configurée sur ce dépôt ; à
remplacer par votre nom légal ou raison sociale si vous préférez avant de
publier). Bibliothèques tierces embarquées (Plotly.js, sql.js, toutes deux
MIT) documentées dans [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).

## État du projet

Projet personnel, développé et maintenu par son auteur. Pas de tests
automatisés — toutes les validations sont manuelles, section par section,
contre les documents de référence ATIH (voir [CHANGELOG.md](CHANGELOG.md),
section "Dette et périmètre explicitement hors scope" pour le détail des
limites connues).
