"""Calcule les agrégats du 'tableau de bord PMSI' (façon export ATIH existant),
sur la base des seules données RHS groupé + VID-HOSP en base SQLite.

Sections volontairement absentes : Score RR, Valorisation (PMCT/PMST/PMJT/VALO),
COEFF SPEC — elles nécessitent un barème CSARR et une grille tarifaire externes
que le projet n'a pas (choix explicite de l'utilisateur : on les laisse de côté).

Comparaison par PÉRIODES comparables (semaines 01..N), pas par année civile brute :
un fichier de transmission contient toujours le séjour COMPLET (donc, pour un
séjour à cheval, des semaines d'une année antérieure), mais les statistiques ne
doivent porter que sur la période demandée (ex. "M01 à M04" = semaines ISO 1 à 18).
Pour comparer plusieurs années sur cette même période relative (comme le tableau
de bord ATIH de référence), on prend la même plage de semaines (1..max_week, où
max_week vient de l'année la plus récente) pour chaque année qui couvre bien le
début de cette période. Une année dont les données ne remontent pas au moins à la
semaine 1 ou 2 n'est que le reliquat d'un séjour à cheval (queue d'une transmission
précédente) et est exclue — ce n'est pas une vraie période comparable.
- compute_reporting_periods() : liste des périodes comparables réellement
  disponibles dans les données (une par année qualifiante).
- Patients : calculé UNIQUEMENT à partir de VID-HOSP (pas de jointure RHS), en
  comptant un patient (numero_ipp — pas numero_immatriculation_assure, qui est
  le NIR de l'ASSURÉ et peut être celui d'un tiers, ex. conjoint) dès que son
  séjour [date_entree, date_sortie] chevauche la période considérée (un séjour
  à cheval sur deux périodes compte dans chacune, ce qui est normal pour une
  comparaison année sur année).
"""
from __future__ import annotations

import datetime
import sqlite3

from src.util.paths import project_root

DB_PATH = project_root() / "data/processed/pmsi.db"

def _load_intervenant_labels(conn: sqlite3.Connection) -> dict[str, str]:
    """Nomenclature complète (32 codes) issue de `nomenclature_csarr_intervenants`
    — remplace un dictionnaire codé en dur qui ne couvrait que 8 professions et
    laissait des codes bruts non résolus (ex. 10, 33, 69, 88) dans le tableau
    de bord. Le CSV source est en MAJUSCULES (ex. "MASSEUR KINÉSITHÉRAPEUTE") ;
    `.capitalize()` (1ʳᵉ lettre en majuscule, reste en minuscules) donne la
    même forme que l'ancien dictionnaire codé en dur pour tous les codes qui s'y
    trouvaient déjà (vérifié terme à terme le 2026-07-30)."""
    rows = conn.execute("SELECT code, libelle FROM nomenclature_csarr_intervenants").fetchall()
    return {r["code"]: r["libelle"].capitalize() for r in rows}


def _count_present_days(rhs_row: sqlite3.Row) -> int:
    days = (rhs_row["jours_hors_weekend"] or "") + (rhs_row["jours_weekend"] or "")
    return days.count("1")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _last_week_of_month(year: int, month: int) -> int:
    """Numéro de la dernière semaine ISO de `year` rattachée au mois calendaire `month`.

    Convention ATIH (identique à celle de l'année ISO) : une semaine appartient au
    mois qui contient son JEUDI. Vérifié empiriquement contre le tableau de bord de
    référence : en 2025, M01 se termine semaine 05 (jeudi 30/01), M02 semaine 09
    (jeudi 27/02), M03 semaine 13 (jeudi 27/03), M04 semaine 17 (jeudi 24/04) — la
    semaine 18 (jeudi 01/05) appartient déjà à M05.
    """
    last = None
    week = 1
    while week <= 53:
        try:
            thursday = datetime.date.fromisocalendar(year, week, 4)
        except ValueError:
            break
        if thursday.month > month:
            break
        if thursday.month == month:
            last = week
        week += 1
    return last


def compute_reporting_periods(
    conn: sqlite3.Connection,
    finess: str,
    years: list[str] | None = None,
    mois_fin: int | None = None,
) -> list[dict]:
    """Détermine les périodes de reporting COMPARABLES à partir des numero_semaine présents.

    La période cible est l'année ISO la plus récente présente (semaine 1 -> dernière
    semaine ISO présente), dont on déduit le MOIS calendaire de reporting via la règle
    du jeudi (voir _last_week_of_month). Pour chaque AUTRE année présente, on calcule
    la semaine de fin ÉQUIVALENTE pour ce même mois calendaire — les semaines ISO ne
    s'alignent pas identiquement d'une année sur l'autre (ex. fin avril tombe en
    semaine 17 en 2025 mais semaine 18 en 2026), donc on ne peut pas réutiliser le même
    numéro de semaine pour toutes les années. On ne retient une période comparable que
    si l'année couvre bien le début de la période (semaine 1 ou 2 présente) — sinon ce
    ne sont que des semaines résiduelles d'un séjour à cheval (queue d'une transmission
    précédente), pas une vraie période M01-M0N comparable, et l'année est exclue (voir
    docstring du module).

    `years` (optionnel, ex. ["2025", "2026"] — pour le choix utilisateur dans la page
    "TDB choix", max 3 années) restreint le résultat à ces années-là uniquement ; le
    "mois cible" (année la plus récente PARMI `years`) reste la même règle du jeudi
    que sans restriction, juste appliquée à un sous-ensemble d'années plutôt qu'à
    toutes les années présentes en base.

    `mois_fin` (optionnel, 1-12, demande utilisateur 2026-08-05) : impose le mois de
    fin de période au lieu de le déduire de la dernière semaine transmise — la période
    reste TOUJOURS cumulative depuis semaine 01 (convention ATIH "M01 à M0N" inchangée,
    décision utilisateur explicite : pas de vraie fenêtre Mx→My arbitraire, qui aurait
    cassé l'hypothèse "cumul depuis janvier" sur laquelle reposent plusieurs sections
    déjà validées, ex. valorisation "campagne comparable"). Si le mois choisi dépasse
    les données réellement chargées pour une année, cette année affiche simplement
    moins de semaines de données (pas d'erreur, pas de chiffre inventé).
    """
    rows = conn.execute(
        "SELECT DISTINCT numero_semaine FROM rhs_groupe WHERE numero_semaine IS NOT NULL AND finess_epmsi = ?",
        [finess],
    ).fetchall()
    weeks_by_year: dict[str, list[int]] = {}
    for r in rows:
        ns = r["numero_semaine"]
        week, year = int(ns[:2]), ns[2:6]
        weeks_by_year.setdefault(year, []).append(week)

    if years:
        wanted = {str(y) for y in years}
        weeks_by_year = {y: w for y, w in weeks_by_year.items() if y in wanted}

    if not weeks_by_year:
        return []

    target_year = max(weeks_by_year)
    if mois_fin is not None:
        target_month = mois_fin
    else:
        target_max_week = max(weeks_by_year[target_year])
        target_month = datetime.date.fromisocalendar(int(target_year), target_max_week, 4).month

    periods = []
    for year in sorted(weeks_by_year):
        if min(weeks_by_year[year]) > 2:
            continue  # ne couvre pas le début de la période : résidu, pas une vraie année comparable
        max_week = _last_week_of_month(int(year), target_month)
        if max_week is None:
            continue
        period_start = datetime.date.fromisocalendar(int(year), 1, 1)
        period_end = datetime.date.fromisocalendar(int(year), max_week, 7)
        periods.append({
            "year": year,
            "max_week": max_week,
            "start": period_start,
            "end": period_end,
            "label": f"{year} (semaines 01–{max_week:02d})",
        })
    return periods


