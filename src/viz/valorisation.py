"""Valeur produite par jour de présence, au prorata temporis du montant de
valorisation du séjour (valorisation_sejour.montant_br_tot), pour pouvoir
l'agréger sur une période calendaire arbitraire — colonne calculée "mnt_br_pt"
(montant brut, prorata temporis), à distinguer explicitement de montant_br_tot
qui reste la donnée ATIH officielle (l'arrêté de versement) telle que reçue,
jamais modifiée.

Principe de répartition (décision utilisateur du 2026-07-29, précisée le
2026-07-31) : pour chaque MONTANT réellement facturé (une ligne
valorisation_sejour avec montant_br_tot non nul), répartir ce montant de
façon UNIFORME sur les jours de présence RHS qui lui correspondent —
valeur_jour = montant_br_tot / nb_jours_de_presence_correspondants — puis
sommer ces valeurs jour par jour calendaire réel pour obtenir mnt_br_pt par
année civile. Deux cas bien distincts pour déterminer "les jours qui
correspondent" à un montant donné :

1. **Séjour à plusieurs campagnes valorisées (>90j, facturation
   INCRÉMENTALE)** — ex. [identifiant anonymise], séjour PMSI jamais clôturé : confirmé par
   la notice technique ATIH SMR (input/documentation/), « seules les
   journées non facturées en N-1 peuvent être facturées en N ». Chaque
   campagne valorise des jours différents, et l'attribution jour -> campagne
   suit la règle de la notice (p.34-35) : une semaine RHA est rattachée à
   l'année civile du DIMANCHE de cette semaine. Ici campagne (année de
   transmission) et année civile des jours coïncident par construction —
   mnt_br_pt par année civile = montant_br_tot par campagne.

2. **Séjour à une seule campagne valorisée, <90j, facturé à la clôture**
   (règle étendue le 2026-07-31, cf. séjours 12092797/12092888) — la
   facturation est un versement UNIQUE fait à la sortie, mais le séjour peut
   avoir démarré une année civile antérieure (ex. admis fin novembre 2024,
   clos début janvier 2025 : montant enregistré sous la campagne 2025, alors
   que la quasi-totalité des jours de présence RHS sont en 2024). Ici,
   contrairement au cas 1, la "campagne" ATIH (année de transmission de
   clôture) NE correspond PAS à l'année civile réelle des jours. Le montant
   unique est donc réparti sur TOUS les jours de présence RHS du séjour,
   toutes années confondues, et mnt_br_pt par année civile peut différer de
   montant_br_tot par campagne (ex. mnt_br_pt-2024 > 0 alors que
   montant_br_tot-campagne-2024 = 0€) — c'est précisément l'écart que ce
   calcul pro-rata temporis "home-made" met en évidence, à comparer avec les
   chiffres officiels de l'arrêté de versement (montant_br_tot par campagne).

3. **Séjour entrée=sortie le même jour calendaire (0 journée de présence
   RHS)** — le Guide Méthodologique (Annexe III) est explicite : ni le jour
   d'entrée ni le jour de sortie ne comptent comme "journée de présence"
   dans ce cas précis (règle générale : un jour ne compte que si le patient
   est "présent à minuit", jamais vrai ici) — le RHS a donc bien 0 jour
   marqué présent, ce n'est pas un défaut de données. Pourtant ATIH facture
   quand même un montant. Vérifié empiriquement (2026-07-31, 4 séjours,
   [etablissement anonymise] et [etablissement anonymise]) : ce montant reproduit EXACTEMENT (à l'arrondi
   près) le Supplément Zone Basse (SZB) du barème input/tarifs/tarifs_qv.xlsx
   multiplié par coeff_segur — c'est-à-dire le tarif d'exactement UN jour de
   zone basse. Ces séjours sont donc traités comme un cas particulier du cas
   2 (versement unique) où, à défaut de jour de présence RHS, on retombe sur
   la date d'entrée VID-HOSP comme unique jour d'attribution.

Le nombre de jours utilisé comme dénominateur vient du RHS (toujours
disponible), pas de valorisation_sejour.nb_jours_valorises_gmt/gmth : les
deux sont normalement identiques (vérifié empiriquement) mais NBJV_GMT/GMTH
peuvent être vides sur un séjour anormalement long (constaté sur [identifiant anonymise],
campagne 2026, GMT=9999) — utiliser le RHS évite de perdre ce montant.

Point d'attention rencontré : rhs_groupe.numero_admin_sejour est zero-paddé
(ex. "024870040") alors que valorisation_sejour.numero_admin_sejour ne l'est
pas (ex. "24870040") — la jointure se fait donc sur la valeur numérique, pas
la chaîne brute.
"""
from __future__ import annotations

