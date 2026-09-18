# CHANGELOG — SMRXplore

> Notes de la version publiée. L'historique de développement complet
> n'est pas publié sur ce dépôt.

---

### 3.11.1 — Corrige .gitignore : app/formula/ et app/explorer/ jamais suivis par git
`app/*` est ignoré par défaut puis ré-autorisé fichier par fichier ; les
deux dossiers du moteur d'expressions calculées de l'Explorateur (chargés
activement par `explorateur.html`, embarqués via `--add-data` depuis
3.9.0) n'avaient jamais été ajoutés à la liste blanche. Invisible en
local (les fichiers existent sur le disque même non suivis), mais un
clone frais (CI GitHub Actions) ne les a jamais eus — chaque build
SMRXplore CI échouait silencieusement depuis le 2026-09-11, découvert
seulement en poussant le tag `v3.11.0` (échec sur les 4 plateformes,
aucune Release publiée, retagué directement en 3.11.1).
