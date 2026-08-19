# TODO — projet PMSI-SMR

## Référentiels externes à ajouter

- [ ] **Fichier des codes d'erreur de groupage** (`code_retour_groupage` / `indicateur_erreur`
  du RHS groupé) — actuellement on n'affiche que le code brut (ex. `28`) en section 7
  "Erreurs groupage" du tableau de bord, faute du libellé complet (ex. `0028 - Mode
  d'entrée absent ou non numérique`). Ajouter un référentiel (CSV/JSON) code → libellé,
  le charger dans `src/viz/tableau_de_bord.py` (`section_erreurs_groupage`), et l'afficher
  dans `src/viz/render_dashboard.py` à la place du code seul. Utile aussi pour la note
  "séjours en erreur" de la section 5 (voir mémoire `project-pmsi-smr-extractor`, séjour
  024909882 / erreur 0028 découvert le 2026-07-28).

## Variables à ajouter (fichier VisualValoSejours)

- [x] **Montant molécules onéreuses** (`montant_am_med`, alias CSV `MNT_AM_MED`) et
  **montant transport** (`montant_am_trans`, alias CSV `MNT_AM_TRANS`) — exposées comme
  mesures dans le catalogue de l'Explorateur (`SOURCES.valo.measures`, `app/catalogue.js`),
  2026-08-19. Les deux colonnes existaient déjà dans le schéma
  (`config/formats/valorisation_sejour.schema.json`), seule l'exposition au catalogue
  manquait.
- [ ] Même ajout côté tableaux de bord simples (`src/viz/valorisation.py` /
  `render_dashboard.py`) si besoin — pas fait pour l'instant, seul l'Explorateur les propose.

## Autres pistes ouvertes (voir mémoire du projet pour le détail)

- [ ] `Nb CSARR` (section 4, indicateur cumulatif) : formule encore approximative
  (plafond 2/jour), définition ATIH exacte non confirmée — distincte de la section 5
  qui, elle, est validée exacte.
- [ ] `ZZM+092` (assistant social, intervenant 62) : écart résiduel de 1 acte en M03-2026
  non expliqué même après avoir exclu le séjour en erreur 024909882 — cause non identifiée.
- [ ] `Nb moy. interv./RHS` (section 4) : approximation (CSARR+CSAR)/RHS à valider contre
  la définition ATIH exacte.
- [ ] Score RR, Valorisation (PMCT/PMST/PMJT/VALO), Coeff. spécialisation : nécessitent un
  barème CSARR et une grille tarifaire externes — volontairement hors périmètre pour l'instant.