def years_disponibles(conn: sqlite3.Connection, finess: str) -> list[str]:
    """Années ISO présentes dans le RHS groupé pour un FINESS (pour peupler le
    formulaire de choix — indépendant de la logique de période comparable
    ci-dessus, juste la liste brute des années qui ont au moins une ligne)."""
    rows = conn.execute(
        "SELECT DISTINCT substr(numero_semaine, 3, 4) AS annee FROM rhs_groupe "
        "WHERE numero_semaine IS NOT NULL AND finess_epmsi = ? ORDER BY 1",
        [finess],
    ).fetchall()
    return [r["annee"] for r in rows if r["annee"]]


def _period_filter(
    period: dict, finess: str, axis_filter: tuple[str, str] | None = None
) -> tuple[str, list]:
    """`axis_filter` (optionnel, ex. `("numero_unite_medicale", "3001")` ou
    `("type_hospitalisation", "1")`, 2026-08-04) restreint aussi la ligne RHS
    à cette valeur — utilisé pour générer un TDB secondaire complet PAR
    valeur d'UF ou de type d'hospitalisation (une ligne RHS ne peut avoir
    qu'une seule valeur, donc pas d'ambiguïté)."""
    clause = "finess_epmsi = ? AND substr(numero_semaine, 3, 4) = ? AND CAST(substr(numero_semaine, 1, 2) AS INTEGER) <= ?"
    params = [finess, period["year"], period["max_week"]]
    if axis_filter:
        champ, valeur = axis_filter
        clause += f" AND {champ} = ?"
        params.append(valeur)
    return clause, params


def section_sejours(
    conn: sqlite3.Connection, periods: list[dict], finess: str, axis_filter: tuple[str, str] | None = None
) -> dict:
    out = {}
    for period in periods:
        clause, params = _period_filter(period, finess, axis_filter)
        rows = conn.execute(f"SELECT * FROM rhs_groupe WHERE {clause}", params).fetchall()
        nb_rhs = len(rows)
        nb_ssr = len({r["numero_admin_sejour"] for r in rows})
        nb_journees = sum(_count_present_days(r) for r in rows)
        nb_semaines = len({r["numero_semaine"] for r in rows})
        dmh = nb_journees / nb_ssr if nb_ssr else 0
        nb_lits_moy = nb_journees / (nb_semaines * 7) if nb_semaines else 0
        nb_sans_erreur = sum(
            1 for r in rows if not (r["indicateur_erreur"] or "").strip()
        )
        exh = 100 * nb_sans_erreur / nb_rhs if nb_rhs else 0
        out[period["year"]] = {
            "nb_ssr": nb_ssr,
            "nb_rhs": nb_rhs,
            "nb_journees": nb_journees,
            "dmh": dmh,
            "nb_lits_moy": nb_lits_moy,
            "exh": exh,
        }
    return out


def _last_rhs_presence_by_sejour(conn: sqlite3.Connection, finess: str) -> dict[tuple[str, str], datetime.date]:
    """Pour chaque séjour (finess, numero_admin_sejour), date de fin (dimanche) de la
    dernière semaine RHS effectivement présente.

    Pour un séjour SSR long, le VID-HOSP peut ne représenter qu'une TRANCHE de
    facturation (avec montants, taux de remboursement...) et pas la présence
    physique complète : son date_sortie peut donc être antérieur à la fin réelle du
    séjour alors que le patient est toujours suivi semaine après semaine en RHS. On
    utilise cette date RHS comme borne de fin minimale pour ne pas perdre ces
    patients (vu empiriquement : séjour [identifiant anonymise], VID-HOSP date_sortie 20/06/2024,
    mais RHS toujours présent semaine 18-2026).
    """
    rows = conn.execute(
        "SELECT finess_epmsi, numero_admin_sejour, numero_semaine FROM rhs_groupe "
        "WHERE numero_semaine IS NOT NULL AND finess_epmsi = ?",
        [finess],
    ).fetchall()
    out: dict[tuple[str, str], datetime.date] = {}
    for r in rows:
        ns = r["numero_semaine"]
        week, year = int(ns[:2]), ns[2:6]
        try:
            end = datetime.date.fromisocalendar(int(year), week, 7)
        except ValueError:
            continue
        key = (r["finess_epmsi"], r["numero_admin_sejour"])
        if key not in out or end > out[key]:
            out[key] = end
    return out


def section_patients(
    conn: sqlite3.Connection, period: dict, finess: str, axis_filter: tuple[str, str] | None = None
) -> dict:
    """Patients distincts sur LA période de reporting, à partir de VID-HOSP
    (pas de jointure RHS pour l'identité/sexe/âge — seule la borne de fin de
    présence peut être étendue par la dernière semaine RHS du séjour, voir
    _last_rhs_presence_by_sejour).

    Un séjour compte pour un patient dès que sa plage [date_entree, fin réelle]
    chevauche la fenêtre de reporting — un séjour à cheval sur deux années ne
    compte le patient qu'UNE fois, pas une fois par année (il n'y a qu'une seule
    période ici, pas un découpage par année civile).

    L'effectif (F/M/Total) est dédoublonné par patient (numero_ipp — l'IPP
    identifie directement le patient, contrairement au numéro de sécurité
    sociale de l'assuré qui peut être celui d'un tiers, ex. conjoint), mais
    l'âge moyen NE L'EST PAS : validé cellule par cellule contre
    l'expression QlikView de référence `avg(G_AGE)` (dimensions année, sexe),
    qui fait une moyenne simple sur tous les séjours de la période — un patient
    avec 2 séjours dans l'année contribue 2 fois à la moyenne d'âge même s'il
    n'est compté qu'une fois dans l'effectif. Âge = (date_entree − date_naissance)
    en jours / 365,25, par séjour (pas par patient).

    `axis_filter` (optionnel, TDB secondaire "par UF"/"par type
    d'hospitalisation", 2026-08-04) : VID-HOSP n'a pas ces champs (propres au
    RHS), donc pas de filtrage direct possible — on restreint plutôt aux
    séjours ayant ≥1 ligne RHS correspondant au filtre sur la période (voir
    _sejours_matching_axis). Proxy assumé, différent de la méthode VID-HOSP
    pure validée pour le TDB principal non filtré.
    """
    period_start, period_end = period["start"], period["end"]
    sejours_ok = _sejours_matching_axis(conn, period, finess, axis_filter)

    rows = conn.execute(
        "SELECT numero_ipp, sexe_beneficiaire, date_naissance_beneficiaire, "
        "date_hospitalisation, date_entree, date_sortie, finess_epmsi, numero_admin_sejour "
        "FROM vid_hosp WHERE (date_entree IS NOT NULL OR date_hospitalisation IS NOT NULL) AND finess_epmsi = ?",
        [finess],
    ).fetchall()
    last_rhs_presence = _last_rhs_presence_by_sejour(conn, finess)

    bucket = {"F": 0, "M": 0, "ages_f": [], "ages_m": []}
    seen_ipp: set[str] = set()
    for r in rows:
        if sejours_ok is not None and int(r["numero_admin_sejour"]) not in sejours_ok:
            continue
        start_raw = r["date_entree"] or r["date_hospitalisation"]
        if not start_raw:
            continue
        start = datetime.date.fromisoformat(start_raw)
        end = datetime.date.fromisoformat(r["date_sortie"]) if r["date_sortie"] else period_end
        rhs_end = last_rhs_presence.get((r["finess_epmsi"], r["numero_admin_sejour"]))
        if rhs_end is not None and rhs_end > end:
            end = rhs_end
        if end < start:
            end = start

        # chevauchement avec [period_start, period_end] ?
        if end < period_start or start > period_end:
            continue

        ipp = r["numero_ipp"]
        sexe = r["sexe_beneficiaire"]
        age = None
        if r["date_entree"] and r["date_naissance_beneficiaire"]:
            entree = datetime.date.fromisoformat(r["date_entree"])
            naissance = datetime.date.fromisoformat(r["date_naissance_beneficiaire"])
            age = (entree - naissance).days / 365.25
        if sexe == "2" and age is not None:
            bucket["ages_f"].append(age)
        elif sexe == "1" and age is not None:
            bucket["ages_m"].append(age)

        if ipp in seen_ipp:
            continue
        seen_ipp.add(ipp)
        if sexe == "2":
            bucket["F"] += 1
        elif sexe == "1":
            bucket["M"] += 1

    total = bucket["F"] + bucket["M"]
    ages_all = bucket["ages_f"] + bucket["ages_m"]
    return {
        "f": bucket["F"],
        "m": bucket["M"],
        "total": total,
        "pct_f": 100 * bucket["F"] / total if total else 0,
        "pct_m": 100 * bucket["M"] / total if total else 0,
        "age_f": sum(bucket["ages_f"]) / len(bucket["ages_f"]) if bucket["ages_f"] else None,
        "age_m": sum(bucket["ages_m"]) / len(bucket["ages_m"]) if bucket["ages_m"] else None,
        "age_total": sum(ages_all) / len(ages_all) if ages_all else None,
    }


