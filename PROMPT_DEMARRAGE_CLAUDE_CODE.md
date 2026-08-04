# Projet : Extracteur & visualiseur PMSI-SMR (RHS groupé + VID-HOSP)

Copiez-collez ce document tel quel comme premier message à Claude Code, dans le dossier
de votre projet (aux côtés des fichiers `RHS_groupe.csv`, `VID-HOSP.csv`, et d'exemples
réels/anonymisés de fichiers `.RHS` et `.VID`).

---

## 1. Objectif

Construire un outil **portable** (auto-suffisant, aucune dépendance à un chemin absolu)
qui :

1. **Parse** des fichiers texte à largeur fixe (fixed-width) issus du PMSI-SMR :
   - **RHS groupé** (Résumé Hebdomadaire Standardisé, format DAF/ex-OQN)
   - **VID-HOSP** (Valorisation individuelle des données d'hospitalisation)
2. **Stocke** les données extraites dans une base structurée (SQLite recommandé pour la
   portabilité — un seul fichier, pas de serveur à installer).
3. **Génère** des tableaux, graphiques et listes/filtres interactifs façon QlikView/Tableau
   à partir de ces données stockées (exploration croisée, filtres dynamiques, drill-down).
4. **Crée automatiquement toute son arborescence** dans le dossier où le script est lancé
   (aucune installation manuelle de dossiers).

## 2. Fichiers de spécification fournis

- `RHS_groupe.csv` : export brut de l'onglet Excel "RHS groupé" (positions, tailles,
  types, obligations, modalités).
- `VID-HOSP.csv` : export brut de l'onglet Excel "VID-HOSP".

Ces CSV sont le dump fidèle des feuilles Excel officielles de spécification de format
PMSI-SMR 2026. **Avant d'écrire le moindre code de parsing**, lis-les entièrement et
propose-moi ta compréhension du schéma (voir section 4) pour validation.

## 3. Points de complexité connus (à anticiper)

### 3.1 RHS groupé — longueur d'enregistrement variable

La longueur totale d'un enregistrement RHS groupé suit la formule :

```
190 + (8 × n1) + (35 × n2) + (30 × n3) + (23 × n4)
```

où n1, n2, n3, n4 sont eux-mêmes des **champs du bloc fixe** (positions 175-184) :

- `n1` = Nombre de diagnostics associés significatifs (DAS) — positions 175-176
- `n2` = Nombre d'actes CSARR — positions 177-179
- `n3` = Nombre d'actes CSAR — positions 180-182
- `n4` = Nombre d'actes CCAM — positions 183-184

Après le bloc fixe (positions 1 à 190), il faut donc **relire en boucle** :
- n1 fois un bloc DAS de 8 caractères,
- puis n2 fois un bloc CSARR de 35 caractères,
- puis n3 fois un bloc CSAR de 30 caractères,
- puis n4 fois un bloc CCAM de 23 caractères.

Le parseur doit lire n1/n2/n3/n4 en premier, puis calculer dynamiquement les offsets de
chaque bloc répété pour cet enregistrement précis (chaque ligne du fichier peut avoir une
longueur différente selon ses propres n1..n4).

### 3.2 RHS groupé — variables de groupage à lectures multiples sur les mêmes positions

Dans le bloc "Groupage" (positions 53 à 65), plusieurs variables de sortie
(`x²`, `GL`, `GR`, `GN`, `CM`, `Code`, `NR`, `NL`, `sévérité`, `Code retour`,
`Indicateur d'erreur`) partagent ou chevauchent les mêmes plages d'octets, car leur
signification dépend de la **version de classification** (colonne "Version
classification", positions 53-54).

➡️ Le parseur doit lire la version de classification en premier, puis en déduire
comment nommer/interpréter les champs situés en 55-56, 57-58, 59, 60, 61, 62-64, 65 —
c'est-à-dire produire **plusieurs variables de sortie nommées** (CM, GN, GME, etc.) à
partir des mêmes positions source, selon une table de correspondance
version → nom de variable.

Propose-moi le mapping exact que tu déduis du CSV avant de coder cette partie ; je te
confirmerai ou corrigerai.

### 3.3 VID-HOSP — bloc répété "DMT" (disciplines de prestations)

À partir de la position 467, le champ `Nombre de disciplines de prestations (N)` indique
combien de blocs DMT (Discipline Médico-Tarifaire) suivent. Chaque bloc DMT fait
**50 caractères** (3+2+8+8+3+7+8+3+8) et doit être relu N fois en boucle, comme pour les
blocs répétés du RHS groupé.

## 4. Ce que j'attends de toi avant de coder

1. Lis `RHS_groupe.csv` et `VID-HOSP.csv` en entier.
2. Restitue-moi, sous forme de **schéma JSON structuré** (pas de code encore), pour
   chaque format :
   - la liste des champs du bloc fixe (nom, position début/fin, longueur, type, requis),
   - la définition des blocs répétés (nom du champ compteur, largeur du bloc, champs du
     bloc),
   - ta proposition de mapping pour les variables de groupage multi-lues (section 3.2).
3. Attends ma validation avant d'implémenter le parseur.

## 5. Architecture attendue (à créer automatiquement par le script)

```
./ (dossier où le script est lancé)
├── data/
│   ├── raw/              # fichiers sources déposés par l'utilisateur (RHS/VID bruts)
│   ├── processed/        # base(s) SQLite générée(s)
│   └── logs/             # logs de parsing, rejets, erreurs de format
├── config/
│   └── formats/          # schémas JSON des formats (dérivés des CSV de specs)
├── src/
│   ├── parsing/          # lecteurs fixed-width, gestion des blocs répétés
│   ├── storage/          # écriture/lecture SQLite
│   └── viz/               # génération tableaux/graphiques/listes interactives
├── app/                   # application de visualisation (ex. dashboard local)
└── README.md
```

Le script principal doit détecter, au premier lancement, l'absence de cette
arborescence et la créer intégralement (aucune étape d'installation manuelle requise).

## 6. Visualisation façon QlikView/Tableau

- Filtres croisés dynamiques (par établissement, période, unité médicale, type de
  séjour, etc.).
- Tableaux agrégés (ex. nombre de séjours par UM, durée moyenne, répartition CM/GME).
- Graphiques (répartition, évolution temporelle, pyramide des âges, etc.).
- Interface locale, pas de dépendance cloud (ex. dashboard HTML/JS local, ou notebook
  interactif) — à proposer et discuter avant implémentation.

## 7. Contraintes générales

- Code en Python de préférence (ou à discuter).
- Portable : un `pip install -r requirements.txt` (ou équivalent) doit suffire ;
  aucun chemin absolu codé en dur.
- Gestion des erreurs de format : lignes mal formées doivent être journalisées, pas
  bloquer tout le traitement.
- Travailler par petites étapes validées : (1) schéma des formats, (2) parseur +
  stockage, (3) tests sur fichiers réels, (4) couche de visualisation.

---

**Première tâche demandée : étape 4 ci-dessus (restitution du schéma JSON pour
validation), rien d'autre pour l'instant.**