import datetime
import sqlite3
from collections import defaultdict


def _rhs_presence_days_by_sejour(
    conn: sqlite3.Connection, finess: str | None = None
) -> dict[tuple[str, int], list[datetime.date]]:
    """Pour chaque séjour, TOUS ses jours calendaires de présence RHS,
    toutes années confondues (pas de partition par campagne ici)."""
    clause = "WHERE numero_semaine IS NOT NULL"
    params: list = []
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    rhs_rows = conn.execute(
        "SELECT finess_epmsi, numero_admin_sejour, numero_semaine, "
        "jours_hors_weekend, jours_weekend "
        f"FROM rhs_groupe {clause}",
        params,
    ).fetchall()

    out: dict[tuple[str, int], list[datetime.date]] = {}
    for finess, numadmin, numero_semaine, jhw, jwe in rhs_rows:
        week, year = int(numero_semaine[:2]), int(numero_semaine[2:6])
        flags = (jhw or "") + (jwe or "")
        for weekday, flag in enumerate(flags, start=1):
            if flag != "1":
                continue
            try:
                jour = datetime.date.fromisocalendar(year, week, weekday)
            except ValueError:
                continue
            key = (finess, int(numadmin))
            out.setdefault(key, []).append(jour)
    return out


def _rhs_presence_days_by_campagne(
    conn: sqlite3.Connection, finess: str | None = None
) -> dict[tuple[str, int, int], list[datetime.date]]:
    """Pour chaque (séjour, année de campagne), la liste des jours calendaires
    marqués présents dans le RHS groupé, rattachés à l'année civile du
    dimanche de leur semaine (règle notice p.34-35 — valable pour le cas
    incrémental >90j, cf. docstring module, cas 1)."""
    by_sejour = _rhs_presence_days_by_sejour(conn, finess)
    # Recompute per-day with the campagne (dimanche-year) key instead of
    # collapsing to the séjour alone.
    clause = "WHERE numero_semaine IS NOT NULL"
    params: list = []
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    rhs_rows = conn.execute(
        "SELECT finess_epmsi, numero_admin_sejour, numero_semaine, "
        "jours_hors_weekend, jours_weekend "
        f"FROM rhs_groupe {clause}",
        params,
    ).fetchall()

    out: dict[tuple[str, int, int], list[datetime.date]] = {}
    for finess, numadmin, numero_semaine, jhw, jwe in rhs_rows:
        week, year = int(numero_semaine[:2]), int(numero_semaine[2:6])
        try:
            dimanche = datetime.date.fromisocalendar(year, week, 7)
        except ValueError:
            continue
        campagne = dimanche.year
        flags = (jhw or "") + (jwe or "")
        for weekday, flag in enumerate(flags, start=1):
            if flag != "1":
                continue
            try:
                jour = datetime.date.fromisocalendar(year, week, weekday)
            except ValueError:
                continue
            key = (finess, int(numadmin), campagne)
            out.setdefault(key, []).append(jour)
    return out


