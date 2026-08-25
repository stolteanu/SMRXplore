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
from functools import lru_cache


def _norm_numadmin(raw) -> str:
    """Normalise numero_admin_sejour pour le matching rhs_groupe/valorisation_sejour
    (zero-paddé côté RHS, pas côté valorisation, cf. note ci-dessus) : retire les
    zéros de tête comme le ferait int(), mais SANS planter sur une valeur
    alphanumérique erronée (ex. "070246515N001", un numéro de dossier faux
    constaté dans un fichier source mais qui doit quand même être chargé en
    base, 2026-08-07) — une telle valeur est alors simplement dépouillée de ses
    zéros de tête et gardée telle quelle comme clé."""
    s = str(raw).strip()
    return s.lstrip("0") or "0"


@lru_cache(maxsize=64)
def _rhs_presence_days_by_sejour(
    conn: sqlite3.Connection, finess: str | None = None
) -> dict[tuple[str, int], list[datetime.date]]:
    """Pour chaque séjour, TOUS ses jours calendaires de présence RHS,
    toutes années confondues (pas de partition par campagne ici).

    Mise en cache (2026-08-25, correctif de performance) : résultat pur
    fonction de (conn, finess), identique quel que soit l'axis_filter — un
    TDB secondaire "par UF" appelle cette fonction une fois par valeur d'UF
    (voir generate_axis_reports), qui rescannait sinon `rhs_groupe` en
    entier à chaque fois (jusqu'à ~900k appels à _norm_numadmin observés au
    profilage pour un seul établissement). La clé de cache est l'IDENTITÉ de
    l'objet connexion (sqlite3.Connection est hashable par défaut) : une
    nouvelle connexion (nouvel appel à connect()) invalide automatiquement
    le cache, donc aucun risque de données périmées après un rechargement.
    Accès uniquement en lecture par tous les appelants (jamais muté) —
    sûr à partager entre appels."""
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
            key = (finess, _norm_numadmin(numadmin))
            out.setdefault(key, []).append(jour)
    return out


@lru_cache(maxsize=64)
def _dernier_uf_par_sejour(conn: sqlite3.Connection, finess: str | None = None) -> dict[tuple[str, int], str]:
    """Mise en cache : voir _rhs_presence_days_by_sejour.

    Dernière UF connue (numero_unite_medicale de la dernière semaine RHS)
    par séjour — filet de sécurité pour la ventilation UF de montant_br_tot
    (2026-08-05) quand un séjour n'a AUCUNE journée de présence RHS (cas
    "entrée=sortie le même jour calendaire", cf. docstring module) : pas de
    jour à répartir en %, donc tout son montant va à cette dernière UF
    connue plutôt que d'être silencieusement perdu (trouvé en vérifiant que
    la somme sur toutes les UF reproduit exactement le total établissement —
    exigence explicite de l'utilisateur — écart de 528.94€ sur [etablissement anonymise]/2026
    avant ce correctif, exactement les 2 séjours "0 jour" 27086914/27087145)."""
    clause = "WHERE numero_unite_medicale IS NOT NULL AND numero_unite_medicale != ''"
    params: list = []
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    rows = conn.execute(
        f"SELECT finess_epmsi, numero_admin_sejour, numero_semaine, numero_unite_medicale FROM rhs_groupe {clause}",
        params,
    ).fetchall()
    best: dict[tuple[str, int], tuple[int, str]] = {}
    for finess_v, numadmin, numero_semaine, uf in rows:
        key = (finess_v, _norm_numadmin(numadmin))
        week = int(numero_semaine[:2])
        prev = best.get(key)
        if prev is None or week >= prev[0]:
            best[key] = (week, uf)
    return {k: v[1] for k, v in best.items()}


@lru_cache(maxsize=64)
def _rhs_presence_days_by_campagne(
    conn: sqlite3.Connection, finess: str | None = None
) -> dict[tuple[str, int, int], list[datetime.date]]:
    """Pour chaque (séjour, année de campagne), la liste des jours calendaires
    marqués présents dans le RHS groupé, rattachés à l'année civile du
    dimanche de leur semaine (règle notice p.34-35 — valable pour le cas
    incrémental >90j, cf. docstring module, cas 1).

    Mise en cache : voir _rhs_presence_days_by_sejour (même justification,
    même garantie de fraîcheur via l'identité de connexion)."""
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
            key = (finess, _norm_numadmin(numadmin), campagne)
            out.setdefault(key, []).append(jour)
    return out