def section_journees_semaine(
    conn: sqlite3.Connection, periods: list[dict], finess: str, axis_filter: tuple[str, str] | None = None
) -> dict:
    out = {}
    for period in periods:
        clause, params = _period_filter(period, finess, axis_filter)
        rows = conn.execute(
            f"SELECT numero_semaine, jours_hors_weekend, jours_weekend FROM rhs_groupe WHERE {clause}",
            params,
        ).fetchall()
        per_week: dict[str, int] = {}
        for r in rows:
            week = r["numero_semaine"][:2]
            per_week[week] = per_week.get(week, 0) + _count_present_days(r)
        out[period["year"]] = dict(sorted(per_week.items()))
    return out


def _dedup_child_rows(
    conn: sqlite3.Connection, table: str, rhs_ids: list[int], max_per_key: int = 2
) -> list[sqlite3.Row]:
    """Renvoie les lignes d'une table enfant (CSARR/CSAR) en plafonnant à `max_per_key`
    occurrences identiques (même bloc complet, mêmes valeurs sur tous les champs) par
    séjour/RHS/jour. Un même acte CSARR/CSAR peut légitimement être réalisé deux fois le
    même jour (une fois le matin, une fois l'après-midi) — confirmé par l'utilisateur,
    2026-07-28 : un seul exemplaire par jour serait un dédoublonnage trop agressif. Seul
    un 3e exemplaire (ou plus) identique est un vrai doublon de transmission à écarter.
    """
    if not rhs_ids:
        return []
    cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall() if c[1] != "id"]
    col_list = ", ".join(cols)
    placeholders = ",".join("?" * len(rhs_ids))
    rows = conn.execute(
        f"SELECT {col_list} FROM {table} WHERE parent_id IN ({placeholders}) ORDER BY parent_id, seq",
        rhs_ids,
    ).fetchall()
    counts: dict[tuple, int] = {}
    kept: list[sqlite3.Row] = []
    for r in rows:
        key = tuple(r[c] for c in cols if c != "seq")
        n = counts.get(key, 0)
        if n < max_per_key:
            kept.append(r)
        counts[key] = n + 1
    return kept


def section_indicateurs(
    conn: sqlite3.Connection, periods: list[dict], finess: str, axis_filter: tuple[str, str] | None = None
) -> dict:
    out = {}
    for period in periods:
        clause, params = _period_filter(period, finess, axis_filter)
        rhs_rows = conn.execute(f"SELECT * FROM rhs_groupe WHERE {clause}", params).fetchall()
        nb_rhs = len(rhs_rows)

        avq_phys, avq_cogn = [], []
        das_counts = []
        for r in rhs_rows:
            phys_vals = [
                r[f] for f in (
                    "dependance_habillage_toilette", "dependance_deplacement",
                    "dependance_alimentation", "dependance_continence",
                ) if r[f] is not None
            ]
            if phys_vals:
                # score AVQ = SOMME des items (pas la moyenne) — calé empiriquement
                # sur le tableau de bord de référence (12.0 pour 4 items 1-4, pas 3.0)
                avq_phys.append(sum(int(v) for v in phys_vals))
            cogn_vals = [
                r[f] for f in ("dependance_comportement", "dependance_relation")
                if r[f] is not None
            ]
            if cogn_vals:
                avq_cogn.append(sum(int(v) for v in cogn_vals))
            das_counts.append(r["n1_nb_das"] or 0)

        rhs_ids = [r["id"] for r in rhs_rows]
        nb_csarr = 0
        nb_csar = 0
        nb_diag = 0
        if rhs_ids:
            placeholders = ",".join("?" * len(rhs_ids))
            # NB CSARR = somme de nombre_realisations sur les blocs CSARR dédoublonnés
            # (bloc complet identique = un seul acte, même si transmis deux fois) — validé
            # exact (230) contre la référence sur S01-2024 : COUNT(*) brut donnait 239,
            # COUNT(*) après dédoublonnage 226, seule la SOMME des réalisations post-dédoublonnage
            # tombe juste à 230.
            csarr_rows = _dedup_child_rows(conn, "rhs_groupe_csarr", rhs_ids)
            nb_csarr = sum(r["nombre_realisations"] or 0 for r in csarr_rows)
            csar_rows = _dedup_child_rows(conn, "rhs_groupe_csar", rhs_ids)
            nb_csar = sum(r["nombre_realisations"] or 0 for r in csar_rows)
            # NB DIAG = nombre de couples (RHS, code_das) DISTINCTS — validé exact contre
            # le script QlikView de référence (bloc DAS chargé en "load distinct RHS_ID, G_DAS"),
            # qui dédoublonne un même code DAS répété plusieurs fois dans une même semaine RHS.
            nb_diag = conn.execute(
                f"SELECT COUNT(DISTINCT parent_id || '|' || trim(code_das)) n "
                f"FROM rhs_groupe_das WHERE parent_id IN ({placeholders})",
                rhs_ids,
            ).fetchone()["n"]

        nb_journees = sum(_count_present_days(r) for r in rhs_rows)

        out[period["year"]] = {
            "avq_phys_moy": sum(avq_phys) / len(avq_phys) if avq_phys else None,
            "avq_cogn_moy": sum(avq_cogn) / len(avq_cogn) if avq_cogn else None,
            "nb_csarr": nb_csarr,
            "nb_diag_approx": nb_diag,
            "nb_das_moy_rhs": sum(das_counts) / len(das_counts) if das_counts else 0,
            # approximation : (CSARR + CSAR) / nb RHS - à valider contre la définition exacte de "INTERV"
            "nb_moy_interv_rhs": (nb_csarr + nb_csar) / nb_rhs if nb_rhs else 0,
            "nb_moy_csarr_j": nb_csarr / nb_journees if nb_journees else 0,
        }
    return out


