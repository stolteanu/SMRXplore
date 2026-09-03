# Historique et architecture du projet PMSI-SMR

> Reconstruction chronologique du projet, du premier fichier source jusqu'à
> l'état actuel — écrite le 2026-07-30 à la demande de l'utilisateur, pour
> retrouver le fil du plan quand plusieurs sessions de conversation se sont
> succédé. Ce document est la source de vérité sur "où on en est et pourquoi",
> à mettre à jour à chaque jalon important plutôt que de laisser cette
> information dispersée dans l'historique de conversation.
>
> **Note méthodologique (ajoutée 2026-09-02)** : toute comparaison contre un
> document de référence ATIH mentionnée ci-dessous a été effectuée
> **manuellement par l'utilisateur**, en dehors des sessions avec l'assistant
> — celui-ci n'a jamais lui-même ouvert ni analysé de fichier de données réel
> non anonymisé ; il a implémenté les calculs selon la spécification, et
> l'utilisateur a rapporté le résultat de sa propre vérification (concordance
> ou écart à corriger). Les identifiants d'établissement et montants
> initialement cités à titre d'exemple ont été anonymisés/généralisés.
>
> Les fichiers source (RHS groupé, VID-HOSP, VisualValoSéjours) ont été
> anonymisés en dehors de toute session avec l'assistant Claude, avant tout
> partage de fichier réel. Le procédé : NDA, NIR/numéro d'immatriculation et
> IPP sont régénérés à partir d'une seed aléatoire, en conservant la
> correspondance entre les trois fichiers source (même identifiant réel →
> même pseudonyme partout) ; la date de naissance est décalée d'un nombre de
> jours aléatoire entre -5 et +5 ; la commune de résidence est randomisée en
> conservant le département.

## 0. Objectif final (le "souhait")

> Une application web **indépendante** qui permet de construire des
> **tableaux de bord dynamiques** à partir de fichiers source PMSI-SMR, selon
> des **règles préétablies** (schémas, nomenclatures, méthodes de calcul
> validées) — pas un script jetable, un vrai outil réutilisable mois après
> mois, remis entre les mains d'un non-développeur.

Trois qualités recherchées dès le départ, chacune tracée dans les décisions
d'architecture ci-dessous :
- **Portable** : pas de dépendance cloud, aucun chemin absolu codé en dur,
  auto-création de son arborescence.
- **Fiable** : chaque calcul est validé contre un document de référence ATIH
  réel avant d'être considéré comme acquis (voir §4).
- **Autonome à terme** : le pipeline de parsing reste en Python (mainteneur),
  mais la restitution/exploration doit pouvoir tourner sans serveur, dans un
  navigateur, à partir d'un simple dossier remis à l'utilisateur final (voir
  §6, sql.js).

---

## 1. Les fichiers source (le point de départ)

Trois familles de fichiers, un jeu par établissement × mois de transmission :

