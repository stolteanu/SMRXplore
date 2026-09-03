# Licences tierces

Ce projet est distribué sous licence GPL-3.0 (voir [LICENSE](LICENSE)). Il
embarque deux bibliothèques tierces, toutes deux sous licence MIT
(compatible avec la GPL-3.0) — textes complets ci-dessous, reproduits
verbatim depuis leurs dépôts officiels respectifs.

## Plotly.js (`app/lib/plotly.min.js`)

Source : https://github.com/plotly/plotly.js

```
MIT License

Copyright (c) 2016-2024 Plotly Technologies Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## sql.js (`app/lib/sql-wasm.js`, `app/lib/sql-wasm.wasm`)

Source : https://github.com/sql-js/sql.js

```
MIT license

Copyright (c) 2017 sql.js authors (see AUTHORS)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS," without any guarantees, express or implied, covering merchantability, fitness for a particular purpose, or non-infringement. In no event shall authors or copyright holders be liable for claims, damages, or other liabilities, whether in contract, tort, or otherwise, arising from the software or its use.
```

sql.js elle-même compile SQLite (domaine public) en WebAssembly via
Emscripten — aucune obligation de licence supplémentaire pour SQLite.

## Nomenclatures ATIH (`config/nomenclatures/`)

Ce dossier contient les **schémas JSON décrivant le format** des
référentiels publiés par l'ATIH (CIM-10, CCAM, CSARR, CSAR, GME) — noms de
colonnes, types, clés naturelles — ainsi qu'un **seed** (`seed.db`,
extraction des seules tables `nomenclature_*`, jamais de données patients)
contenant leur contenu réel : ces référentiels sont des données
**publiques**, non la propriété de l'ATIH, embarquables sans restriction
dans les binaires distribués (`SMRXplore`). Ce seed permet à tout
exécutable construit sans accès à la machine de développement (build CI
GitHub Actions notamment) de rester fonctionnel dès le téléchargement,
sans que l'utilisateur final n'ait à se procurer ni charger lui-même les
fichiers source ATIH bruts (réservé à la maintenance du référentiel via
`tools/charger_nomenclatures.py`).