def _rhs_presence_days_by_week(
    conn: sqlite3.Connection, finess: str | None = None
) -> dict[tuple[str, int, int, int], list[datetime.date]]:
    """Pour chaque (séjour, année, semaine ISO), ses jours calendaires de
    présence RHS — clé plus fine que _rhs_presence_days_by_campagne, utilisée
    pour attribuer un montant HTP (une ligne valorisation_sejour par semaine
    RHA, cf. docstring module cas 4) à SA semaine précise plutôt qu'à
    l'ensemble de l'année de campagne."""
    clause = "WHERE numero_semaine IS NOT NULL"
    params: list = []
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    rhs_rows = conn.execute(
        "SELECT finess_epmsi, numero_admin_sejour, numero_semaine, "
        "jours_hors_weekend, jours_weekend "
        f"FROM rhs_groupe {clause}",
        params,
    ).fetchall()

    out: dict[tuple[str, int, int, int], list[datetime.date]] = {}
    for finess_v, numadmin, numero_semaine, jhw, jwe in rhs_rows:
        week, year = int(numero_semaine[:2]), int(numero_semaine[2:6])
        flags = (jhw or "") + (jwe or "")
        for weekday, flag in enumerate(flags, start=1):
            if flag != "1":
                continue
            try:
                jour = datetime.date.fromisocalendar(year, week, weekday)
            except ValueError:
                continue
            key = (finess_v, int(numadmin), year, week)
            out.setdefault(key, []).append(jour)
    return out


def _date_entree_par_sejour(
    conn: sqlite3.Connection, finess: str | None = None
) -> dict[tuple[str, int], datetime.date]:
    """date_entree (VID-HOSP) par séjour — utilisée en dernier recours pour
    les séjours entrée=sortie le même jour calendaire (0 journée de présence
    RHS, cf. règle "présent à minuit" du Guide Méthodologique), qui sont
    quand même facturés 1 jour (vérifié 2026-07-31 : montant_br_tot de ces
    séjours reproduit exactement le Supplément Zone Basse × coeff_segur du
    barème tarifs_qv.xlsx — soit précisément le tarif d'UN jour de zone
    basse)."""
    clause = "WHERE date_entree IS NOT NULL"
    params: list = []
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    rows = conn.execute(
        f"SELECT finess_epmsi, numero_admin_sejour, date_entree FROM vid_hosp {clause}",
        params,
    ).fetchall()
    out: dict[tuple[str, int], datetime.date] = {}
    for finess_v, numadmin, date_entree in rows:
        out[(finess_v, int(numadmin))] = datetime.date.fromisoformat(date_entree)
    return out


EXCLUSION_MONTANT_OFFICIEL = (
    "COALESCE(nv_nonfactam, 0) = 0 AND COALESCE(nv_chain, 0) = 0 AND COALESCE(nv_attente_dts, 0) = 0"
)
"""Séjours exclus du montant BR officiel (arrêté de versement) partout où
`valorisation_sejour.montant_br_tot` est sommé pour affichage :

- `nv_nonfactam` ("non facturable Assurance Maladie", exclu 2026-07-31) :
  vérifié sur [etablissement anonymise]/2026, 1 séjour HC à 37703.63€.
- `nv_chain` ("chaînage") et `nv_attente_dts` ("en attente de droits", ajoutés
  2026-08-05) : trouvés empiriquement en reproduisant EXACTEMENT au centime
  près deux totaux d'un tableau ATIH externe fourni par l'utilisateur —
  [etablissement anonymise]/2026 (765717.70€ − 2 séjours NV_CHAIN à 40618.11€ = 725099.59€)
  et [etablissement anonymise]/2026 (630123.81€ − 4 séjours NV_ATTENTE_DTS à 23141.53€ − 1
  séjour NV_CHAIN à 7117.00€ = 599865.28€).

Toutes les AUTRES variables NV_* du fichier VisualValoSejours (nv_cm90,
nv_nonclos, nv_pie, nv_varano, nv_article51, nv_telereadapt, nv_evcepr,
nv_gmt9999, nv_horsperiode) ont été testées sur ces deux mêmes cas et NE
CONTRIBUENT PAS à reproduire les totaux ATIH (montant associé = 0€ ou déjà
couvert par une autre exclusion) — ne pas les exclure sans nouvelle preuve
empirique contre une référence externe."""


