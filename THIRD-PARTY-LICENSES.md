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

Les fichiers de ce dossier sont des **schémas JSON décrivant le format**
des référentiels publiés par l'ATIH (CIM-10, CCAM, CSARR, CSAR, GME) — noms
de colonnes, types, clés naturelles. **Aucune donnée de référence ATIH
elle-même (le contenu des tables, ex. la liste complète des codes CIM-10 et
leurs libellés) n'est incluse dans ce dépôt** : ces référentiels sont
chargés à l'exécution par `tools/charger_nomenclatures.py` depuis des
fichiers source que chaque utilisateur doit se procurer séparément auprès
de l'ATIH, puis restent dans `data/`/`input/` (jamais versionnés — voir
`.gitignore`).