| Fichier | Contenu | Repère | Dossier |
|---|---|---|---|
| **RHS groupé** | 1 ligne = 1 semaine ISO d'hospitalisation d'un séjour SSR (activité, actes CSARR/CSAR/CCAM, diagnostics, groupage GME) | `<FINESS>.<AAAA>.<MM>.rhs.<horodatage>.txt` | `input/rhs/` |
| **VID-HOSP** | 1 ligne = 1 séjour (identité patient, dates d'entrée/sortie, disciplines de prestation) | `<FINESS>.<AAAA>.<MM>.vdh.<horodatage>.txt` | `input/vdh/` |
| **VisualValoSéjours** | 1 ligne = 1 séjour, export ATIH déjà chiffré (montants BR/AM, jours valorisés) | `<FINESS>.<AAAA>.<MM>.SMR.VisualValoSejours.csv` | `input/valorisation/` |

Deux établissements réels (anonymisés dans ce document) servent de jeu de
test tout du long, chacun avec 3 transmissions mensuelles (2024, 2025, 2026)
couvrant un format ancien (pré-mars 2025) et un format récent — utile pour
valider le parsing multi-version dès le départ plutôt qu'après coup.

Chaque fichier est un format **largeur fixe** (RHS/VID-HOSP) ou CSV
(valorisation), documenté par des specs Excel ATIH officielles
(`input/formats/standard/`, `RHS_groupe.csv`, `VID-HOSP.csv`) — jamais du
"reverse engineering" à l'aveugle : toute règle de découpage vient d'abord de
la spec, puis est confrontée aux fichiers réels.

---

## 2. Phase 1 — Comprendre le format avant de coder (schéma)

**Étape validée avant tout code de parsing.** Les specs Excel ATIH sont
ambiguës par endroits (variables versionnées, références croisées vers une
norme B2 externe) — chaque ambiguïté a été résolue avec l'utilisateur avant
d'écrire le schéma définitif, jamais devinée :

- Position 55-61 du RHS groupé : un seul champ atomique `code_gme`, pas 5
  variables alternatives comme les en-têtes CSV le suggéraient — confirmé
  directement par l'utilisateur.
- Formule de longueur RHS groupé : `190 + 8·n1 + 35·n2 + 30·n3 + 23·n4`
  (blocs DAS/CSARR/CSAR/CCAM répétés).
- Formule VID-HOSP : `470 + 50·N` (blocs DMT répétés).
- Anomalie réelle tolérée dès le schéma : un `.` littéral dans un champ
  numérique `prix_unitaire` cassé côté source → le parseur logue et garde la
  valeur brute plutôt que de rejeter la ligne (principe appliqué partout
  depuis : ne jamais faire planter le pipeline sur une donnée source
  imparfaite, la signaler).

**Livrable** : `config/formats/rhs_groupe.schema.json`,
`config/formats/vid_hosp.schema.json` — le schéma est la seule source de
vérité pour le découpage, jamais dupliqué en dur dans le code de parsing
([src/parsing/fixed_width.py](src/parsing/fixed_width.py) est générique,
piloté par schéma).

**Découverte ultérieure (multi-version)** : les fichiers réels mélangent
plusieurs versions de format dans un même envoi (une transmission renvoie
tout l'historique d'un séjour, donc d'anciennes semaines en ancien format
cohabitent avec les nouvelles). Deux schémas supplémentaires ajoutés après
coup, dès qu'un fichier 2025 plus ancien a révélé le besoin :
`rhs_groupe_m1c.schema.json` (187 caractères, pas de bloc CSAR — CSAR
n'existait pas encore) et `vid_hosp_v015.schema.json` (468 caractères).
[run.py](run.py) détecte la version ligne par ligne (positions fixes lisant
le code version) et route vers le bon schéma de PARSING, mais insère
toujours avec le schéma CANONIQUE (les champs absents d'une variante
deviennent NULL naturellement).

---

## 3. Phase 2 — Parser + stockage

- [src/parsing/fixed_width.py](src/parsing/fixed_width.py) : parseur
  générique piloté par schéma JSON (pas de parsing spécifique par format
  codé en dur).
- [src/storage/sqlite_store.py](src/storage/sqlite_store.py) : chaque schéma
  déclare une `natural_key` — devenue la clé UNIQUE de la table SQLite, avec
  `INSERT OR REPLACE`. Chargement des fichiers en ordre **chronologique**
  (nom de fichier trié) ⇒ la transmission la plus récente écrase
  naturellement les semaines/séjours qui se recoupent entre deux envois. Pas
  de logique de dédoublonnage écrite à la main : c'est une propriété de
  l'ordre de chargement + de la contrainte UNIQUE.
- **Vérifié manuellement par l'utilisateur** (chargement de deux
  transmissions successives sur données réelles, chiffres anonymisés ici) :
  le nombre de lignes RHS effectivement stockées après chargement du second
  fichier était cohérent avec le chevauchement attendu entre les deux
  transmissions (ni trop, ni pas assez de lignes dédupliquées).

---

## 4. Phase 3 — Nomenclatures (code → libellé)

Chantier séparé du pipeline RHS/VID-HOSP, avec sa propre convention : chaque
nomenclature vit dans `input/nomenclatures/<type>/`, chargée par
[tools/charger_nomenclatures.py](tools/charger_nomenclatures.py) via un
registre (`config/nomenclatures/registry.json`), politique
**dernier-libellé-gagne** assumée pour toutes (seule la version en vigueur
compte, pas d'historique multi-année conservé) — les tables de FAITS gardent
les codes bruts, la résolution en libellé se fait uniquement à l'affichage.

| Nomenclature | Source | Statut |
|---|---|---|
| CIM-10 (diagnostics) | Kit ATIH + XML ClaML (hiérarchie) | ✅ 42 897 codes, 11 969 nœuds |
| CCAM | Fichier complémentaire ATIH | ✅ 8 843 codes, 1 699 nœuds |
| CSARR (+ hiérarchie + intervenants) | Fichier complémentaire ATIH | ✅ 539 actes |
| CSAR (+ hiérarchie + transcodage CSARR + intervenants) | Fichier ATIH + guide PDF | ✅ 146 actes |
| GME (CM/GN/GR/GL/GME) | `TOTAL_listes_groupes.xlsx` | ✅ 2 559 nœuds |
| Intervenants CSARR/CSAR | Listes fournies par l'utilisateur (pas de source ATIH structurée) | ✅ 32 + 34 codes |
| FG (codes erreur de groupage) | `FG_erreurs.TXT` | ✅ 184 codes + actes concernés |
| Pondérations actes (`ACTES_ponderations`) | Fichier ATIH | ✅ chargé, non dédupliqué par version (voir limite ci-dessous) |

**Chaque item a été vérifié manuellement par l'utilisateur**, pas juste
chargé : comptage de lignes attendu vs obtenu, reconstruction d'une chaîne
hiérarchique connue et comparaison avec l'exemple du fichier source (ex. GME
`0103LA0` → GL → GR → GN → CM, vérifié champ par champ contre la première
ligne du fichier ATIH par l'utilisateur, pas par l'assistant).

**Limite connue et documentée** (pas une régression, une dette identifiée) :
`nomenclature_ponderation_actes` n'a jamais reçu son propre passage de
dédoublonnage par natural_key comme les autres nomenclatures (54 codes ont
plusieurs versions par date de validité `debut`/`fin`) — contournée en 2026-
07-30 par une politique dernier-gagne appliquée à la lecture (dans
[tableau_de_bord.py](src/viz/tableau_de_bord.py), pas dans le loader), le
temps de statuer si une vraie modélisation temporelle est nécessaire.

---

## 5. Phase 4 — Le tableau de bord, validé section par section

**Principe de méthode, tenu tout du long** : chaque section du TDB reproduit
un tableau du rapport ATIH de référence fourni par l'utilisateur (établissement
anonymisé dans ce document), et n'est déclarée "faite" qu'après comparaison
chiffre par chiffre **effectuée manuellement par l'utilisateur** — jamais
"ça a l'air bon", et jamais une comparaison réalisée par l'assistant
lui-même sur les fichiers réels.