def _rhs_day_axis(
    conn: sqlite3.Connection, finess: str | None = None
) -> dict[tuple[str, int, datetime.date], tuple[str | None, str | None]]:
    """Pour chaque jour de présence RHS, l'UF (`numero_unite_medicale`) et le
    type d'hospitalisation de la ligne RHS qui l'a produit — utilisé pour
    ventiler compute_valeur_journaliere par axe (TDB secondaire "par UF" /
    "par type d'hospitalisation", 2026-08-04) SANS changer le dénominateur
    (nb total de jours du séjour/de la campagne) qui détermine le tarif
    journalier — seule la sélection des jours SOMMÉS dans le résultat change,
    pas le calcul de valeur_jour lui-même."""
    clause = "WHERE numero_semaine IS NOT NULL"
    params: list = []
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    rows = conn.execute(
        "SELECT finess_epmsi, numero_admin_sejour, numero_semaine, "
        "jours_hors_weekend, jours_weekend, numero_unite_medicale, type_hospitalisation "
        f"FROM rhs_groupe {clause}",
        params,
    ).fetchall()
    out: dict[tuple[str, int, datetime.date], tuple[str | None, str | None]] = {}
    for finess_v, numadmin, numero_semaine, jhw, jwe, uf, type_hosp in rows:
        week, year = int(numero_semaine[:2]), int(numero_semaine[2:6])
        flags = (jhw or "") + (jwe or "")
        for weekday, flag in enumerate(flags, start=1):
            if flag != "1":
                continue
            try:
                jour = datetime.date.fromisocalendar(year, week, weekday)
            except ValueError:
                continue
            out[(finess_v, int(numadmin), jour)] = (uf, type_hosp)
    return out


def _matches_axis(
    day_axis: dict[tuple[str, int, datetime.date], tuple[str | None, str | None]],
    axis_filter: tuple[str, str] | None,
    finess_v: str,
    numadmin: int,
    jour: datetime.date,
) -> bool:
    if axis_filter is None:
        return True
    got = day_axis.get((finess_v, numadmin, jour))
    if got is None:
        return False
    uf, type_hosp = got
    champ, valeur = axis_filter
    value = uf if champ == "numero_unite_medicale" else type_hosp
    return value == valeur