def section_activite_csarr(
    conn: sqlite3.Connection, periods: list[dict], finess: str, axis_filter: tuple[str, str] | None = None
) -> dict:
    # Validé exact (2026-07-28) contre le rapport ATIH officiel "Activité CSARR par
    # intervenant, année N" (année 2024 complète, 6 professions + total 14649 ; puis
    # M01/M02/M03-2026 cumulatifs) : AUCUN dédoublonnage — SUM(nombre_realisations) brut,
    # blocs identiques inclus. ATIH exclut de son rapport les séjours en erreur de
    # groupage bloquante (ex. 0028 "mode d'entrée absent" — repéré sur le séjour
    # 024909882, 2026) car ils n'ont pas de tarif valide (logique facturation). Choix
    # délibéré de l'utilisateur (2026-07-28) : CE tableau de bord reste en logique
    # ACTIVITÉ, pas facturation — on ne les exclut PAS ici, précisément pour que l'écart
    # avec les chiffres officiels ATIH serve de signal d'alerte sur les séjours en
    # erreur (voir section_erreurs_activite pour le décompte de ce qu'ils représentent).
    labels = _load_intervenant_labels(conn)
    out = {}
    for period in periods:
        clause, params = _period_filter(period, finess, axis_filter)
        rows = conn.execute(
            "SELECT c.code_intervenant, SUM(c.nombre_realisations) n "
            "FROM rhs_groupe_csarr c "
            "JOIN rhs_groupe r ON r.id = c.parent_id "
            f"WHERE {clause.replace('numero_semaine', 'r.numero_semaine').replace('finess_epmsi', 'r.finess_epmsi')} "
            "AND c.code_intervenant IS NOT NULL "
            "GROUP BY c.code_intervenant ORDER BY n DESC",
            params,
        ).fetchall()
        out[period["year"]] = [
            {"code": r["code_intervenant"], "label": labels.get(r["code_intervenant"], r["code_intervenant"]), "n": r["n"]}
            for r in rows
        ]
    return out


_LIEU_FLAG_COL = {"HW": "mod_hw", "LJ": "mod_lj", "XH": "mod_xh", "L3": "mod_l3"}


def _load_ponderation_actes(conn: sqlite3.Connection) -> dict[str, dict]:
    """Table `nomenclature_ponderation_actes` chargée SANS dédoublonnage par
    natural_key (contrairement à toutes les autres nomenclatures du projet) :
    54 codes CSARR y ont plusieurs lignes, une par période de validité
    (colonnes `debut`/`fin`, en années). Politique dernier-gagne appliquée ici
    (choix utilisateur 2026-07-30, cohérent avec le reste du projet) : on
    garde la ligne au `debut` le plus récent pour chaque code — le barème le
    plus à jour est appliqué à toutes les années comparées, y compris les
    plus anciennes."""
    rows = conn.execute(
        "SELECT code, ponderation_patient, mod_hw, mod_lj, mod_xh, mod_l3, debut "
        "FROM nomenclature_ponderation_actes WHERE nomenclature = 'CSARR'"
    ).fetchall()
    best: dict[str, dict] = {}
    for r in rows:
        try:
            debut = int(r["debut"]) if r["debut"] else -1
        except ValueError:
            debut = -1
        prev = best.get(r["code"])
        if prev is None or debut >= prev["_debut"]:
            try:
                pond = float(r["ponderation_patient"]) if r["ponderation_patient"] not in (None, "") else 0.0
            except ValueError:
                pond = 0.0
            best[r["code"]] = {
                "ponderation": pond,
                "mod_hw": r["mod_hw"] == "x",
                "mod_lj": r["mod_lj"] == "x",
                "mod_xh": r["mod_xh"] == "x",
                "mod_l3": r["mod_l3"] == "x",
                "_debut": debut,
            }
    return best