| Section | Calcul | Vérifié manuellement par l'utilisateur contre |
|---|---|---|
| 1 · Patients | Dédup par `numero_ipp`, chevauchement de période | Totaux mensuels du rapport ATIH de référence |
| 2 · Séjours | Nb SSR/RHS/journées, DMH, NbLits moy, EXH | Mois par mois, exact |
| 3 · Journées de présence/semaine | Comptage RHS par flags jour | Graphe, cf. §7 pour les évolutions visuelles |
| 4 · Indicateurs | AVQ (somme d'items), Nb diag, Nb CSARR (plafond 2/j) | AVQ + Nb diag exacts ; Nb CSARR résiduel marginal |
| 5 · Activité CSARR/intervenant | Comptage brut, sans dédoublonnage | Rapport ATIH "Activité CSARR par intervenant" |
| 6 · Valorisation | Montant BR pro-rata + PMCT/PMST/PMJT | Cohérence interne (somme journalière = `SUM(montant_br_tot)`), voir §5bis |

**Corrections notables en cours de route** (le genre de détail qui, sans
trace écrite, se reperd d'une session à l'autre) :
- Âge patient : d'abord `année(fin période) − année(naissance)` (proxy
  grossier), corrigé en `(date_entrée − date_naissance)/365,25` par séjour,
  ET la moyenne d'âge n'est PAS dédupliquée par patient (elle suit
  `avg(G_AGE)` de la référence QlikView, qui moyenne sur chaque séjour).
