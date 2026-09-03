# CHANGELOG — projet PMSI-SMR

> Reconstruction rétroactive du chemin parcouru, en versions incrémentales
> (façon "release notes" logiciel), écrite le 2026-08-18 à la demande de
> l'utilisateur pour servir de base à la définition de l'architecture finale
> du produit et de son périmètre fonctionnel figé. Mise à jour le 2026-09-02
> (2.5.2 → 3.6.1, 47 commits reconstruits depuis la dernière mise à jour).
>
> **Convention de version** (semver appliqué a posteriori, le projet n'a pas
> été tagué au fil de l'eau) :
> - **MAJOR** (x.0.0) = changement d'architecture ou de paradigme (nouveau
>   composant structurant, rupture avec l'existant).
> - **MINOR** (0.x.0) = nouvelle fonctionnalité livrée, compatible avec
>   l'existant.
> - **PATCH** (0.0.x) = correctif, ajustement, affinage d'une fonctionnalité
>   déjà livrée.
>
> Les versions **0.x** couvrent les 10 premiers jours de développement
> (~2026-07-15 → 2026-08-03), avant l'initialisation du dépôt Git — elles
> sont reconstruites à partir de [PROJECT_HISTORY.md](PROJECT_HISTORY.md) et
> des dates de mémoire de session, pas de commits. À partir de **1.0.0**,
> chaque entrée correspond à un commit réel (hash entre parenthèses),
> `git log --reverse` faisant foi pour l'ordre et les dates.
>
> **Note méthodologique (ajoutée 2026-09-02)** : toute mention de
> vérification/validation "contre la référence ATIH" ci-dessous a été
> effectuée **manuellement par l'utilisateur**, jamais par l'assistant en
> analysant lui-même des fichiers de données réels non anonymisés — celui-ci
> a implémenté les calculs, l'utilisateur a comparé le résultat à ses propres
> références et rapporté la concordance ou l'écart à corriger. Les
> identifiants d'établissement et montants réels initialement cités à titre
> d'exemple ont été anonymisés/généralisés dans ce document.

---

## 0.x — Le moteur (pipeline Python, pré-dépôt Git)

Tout ce socle a précédé le premier commit et n'existe dans aucun historique
Git — reconstruit depuis [PROJECT_HISTORY.md](PROJECT_HISTORY.md) §1-5 et la
mémoire du projet.

### 0.1.0 — Schéma des fichiers source
Lecture des specs Excel ATIH (RHS groupé, VID-HOSP), résolution des
ambiguïtés avec l'utilisateur, écriture de
`config/formats/rhs_groupe.schema.json` et `vid_hosp.schema.json`. Aucun
octet de données réelles parsé à ce stade — le schéma est validé *avant*
le code.

### 0.2.0 — Parseur générique + stockage SQLite
[src/parsing/fixed_width.py](src/parsing/fixed_width.py) (parseur piloté
par schéma JSON, pas de logique par format codée en dur) +
[src/storage/sqlite_store.py](src/storage/sqlite_store.py) (`natural_key`
par schéma = contrainte UNIQUE + `INSERT OR REPLACE`, dédoublonnage par
ordre chronologique de chargement, sans code de dédoublonnage écrit à la
main).

### 0.2.1 — Support multi-version des formats
Découverte que les fichiers réels mélangent plusieurs versions de format
(anciennes semaines d'un séjour encore en ancien format). Ajout de
`rhs_groupe_m1c.schema.json` et `vid_hosp_v015.schema.json`, détection de
version ligne par ligne dans `run.py`, insertion toujours sur le schéma
canonique.

### 0.3.0 — Nomenclatures (code → libellé)
Chantier séparé : CIM-10 (+ hiérarchie ClaML), CCAM (+ hiérarchie), CSARR
(+ hiérarchie + intervenants), CSAR (+ hiérarchie + transcodage CSARR↔CSAR
+ intervenants), GME (CM/GN/GR/GL/GME). Politique **dernier-libellé-gagne**
assumée pour toutes. `tools/charger_nomenclatures.py` + registre
`config/nomenclatures/registry.json`.

### 0.3.1 — Correctifs patients/dates (TDB, premiers calculs)
Série de corrections découvertes en confrontant le calcul à la référence
ATIH réelle, chacune documentée pour ne pas se reperdre :
- Mapping mois → semaine ISO fin de mois, corrigé pour être année-variant.
- Clé de dédoublonnage patient : `numero_ipp` (pas le NIR de l'assuré, qui
  peut être partagé par un conjoint co-hospitalisé).
- Sexe patient : `sexe_beneficiaire` direct, jamais dérivé du NIR.
- Âge : `(date_entrée − date_naissance)/365,25` par séjour, moyenne
  non-dédupliquée par patient (suit `avg(G_AGE)` de la référence QlikView).
- Fenêtre de présence patient élargie par la dernière semaine RHS quand le
  dossier PMSI n'a jamais été clôturé côté VID-HOSP.

### 0.4.0 — Moteur de valorisation (v1, répartition uniforme)
Ingestion de l'export ATIH pré-chiffré "VisualValoSéjours"
([src/viz/valorisation.py](src/viz/valorisation.py)). Hypothèse de départ :
répartition uniforme du montant sur les jours de présence RHS du séjour
(`valeur_jour = montant_br_tot / nb_jours_valorisés`).

### 0.4.1 — Correctif majeur : valorisation incrémentale par campagne
**Invalidation de l'hypothèse cumulative** après lecture de la notice
technique ATIH officielle : la valorisation SMR est incrémentale par
campagne (seuls les jours non facturés en N-1 peuvent l'être en N). La
`natural_key` de `valorisation_sejour` passe de `(finess, numadmin)` à
`(finess, numadmin, campagne)`. Vérifié manuellement par l'utilisateur
"sans perte" : somme des valeurs journalières = `SUM(montant_br_tot)`, écart
négligeable.

### 0.5.0 — Tableau de bord fixe, sections 1-6
[src/viz/tableau_de_bord.py](src/viz/tableau_de_bord.py) +
[render_dashboard.py](src/viz/render_dashboard.py). Chaque section validée
chiffre par chiffre par l'utilisateur (manuellement, sur données réelles
anonymisées dans cette documentation) contre le rapport ATIH de référence
(patients, séjours, journées/semaine, indicateurs AVQ, activité
CSARR/intervenant, valorisation).

### 0.6.0 — Refonte visuelle du TDB
Neuf itérations ciblées, chacune vérifiée en navigateur avant la suivante :
palette (fond vert pâle, pas de mode sombre sur ce document), graphique en
spline, audit impression monochrome, échelle Y relative avec graduations
honnêtes, axe secondaire "lits" + lignes de référence, restructuration du
tableau Activité CSARR (année sur année + pondération ATIH), en-têtes de
tableau normalisés, **scission en 3 documents** (TDB principal / annexe
erreurs / journal technique).

---

## 1.x — Le rapport figé + l'infrastructure de diffusion

Premiers commits Git : le TDB est déclaré stable, l'effort se déplace vers
le rendre livrable (exécutable autonome) et vers un second axe de
restitution (exploration libre).

### 1.0.0 — Point de référence : TDB à 9 sections, design gelé
`7ad188d` (2026-08-04)
Premier commit du dépôt. Le tableau de bord fixe est déclaré stable et
versionné comme référence — toute évolution ultérieure du TDB se fait par
diff contre ce point, plus par réécriture.

### 1.1.0 — Serveur de lancement local + TDB secondaire UF/HC-HTP
`3ff4349` (2026-08-04)
Ajout d'un serveur local de lancement et d'un second tableau de bord
ventilé par unité fonctionnelle et par type d'hospitalisation (HC/HTP).

### 1.1.1 — Sources de l'interface trackées dans Git
`62478e1` (2026-08-04)
**Bascule d'architecture silencieuse mais structurante** : c'est ce commit
qui fait entrer dans le dépôt `app/explorateur.html`, `app/app.js`,
`app/catalogue.js`, `app/tdb-choix.html` et sql.js vendored — l'explorateur
interactif (sql.js/WebAssembly, zéro dépendance serveur) existait déjà en
pratique (décision du 2026-07-30, cf. §6 de PROJECT_HISTORY.md) mais
n'était pas encore versionné. Seuls les fichiers *sources* de `app/` sont
suivis, pas les rapports HTML générés.

### 1.2.0 — Build .exe autonome (PyInstaller)
`70e42ea` (2026-08-05)
Chemins rendus compatibles PyInstaller, empaquetage en exécutable autonome
— première étape vers "remis entre les mains d'un non-développeur" (§0 de
PROJECT_HISTORY.md).

### 1.2.1 — Launcher centralisé + correctif de performance critique
`8718504` (2026-08-05)
Centralisation de la mise à jour des données dans le launcher ; correction
d'un bug de performance bloquant.

### 1.3.0 — Exclusion NV_CHAIN/NV_ATTENTE_DTS + colonne « manque à gagner »
`abc5f22` (2026-08-05)
Ces séjours ne doivent pas compter dans le montant BR officiel — exclusion
validée manuellement par l'utilisateur sur plusieurs établissements réels
(anonymisés), avec une colonne dédiée pour rendre visible ce qui est exclu
plutôt que de le faire disparaître silencieusement.

### 1.3.1 — [ESSAI] Estimation des recettes des séjours <90j en cours
`78ad2d5` (2026-08-05)
Marqué "ESSAI" par l'auteur au moment du commit — estimation PMJT sans
boucle, expérimentale.

### 1.3.2 — Affichage de l'estimation comme « Montant BR PT + estimation »
`6bdfb20` (2026-08-05)
Stabilisation de l'essai précédent : présenté comme une estimation
explicitement distincte du montant BR certain, pas mélangé dedans.

### 1.4.0 — Simplification de la section 6 (Valorisation)
`5877245` (2026-08-05)
Réduction à 6 colonnes, renommage PT → PRT pour lever une ambiguïté de
lecture.

### 1.4.1 — Choix du mois de fin de période dans TDB choix
`732b879` (2026-08-05)
Paramètre utilisateur ajouté à l'écran de sélection, avant génération du
rapport.

### 1.5.0 — Ventilation du montant BR TOT par type d'hospitalisation et par UF
`51d2c1c` (2026-08-05)
Ventilation exacte par type d'hospitalisation, approximative (prorata) par
UF dans un premier temps.

### 1.5.1 — Ventilation par UF rendue exacte
`e580d88` (2026-08-05)
Le prorata portait sur les journées de la période seule ; corrigé pour
porter sur TOUTES les journées du séjour, rendant la ventilation par UF
exacte et non plus approximative.

### 1.5.2 — Correctif `valeurs_axe` (énumération des UF)
`5ce7700` (2026-08-05)
Les UF n'étaient énumérées que sur la période affichée, pas sur toute la
base — corrigé pour éviter des UF manquantes dans les filtres/axes.

### 1.6.0 — Regroupement d'UF en services (TDB secondaire)
`9261d51` (2026-08-06)
Permet de replier plusieurs unités fonctionnelles sous un même service dans
le TDB secondaire par UF.

*(Rupture de 11 jours dans l'historique Git : travail réel effectué sur
l'explorateur — modes "Liste filtrée" et "Fiche séjour (NDA)", cf. mémoire
`project-pmsi-smr-explorateur-recherche-nda`, terminé le 2026-08-13 — mais
committé seulement le 2026-08-17, cf. version 1.7.0 ci-dessous.)*

### 1.7.0 — Correctif clé naturelle RHS + matching NDA alphanumérique
`5e91053`, `1644686` (2026-08-17)
Ajout de `numero_unite_medicale` à la `natural_key` RHS (82 RHS récupérés,
valorisation inchangée au centime près) ; correctif du matching
`numero_admin_sejour` sur des valeurs alphanumériques (auparavant supposées
purement numériques).

> Note : les modes **"Liste filtrée"** (filtres multi-critères combinables
> sur les 7 sources) et **"Fiche séjour (NDA)"** (consultation façon
> logiciel de saisie PMSI, façon fiche patient) de l'explorateur ont été
> construits et validés le 2026-08-13, dans la même branche de travail que
> ces correctifs, mais ne portent pas de commit dédié identifiable — leur
> code fait partie de `app/explorateur.html`/`app/app.js` tel que livré
> ci-dessus. Signalé ici pour ne pas perdre la trace de la fonctionnalité.

---

## 2.x — L'explorateur devient un outil de BI graphique

Rupture nette avec l'existant : l'explorateur, jusque-là un simple tableau
croisé + liste/fiche, gagne un moteur de graphiques complet — assez
substantiel pour justifier un changement de version majeure.

### 2.0.0 — Mode Graphique (barres, lignes, camembert, treemap...)
`4d68de1` (2026-08-17)
Plus gros commit du projet (2297 lignes). Ajout d'un 4ᵉ mode à
l'explorateur : rendu graphique direct des résultats du tableau croisé,
premiers types de graphiques (barres, lignes, camembert, treemap).

### 2.1.0 — Extension des types de graphiques + lisibilité
`a0a664d` (2026-08-17)
4 nouveaux types (barres horizontales, bulles, sunburst, Sankey) + travail
de centrage et de lisibilité générale.

### 2.1.1 — Correctif de mise à l'échelle des graphiques
`13b17b2` (2026-08-17)
La taille était plafonnée en dur ; corrigée pour se magnifier librement au
conteneur.

### 2.2.0 — Mode graphique interactif (Plotly.js), fenêtre dédiée
`fa08b8f` (2026-08-17)
Vendoring de Plotly.js en local (`app/lib/plotly.min.js`), ouverture dans
une fenêtre séparée (`app/plotly_viewer.html`) pour l'interaction
(zoom/pan/hover) — en complément, pas en remplacement, du rendu SVG intégré
existant.

### 2.2.1 — Titres et libellés d'axes (Plotly)
`0ddf203` (2026-08-17)

### 2.2.2 — Titres et libellés d'axes (rendu SVG intégré)
`457378b` (2026-08-17)
Même traitement appliqué au rendu SVG pour rester cohérent entre les deux
moteurs de rendu.

### 2.3.0 — Étiquettes de données, couleurs de séries, spline, radar + correctif fan-out
`171df48` (2026-08-18)
Plus gros commit après le 2.0.0 (396 lignes nettes). Deux volets distincts
dans le même commit :
- **Fonctionnel** : étiquettes de données sur les graphiques, palette de
  couleurs par série, type spline, type radar.
- **Correctif de fond** (cf. mémoire
  `pmsi-smr-correctif-fanout-jointure-mesure-croisee`) : les sommes de
  mesures croisées entre sources étaient gonflées par un fan-out de
  jointure (montant × nombre de lignes RHS du séjour) — dédoublonné dans
  `extractValues()`.

### 2.4.0 — Variables de regroupement hiérarchique GME/CSARR/CIM-10
`945a92a` (2026-08-18)
Ajout de variables dérivées (CM/GR/GL, chapitres CSARR/CIM-10) utilisables
comme dimensions de regroupement dans le pivot et les graphiques —
supersédé en partie par 2.5.0 ci-dessous pour le cas spécifique de la
Valorisation croisée.

### 2.5.0 — Répartition des montants Valorisation au jour de présence RHS
`e450862` (2026-08-18)
**Le correctif méthodologique le plus disputé de cette phase** (cf.
mémoire `pmsi-smr-repartition-jour-present-montant-valo`). Le rattachement
RHS↔Valorisation se faisait par séjour/semaine seul, ce qui donnait des
totaux différents selon la variable de regroupement utilisée (GN, GR...).
Remplacé par une répartition au prorata des jours de présence RHS — les
totaux sont désormais identiques quel que soit le regroupement, écart
résiduel marginal entièrement expliqué par des lignes Valorisation sans RHS
correspondant (désalignement de fichiers source, pas une erreur de calcul).
Écart quantifié et vérifié manuellement par l'utilisateur, pas par
l'assistant sur les fichiers réels.

### 2.5.1 — Retrait du bandeau d'avertissement croisement RHS/Valorisation
`18609c2` (2026-08-18)
Bandeau devenu obsolète une fois 2.5.0 vérifié manuellement par l'utilisateur
comme donnant des totaux exacts — retiré, à ne pas réintroduire sans
régression concrète constatée.

### 2.5.2 — Correctif GR/GL/Sévérité (caractère isolé, pas le code cumulé)
`1ce601d` (2026-08-18)
`app/catalogue.js` : le code GR/GL/Sévérité doit être lu comme un caractère
de type isolé dans le code GME, pas comme le code cumulé jusqu'à cette
position.

### 2.6.0 — DMS vraie (durée moyenne de séjour, durée complète)
`2fe2617` (2026-08-18)

### 2.7.0 — Chaque mesure compte sur son propre fichier + période personnalisée
`bfb7c45` (2026-08-18)
Correctif méthodologique de fond : une mesure croisée (ex. "Nombre de DAS")
comptait auparavant via le "meilleur candidat" résolu vers un fichier
tiers puis dédupliqué, ce qui sous-comptait tout fichier détail
(DAS/CSARR/CSAR/CCAM, plusieurs lignes par séjour) et faisait varier le
résultat selon l'onglet de base choisi. Chaque expression compte désormais
sur les lignes réelles de SON PROPRE fichier — seul le croisement RHS→Valo
garde un mécanisme dédié (répartition au jour de présence, la seule clé de
répartition fiable disponible). + période personnalisée (mêmes jour/mois
chaque année, pas seulement "cumulé depuis janvier").

### 2.8.0 — Sous-totaux, validation de période, exports graphiques, mesures Valo manquantes
`1b0640f` (2026-08-19)

### 2.9.0 — Donut, graphiques 3D, mixte barres+lignes, double axe Y
`7877088` (2026-08-19)

### 2.9.1 — Sélecteurs sans défaut implicite + correctif année croisée RHS/Valo
`273d9a8` (2026-08-19)
Plus aucun sélecteur de variable ne présélectionne une valeur par défaut
(risque de génération sur une sélection implicite, jamais voulue) ; correctif
d'un désalignement d'année lors d'un croisement RHS/Valorisation.

### 2.9.2 — Tri chronologique de la semaine sur plusieurs années
`d5cc3fb` (2026-08-19)

### 2.10.0 — [RETIRÉ EN 3.1.2] Moyenne mobile + expressions sur mesure (formule/ratio)
`e342ebe` (2026-08-19)
Première tentative d'une **variable calculée** dans l'Explorateur (formule/
ratio sur une expression) — retirée 5 jours plus tard (3.1.2, `1f9fea0`,
2026-08-24) : "trop confuse en l'état". Précédent direct à garder en tête
pour toute réintroduction future de ce type de fonctionnalité — le problème
n'était pas la faisabilité technique mais l'ergonomie de sélection.

### 2.11.0 — Bouton "Ouvrir dans une nouvelle page", largeur au contenu en export HTML
`7095c07` (2026-08-20)

---

## 3.x — Administration web des données + Explorateur, itérations continues

Rupture nette avec l'existant : jusqu'ici, charger/supprimer des données
était réservé au mainteneur en ligne de commande (`run.py`,
`tools/supprimer_etablissement.py`). L'ajout d'une interface web
d'administration (upload, suppression) est un nouveau composant structurant
— assez substantiel pour justifier le changement de version majeure. Le
reste de cette branche est une longue série d'itérations et de correctifs
sur l'Explorateur (tableau croisé, graphiques, export, thème) — groupés ici
par lot cohérent plutôt qu'un commit = une version, pour rester lisible.

### 3.0.0 — Admin web : upload UI (RHS/VID-HOSP/VisualValoSejours) + suppression d'établissement
`6c2e5e0`, `1f7e7b8` (2026-08-20/21)
Plus besoin de copier des fichiers dans `input/` à la main ni d'utiliser la
CLI pour retirer un établissement — les deux passent par `app/admin.html`.

### 3.0.1 — Sépare montant BR séjour et suppléments (transport/MO/cancéro) dans la valorisation
`a8a4edb` (2026-08-21)

### 3.0.2 — Distingue erreurs bloquantes et avertissements contournables à l'upload
`b28bc1f` (2026-08-21)

### 3.0.3 — Ajoute `date_entree_um` à la clé naturelle `rhs_groupe`
`ba8f09e` (2026-08-21)

### 3.0.4 — Format M1B, exclusion M1C/M1B pour aligner le Nb RHS sur ATIH
`b1b380d` (2026-08-24)

### 3.0.5 — Correctif réinitialisation des variables Explorateur au changement d'établissement
`903b926` (2026-08-24)

### 3.1.0 — Dimensions Explorateur (âge, département, indicateurs nv_*) + regroupements temporels
`4524b17` (2026-08-24)

### 3.1.1 — Clarifie les mesures de comptage DAS/CSARR/CSAR/CCAM
`cce9a59` (2026-08-24)

### 3.1.2 — Retire les expressions Formule/Ratio (trop confuses en l'état)
`1f9fea0` (2026-08-24)
Retrait de la fonctionnalité ajoutée en 2.10.0 — voir la note associée.

### 3.2.0 — Retire la limite de 5 établissements, tout sélectionner/désélectionner, valeurs vides en filtre
`aa9a0ed` (2026-08-25)
+ correctif du libellé des colonnes du tableau croisé et de la valorisation
par groupe d'UF, dans le même commit.

### 3.2.1 — Regroupement/filtre UF du TDB secondaire : case à cocher, historique des noms, perf, contraste
`a60ed07` (2026-08-25)

### 3.2.2 — Groupes UF proposés en case à cocher séparée (décochée par défaut)
`f73283f` (2026-08-25)
Corrige aussi le chevauchement entre groupes.

### 3.2.3 — Correctifs tableau croisé dédoublé + gel navigateur, libellés de variables codées
`6eb6696` (2026-08-26)

### 3.2.4 — Refonte de l'en-tête colonne du tableau croisé (9 itérations rapides)
`125bddd` → `7328ff6` (2026-08-26)
Série resserrée le même jour : annulation d'un correctif de colonne
fantôme qui désalignait les totaux, repositionnement du libellé de
dimension colonne (au-dessus, style standard, répété par groupe, bon
niveau d'imbrication), colonne Total sur toute la hauteur d'en-tête,
sous-totaux par colonne (symétriques des sous-totaux par ligne), correctif
du rowspan sous-total, en-tête collant posé en bloc sur `<thead>`, retrait
du plafond de hauteur, correctif du rendu cassé en export HTML/nouvelle page.

### 3.3.0 — Filtres non présélectionnés, réordonnancement des variables, sticky multi-lignes, retrait export Word
`39ad60a` (2026-08-27)

### 3.3.1 — Option pour masquer les valeurs (vide) des variables
`532c697` (2026-08-27)

### 3.4.0 — Tendance : dégradé/flèche + sparkline sur lignes et colonnes
`207bf89` (2026-08-27)

### 3.4.1 — Thème clair/sombre/système, couleur personnalisable
`9b36af1`, `b9b8e06` (2026-08-27)

### 3.4.2 — Correctifs export Excel (couleurs B&W manquantes, largeur de colonne dynamique)
`68ccb49`, `6b9a0b6` (2026-08-27)

### 3.4.3 — Mémorise la dernière sélection de filtres, années indépendantes des FINESS
`7cef331` (2026-08-28)

### 3.4.4 — Port fixe (8743) pour préserver le stockage local du navigateur
`906d9e0` (2026-08-28)

### 3.4.5 — Sauvegarde automatique de `pmsi.db` avant "charger"/"supprimer"
`195fb86` (2026-08-28)

### 3.4.6 — Tri interactif des lignes du tableau croisé (clic d'en-tête)
`77d58f2` (2026-08-28)

### 3.4.7 — Répartition Valo→UF des séjours 0-jour, libellé "(sans correspondance)"
`9b3e29c` (2026-08-28)

### 3.4.8 — Correctifs graphiques (libellés, étiquettes de données, camembert imbriqué)
`d3a74fd` (2026-08-28)

### 3.5.0 — Option "parts écartées" (exploded) pour camembert/donut/sunburst
`5b4f61c` (2026-09-02)

### 3.6.0 — Déploiement portable SMRXplore (ressources embarquées, exe unique)
`ccf542e` (2026-09-02)
`SMRXPLORE\SMRXplore.exe` redistribuable seul (PyInstaller `--add-data`,
`src/util/paths.py::resource_root()`) — même mécanisme requis, découvert
insuffisamment répercuté sur `launch.exe`, cf. 3.6.1.

### 3.6.1 — Corrige la reconstruction de `launch.exe` (`--add-data` manquant)
`9d9908b` (2026-09-02)
La commande de build documentée pour `launch.exe` ne l'embarquait plus
depuis 3.6.0 — reconstruction silencieusement périmée. `tools/build_launch.py`
ajouté, factorisé avec `tools/deployer_smrxplore.py` dans
`tools/_build_common.py`.

### 3.6.2 — Publication : licence GPL-3.0, README, anonymisation de la documentation
`94a2b90`, `21847e1` (2026-09-02/03) — **dernier commit à ce jour**
Préparation à la publication du dépôt (privé) sur GitHub :
- `LICENSE` (GPL-3.0, verbatim), `README.md`, `THIRD-PARTY-LICENSES.md`
  (Plotly.js et sql.js, toutes deux MIT).
- `CHANGELOG.md`/`PROJECT_HISTORY.md` anonymisés : retrait des identifiants
  d'établissement réels et montants cités à titre d'exemple ; clarification
  que toute comparaison contre une référence ATIH mentionnée dans ces
  documents a été effectuée **manuellement par l'utilisateur**, jamais par
  l'assistant en analysant lui-même des fichiers de données réels non
  anonymisés.
- Historique Git réécrit (`git filter-branch`) pour purger ces mêmes
  identifiants des révisions passées de ces documents avant le premier push
  — l'historique complet d'origine reste conservé localement (jamais poussé)
  pour dépannage interne, voir la mémoire projet dédiée.

### 3.7.0 — SMRXplore multiplateforme (Windows/Linux/macOS)
`37a576c` (2026-09-03) — **dernier commit à ce jour**
Le séparateur `--add-data` de PyInstaller était codé en dur (`;`, syntaxe
Windows uniquement) dans `tools/_build_common.py` — remplacé par
`os.pathsep`, seul changement de code nécessaire (le reste du pipeline
n'utilisait déjà que la bibliothèque standard, sans appel Windows-only).
Nouveau `.github/workflows/build-smrxplore.yml` : construit `SMRXplore` sur
les 3 plateformes en parallèle, déclenché manuellement ou sur un tag
`vX.Y.Z` — jamais automatique à chaque commit, cohérent avec le cycle de
vie "déploiement sur demande" de `SMRXplore.exe`. Testé de bout en bout :
les 3 builds (Windows, Linux, macOS) réussissent sur `master`.

### 3.7.1 — Corrige les binaires publiés (nomenclatures manquantes) + release GitHub
`79aa489`, `c06b2df` (2026-09-03) — **dernier commit à ce jour**
Deux correctifs découverts en testant une vraie release `v3.7.0` :
- Le workflow ne publiait les binaires qu'en artefacts de run (temporaires,
  90 jours), jamais attachés à la Release GitHub elle-même — nouveau job
  `release` (`softprops/action-gh-release`) qui les y publie directement
  sur tag `vX.Y.Z`.
- Plus grave : les binaires construits en CI étaient ~12 Mo plus légers que
  le build local et **non fonctionnels** — sans `data/processed/pmsi.db`
  local (exclu du dépôt), aucune nomenclature ATIH n'était embarquée,
  empêchant toute génération de tableau de bord. Les nomenclatures ATIH
  (CIM-10, CCAM, CSARR, CSAR, GME) sont des données publiques, pas la
  propriété de l'ATIH — leur contenu peut être redistribué sans
  restriction. Ajout de `config/nomenclatures/nomenclatures_seed.db` (extraction des
  tables `nomenclature_*` uniquement, jamais de données patients), utilisé
  en repli par `tools/_build_common.py` pour que tout build (local ou CI)
  produise un exécutable réellement utilisable dès le téléchargement.

### 3.7.2 — Corrige openpyxl manquant dans les builds CI (2e écart de taille)
`2623a86` (2026-09-03) — **dernier commit à ce jour**
Après le correctif 3.7.1, les binaires CI restaient plus légers que le
build local (15 Mo vs 23-27 Mo) — `requirements.txt` affirmait à tort
"bibliothèque standard uniquement" alors que `run.py` importe `openpyxl`
au niveau module (`src/tarifs/gmt.py`, grille tarifaire GMT chargée au
bouton "Mettre à jour" de l'admin web). Installé localement par accident
(jamais déclaré), jamais en CI (`requirements-dev.txt` n'installait que
`pyinstaller`) : les binaires publiés auraient planté au premier
chargement de fichier xlsx. `openpyxl` déclaré dans `requirements.txt`,
workflow CI installe désormais `requirements.txt` + `requirements-dev.txt`.

### 3.7.3 — Corrige le seed nomenclatures committé (vrai bug, silencieux)
`98701ea` (2026-09-03) — **dernier commit à ce jour**
La taille des binaires publiés restait anormalement basse même après 3.7.1 —
en téléchargeant et lançant réellement le binaire de la release `v3.7.2`
(dans un bac à sable isolé, jamais sur ce dépôt), `/api/charger` produisait
un `pmsi.db` sans aucune table `nomenclature_*`. Cause : le fichier committé
en 3.7.1 s'appelait `seed.db`, mais `run.py::seed_nomenclatures()` cherche
`nomenclatures_seed.db` dans le bundle PyInstaller — le seed était bien
embarqué (d'où l'augmentation de taille observée) mais jamais copié dans
`pmsi.db`, échec resté invisible faute de message d'erreur. Renommé
`config/nomenclatures/seed.db` → `nomenclatures_seed.db` ; `run.py` signale
désormais un seed manquant au lieu d'échouer silencieusement. Retesté de
bout en bout après correctif : 16/16 tables `nomenclature_*` présentes,
contenu identique à l'original.

### 3.7.4 — Corrige un module manquant en CI (src.viz.render_dashboard)
`4224066` (2026-09-03) — **dernier commit à ce jour**
Signalé par l'utilisateur en testant le vrai binaire `v3.7.3` : la
génération d'un tableau de bord simple plantait avec `ModuleNotFoundError:
No module named 'src.viz.render_dashboard'`. Comparaison des archives
PyInstaller (`pyi-archive_viewer`) entre le binaire publié et deux
reconstructions locales identiques : le module (importé uniquement à
l'intérieur d'une fonction de `app_server.py`, route déclenchée à la
demande) manquait du binaire CI mais était bien présent en local — même
code, même version de PyInstaller (6.22.2), seule différence connue Python
3.11 (CI) vs 3.12 (local). Détection statique des imports différée
apparemment peu fiable selon l'environnement. Les modules concernés (`run`,
`src.viz.render_dashboard`, `tools.publier_explorateur`,
`tools.supprimer_etablissement`) sont désormais déclarés explicitement en
`--hidden-import`, indépendamment de la détection automatique.

### 3.7.5 — Corrige la VRAIE cause : f-string incompatible Python 3.11 (ligne 496)
`481df62` (2026-09-03) — **dernier commit à ce jour**
Le module manquant persistait malgré 3.7.4 (--hidden-import) — trouvé avec
un script diagnostique autonome exécuté directement en CI (Python 3.11
réel) : `SyntaxError: f-string expression part cannot include a backslash`
à `src/viz/render_dashboard.py:497`, une f-string imbriquée avec des
guillemets échappés dans la partie `{expression}` d'une f-string englobante.
Restriction du langage levée seulement en Python 3.12 (PEP 701) — compile
silencieusement en local (3.12), échoue en CI (3.11 sur les 3 runners).
PyInstaller catche cette `SyntaxError` en interne et exclut le module comme
« invalid » sans erreur visible, d'où l'inefficacité de `--hidden-import`
(force l'inclusion d'un import, pas la compilation d'un fichier syntaxiquement
invalide pour la version Python utilisée). Remplacé par une variable
intermédiaire, même patron que le code équivalent plus bas dans le fichier.
Retesté de bout en bout sur le vrai binaire CI téléchargé : génération de
TDB fonctionnelle.

---

## Où en est le produit maintenant (référence pour l'architecture finale)

### Composants livrés

| Composant | Rôle | Statut |
|---|---|---|
| Pipeline Python (`run.py`, `src/parsing/`, `src/storage/`) | Parse RHS groupé + VID-HOSP + Valorisation, stocke en SQLite, dédoublonne | Stable depuis 0.2.x, mainteneur uniquement |
| Nomenclatures (`src/nomenclatures/`, `tools/charger_nomenclatures.py`) | CIM-10, CCAM, CSARR, CSAR, GME + hiérarchies | Complet depuis 0.3.0 |
| Admin web (`app/admin.html`) | Upload RHS/VID-HOSP/VisualValoSejours + suppression complète d'un établissement, depuis le navigateur | Depuis 3.0.0 |
| Moteur de valorisation (`src/viz/valorisation.py`) | Répartition des montants au jour de présence RHS, par campagne | Stable depuis 0.4.1, affiné en 2.5.0 et 3.0.1 (suppléments séparés) |
| TDB fixe (`src/viz/tableau_de_bord.py`, `render_dashboard.py`) | Rapport officiel, 9 sections, validé cellule par cellule par l'utilisateur (manuellement) contre la référence ATIH | Gelé depuis 1.0.0, patché en 1.x-3.x |
| TDB secondaire UF/HC-HTP | Ventilation par unité fonctionnelle / type d'hospitalisation | Depuis 1.1.0, affiné en 1.5-1.6 et 3.2.x |
| Launcher + build `.exe` (PyInstaller) | Distribution autonome, non-développeur — `launch.exe` (interne) et `SMRXPLORE\SMRXplore.exe` (portable, ressources embarquées) | Depuis 1.2.0, ressources embarquées depuis 3.6.0 |
| Explorateur interactif (`app/`, sql.js/WebAssembly) | 4 modes : Tableau croisé, Liste filtrée, Fiche séjour (NDA), Graphique — 100% front-end statique, zéro serveur à l'usage | Depuis 1.1.1 (base), 2.0.0+ (graphiques), itéré en continu jusqu'à 3.6.x |
| Moteur graphique (SVG intégré + Plotly.js interactif) | 10+ types de graphiques (dont donut, 3D, mixte, sunburst, Sankey, parts écartées), cohérents entre les deux moteurs de rendu | Depuis 2.0.0, complété jusqu'à 3.5.0 |

### Fonctionnalités actuellement couvertes
- Ingestion multi-version, multi-établissement, multi-campagne des 3
  familles de fichiers source — désormais aussi via upload web (Admin), plus
  seulement en copiant des fichiers dans `input/`.
- Résolution code → libellé sur 5 nomenclatures + hiérarchies complètes.
- Valorisation exacte, répartie au jour, robuste à tout regroupement ;
  suppléments (transport/MO/cancéro) distingués du montant séjour.
- Rapport officiel figé (TDB) + rapport secondaire par UF/HC-HTP (regroupement
  d'UF en services, personnalisable).
- Exploration libre : pivot (tri interactif, sous-totaux ligne/colonne,
  tendance), filtres multi-critères inter-sources, fiche séjour détaillée,
  10+ types de graphiques (dont interactifs), thème clair/sombre/système.
- Export HTML/PDF/Excel depuis l'explorateur (export Word retiré en 3.3.0,
  jamais fiable).
- Distribution en exécutable autonome — `launch.exe` (usage interne) ou
  `SMRXPLORE\SMRXplore.exe` (portable, un seul fichier, redistribuable).

### Fonctionnalité tentée puis retirée
- **Expressions Formule/Ratio dans l'Explorateur** (2.10.0 → retirée en
  3.1.2, 2026-08-19→24) : première tentative d'une "variable calculée" —
  jugée trop confuse en l'état par l'utilisateur. Une seconde approche
  (mesure ÷ mesure, prototype dédié) a été explorée et validée
  fonctionnellement le 2026-09-02 avant d'être explicitement annulée par
  l'utilisateur — voir la session correspondante, pas de trace dans le
  dépôt (aucun commit).

### Dette et périmètre explicitement hors scope (voir aussi [TODO.md](TODO.md))
- Score RR / GR officiel non reconstruit (barème ATIH complet manquant).
- `nomenclature_ponderation_actes` : dédoublonnage par natural_key
  contourné à la lecture, pas dans le loader.
- Libellé complet des codes d'erreur de groupage (référentiel non chargé).
- `Nb CSARR` (section 4) : formule approximative, définition ATIH exacte
  non confirmée.
- Pas de tests automatisés (`pytest`) — toutes les validations sont
  manuelles, section par section, contre les documents de référence ATIH.
- Le pipeline de parsing reste Python côté mainteneur — pour une
  application 100% autonome côté utilisateur final (import de ses propres
  fichiers sans intervention du mainteneur), il resterait à l'empaqueter
  ou le porter en partie côté client (WASM).