def _load_modulateurs(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT code, majoration_individuel, majoration_collectif FROM nomenclature_ponderation_modulateurs"
    ).fetchall()

    def _pct(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None  # None, vide, ou texte type "sans objet"

    return {r["code"]: {"individuel": _pct(r["majoration_individuel"]), "collectif": _pct(r["majoration_collectif"])} for r in rows}


def section_ponderation_csarr(
    conn: sqlite3.Connection, periods: list[dict], finess: str, axis_filter: tuple[str, str] | None = None
) -> dict:
    """Score pondéré par intervenant = somme, sur chaque réalisation CSARR, de
    `ponderation_patient` (nomenclature_ponderation_actes) éventuellement
    majoré par le modulateur de LIEU (HW/LJ/XH/L3, nomenclature_ponderation_
    modulateurs) — UNIQUEMENT si cet acte y est éligible (colonnes mod_hw/
    mod_lj/mod_xh/mod_l3 de la table de pondération). Majoration individuelle
    si nombre_reel_patients <= 1, collective sinon. Le modulateur PATIENT (EZ,
    fractionnement) et les modulateurs de TECHNICITÉ (QM/QS/QF/QI/QC/QQ) n'ont
    aucune majoration dans le fichier ATIH (0 % partout) — ignorés ici, pas
    par oubli. Couverture vérifiée le 2026-07-30 : les 206 codes CSARR
    distincts utilisés dans ce jeu de données sont tous présents dans la
    table de pondération (aucun acte non résolu)."""
    ponderations = _load_ponderation_actes(conn)
    modulateurs = _load_modulateurs(conn)
    out = {}
    for period in periods:
        clause, params = _period_filter(period, finess, axis_filter)
        rows = conn.execute(
            "SELECT c.code_intervenant, c.code_principal, c.code_modulateur_lieu, "
            "c.nombre_realisations, c.nombre_reel_patients "
            "FROM rhs_groupe_csarr c "
            "JOIN rhs_groupe r ON r.id = c.parent_id "
            f"WHERE {clause.replace('numero_semaine', 'r.numero_semaine').replace('finess_epmsi', 'r.finess_epmsi')} "
            "AND c.code_intervenant IS NOT NULL",
            params,
        ).fetchall()
        scores: dict[str, float] = {}
        for r in rows:
            acte = ponderations.get(r["code_principal"])
            if acte is None:
                continue
            pct = 0.0
            lieu = r["code_modulateur_lieu"]
            flag_col = _LIEU_FLAG_COL.get(lieu)
            if flag_col and acte[flag_col]:
                modul = modulateurs.get(lieu)
                if modul:
                    individuel = (r["nombre_reel_patients"] or 1) <= 1
                    raw = modul["individuel"] if individuel else modul["collectif"]
                    pct = raw if raw is not None else 0.0
            weighted = acte["ponderation"] * (1 + pct / 100) * (r["nombre_realisations"] or 1)
            scores[r["code_intervenant"]] = scores.get(r["code_intervenant"], 0.0) + weighted
        out[period["year"]] = scores
    return out


def section_erreurs_activite(
    conn: sqlite3.Connection, periods: list[dict], finess: str, axis_filter: tuple[str, str] | None = None
) -> dict:
    """Décompte (diag, CSARR, CSAR) porté par des séjours en erreur de groupage
    bloquante (indicateur_erreur rempli), à titre d'information seulement — ce tableau
    de bord garde volontairement ces séjours dans tous les totaux (logique activité,
    pas facturation), contrairement au rapport ATIH officiel qui les exclut. Un nombre
    élevé ici est un signal d'alerte sur des séjours à corriger, pas une erreur de calcul.
    """
    out = {}
    for period in periods:
        clause, params = _period_filter(period, finess, axis_filter)
        rhs_ids = [
            r["id"] for r in conn.execute(
                f"SELECT id FROM rhs_groupe WHERE {clause} AND indicateur_erreur IS NOT NULL AND trim(indicateur_erreur) != ''",
                params,
            ).fetchall()
        ]
        nb_diag = 0
        nb_csarr = 0
        nb_csar = 0
        if rhs_ids:
            placeholders = ",".join("?" * len(rhs_ids))
            nb_diag = conn.execute(
                f"SELECT COUNT(DISTINCT parent_id || '|' || trim(code_das)) n "
                f"FROM rhs_groupe_das WHERE parent_id IN ({placeholders})",
                rhs_ids,
            ).fetchone()["n"]
            nb_csarr = conn.execute(
                f"SELECT SUM(nombre_realisations) n FROM rhs_groupe_csarr WHERE parent_id IN ({placeholders})",
                rhs_ids,
            ).fetchone()["n"] or 0
            nb_csar = conn.execute(
                f"SELECT SUM(nombre_realisations) n FROM rhs_groupe_csar WHERE parent_id IN ({placeholders})",
                rhs_ids,
            ).fetchone()["n"] or 0
        out[period["year"]] = {
            "nb_sejours_erreur": len({
                r["numero_admin_sejour"] for r in conn.execute(
                    f"SELECT numero_admin_sejour FROM rhs_groupe WHERE {clause} AND indicateur_erreur IS NOT NULL AND trim(indicateur_erreur) != ''",
                    params,
                ).fetchall()
            }),
            "nb_rhs_erreur": len(rhs_ids),
            "nb_diag_erreur": nb_diag,
            "nb_csarr_erreur": nb_csarr,
            "nb_csar_erreur": nb_csar,
        }
    return out


def section_absence_csarr(
    conn: sqlite3.Connection, periods: list[dict], finess: str, axis_filter: tuple[str, str] | None = None
) -> dict:
    out = {}
    for period in periods:
        clause, params = _period_filter(period, finess, axis_filter)
        rows = conn.execute(
            f"SELECT numero_admin_sejour, n2_nb_csarr, jours_hors_weekend, jours_weekend FROM rhs_groupe WHERE {clause}",
            params,
        ).fetchall()
        nb_rhs = len(rows)
        rhs_sans_acte = [r for r in rows if (r["n2_nb_csarr"] or 0) == 0]
        nb_rhs_sans_acte = len(rhs_sans_acte)
        nb_jrs_sans_acte = sum(_count_present_days(r) for r in rhs_sans_acte)

        csarr_par_sejour: dict[str, int] = {}
        for r in rows:
            s = r["numero_admin_sejour"]
            csarr_par_sejour[s] = csarr_par_sejour.get(s, 0) + (r["n2_nb_csarr"] or 0)
        nb_ssr_sans_acte = sum(1 for total in csarr_par_sejour.values() if total == 0)

        out[period["year"]] = {
            "nb_ssr_sans_acte": nb_ssr_sans_acte,
            "nb_rhs_sans_acte": nb_rhs_sans_acte,
            "nb_jrs_sans_acte": nb_jrs_sans_acte,
            "pct_rhs_sans_acte": 100 * nb_rhs_sans_acte / nb_rhs if nb_rhs else 0,
        }
    return out


def section_erreurs_groupage(
    conn: sqlite3.Connection, periods: list[dict], finess: str, axis_filter: tuple[str, str] | None = None
) -> dict:
    out = {}
    for period in periods:
        clause, params = _period_filter(period, finess, axis_filter)
        rows = conn.execute(
            "SELECT indicateur_erreur, numero_admin_sejour FROM rhs_groupe "
            f"WHERE {clause} AND indicateur_erreur IS NOT NULL AND indicateur_erreur != ''",
            params,
        ).fetchall()
        par_code: dict[str, dict] = {}
        for r in rows:
            code = r["indicateur_erreur"]
            bucket = par_code.setdefault(code, {"sejours": set(), "nb_rhs": 0})
            bucket["sejours"].add(r["numero_admin_sejour"])
            bucket["nb_rhs"] += 1
        out[period["year"]] = [
            {"code": code, "nb_ssr": len(b["sejours"]), "nb_rhs": b["nb_rhs"]}
            for code, b in sorted(par_code.items())
        ]
    return out


def section_incoherences_vidhosp_rhs(conn: sqlite3.Connection, finess: str) -> list[dict]:
    """Détecte les séjours où le VID-HOSP ne concorde pas avec le RHS groupé :
    dossier RHS présent avec des semaines hors de la plage [date_entree, date_sortie]
    du VID-HOSP (dossier PMSI non clôturé alors que le RHS continue d'être transmis),
    ou séjour RHS sans aucun enregistrement VID-HOSP du tout.

    Repéré empiriquement sur le séjour [identifiant anonymise] : dossier administratif clôturé le
    20/06/2024 (un autre dossier, EHPAD, ouvre le même jour — hors périmètre PMSI-SSR,
    0 ligne RHS), mais la clôture PMSI/VID-HOSP n'a jamais été faite : le RHS continue
    à être transmis semaine après semaine jusqu'à la semaine 18-2026 alors que le
    VID-HOSP reste bloqué à une sortie du 20/06/2024.
    """
    rhs_rows = conn.execute(
        "SELECT finess_epmsi, numero_admin_sejour, numero_semaine, date_debut_sejour, date_fin_sejour "
        "FROM rhs_groupe WHERE numero_admin_sejour IS NOT NULL AND finess_epmsi = ?",
        [finess],
    ).fetchall()

    by_sejour: dict[tuple[str, str], dict] = {}
    for r in rhs_rows:
        key = (r["finess_epmsi"], r["numero_admin_sejour"])
        b = by_sejour.setdefault(key, {"weeks": [], "date_debut": None, "date_fin": None})
        ns = r["numero_semaine"]
        if ns:
            week, year = int(ns[:2]), ns[2:6]
            try:
                b["weeks"].append(datetime.date.fromisocalendar(int(year), week, 7))
            except ValueError:
                pass
        if r["date_debut_sejour"]:
            b["date_debut"] = min(b["date_debut"] or r["date_debut_sejour"], r["date_debut_sejour"])
        if r["date_fin_sejour"]:
            b["date_fin"] = max(b["date_fin"] or r["date_fin_sejour"], r["date_fin_sejour"])

    vidhosp_by_sejour: dict[tuple[str, str], sqlite3.Row] = {}
    for r in conn.execute(
        "SELECT finess_epmsi, numero_admin_sejour, numero_immatriculation_assure, "
        "date_entree, date_hospitalisation, date_sortie FROM vid_hosp WHERE finess_epmsi = ?",
        [finess],
    ).fetchall():
        vidhosp_by_sejour[(r["finess_epmsi"], r["numero_admin_sejour"])] = r

    anomalies = []
    for key, b in by_sejour.items():
        if not b["weeks"]:
            continue
        rhs_last_week = max(b["weeks"])
        rhs_end = datetime.date.fromisoformat(b["date_fin"]) if b["date_fin"] else rhs_last_week
        vh = vidhosp_by_sejour.get(key)
        if vh is None:
            anomalies.append({
                "numero_admin_sejour": key[1],
                "nir": None,
                "vidhosp_entree": None,
                "vidhosp_sortie": None,
                "rhs_derniere_semaine": rhs_last_week.isoformat(),
                "type": "Aucun enregistrement VID-HOSP pour ce séjour",
            })
            continue
        vh_sortie = datetime.date.fromisoformat(vh["date_sortie"]) if vh["date_sortie"] else None
        # Écart minimal avant de signaler : un séjour encore en cours a un date_sortie
        # VID-HOSP provisoire (fin du mois de la transmission), à quelques jours de la
        # dernière semaine RHS — pas une vraie incohérence. Seul un écart de plusieurs
        # semaines trahit un dossier PMSI réellement non clôturé.
        if vh_sortie is not None and (rhs_end - vh_sortie).days > 21:
            anomalies.append({
                "numero_admin_sejour": key[1],
                "nir": vh["numero_immatriculation_assure"],
                "vidhosp_entree": vh["date_entree"] or vh["date_hospitalisation"],
                "vidhosp_sortie": vh["date_sortie"],
                "rhs_derniere_semaine": rhs_last_week.isoformat(),
                "type": "Dossier PMSI non clôturé (RHS transmis après la sortie VID-HOSP)",
            })
    anomalies.sort(key=lambda a: a["numero_admin_sejour"])
    return anomalies


def list_finess(conn: sqlite3.Connection) -> list[str]:
    """Liste des FINESS présents en base (union RHS/VID-HOSP), triés."""
    rows = conn.execute(
        "SELECT DISTINCT finess_epmsi FROM rhs_groupe "
        "UNION SELECT DISTINCT finess_epmsi FROM vid_hosp"
    ).fetchall()
    return sorted(r["finess_epmsi"] for r in rows if r["finess_epmsi"])


TYPE_HOSPITALISATION_LABELS = {
    "1": "Hospitalisation complète (HC)",
    "2": "Hospitalisation partielle de jour (HTP)",
    "3": "Hospitalisation partielle de nuit (HTP)",
}


def valeurs_axe(conn: sqlite3.Connection, periods: list[dict], finess: str, champ: str) -> list[str]:
    """Valeurs distinctes de `champ` (`numero_unite_medicale` ou
    `type_hospitalisation`) réellement présentes sur les périodes demandées —
    sert à énumérer les TDB secondaires à générer (un TDB complet PAR valeur,
    demande utilisateur 2026-08-04, voir build(..., axis_filter=...))."""
    values: set[str] = set()
    for period in periods:
        clause, params = _period_filter(period, finess)
        rows = conn.execute(
            f"SELECT DISTINCT {champ} FROM rhs_groupe WHERE {clause} AND {champ} IS NOT NULL AND {champ} != ''",
            params,
        ).fetchall()
        values.update(r[0] for r in rows)
    return sorted(values)


def _sejours_matching_axis(
    conn: sqlite3.Connection, period: dict, finess: str, axis_filter: tuple[str, str] | None
) -> set[int] | None:
    """Séjours ayant au moins une ligne RHS correspondant à `axis_filter` sur
    la période — utilisé pour restreindre la section Patients (VID-HOSP,
    aucune notion d'UF/type d'hospitalisation propre) dans un TDB secondaire.
    Renvoie None si `axis_filter` est None (pas de restriction)."""
    if not axis_filter:
        return None
    clause, params = _period_filter(period, finess, axis_filter)
    rows = conn.execute(
        f"SELECT DISTINCT numero_admin_sejour FROM rhs_groupe WHERE {clause}", params
    ).fetchall()
    return {int(r[0]) for r in rows}


_GME_CODE_LENGTH = {"CM": 2, "GN": 4, "GME": 7}


def _load_gme_labels(conn: sqlite3.Connection, quoi: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT code, libelle_court, libelle_long FROM nomenclature_gme WHERE kind = ?", [quoi]
    ).fetchall()
    return {r["code"]: (r["libelle_long"] or r["libelle_court"] or r["code"]) for r in rows}


def _sejour_code_gme_by_period(
    conn: sqlite3.Connection,
    period: dict,
    finess: str,
    length: int,
    axis_filter: tuple[str, str] | None = None,
) -> dict[int, str]:
    """Pour chaque séjour actif dans la période, le code GME (tronqué à
    `length` caractères — CM=2/GN=4/GME=7, cf. gme.py) de sa DERNIÈRE semaine
    RHS connue dans la période : représente son classement le plus à jour,
    au cas où un séjour serait re-groupé d'une semaine à l'autre."""
    clause, params = _period_filter(period, finess, axis_filter)
    rows = conn.execute(
        f"SELECT numero_admin_sejour, numero_semaine, code_gme FROM rhs_groupe "
        f"WHERE {clause} AND code_gme IS NOT NULL AND code_gme != ''",
        params,
    ).fetchall()
    best: dict[int, tuple[int, str]] = {}
    for numadmin, numero_semaine, code in rows:
        numadmin = int(numadmin)
        week = int(numero_semaine[:2])
        prev = best.get(numadmin)
        if prev is None or week >= prev[0]:
            best[numadmin] = (week, code[:length])
    return {k: v[1] for k, v in best.items()}


def section_palmares_gme(
    conn: sqlite3.Connection,
    periods: list[dict],
    finess: str,
    quoi: str,
    top_n: int = 5,
    axis_filter: tuple[str, str] | None = None,
) -> dict:
    """Palmarès des `top_n` codes CM/GN/GME les plus fréquents (classés sur
    l'EFFECTIF total cumulé sur toutes les périodes comparées — mêmes 5 codes
    affichés pour chaque année, même si leur rang change d'une année à
    l'autre), avec effectif (nb séjours) et valorisation (montant_br_tot,
    même filtre de comparabilité campagne/max_week que la section 6) par
    colonne-année, plus le % de chacun par rapport au total (tous codes, pas
    seulement le top `top_n`) de sa colonne.

    Un séjour compte pour le code GME de sa DERNIÈRE semaine RHS connue dans
    la période (voir _sejour_code_gme_by_period) — cohérent avec le principe
    "classement le plus à jour" déjà utilisé ailleurs dans ce module.
    """
    from src.viz.valorisation import EXCLUSION_MONTANT_OFFICIEL, _derniere_semaine_rhs_par_sejour

    length = _GME_CODE_LENGTH[quoi]
    labels = _load_gme_labels(conn, quoi)

    effectifs: dict[str, dict[str, int]] = {}
    valorisations: dict[str, dict[str, float]] = {}

    for period in periods:
        y = period["year"]
        sejour_codes = _sejour_code_gme_by_period(conn, period, finess, length, axis_filter)

        eff: dict[str, int] = {}
        for code in sejour_codes.values():
            eff[code] = eff.get(code, 0) + 1
        effectifs[y] = eff

        derniere_semaines = _derniere_semaine_rhs_par_sejour(conn, int(y), finess)
        clause = f"WHERE campagne = ? AND montant_br_tot IS NOT NULL AND {EXCLUSION_MONTANT_OFFICIEL}"
        params: list = [int(y)]
        if finess is not None:
            clause += " AND finess_epmsi = ?"
            params.append(finess)
        rows = conn.execute(
            "SELECT numero_admin_sejour, montant_br_tot - COALESCE(montant_br_trans, 0) "
            f"FROM valorisation_sejour {clause}",
            params,
        ).fetchall()
        val: dict[str, float] = {}
        for numadmin, montant in rows:
            numadmin = int(numadmin)
            derniere = derniere_semaines.get(numadmin)
            if derniere is None or derniere > period["max_week"]:
                continue
            code = sejour_codes.get(numadmin)
            if code is None:
                continue
            val[code] = val.get(code, 0.0) + montant
        valorisations[y] = val

    totals: dict[str, int] = {}
    for eff in effectifs.values():
        for code, n in eff.items():
            totals[code] = totals.get(code, 0) + n
    top_codes = sorted(totals, key=lambda c: totals[c], reverse=True)[:top_n]

    total_eff_by_year = {y: sum(eff.values()) for y, eff in effectifs.items()}
    total_val_by_year = {y: sum(val.values()) for y, val in valorisations.items()}

    rows_out = []
    for code in top_codes:
        row = {"code": code, "libelle": labels.get(code, code), "data": {}}
        for period in periods:
            y = period["year"]
            n = effectifs[y].get(code, 0)
            v = valorisations[y].get(code, 0.0)
            tot_n, tot_v = total_eff_by_year[y], total_val_by_year[y]
            row["data"][y] = {
                "effectif": n,
                "pct_effectif": (100.0 * n / tot_n) if tot_n else 0.0,
                "valorisation": v,
                "pct_valorisation": (100.0 * v / tot_v) if tot_v else 0.0,
            }
        rows_out.append(row)

    return {"quoi": quoi, "rows": rows_out}


# Libellés des caractères structurels du code GME (cf. décision utilisateur
# 2026-07-30 sur le sens des lettres GR/GL, et 2026-08-03 sur les sévérités) :
# GR (5e caractère) = type de rééducation ; GL (6e caractère) = niveau de
# dépendance (HC uniquement) ; 7e caractère = sévérité. "ERR" est une clé
# de repli (pas un vrai caractère du code) pour tout séjour dont le type GR
# n'est pas reconnu — cas confirmé empiriquement : `9096ZZ0`, le code_gme
# placeholder d'un séjour en erreur de groupage bloquante (indicateur_erreur
# rempli, code_retour_groupage='28' = "mode d'entrée absent") — ne pas le
# classer à tort sous une vraie catégorie (ex. sévérité "0", qui a par
# ailleurs un sens réel pour les vrais séjours HTP).
_GR_LABELS = {
    "P": "Pédiatrique (HC)",
    "S": "Spécialisée (HC)",
    "T": "Globale (HC)",
    "U": "Autre (HC)",
    "H": "Pédiatrique (HTP)",
    "I": "Très intensive (HTP)",
    "J": "Intensive (HTP)",
    "K": "Modérée (HTP)",
    "L": "Indifférenciée (HTP)",
}
_GL_LABELS = {"A": "Niveau A", "B": "Niveau B", "C": "Niveau C"}
_SEVERITE_LABELS = {"0": "HTP", "1": "HC sans sévérité", "2": "HC avec sévérité"}
_ERREUR_KEY, _ERREUR_LABEL = "ERR", "Erreur de groupage"


def _structure_bucket_key(code: str, block: str) -> str:
    gr_letter = code[4] if len(code) > 4 else None
    if gr_letter not in _GR_LABELS:
        return _ERREUR_KEY
    if block == "gr":
        return gr_letter
    if block == "gl":
        gl_letter = code[5] if len(code) > 5 else None
        return gl_letter if gl_letter in _GL_LABELS else _ERREUR_KEY
    sev = code[6] if len(code) > 6 else None
    return sev if sev in _SEVERITE_LABELS else _ERREUR_KEY


def section_structure_gme(
    conn: sqlite3.Connection, periods: list[dict], finess: str, axis_filter: tuple[str, str] | None = None
) -> dict:
    """Section 9 — trois blocs statistiques TRANSVERSES (toutes CM/GN
    confondues, pas de top N) sur la structure du groupage GME, demandés par
    l'utilisateur en complément des palmarès CM/GN (sections 7-8) : type de
    rééducation (GR), niveau de dépendance (GL), sévérité — chacun avec un
    sous-total. Même principe d'attribution séjour→code que section_palmares_gme
    (dernière semaine RHS connue de la période) et même filtre de
    comparabilité valorisation que la section 6.
    """
    from src.viz.valorisation import EXCLUSION_MONTANT_OFFICIEL, _derniere_semaine_rhs_par_sejour

    blocks = ("gr", "gl", "sev")
    effectifs: dict[str, dict[str, dict[str, int]]] = {b: {} for b in blocks}
    valorisations: dict[str, dict[str, dict[str, float]]] = {b: {} for b in blocks}

    for period in periods:
        y = period["year"]
        sejour_codes = _sejour_code_gme_by_period(conn, period, finess, 7, axis_filter)

        for block in blocks:
            eff: dict[str, int] = {}
            for code in sejour_codes.values():
                k = _structure_bucket_key(code, block)
                eff[k] = eff.get(k, 0) + 1
            effectifs[block][y] = eff

        derniere_semaines = _derniere_semaine_rhs_par_sejour(conn, int(y), finess)
        clause = f"WHERE campagne = ? AND montant_br_tot IS NOT NULL AND {EXCLUSION_MONTANT_OFFICIEL}"
        params: list = [int(y)]
        if finess is not None:
            clause += " AND finess_epmsi = ?"
            params.append(finess)
        rows = conn.execute(
            "SELECT numero_admin_sejour, montant_br_tot - COALESCE(montant_br_trans, 0) "
            f"FROM valorisation_sejour {clause}",
            params,
        ).fetchall()
        val_by_block: dict[str, dict[str, float]] = {b: {} for b in blocks}
        for numadmin, montant in rows:
            numadmin = int(numadmin)
            derniere = derniere_semaines.get(numadmin)
            if derniere is None or derniere > period["max_week"]:
                continue
            code = sejour_codes.get(numadmin)
            if code is None:
                continue
            for block in blocks:
                k = _structure_bucket_key(code, block)
                val_by_block[block][k] = val_by_block[block].get(k, 0.0) + montant
        for block in blocks:
            valorisations[block][y] = val_by_block[block]

    labels_by_block = {"gr": _GR_LABELS, "gl": _GL_LABELS, "sev": _SEVERITE_LABELS}
    order_by_block = {"gr": list(_GR_LABELS), "gl": list(_GL_LABELS), "sev": list(_SEVERITE_LABELS)}

    def build_rows(block: str) -> list[dict]:
        eff_by_year = effectifs[block]
        val_by_year = valorisations[block]
        totals_by_key: dict[str, int] = {}
        for eff in eff_by_year.values():
            for k, n in eff.items():
                totals_by_key[k] = totals_by_key.get(k, 0) + n
        keys = [k for k in order_by_block[block] if totals_by_key.get(k)]
        if totals_by_key.get(_ERREUR_KEY):
            keys.append(_ERREUR_KEY)

        rows_out = []
        for key in keys:
            row = {"code": key, "libelle": labels_by_block[block].get(key, _ERREUR_LABEL), "data": {}}
            for period in periods:
                y = period["year"]
                eff, val = eff_by_year.get(y, {}), val_by_year.get(y, {})
                n, v = eff.get(key, 0), val.get(key, 0.0)
                tot_n, tot_v = sum(eff.values()), sum(val.values())
                row["data"][y] = {
                    "effectif": n,
                    "pct_effectif": (100.0 * n / tot_n) if tot_n else 0.0,
                    "valorisation": v,
                    "pct_valorisation": (100.0 * v / tot_v) if tot_v else 0.0,
                }
            rows_out.append(row)

        subtotal = {"code": None, "libelle": "Sous-total", "data": {}}
        for period in periods:
            y = period["year"]
            eff, val = eff_by_year.get(y, {}), val_by_year.get(y, {})
            tot_n, tot_v = sum(eff.values()), sum(val.values())
            subtotal["data"][y] = {
                "effectif": tot_n,
                "pct_effectif": 100.0 if tot_n else 0.0,
                "valorisation": tot_v,
                "pct_valorisation": 100.0 if tot_v else 0.0,
            }
        rows_out.append(subtotal)
        return rows_out

    return {
        "gr": {"titre": "Type de rééducation (GR)", "rows": build_rows("gr")},
        "gl": {"titre": "Niveau de dépendance (GL)", "rows": build_rows("gl")},
        "sev": {"titre": "Sévérité", "rows": build_rows("sev")},
    }


def section_valorisation(
    conn: sqlite3.Connection,
    periods: list[dict],
    finess: str,
    sejours: dict,
    axis_filter: tuple[str, str] | None = None,
) -> dict:
    """Section 6 — Valorisation : montant BR (Budget Régulé) reconstitué pour
    la période, réparti au prorata temporis par jour de présence (voir
    src/viz/valorisation.py — répartition uniforme du montant de chaque
    CAMPAGNE sur ses jours de présence RHS attribuables), puis 3 prix moyens
    dérivés (demande utilisateur 2026-07-30) :
    - PMCT (prix moyen par cas traité)   = montant BR / nb séjours (nb_ssr)
    - PMST (prix moyen par semaine traitée) = montant BR / nb semaines (nb_rhs
      — chaque ligne RHS groupé = une semaine ISO d'un séjour)
    - PMJT (prix moyen par jour traité)  = montant BR / nb journées de
      présence (nb_journees)
    `sejours` = data["sejours"] déjà calculé (section_sejours), réutilisé pour
    ces dénominateurs plutôt que recalculé ici.

    Ajout 2026-07-31 (demande utilisateur, vérification qualité) :
    `montant_br_tot` = figure OFFICIELLE ATIH (le montant reçu/facturé),
    affichée à côté de `montant_br_pt` (renommé depuis `montant_br`, notre
    calcul pro rata temporis) pour que l'utilisateur puisse comparer les
    deux. Pour rester comparable à une vraie transmission M04 (le cas de
    2026, où le fichier source EST une transmission M04), les campagnes
    2024/2025 — dont on ne dispose qu'en transmission M12 (année complète) —
    sont restreintes aux séjours dont l'activité RHS ne dépasse pas la
    semaine limite `max_week` de la période (voir
    montant_br_tot_campagne_comparable dans src/viz/valorisation.py) : un
    séjour encore ouvert après cette semaine n'aurait pas eu de montant
    stable/connu dans une vraie transmission M04 de son année, même s'il
    apparaît déjà soldé dans le fichier M12 qu'on a chargé. Approximation
    assumée (pas de vraie transmission M04 2024/2025 disponible).

    `axis_filter` (optionnel, TDB secondaire "par UF"/"par type
    d'hospitalisation", 2026-08-04, décision utilisateur) : `montant_br_pt`
    est reproraté sur les seuls jours de présence RHS qui tombent dans le
    filtre (voir valeur_sur_periode/compute_valeur_journaliere) — nouvelle
    hypothèse de calcul, non validée contre une référence externe.
    `montant_br_tot` (figure OFFICIELLE ATIH, attachée au séjour ENTIER, donc
    non ventilable par UF/type d'hospitalisation) devient None dans ce cas :
    pas de valeur inventée pour un montant qui n'est pas attribuable au
    filtre.

    `montant_br_tot_sans_filtre` / `montant_br_non_fact` (2026-08-05, demande
    utilisateur) : `montant_br_tot_sans_filtre` reprend le même calcul SANS
    exclure les séjours nv_nonfactam/nv_chain/nv_attente_dts (exclure=False,
    voir montant_br_tot_campagne_comparable) ; `montant_br_non_fact` est la
    différence (montant_br_tot_sans_filtre − montant_br_tot) — la recette
    "perdue" à cause de ces anomalies (non facturable AM, chaînage, en
    attente de droits), pour donner une idée du manque à gagner plutôt que
    de le faire disparaître silencieusement du TDB. Comme montant_br_tot,
    absent (None) dans un TDB secondaire filtré par axe (non attribuable).

    `estimation_en_cours` (ESSAI, 2026-08-05, demande utilisateur) : pour
    les séjours <90j non clos "propres" (aucune anomalie nv_chain/
    nv_attente_dts/nv_nonfactam — voir sejours_non_factures_sans_anomalie),
    applique le PMJT déjà calculé ci-dessous (donc SANS boucle : le PMJT
    n'est jamais recalculé à partir de cette estimation) à leurs journées de
    présence pour estimer la recette qu'ils produiront une fois facturés.
    Absent dans un TDB secondaire filtré par axe, comme montant_br_tot."""
    from src.viz.valorisation import (
        estimation_recettes_sejours_en_cours,
        montant_br_tot_campagne_comparable,
        valeur_sur_periode,
    )

    out = {}
    for period in periods:
        y = period["year"]
        montant_br_pt = valeur_sur_periode(conn, period["start"], period["end"], finess, axis_filter)
        sej = sejours[y]
        pmjt = montant_br_pt / sej["nb_journees"] if sej["nb_journees"] else None
        montant_br_tot = None
        montant_br_tot_sans_filtre = None
        montant_br_non_fact = None
        estimation_en_cours = None
        if not axis_filter:
            montant_br_tot = montant_br_tot_campagne_comparable(conn, y, period["max_week"], finess)
            montant_br_tot_sans_filtre = montant_br_tot_campagne_comparable(
                conn, y, period["max_week"], finess, exclure=False
            )
            montant_br_non_fact = montant_br_tot_sans_filtre - montant_br_tot
            estimation_en_cours = estimation_recettes_sejours_en_cours(conn, period, finess, pmjt)
        montant_br_pt_avec_estimation = (
            montant_br_pt + estimation_en_cours["montant"] if estimation_en_cours else None
        )
        out[y] = {
            "montant_br_pt": montant_br_pt,
            "montant_br_tot": montant_br_tot,
            "montant_br_tot_sans_filtre": montant_br_tot_sans_filtre,
            "montant_br_non_fact": montant_br_non_fact,
            "estimation_en_cours": estimation_en_cours,
            "montant_br_pt_avec_estimation": montant_br_pt_avec_estimation,
            "pmct": montant_br_pt / sej["nb_ssr"] if sej["nb_ssr"] else None,
            "pmst": montant_br_pt / sej["nb_rhs"] if sej["nb_rhs"] else None,
            "pmjt": pmjt,
        }
    return out


def build(
    finess: str,
    years: list[str] | None = None,
    axis_filter: tuple[str, str] | None = None,
    mois_fin: int | None = None,
) -> dict:
    """`years` (optionnel, ex. ["2025", "2026"], max 3) restreint le TDB aux
    années choisies dans la page "TDB choix" — voir compute_reporting_periods.
    Sans argument, comportement inchangé (toutes les années comparables
    disponibles), pour ne pas casser les appels existants (CLI, main()).

    `axis_filter` (optionnel, ex. `("numero_unite_medicale", "3001")` ou
    `("type_hospitalisation", "1")`, 2026-08-04) : produit un TDB complet
    restreint à cette seule valeur d'UF/type d'hospitalisation — un TDB
    secondaire = un appel à build() par valeur (voir
    src/viz/render_dashboard.py generate_axis_reports()), pas une section en
    plus du TDB principal.

    `mois_fin` (optionnel, 1-12, 2026-08-05) : voir compute_reporting_periods —
    impose le mois de fin de période (toujours cumulatif depuis janvier)."""
    conn = connect()
    periods = compute_reporting_periods(conn, finess, years, mois_fin)
    years = [p["year"] for p in periods]
    sejours = section_sejours(conn, periods, finess, axis_filter)
    data = {
        "finess": finess,
        "periods": periods,
        "years": years,
        "sejours": sejours,
        "patients": {p["year"]: section_patients(conn, p, finess, axis_filter) for p in periods},
        "journees_semaine": section_journees_semaine(conn, periods, finess, axis_filter),
        "indicateurs": section_indicateurs(conn, periods, finess, axis_filter),
        "activite_csarr": section_activite_csarr(conn, periods, finess, axis_filter),
        "ponderation_csarr": section_ponderation_csarr(conn, periods, finess, axis_filter),
        "valorisation": section_valorisation(conn, periods, finess, sejours, axis_filter),
        "palmares_cm": section_palmares_gme(conn, periods, finess, "CM", axis_filter=axis_filter),
        "palmares_gn": section_palmares_gme(conn, periods, finess, "GN", axis_filter=axis_filter),
        "structure_gme": section_structure_gme(conn, periods, finess, axis_filter),
        "erreurs_activite": section_erreurs_activite(conn, periods, finess, axis_filter),
        "absence_csarr": section_absence_csarr(conn, periods, finess, axis_filter),
        "erreurs_groupage": section_erreurs_groupage(conn, periods, finess, axis_filter),
        "incoherences_vidhosp_rhs": section_incoherences_vidhosp_rhs(conn, finess),
    }
    conn.close()
    return data


if __name__ == "__main__":
    import json
    import sys
    conn = connect()
    target = sys.argv[1] if len(sys.argv) > 1 else list_finess(conn)[0]
    conn.close()
    print(json.dumps(build(target), ensure_ascii=False, indent=1))