- Clé de dédoublonnage patient : `numero_ipp`, pas
  `numero_immatriculation_assure` (NIR de l'ASSURÉ, peut être celui d'un
  tiers — ex. conjoint co-hospitalisé).
- Sexe patient : `sexe_beneficiaire` directement, jamais dérivé du 1er
  chiffre du NIR (qui est celui de l'assuré, pas forcément le bénéficiaire).
- Fenêtre de présence patient étendue par la dernière semaine RHS quand le
  dossier PMSI n'a jamais été clôturé côté VID-HOSP (anomalie réelle
  identifiée et documentée par l'utilisateur sur un séjour précis, pas
  corrigée à la source — identifiant anonymisé dans ce document).
- Le mapping mois → semaine ISO de fin suit la règle "le jeudi de la semaine
  détermine son mois" — année-variant (semaine 17 en 2025, semaine 18 en
  2026 pour fin avril), un bug de mapping fixe a été détecté et corrigé ici.

### 5bis. La valorisation (montant BR), le sous-chantier le plus disputé

Hypothèse de départ : les montants d'une transmission sont un total cumulatif
(comme RHS/VID-HOSP, dernier-gagne). **Invalidée** après lecture de la
notice technique ATIH officielle (`input/documentation/`) : la valorisation
SMR est **incrémentale par campagne** — seuls les jours non facturés en N-1
peuvent l'être en N. Conséquence directe sur le schéma : la
`natural_key` de `valorisation_sejour` est passée de
`(finess, numadmin)` à `(finess, numadmin, campagne)`, chaque campagne gardant
sa propre ligne au lieu de s'écraser. Le moteur pro-rata
([src/viz/valorisation.py](src/viz/valorisation.py)) répartit le montant de
chaque campagne uniquement sur SES jours de présence RHS (attribués par
année civile du dimanche de la semaine RHS, règle ATIH p.34-35) — vérifié
manuellement par l'utilisateur "sans perte" : la somme des valeurs
journalières distribuées reproduit `SUM(montant_br_tot)`, à un écart
négligeable près (séjours "zéro jour" connus).

**Bug de filtrage établissement corrigé le 2026-07-30** au moment d'ajouter
la section 6 du TDB : `valeur_sur_periode()` ne filtrait par aucun FINESS —
dans le TDB multi-établissements, ça sommait TOUS les établissements de la
base. Paramètre `finess` ajouté partout dans le module.

---

## 6. Le deuxième axe : l'explorateur interactif (sql.js)

Décision d'architecture du 2026-07-30, distincte du TDB fixe : plutôt qu'un
serveur Python pour l'exploration ad hoc (pivot table, dimensions/mesures
libres), **sql.js (SQLite → WebAssembly)** tourne directement dans le
navigateur contre une copie de `pmsi.db` — zéro dépendance serveur à l'usage,
juste un dossier `app/` à double-cliquer. C'est la première brique concrète
vers l'objectif "application web indépendante" du §0 : le pipeline de
parsing reste Python (côté mainteneur, `run.py`), mais la **restitution**
(TDB fixe + explorateur libre) est déjà 100% front-end statique.

- `app/explorateur.html` + `app/catalogue.js` + `app/app.js`, sql.js vendored
  localement (pas de CDN).
- Pivot : dimensions/mesures/agrégations construites côté client en JS
  (évite les limites de sql.js sur les agrégats custom type MEDIAN).
- Fallback `<input type=file>` pour le cas `file://` où `fetch()` est bloqué
  par le navigateur.
- Export HTML/PDF (`window.print()`)/Word (polyglotte MHTML) — sans build
  step, aucune lib externe vendée pour ça.