def compute_valeur_journaliere(
    conn: sqlite3.Connection, finess: str | None = None, axis_filter: tuple[str, str] | None = None
) -> list[dict]:
    """Une ligne par (séjour, jour de présence RHS concerné) avec sa valeur
    pro-rata temporis (mnt_br_pt). `campagne` porte l'année de la campagne
    ATIH qui a produit ce montant (utile pour tracer sa provenance), mais
    `date` — et donc l'année civile réelle utilisée pour agréger mnt_br_pt —
    peut appartenir à une autre année civile que `campagne` (cf. cas 2 dans
    la docstring module). `finess` filtre sur l'établissement — sans lui, un
    TDB multi-établissements sommerait le montant de TOUS les établissements
    de la base (bug corrigé 2026-07-30).

    `axis_filter` (optionnel, ex. `("numero_unite_medicale", "3001")` ou
    `("type_hospitalisation", "1")`, 2026-08-04) : pour le TDB secondaire "par
    UF"/"par type d'hospitalisation", répartit le montant du séjour au
    PRORATA de ses journées de présence qui tombent dans le filtre — le tarif
    journalier (valeur_jour = montant / nb jours total) reste calculé sur le
    total des jours du séjour/campagne, seuls les jours SOMMÉS dans le
    résultat sont restreints à ceux dont la ligne RHS d'origine correspond au
    filtre. Nouvelle hypothèse de calcul, non validée contre une référence
    ATIH externe (contrairement au reste de ce module)."""
    day_axis = _rhs_day_axis(conn, finess) if axis_filter else {}
    # montant_br_tot = 0.0 n'est pas une vraie facturation (campagne où le
    # séjour existe mais n'a encore rien déclenché de facturable, distinct
    # de NULL en base mais équivalent ici) : exclu au même titre que NULL,
    # sinon une campagne à 0€ ferait à tort compter le séjour comme
    # "plusieurs campagnes valorisées" (cas 1) au lieu de "clôture unique"
    # (cas 2) — bug trouvé sur les séjours 12092797/12092888 (2026-07-31).
    # nv_nonfactam=1 ("non facturable Assurance Maladie") exclu : un séjour
    # ainsi marqué porte quand même un montant_br_tot (valeur de production),
    # mais ce n'est pas une vraie facturation AM — l'inclure gonflait notre
    # total par rapport à la restitution ATIH de référence (trouvé 2026-07-31
    # sur [etablissement anonymise]/2026 : 1 séjour HC à 37703.63€, marqué nv_nonfactam=1).
    clause = f"WHERE montant_br_tot IS NOT NULL AND montant_br_tot != 0 AND {EXCLUSION_MONTANT_OFFICIEL}"
    params: list = []
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    valo_rows = conn.execute(
        "SELECT finess_epmsi, numero_admin_sejour, campagne, numero_semaine, montant_br_tot "
        f"FROM valorisation_sejour {clause}",
        params,
    ).fetchall()

    # Regroupement à deux niveaux : par séjour, puis par campagne au sein du
    # séjour — nécessaire depuis le correctif du natural_key (2026-07-31) qui
    # a arrêté de collapser les lignes HTP (une par semaine RHA au sein d'une
    # même campagne, cf. numero_rha dans le schéma) : un groupe "campagne" peut
    # désormais contenir PLUSIEURS lignes, chacune pour SA semaine propre.
    rows_by_sejour: dict[tuple[str, int], dict[int, list[tuple[str, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for finess_v, numadmin, campagne, numero_semaine, montant in valo_rows:
        rows_by_sejour[(finess_v, int(numadmin))][campagne].append((numero_semaine, montant))

    presence_all = _rhs_presence_days_by_sejour(conn, finess)
    presence_by_campagne = _rhs_presence_days_by_campagne(conn, finess)
    presence_by_week = _rhs_presence_days_by_week(conn, finess)
    date_entree_par_sejour = _date_entree_par_sejour(conn, finess)

    out = []
    for (finess_v, numadmin), campagnes in rows_by_sejour.items():
        n_campagnes = len(campagnes)
        for campagne, rows_in_campagne in campagnes.items():
            if len(rows_in_campagne) > 1:
                # Cas 4 : facturation HTP incrémentale PAR SEMAINE au sein
                # d'une même campagne — chaque ligne (une semaine RHA) est
                # répartie sur SES PROPRES jours de présence, pas sur
                # l'ensemble de l'année de campagne (qui mélangerait les
                # montants de semaines différentes entre elles).
                for numero_semaine, montant in rows_in_campagne:
                    annee_sem, semaine = int(numero_semaine[:4]), int(numero_semaine[4:6])
                    jours = presence_by_week.get((finess_v, numadmin, annee_sem, semaine))
                    if not jours:
                        continue
                    valeur_jour = montant / len(jours)
                    out.extend(
                        {
                            "finess_epmsi": finess_v,
                            "numero_admin_sejour": numadmin,
                            "campagne": campagne,
                            "date": jour,
                            "valeur": valeur_jour,
                        }
                        for jour in jours
                        if _matches_axis(day_axis, axis_filter, finess_v, numadmin, jour)
                    )
                continue

            numero_semaine, montant = rows_in_campagne[0]
            if n_campagnes == 1:
                # Cas 2 : versement unique à la clôture (<90j). Le montant peut
                # couvrir des jours d'une année civile différente de la
                # campagne de transmission — répartir sur TOUS les jours de
                # présence RHS du séjour, toutes années confondues.
                jours = presence_all.get((finess_v, numadmin))
                if not jours:
                    # Séjour entrée=sortie le même jour (0 journée de présence
                    # RHS par construction) mais quand même facturé 1 jour de
                    # zone basse (vérifié empiriquement, voir
                    # _date_entree_par_sejour) : à défaut de jour de présence
                    # RHS, on retombe sur la date d'entrée VID-HOSP.
                    date_entree = date_entree_par_sejour.get((finess_v, numadmin))
                    if date_entree is None:
                        continue
                    jours = [date_entree]
            else:
                # Cas 1 : facturation incrémentale >90j, une campagne = une
                # année civile distincte de jours (règle du dimanche).
                jours = presence_by_campagne.get((finess_v, numadmin, campagne))
                if not jours:
                    continue
            valeur_jour = montant / len(jours)
            out.extend(
                {
                    "finess_epmsi": finess_v,
                    "numero_admin_sejour": numadmin,
                    "campagne": campagne,
                    "date": jour,
                    "valeur": valeur_jour,
                }
                for jour in jours
                if _matches_axis(day_axis, axis_filter, finess_v, numadmin, jour)
            )
    return out


def montant_br_tot_campagne(conn: sqlite3.Connection, campagne: int, finess: str | None = None) -> float:
    """montant_br_tot officiel ATIH (arrêté de versement), sommé pour une
    CAMPAGNE (année de transmission) donnée — à comparer avec mnt_br_pt de
    la même année civile pour visualiser l'écart dû aux séjours facturés à
    cheval sur le 31/12 (cf. docstring module).

    montant_br_trans (suppléments transport) EXCLU : vérifié 2026-07-31 sur
    [etablissement anonymise]/2026 face à la restitution Ovalide « Casemix par GME/GMT »
    (input/valorisation/ovalide/) — le total HC officiel qu'elle affiche
    (847380.16€) est EXACTEMENT la somme de sa colonne « Montant BR Total
    séjour (A+B+C) » = GMT + GMT hebdo + suppléments cancérologie, et exclut
    le transport (reporté ailleurs par ATIH). montant_br_tot (colonne du CSV
    VisualValoSejours), lui, inclut le transport — sans cette exclusion notre
    total dépassait le leur de 17907.81€, exactement la somme de
    montant_br_trans sur les séjours HC concernés."""
    clause = f"WHERE campagne = ? AND montant_br_tot IS NOT NULL AND {EXCLUSION_MONTANT_OFFICIEL}"
    params: list = [campagne]
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    return conn.execute(
        f"SELECT SUM(montant_br_tot - COALESCE(montant_br_trans, 0)) FROM valorisation_sejour {clause}",
        params,
    ).fetchone()[0] or 0.0


def _derniere_semaine_rhs_par_sejour(
    conn: sqlite3.Connection, campagne: int, finess: str | None = None
) -> dict[int, int]:
    """Pour chaque séjour, le numéro de semaine ISO le plus élevé (1-53) parmi
    ses lignes RHS groupé dont l'ANNÉE du numero_semaine est `campagne` — sert
    à approximer si ce séjour était déjà clos/connu à une date donnée de
    l'année (cf. montant_br_tot_campagne_comparable)."""
    clause = "WHERE numero_semaine IS NOT NULL AND CAST(SUBSTR(numero_semaine, 3, 4) AS INTEGER) = ?"
    params: list = [campagne]
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    rows = conn.execute(
        f"SELECT numero_admin_sejour, numero_semaine FROM rhs_groupe {clause}",
        params,
    ).fetchall()
    out: dict[int, int] = {}
    for numadmin, numero_semaine in rows:
        numadmin = int(numadmin)
        week = int(numero_semaine[:2])
        if week > out.get(numadmin, 0):
            out[numadmin] = week
    return out


def montant_br_tot_campagne_comparable(
    conn: sqlite3.Connection, campagne: int, max_week: int, finess: str | None = None, exclure: bool = True
) -> float:
    """montant_br_tot officiel ATIH, mais restreint aux séjours dont TOUTE
    l'activité RHS (de cette campagne) tient dans les semaines 01..max_week —
    c-à-d des séjours qui, comme ceux d'une VRAIE transmission "M04", étaient
    déjà clos/connus à cette date. Nécessaire car les fichiers 2024/2025 dont
    on dispose sont des transmissions M12 (année complète, chaque séjour y
    figure avec son montant final de l'année), donc PAS directement
    comparables à une transmission M04 (2026) sans ce filtre — un séjour
    encore actif en semaine 30 (juillet) n'aurait pas encore de montant
    connu/stable dans une vraie transmission M04, alors qu'il apparaît déjà
    soldé dans le fichier M12 qu'on a chargé.

    Limite assumée (demande utilisateur 2026-07-31, "je ne sais pas si on
    peut extraire juste ces séjours") : on n'a PAS de vraie transmission M04
    pour 2024/2025, donc ceci reste une APPROXIMATION a posteriori (séjour
    clos avant la semaine limite ⇒ son montant aurait normalement déjà été
    stable/connu à ce moment), pas une reconstruction exacte de ce qu'aurait
    contenu une transmission M04 réelle.

    `exclure` (2026-08-05, demande utilisateur) : si False, ne filtre PAS
    sur EXCLUSION_MONTANT_OFFICIEL (nv_nonfactam/nv_chain/nv_attente_dts) —
    donne le montant BRUT, toutes anomalies comprises. La différence entre
    l'appel filtré (exclure=True, le montant "officiel" affiché ailleurs) et
    ce montant brut est la recette non perçue à cause de ces anomalies
    (montant_br_non_fact, voir section_valorisation)."""
    dernieres_semaines = _derniere_semaine_rhs_par_sejour(conn, campagne, finess)

    # Exclusions cf. EXCLUSION_MONTANT_OFFICIEL. montant_br_trans (transport)
    # exclu aussi, cf. docstring de montant_br_tot_campagne — même correctif,
    # même vérification.
    condition_exclusion = EXCLUSION_MONTANT_OFFICIEL if exclure else "1 = 1"
    clause = f"WHERE campagne = ? AND montant_br_tot IS NOT NULL AND {condition_exclusion}"
    params: list = [campagne]
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    rows = conn.execute(
        "SELECT numero_admin_sejour, montant_br_tot - COALESCE(montant_br_trans, 0) "
        f"FROM valorisation_sejour {clause}",
        params,
    ).fetchall()

    total = 0.0
    for numadmin, montant in rows:
        numadmin = int(numadmin)
        derniere_semaine = dernieres_semaines.get(numadmin)
        if derniere_semaine is not None and derniere_semaine <= max_week:
            total += montant
    return total


def montant_br_pt_par_annee(conn: sqlite3.Connection, finess: str | None = None) -> dict[int, float]:
    """mnt_br_pt agrégé par ANNÉE CIVILE RÉELLE des jours de présence — à
    comparer avec montant_br_tot agrégé par CAMPAGNE (année de transmission
    ATIH) pour vérifier/expliquer les écarts (cf. docstring module, cas 2)."""
    totals: dict[int, float] = defaultdict(float)
    for row in compute_valeur_journaliere(conn, finess):
        totals[row["date"].year] += row["valeur"]
    return dict(totals)


def valeur_sur_periode(
    conn: sqlite3.Connection,
    date_debut: datetime.date,
    date_fin: datetime.date,
    finess: str | None = None,
    axis_filter: tuple[str, str] | None = None,
) -> float:
    """Somme des valeurs journalières pro-rata dont le jour tombe dans
    [date_debut, date_fin] (bornes incluses). `axis_filter` : voir
    compute_valeur_journaliere (TDB secondaire par UF/type d'hospitalisation)."""
    rows = compute_valeur_journaliere(conn, finess, axis_filter)
    return sum(r["valeur"] for r in rows if date_debut <= r["date"] <= date_fin)


def sejours_non_factures_sans_anomalie(conn: sqlite3.Connection, finess: str, campagne: int) -> set[int]:
    """ESSAI (demande utilisateur 2026-08-05, facile à retirer — voir
    estimation_recettes_sejours_en_cours). Séjours actifs dans `campagne`
    (au moins 1 ligne RHS dont l'année du numero_semaine est `campagne`)
    qui n'ont ENCORE aucun montant_br_tot connu (séjour <90j pas encore
    clos, GMT=9999 par construction — cf. docstring module) ET qui ne
    portent AUCUNE des 3 anomalies d'EXCLUSION_MONTANT_OFFICIEL
    (nv_chain/nv_attente_dts/nv_nonfactam). Distinction importante trouvée
    empiriquement en creusant un écart signalé par l'utilisateur : sur
    [etablissement anonymise]/2026, 18 des 20 séjours "jamais facturés" sont en fait
    marqués nv_chain — pas de simples séjours en attente, mais des
    anomalies à part. Seuls les séjours vraiment "propres" sont candidats
    à l'estimation ci-dessous."""
    actifs = {
        int(r[0])
        for r in conn.execute(
            "SELECT DISTINCT numero_admin_sejour FROM rhs_groupe "
            "WHERE finess_epmsi = ? AND substr(numero_semaine, 3, 4) = ?",
            [finess, str(campagne)],
        ).fetchall()
    }
    deja_factures = {
        int(r[0])
        for r in conn.execute(
            "SELECT DISTINCT numero_admin_sejour FROM valorisation_sejour "
            "WHERE finess_epmsi = ? AND montant_br_tot IS NOT NULL",
            [finess],
        ).fetchall()
    }
    en_anomalie = {
        int(r[0])
        for r in conn.execute(
            "SELECT DISTINCT numero_admin_sejour FROM valorisation_sejour "
            "WHERE finess_epmsi = ? AND (COALESCE(nv_chain, 0) != 0 OR COALESCE(nv_attente_dts, 0) != 0 "
            "OR COALESCE(nv_nonfactam, 0) != 0)",
            [finess],
        ).fetchall()
    }
    return (actifs - deja_factures) - en_anomalie


def estimation_recettes_sejours_en_cours(
    conn: sqlite3.Connection, period: dict, finess: str, pmjt: float | None
) -> dict:
    """ESSAI (demande utilisateur 2026-08-05). Estime la recette non encore
    facturée des séjours <90j non clos "propres" (voir
    sejours_non_factures_sans_anomalie) en appliquant le PMJT RÉEL — calculé
    à partir de montant_br_pt/nb_journées déjà observés, PAS recalculé avec
    cette estimation — à leurs journées de présence RHS dans la période.
    Volontairement PAS de boucle : le taux (PMJT) et l'estimation qui
    l'utilise ne partagent jamais le même calcul. Résultat affiché à part de
    montant_br_pt, jamais fusionné dedans — nouvelle hypothèse non validable
    contre une référence externe par construction (ces séjours n'ont encore
    aucun montant ATIH connu)."""
    if not pmjt:
        return {"montant": 0.0, "nb_sejours": 0, "nb_journees": 0}
    cible = sejours_non_factures_sans_anomalie(conn, finess, int(period["year"]))
    if not cible:
        return {"montant": 0.0, "nb_sejours": 0, "nb_journees": 0}
    presence = _rhs_presence_days_by_sejour(conn, finess)
    nb_journees = 0
    for numadmin in cible:
        jours = presence.get((finess, numadmin), [])
        nb_journees += sum(1 for j in jours if period["start"] <= j <= period["end"])
    return {"montant": nb_journees * pmjt, "nb_sejours": len(cible), "nb_journees": nb_journees}