@lru_cache(maxsize=64)
def _rhs_presence_days_by_week(
    conn: sqlite3.Connection, finess: str | None = None
) -> dict[tuple[str, int, int, int], list[datetime.date]]:
    """Pour chaque (séjour, année, semaine ISO), ses jours calendaires de
    présence RHS — clé plus fine que _rhs_presence_days_by_campagne, utilisée
    pour attribuer un montant HTP (une ligne valorisation_sejour par semaine
    RHA, cf. docstring module cas 4) à SA semaine précise plutôt qu'à
    l'ensemble de l'année de campagne.

    Mise en cache : voir _rhs_presence_days_by_sejour."""
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
            key = (finess_v, _norm_numadmin(numadmin), year, week)
            out.setdefault(key, []).append(jour)
    return out


@lru_cache(maxsize=64)
def _date_entree_par_sejour(
    conn: sqlite3.Connection, finess: str | None = None
) -> dict[tuple[str, int], datetime.date]:
    """Mise en cache : voir _rhs_presence_days_by_sejour.

    date_entree (VID-HOSP) par séjour — utilisée en dernier recours pour
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
        out[(finess_v, _norm_numadmin(numadmin))] = datetime.date.fromisoformat(date_entree)
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


TYPE_HOSPITALISATION_GROUPES = {"1": "1", "2": "2", "3": "2"}
"""Fusionne HTP jour (2) et HTP nuit (3) en un seul groupe "2" — demande
utilisateur 2026-08-05 : établissement non spécialisé en HTP de nuit, la
distinction jour/nuit n'a pas de sens ici ("tout est de jour"). Code "1" (HC)
seul dans son groupe. Appliqué à la source dans _rhs_day_axis pour que TOUT
le reste du module (day_axis, montant_br_tot_campagne_comparable, TDB
secondaire par type d'hospitalisation) ne voie plus jamais le code "3" isolé."""


@lru_cache(maxsize=64)
def _rhs_day_axis(
    conn: sqlite3.Connection, finess: str | None = None
) -> dict[tuple[str, int, datetime.date], tuple[str | None, str | None]]:
    """Mise en cache : voir _rhs_presence_days_by_sejour.

    Pour chaque jour de présence RHS, l'UF (`numero_unite_medicale`) et le
    type d'hospitalisation de la ligne RHS qui l'a produit — utilisé pour
    ventiler compute_valeur_journaliere par axe (TDB secondaire "par UF" /
    "par type d'hospitalisation", 2026-08-04) SANS changer le dénominateur
    (nb total de jours du séjour/de la campagne) qui détermine le tarif
    journalier — seule la sélection des jours SOMMÉS dans le résultat change,
    pas le calcul de valeur_jour lui-même. Le type d'hospitalisation est
    normalisé via TYPE_HOSPITALISATION_GROUPES (HTP jour/nuit fusionnés)."""
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
        type_hosp = TYPE_HOSPITALISATION_GROUPES.get(type_hosp, type_hosp)
        flags = (jhw or "") + (jwe or "")
        for weekday, flag in enumerate(flags, start=1):
            if flag != "1":
                continue
            try:
                jour = datetime.date.fromisocalendar(year, week, weekday)
            except ValueError:
                continue
            out[(finess_v, _norm_numadmin(numadmin), jour)] = (uf, type_hosp)
    return out


def _axis_value_matches(value: str | None, valeur) -> bool:
    """Compare une valeur d'axe (UF ou type d'hospitalisation) à la valeur du
    filtre — qui peut être soit une valeur unique, soit une liste/tuple/set de
    codes UF (regroupement en "service" défini par l'utilisateur, cf.
    _period_filter dans tableau_de_bord.py, même sémantique IN (...)). Sans ce
    cas de liste, un groupe ne matchait jamais aucun jour (comparaison
    str == list toujours fausse) et la valorisation par groupe d'UF ressortait
    à zéro — centralisé ici pour que tous les points de calcul (jour par jour
    et montant officiel par séjour) traitent les groupes de la même façon."""
    if isinstance(valeur, (list, tuple, set)):
        return value in valeur
    return value == valeur


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
    return _axis_value_matches(value, valeur)


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
    # montant_br_sej (= montant_br_gmt + montant_br_gmth, SANS supplément —
    # transport/molécules onéreuses/cancérologie exclus, voir docstring
    # module et _ensure_montant_br_sej_column dans src/storage/valorisation_store.py)
    # = 0.0 n'est pas une vraie facturation (campagne où le séjour existe
    # mais n'a encore rien déclenché de facturable) : exclu au même titre que
    # NULL, sinon une campagne à 0€ ferait à tort compter le séjour comme
    # "plusieurs campagnes valorisées" (cas 1) au lieu de "clôture unique"
    # (cas 2) — bug trouvé sur les séjours 12092797/12092888 (2026-07-31).
    # nv_nonfactam=1 ("non facturable Assurance Maladie") exclu : un séjour
    # ainsi marqué porte quand même un montant (valeur de production), mais
    # ce n'est pas une vraie facturation AM — l'inclure gonflait notre total
    # par rapport à la restitution ATIH de référence (trouvé 2026-07-31 sur
    # [etablissement anonymise]/2026 : 1 séjour HC à 37703.63€, marqué nv_nonfactam=1).
    clause = f"WHERE montant_br_sej IS NOT NULL AND montant_br_sej != 0 AND {EXCLUSION_MONTANT_OFFICIEL}"
    params: list = []
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    valo_rows = conn.execute(
        "SELECT finess_epmsi, numero_admin_sejour, campagne, numero_semaine, montant_br_sej "
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
        rows_by_sejour[(finess_v, _norm_numadmin(numadmin))][campagne].append((numero_semaine, montant))

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
        numadmin = _norm_numadmin(numadmin)
        week = int(numero_semaine[:2])
        if week > out.get(numadmin, 0):
            out[numadmin] = week
    return out


RHS_VERS_VALO_TYPE_HOSPITALISATION = {"1": "C", "2": "P", "3": "P"}
"""Traduit les codes `type_hospitalisation` du RHS groupé (1=HC, 2=HTP jour,
3=HTP nuit) vers ceux, DIFFÉRENTS, de `valorisation_sejour.type_hospitalisation`
(C=Complète, P=Partielle — pas de distinction jour/nuit côté valorisation).
Utilisé pour ventiler montant_br_tot par type d'hospitalisation (2026-08-05,
demande utilisateur) : contrairement à l'UF (aucune colonne équivalente dans
VisualValoSejours), le type d'hospitalisation EST une colonne native du
fichier de valorisation — chaque ligne y est déjà typée à la source, pas
besoin de la déduire du RHS. Vérifié sur [etablissement anonymise]/2026 : la somme HC+HTP
(847380.16€ + 130354.22€ = 977734.38€) reproduit EXACTEMENT le total
établissement déjà validé, et le montant HC seul (847380.16€) est le même
chiffre déjà confirmé le 2026-07-31 contre la restitution Ovalide "Casemix
par GME/GMT" (voir docstring montant_br_tot_campagne)."""


def montant_br_tot_campagne_comparable(
    conn: sqlite3.Connection,
    campagne: int,
    max_week: int,
    finess: str | None = None,
    exclure: bool = True,
    axis_filter: tuple[str, str] | None = None,
) -> float:
    """montant_br_sej (= montant_br_gmt + montant_br_gmth, SANS supplément —
    décision utilisateur 2026-08-21, voir _ensure_montant_br_sej_column dans
    src/storage/valorisation_store.py ; anciennement montant_br_tot -
    montant_br_trans, qui restait pollué par les molécules onéreuses et le
    supplément cancérologie — les suppléments sont désormais TOUS exclus
    d'ici et communiqués à part, voir montant_br_supplements_campagne_comparable
    ci-dessous), mais restreint aux séjours dont TOUTE l'activité RHS (de
    cette campagne) tient dans les semaines 01..max_week —
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
    (montant_br_non_fact, voir section_valorisation).

    `axis_filter` (2026-08-05, demande utilisateur) : deux ventilations
    supportées, TOUJOURS exactes (la somme sur toutes les valeurs de l'axe
    reproduit le total établissement — vérifié, demande explicite
    utilisateur) :
    - `("type_hospitalisation", "1"/"2"/"3")` : colonne NATIVE
      `valorisation_sejour.type_hospitalisation` (C/P via
      RHS_VERS_VALO_TYPE_HOSPITALISATION) — chaque ligne de facturation est
      déjà typée à la source, filtre SQL direct.
    - `("numero_unite_medicale", "...")` : AUCUNE colonne équivalente dans
      VisualValoSejours, donc chaque séjour sélectionné voit son montant
      OFFICIEL réparti au prorata de ses JOURNÉES DE PRÉSENCE par UF —
      TOUTES campagnes confondues (pas restreint à la période étudiée : un
      séjour à cheval reste réparti selon sa présence en UF sur l'ensemble
      de son séjour, cf. demande utilisateur 2026-08-05 — exemple séjour de
      100j, 80j en UF A / 20j en UF B ⇒ 80%/20% du montant facturé, quelle
      que soit la période affichée). Différent de `montant_br_pt` (qui, lui,
      ne compte que les jours DANS la période étudiée) — cette ventilation-ci
      reste par construction toujours égale au total établissement une fois
      sommée sur toutes les UF, contrairement à une simple somme de
      `montant_br_pt` par UF."""
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

    champ = valeur = None
    if axis_filter is not None:
        champ, valeur = axis_filter
        if champ == "type_hospitalisation":
            # HTP jour/nuit fusionnés (TYPE_HOSPITALISATION_GROUPES) : "2"
            # est le SEUL code HTP possible en pratique désormais (valeurs_axe
            # ne renvoie plus jamais "3" isolément), donc un simple filtre SQL
            # exact sur la colonne native C/P suffit — pas d'ambiguïté à
            # gérer par jour de présence, contrairement à l'UF.
            clause += " AND type_hospitalisation = ?"
            params.append(RHS_VERS_VALO_TYPE_HOSPITALISATION[valeur])
        elif champ != "numero_unite_medicale":
            raise ValueError(
                f"montant_br_tot n'est pas ventilable par {champ!r} (attendu : 'type_hospitalisation' "
                "ou 'numero_unite_medicale')."
            )

    rows = conn.execute(
        "SELECT numero_admin_sejour, montant_br_sej "
        f"FROM valorisation_sejour {clause}",
        params,
    ).fetchall()

    day_axis: dict = {}
    presence_all: dict = {}
    dernier_uf: dict = {}
    if champ == "numero_unite_medicale":
        day_axis = _rhs_day_axis(conn, finess)
        presence_all = _rhs_presence_days_by_sejour(conn, finess)
        dernier_uf = _dernier_uf_par_sejour(conn, finess)

    total = 0.0
    for numadmin, montant in rows:
        numadmin = _norm_numadmin(numadmin)
        derniere_semaine = dernieres_semaines.get(numadmin)
        if derniere_semaine is None or derniere_semaine > max_week:
            continue
        if champ == "numero_unite_medicale":
            jours = presence_all.get((finess, numadmin), [])
            if not jours:
                # Séjour "0 jour de présence" (entrée=sortie même jour) : pas
                # de journée à répartir en % — tout le montant va à sa
                # dernière UF connue (voir _dernier_uf_par_sejour), sinon il
                # disparaîtrait de la somme sur toutes les UF.
                if _axis_value_matches(dernier_uf.get((finess, numadmin)), valeur):
                    total += montant
                continue
            jours_uf = sum(1 for j in jours if _axis_value_matches(day_axis.get((finess, numadmin, j), (None, None))[0], valeur))
            total += montant * (jours_uf / len(jours))
        else:
            total += montant
    return total


def montant_br_supplements_campagne_comparable(
    conn: sqlite3.Connection,
    campagne: int,
    max_week: int,
    finess: str | None = None,
) -> dict[str, float]:
    """Suppléments EXCLUS de montant_br_sej — transport (`montant_br_trans`),
    molécules onéreuses (`montant_am_med`), supplément cancérologie
    (`montant_br_supp_cancero`) — décision utilisateur 2026-08-21 : "en sus"
    du séjour, communiqués À PART plutôt que mélangés au prix par journée
    (voir montant_br_tot_campagne_comparable et compute_valeur_journaliere).
    Même filtre de comparabilité (max_week) et même exclusion d'anomalies
    (EXCLUSION_MONTANT_OFFICIEL) que le total principal, pour que
    total + suppléments reste interprétable."""
    dernieres_semaines = _derniere_semaine_rhs_par_sejour(conn, campagne, finess)
    clause = f"WHERE campagne = ? AND montant_br_tot IS NOT NULL AND {EXCLUSION_MONTANT_OFFICIEL}"
    params: list = [campagne]
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    rows = conn.execute(
        "SELECT numero_admin_sejour, COALESCE(montant_br_trans, 0), COALESCE(montant_am_med, 0), "
        f"COALESCE(montant_br_supp_cancero, 0) FROM valorisation_sejour {clause}",
        params,
    ).fetchall()
    transport = molecules_onereuses = supp_cancero = 0.0
    for numadmin, trans, med, cancero in rows:
        numadmin = _norm_numadmin(numadmin)
        derniere_semaine = dernieres_semaines.get(numadmin)
        if derniere_semaine is None or derniere_semaine > max_week:
            continue
        transport += trans
        molecules_onereuses += med
        supp_cancero += cancero
    return {
        "transport": transport,
        "molecules_onereuses": molecules_onereuses,
        "supp_cancero": supp_cancero,
        "total": transport + molecules_onereuses + supp_cancero,
    }


_CAUSE_NON_VALORISE_LABELS = {
    "nv_chain": "Chaînage (NV_CHAIN)",
    "nv_attente_dts": "En attente de droits (NV_ATTENTE_DTS)",
    "nv_nonfactam": "Non facturable à l'AM (NV_NONFACTAM)",
    "erreur_groupage": "Erreur de groupage (GME 9096Z)",
    "en_cours": "Séjour en cours, pas encore clos (<90j)",
}
"""Ordre d'affichage + libellés du tableau des séjours non valorisés (demande
utilisateur 2026-08-21). Un séjour peut cumuler plusieurs anomalies NV_* :
seule la PREMIÈRE trouvée dans cet ordre est retenue pour le classer (évite
de le compter dans plusieurs causes à la fois)."""


def sejours_non_valorises_campagne(
    conn: sqlite3.Connection, campagne: int, max_week: int, finess: str | None = None
) -> dict:
    """Pour chaque séjour actif dans `campagne` (au moins une ligne RHS dont
    l'année du numero_semaine est `campagne`, clos avant `max_week` — même
    filtre de comparabilité que montant_br_tot_campagne_comparable) mais SANS
    montant_br_sej valorisé, la cause : anomalie NV_* connue, erreur de
    groupage (GME 9096Z), ou simplement en cours (séjour <90j pas encore clos
    — le financement SMR ne se déclenche qu'à la clôture ou au seuil de 90j,
    cf. docstring module). Regroupé par cause avec effectif, PAS par séjour
    individuel (liste nominative jugée hors-sujet pour un TDB d'activité)."""
    dernieres_semaines = _derniere_semaine_rhs_par_sejour(conn, campagne, finess)
    actifs = {numadmin for numadmin, semaine in dernieres_semaines.items() if semaine <= max_week}

    clause = "WHERE campagne = ?"
    params: list = [campagne]
    if finess is not None:
        clause += " AND finess_epmsi = ?"
        params.append(finess)
    rows = conn.execute(
        "SELECT numero_admin_sejour, montant_br_sej, code_gme, "
        "COALESCE(nv_chain, 0), COALESCE(nv_attente_dts, 0), COALESCE(nv_nonfactam, 0) "
        f"FROM valorisation_sejour {clause}",
        params,
    ).fetchall()

    par_sejour: dict[str, dict] = {}
    for numadmin, montant_sej, code_gme, nv_chain, nv_attente_dts, nv_nonfactam in rows:
        numadmin = _norm_numadmin(numadmin)
        if numadmin not in actifs:
            continue
        # Une ligne suffit à disqualifier le séjour de "non valorisé" (une
        # seule campagne/semaine facturée parmi plusieurs suffit).
        if montant_sej:
            par_sejour[numadmin] = None  # marqueur "valorisé, à exclure"
            continue
        if numadmin in par_sejour and par_sejour[numadmin] is None:
            continue
        cause = None
        if nv_chain:
            cause = "nv_chain"
        elif nv_attente_dts:
            cause = "nv_attente_dts"
        elif nv_nonfactam:
            cause = "nv_nonfactam"
        elif code_gme == "9096ZZ0":
            cause = "erreur_groupage"
        else:
            cause = "en_cours"
        # Garde la cause déjà trouvée sur une autre ligne du même séjour
        # (ex. une semaine en nv_chain, une autre "en cours") plutôt que de
        # l'écraser par la dernière ligne lue.
        if numadmin not in par_sejour:
            par_sejour[numadmin] = cause

    effectif_par_cause: dict[str, int] = {}
    for cause in par_sejour.values():
        if cause is None:
            continue
        effectif_par_cause[cause] = effectif_par_cause.get(cause, 0) + 1

    rows_out = [
        {"cause": cle, "libelle": libelle, "effectif": effectif_par_cause.get(cle, 0)}
        for cle, libelle in _CAUSE_NON_VALORISE_LABELS.items()
        if effectif_par_cause.get(cle, 0)
    ]
    return {"rows": rows_out, "total": sum(r["effectif"] for r in rows_out)}


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


def sejours_non_factures_sans_anomalie(conn: sqlite3.Connection, finess: str, campagne: int) -> set[str]:
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
        _norm_numadmin(r[0])
        for r in conn.execute(
            "SELECT DISTINCT numero_admin_sejour FROM rhs_groupe "
            "WHERE finess_epmsi = ? AND substr(numero_semaine, 3, 4) = ?",
            [finess, str(campagne)],
        ).fetchall()
    }
    deja_factures = {
        _norm_numadmin(r[0])
        for r in conn.execute(
            "SELECT DISTINCT numero_admin_sejour FROM valorisation_sejour "
            "WHERE finess_epmsi = ? AND montant_br_tot IS NOT NULL",
            [finess],
        ).fetchall()
    }
    en_anomalie = {
        _norm_numadmin(r[0])
        for r in conn.execute(
            "SELECT DISTINCT numero_admin_sejour FROM valorisation_sejour "
            "WHERE finess_epmsi = ? AND (COALESCE(nv_chain, 0) != 0 OR COALESCE(nv_attente_dts, 0) != 0 "
            "OR COALESCE(nv_nonfactam, 0) != 0)",
            [finess],
        ).fetchall()
    }
    return (actifs - deja_factures) - en_anomalie


def estimation_recettes_sejours_en_cours(
    conn: sqlite3.Connection,
    period: dict,
    finess: str,
    pmjt: float | None,
    axis_filter: tuple[str, str] | None = None,
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
    aucun montant ATIH connu).

    `axis_filter` (2026-08-05) : mêmes clés que compute_valeur_journaliere
    (`numero_unite_medicale` ou `type_hospitalisation`) — ne compte que les
    journées de présence dont la ligne RHS d'origine correspond au filtre,
    via le même day_axis que le reste du module."""
    if not pmjt:
        return {"montant": 0.0, "nb_sejours": 0, "nb_journees": 0}
    cible = sejours_non_factures_sans_anomalie(conn, finess, int(period["year"]))
    if not cible:
        return {"montant": 0.0, "nb_sejours": 0, "nb_journees": 0}
    presence = _rhs_presence_days_by_sejour(conn, finess)
    day_axis = _rhs_day_axis(conn, finess) if axis_filter else {}
    nb_journees = 0
    sejours_concernes = 0
    for numadmin in cible:
        jours = [
            j
            for j in presence.get((finess, numadmin), [])
            if period["start"] <= j <= period["end"] and _matches_axis(day_axis, axis_filter, finess, numadmin, j)
        ]
        if jours:
            sejours_concernes += 1
            nb_journees += len(jours)
    return {"montant": nb_journees * pmjt, "nb_sejours": sejours_concernes, "nb_journees": nb_journees}