- Comparaison multi-établissements (jusqu'à 5) ajoutée en v1.2.

**Décision explicite de l'utilisateur** : le TDB fixe (sections 1-6) reste
le rapport "officiel", validé cellule par cellule, **non retouché** pour
suivre les envies d'exploration libre — l'explorateur est l'outil complé-
mentaire pour tout ce que le TDB fixe ne couvre pas.

---

## 7. Chantier en cours : refonte visuelle du TDB (2026-07-30, cette session)

Point de départ : demande de refonte "le plus de données synthétiques, de
façon visuelle et intuitive" — traité par une longue série d'itérations
ciblées plutôt qu'une refonte en un coup, chacune vérifiée visuellement
(navigateur) avant de passer à la suivante :

1. Palette : thème sombre remplacé par un fond vert pâle ("oeuf d'oie") +
   texte noir (l'utilisateur n'aime pas le mode sombre sur ce TDB précis).
2. Graphique section 3 : lignes brisées → courbes spline (Catmull-Rom),
   contraste des couleurs renforcé, distinction par forme/style de trait (pas
   seulement la couleur) pour rester lisible en impression N&B.
3. Impression monochrome : audit complet, correctif de spécificité CSS
   critique découvert en testant (le thème sombre gagnait quand même à
   l'impression sans le `!important` sur les variables).
4. Échelle Y relative (zoomée sur la plage réelle, pas 0→max) — testée à la
   demande explicite ("on revient en arrière si pas bien"), gardée après
   validation visuelle, avec graduations chiffrées pour rester honnête sur
   l'absence de zéro.
5. Axe secondaire "lits" (journées/7) + 3 lignes de référence
   moyenne/min/max.
6. Tableau 5 (Activité CSARR) restructuré : classement par année → comparaison
   année sur année par intervenant, + pondération ATIH (score pondéré avec
   modulateurs de lieu) ajoutée après clarification explicite de l'utilisateur
   sur ce que "pondération" devait vouloir dire.
7. En-têtes de tableau : gras, centrés, ligne de séparation épaisse, ligne de
   Total en pied de tableau.
8. Restructuration en **3 documents séparés** : TDB principal (activité),
   **annexe** (identification d'erreurs — incohérences VID-HOSP/RHS,
   contenu des séjours en erreur), **journal** (détail technique complet de
   chaque note — dates de validation, sources, méthodologie — pour le debug
   uniquement). Séparation stricte : le TDB ne garde que les définitions
   indispensables à la lecture des tableaux/graphiques, indépendantes de
   l'établissement/période affichés ; tout le reste (dates, formats,
   méthodologie) va au journal.
9. Nettoyage des redondances entre notes/annexe/pied de page (2026-07-30,
   juste avant ce document) : pied de page réduit à la seule liste des
   fichiers source (RHS groupé, VID-HOSP, VisualValoSéjours).

---

## 8. Où on en est / ce qu'il reste pour atteindre le §0

**Fait** : schéma + parsing + stockage dédupliqué, 6 nomenclatures complètes,
moteur de valorisation pro-rata vérifié manuellement par l'utilisateur, TDB
fixe validé section par section contre la référence ATIH (comparaison
effectuée par l'utilisateur, jamais par l'assistant sur des fichiers réels),
annexe + journal séparés, explorateur interactif sql.js sans dépendance
serveur.

**Pas encore fait**, dans l'ordre où ça a été évoqué ou où le manque se
fait sentir :
- Score RR / GR officiel non reconstruit (barème complet manquant : listes
  d'actes spécialisés par GN, seuils GR, CMA — fichiers identifiés dans la
  notice ATIH mais pas encore chargés ; actuellement seul un "score pondéré"
  approximatif existe, section 5).
- `nomenclature_ponderation_actes` : vraie déduplication par natural_key
  encore à faire (contournée à la lecture, voir §4).
- Le pipeline de PARSING (`run.py`) reste Python — pour une application
  100% autonome, il faudrait soit l'empaqueter (installeur portable), soit
  le porter en partie côté client (WASM) si l'utilisateur final doit un jour
  charger ses propres fichiers RHS/VID-HOSP sans l'intervention du
  mainteneur.
- Pas de tests automatisés formels (`pytest` etc.) — les validations sont
  jusqu'ici manuelles, section par section, contre les documents de
  référence ATIH ; à formaliser si le projet doit survivre à plusieurs
  mainteneurs.
