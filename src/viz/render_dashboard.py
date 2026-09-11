# -*- coding: utf-8 -*-
"""Génère app/tableau_de_bord.html à partir des agrégats de tableau_de_bord.build().

Reprend la structure du tableau de bord PMSI de référence (fourni par
l'utilisateur, établissement réel anonymisé) : sections 1 (Patients), 2 (Séjours),
3 (Journées de présence), 4 (Indicateurs), 5 (Activité CSARR), 6
(Valorisation — montant BR pro-rata + PMCT/PMST/PMJT, ajoutée 2026-07-30), 7-8
(Palmarès CM/GN — top 5 codes les plus fréquents par nomenclature de
groupage, avec effectif et valorisation par année, ajoutées 2026-08-03).
Une section 9 "Palmarès GME" a été essayée puis retirée le même jour (choix
utilisateur : n'apportait pas grand-chose de plus que CM/GN et risquait de
surcharger le TDB).
Le Score RR / COEFF SPEC restent volontairement absents : ils nécessitent un
barème CSARR complet (listes d'actes spécialisés par GN, seuils GR) non
reconstruit ici. La section "5bis" (Absence d'actes CSARR) a été retirée de
la conception (choix utilisateur 2026-07-30). La section "Erreurs groupage"
(ex-7) a aussi été retirée. Les "Incohérences VID-HOSP / RHS" et le
"Contenu séjours en erreur" sont produits dans un document ANNEXE distinct
(voir render_annexe() / app/annexe_<finess>.html), pas dans ce TDB.
"""
from __future__ import annotations

import re

from src.util.paths import project_root
from src.viz.tableau_de_bord import build

OUT_DIR = project_root() / "app"

MOIS_FR = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _period_subtitle(finess: str, periods: list[dict]) -> str:
    """Ligne 2 du titre standardisé (demande utilisateur 2026-07-30) :
    FINESS + période en mois/années SEULEMENT, sans détail des semaines —
    ce détail est désormais porté par le graphique section 3 (grille
    pointillée par semaine + libellés d'axe), pas par le texte d'en-tête."""
    starts = [p["start"] for p in periods]
    ends = [p["end"] for p in periods]
    years = [p["year"] for p in periods]
    mois_debut = MOIS_FR[min(starts).month]
    mois_fin = MOIS_FR[max(ends).month]
    an_debut, an_fin = min(years), max(years)
    return f"FINESS : {finess} ; période ({mois_debut} - {mois_fin} ; {an_debut} - {an_fin})"


def fmt(x, decimals=1, suffix=""):
    if x is None:
        return "—"
    return f"{x:,.{decimals}f}{suffix}".replace(",", " ").replace(".", ",")


def fmt_int(x):
    if x is None:
        return "—"
    return f"{x:,}".replace(",", " ")


# ---------- Signalisation couleur (option avant génération, 2026-09-12) ----------
# Reprend EXACTEMENT la formule de l'Explorateur (app/app.js, computeTrendPrevIdx/
# trendDelta/trendHeatClassAttr) : delta en % de variation par rapport à la
# valeur "précédente" (colonne/année antérieure), sauf pour une mesure déjà
# exprimée en % où le delta est un écart en points (une variation relative
# d'un pourcentage par rapport à lui-même donnerait des valeurs absurdes pour
# de petits pourcentages). Plafonné à TREND_CAP_PCT : au-delà, l'opacité du
# fond dégradé sature. Couleurs FIXES ici (pas de sélecteur live comme dans
# l'Explorateur — un TDB généré est un fichier HTML statique, sans JS de
# préférence persistée ; la personnalisation de page, elle, est couverte par
# `apparence`/_apparence_style, séparément).
TREND_CAP_PCT = 15.0
TREND_COLOR_POS = "#1f7a4d"
TREND_COLOR_NEG = "#b1502f"


def _trend_delta(cur, prev, is_pct: bool = False) -> float | None:
    if not isinstance(cur, (int, float)) or not isinstance(prev, (int, float)):
        return None
    if is_pct:
        return cur - prev
    if prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100


FONT_CHOICES = {
    "systeme": '-apple-system, "Segoe UI", sans-serif',
    "arial": "Arial, Helvetica, sans-serif",
    "verdana": "Verdana, Geneva, sans-serif",
    "georgia": "Georgia, \"Times New Roman\", serif",
}


def _apparence_style(apparence: dict | None) -> str:
    """Option avant génération (2026-09-12, demande utilisateur) : personnalise
    la couleur de fond de page, la couleur de contenu (tableaux), la police et
    la couleur des cadres de section d'un TDB, sans toucher au thème par
    défaut des autres documents (annexe, journal, autres TDB). Clés
    optionnelles de `apparence` : "fond" (couleur hex, fond de PAGE),
    "contenu" (couleur hex, fond des TABLEAUX/cartes — cf. correctif
    2026-09-12 : par défaut = "fond" lui-même, PAS un mélange à 95 % blanc
    comme la 1ʳᵉ version, qui rendait tout le contenu quasi blanc quelle que
    soit la couleur de fond choisie), "police" (une clé de FONT_CHOICES),
    "cadre" (couleur hex, cadres/en-têtes de section). Rendu en <style> à
    l'intérieur même du corps du TDB (pas dans STYLE_BLOCK, partagé avec
    l'annexe/le journal). `!important` sur chaque propriété : nécessaire car
    les règles de thème clair/sombre de STYLE_BLOCK (ex.
    `:root[data-theme="dark"] .viz-root`) ont une spécificité CSS plus forte
    qu'un simple `.viz-root` et gagneraient sinon quel que soit le thème
    choisi par l'utilisateur — même technique que le bloc @media print de
    STYLE_BLOCK, qui a le même problème."""
    if not apparence:
        return ""
    rules = []
    fond = apparence.get("fond")
    contenu = apparence.get("contenu") or fond
    if fond:
        rules.append(f".viz-root {{ --page:{fond} !important; }}")
    if contenu:
        rules.append(f".viz-root {{ --surface:{contenu} !important; }}")
        # Regroupements de section (ex. "Type de rééducation (GR)") et lignes
        # de total : un peu plus FONCÉS que le contenu courant plutôt que de
        # garder l'ancienne teinte fixe du thème par défaut (--grid), qui
        # jurait avec une couleur personnalisée — demande utilisateur
        # 2026-09-12.
        group_bg = f"color-mix(in srgb, #000 14%, {contenu})"
        rules.append(
            f".viz-root table tr.group-row td, "
            f".viz-root table tfoot td, .viz-root table tfoot th, "
            f".viz-root table tr.total-row td {{ background:{group_bg} !important; }}"
        )
    police = FONT_CHOICES.get(apparence.get("police", ""))
    if police:
        rules.append(f".viz-root {{ font-family: {police} !important; }}")
    if apparence.get("cadre"):
        cadre = apparence["cadre"]
        rules.append(f".viz-root .table-wrap {{ border-color:{cadre} !important; }}")
        rules.append(
            f".viz-root section > h2 {{ background:color-mix(in srgb, {cadre} 16%, var(--surface)) !important; }}"
        )
    if not rules:
        return ""
    return f"<style>{''.join(rules)}</style>"


def _trend_td(formatted: str, delta: float | None) -> str:
    """Cellule <td> avec dégradé de fond (couleur hausse/baisse) + flèche,
    identique visuellement à l'Explorateur — actif seulement si `delta` est
    fourni (donc uniquement quand la signalisation couleur est activée ET
    qu'une valeur de comparaison existe)."""
    if delta is None or abs(delta) < 0.5:
        return f"<td>{formatted}</td>"
    alpha = min(abs(delta), TREND_CAP_PCT) / TREND_CAP_PCT * 0.55 + 0.08
    color = TREND_COLOR_POS if delta > 0 else TREND_COLOR_NEG
    arrow = "▲" if delta > 0 else "▼"
    style = f"background:color-mix(in srgb, {color} {alpha * 100:.1f}%, var(--surface));"
    return f'<td style="{style}"><span class="trend-arrow" style="color:{color}">{arrow}</span> {formatted}</td>'


class NoteCollector:
    """Les callouts explicatifs ne restent plus accrochés sous chaque tableau
    (demande utilisateur 2026-07-30) : chaque appel à add() enregistre une
    note et renvoie un petit marqueur numéroté (renvoi) à placer dans la
    section. Deux textes distincts par note (demande utilisateur, même jour) :
    `meaning` (juste la signification — ce qu'est l'indicateur) reste dans le
    TDB ; `detail` (dates de validation, sources, méthodologie, limites) part
    dans un troisième document, le JOURNAL (voir render_journal), dédié au
    debug. Une note sans detail n'a rien à envoyer au journal."""

    def __init__(self):
        self.notes: list[tuple[str, str, str | None, bool]] = []

    def add(self, icon: str, meaning: str, detail: str | None = None, linked: bool = True) -> str:
        """`linked=False` pour une note générale (ex. les paragraphes d'intro
        du document) qui n'a pas de renvoi ponctuel dans le corps du texte —
        pas de flèche "retour" dans ce cas (elle pointerait vers une ancre
        qui n'existe nulle part)."""
        self.notes.append((icon, meaning, detail, linked))
        n = len(self.notes)
        return f'<sup class="note-ref" id="note-ref-{n}"><a href="#note-{n}" title="Voir note {n}">{n}</a></sup>'

    def render(self, finess: str) -> str:
        if not self.notes:
            return ""
        items = "".join(
            f'<li id="note-{i}" class="callout {icon}"><span class="ico">{"✓" if icon == "ok" else "i"}</span>'
            f'<div><b>{i}.</b> {meaning}'
            + (f' <a class="note-journal" href="journal_{finess}.html#note-{i}">détails ↗</a>' if detail else "")
            + (f' <a class="note-back" href="#note-ref-{i}">↑</a>' if linked else "")
            + '</div></li>'
            for i, (icon, meaning, detail, linked) in enumerate(self.notes, start=1)
        )
        return f'<section class="notes"><h2>Notes</h2><ol class="notes-list">{items}</ol></section>'

    def render_journal(self) -> str:
        # Une note sans `detail` n'a rien de plus à dire que ce qui est déjà
        # dans le TDB (meaning) : l'omettre du journal évite de répéter le
        # même texte mot pour mot dans les deux documents.
        return "".join(
            f'<li id="note-{i}" class="callout {icon}"><span class="ico">{"✓" if icon == "ok" else "i"}</span>'
            f'<div><b>{i}.</b> {detail}</div></li>'
            for i, (icon, meaning, detail, linked) in enumerate(self.notes, start=1)
            if detail
        )


def _populate_notes(notes: "NoteCollector") -> dict[str, str]:
    """Contenu statique des notes du TDB, dans l'ordre d'apparition —
    indépendant des données de l'établissement, donc appelable aussi bien
    par render() (pour les marqueurs + le résumé "meaning") que par
    render_journal() (pour le détail complet "detail"). Chaque note sépare
    (demande utilisateur 2026-07-30) :
    - meaning : juste la signification de l'indicateur — reste dans le TDB.
    - detail  : dates de validation, sources, méthodologie, limites — part
      dans le journal (app/journal_<finess>.html), pas affiché dans le TDB.
    Retourne un dict NOMMÉ (pas une liste positionnelle) : robuste si l'ordre
    ou le nombre de notes change — pas de risque de décalage silencieux entre
    le marqueur inséré dans une section et la note qu'il est censé pointer.
    Les 2 premières notes (intro générale, ex-paragraphes d'en-tête du TDB —
    demande utilisateur 2026-07-30) n'ont pas de renvoi ponctuel dans le
    corps (linked=False) : elles ouvrent simplement la liste de notes.
    """
    m: dict[str, str] = {}
    m["intro_recalcul"] = notes.add(
        "warn",
        "<b>Score RR</b> et <b>Coeff. spécialisation</b> absents (barème CSARR complet non disponible).",
        linked=False,
    )
    m["intro_periodes"] = notes.add(
        "warn",
        "Comparaison par semaines ISO comparables (01..N), pas par année civile — détail semaine par "
        "semaine : graphique section 3.",
        "Un fichier de transmission contient toujours le séjour complet, y compris ses semaines d'une "
        "année antérieure pour un séjour à cheval. Ces semaines résiduelles (qui ne couvrent pas le "
        "début de la période) sont exclues — seules les années qui couvrent bien semaines 01..N sont "
        "comparées, sur la même plage. Les séjours à cheval entre plusieurs fichiers de transmission "
        "sont dédupliqués par clé naturelle (établissement + séjour + semaine pour RHS ; établissement + "
        "séjour pour VID-HOSP) — la transmission la plus récente l'emporte.",
        linked=False,
    )
    m["patients"] = notes.add(
        "ok",
        "Patient = IPP (pas le n° de sécurité sociale, qui est celui de l'assuré). Compté une fois par "
        "période dès que son séjour la chevauche.",
        "Un séjour à cheval sur deux semaines d'une même période n'est pas compté deux fois. La fin de "
        "présence réelle est étendue par la dernière semaine RHS du séjour si elle dépasse la date de "
        "sortie VID-HOSP (utile pour les longs séjours SSR où le VID-HOSP ne couvre qu'une tranche de "
        "facturation). Validé mois par mois contre le document de référence.",
    )
    m["sejours"] = notes.add(
        "ok",
        "Nb SSR = séjours distincts ; Nb RHS = semaines transmises ; Nb journées = journées de présence ; "
        "DMH = durée moyenne d'hospitalisation ; NbLits moy = lits moyen occupé ; EXH = taux d'occupation.",
        "Validé mois par mois contre le document de référence. La fin de chaque mois est déterminée par "
        "la semaine ISO dont le jeudi tombe dans ce mois — cette semaine de fin varie d'une année sur "
        "l'autre (ex. fin avril = semaine 17 en 2025, semaine 18 en 2026).",
    )
    m["indic_ok"] = notes.add(
        "ok",
        "AVQ phys./cogn. moy. = moyenne des scores de dépendance (somme des items). Nb diag. = "
        "diagnostics distincts (couples RHS/code DAS, dédoublonnés).",
        "Validés exacts contre le document de référence.",
    )
    m["indic_warn"] = notes.add(
        "warn",
        "Nb CSARR = réalisations CSARR (plafond 2 occurrences identiques/jour). "
        "Nb moy. interv./RHS = (CSARR + CSAR) / RHS.",
        "Le plafond à 2/jour distingue une réalisation légitime matin ET après-midi d'un doublon de "
        "transmission (3ᵉ exemplaire identique ou plus). Cet indicateur cumulatif (section 4) suit une "
        "définition ATIH différente de celle du rapport \"Activité CSARR par intervenant\" (section 5) — "
        "les deux ne sont pas censés coïncider. Validé sur semaine isolée (S01-2024 exact), écart "
        "résiduel &lt;0,3 % sur période complète. Nb moy. interv./RHS à confirmer contre la définition "
        "exacte.",
    )
    m["activite_ok"] = notes.add(
        "ok",
        "Nb réalisations = comptage brut des actes CSARR par intervenant (sans dédoublonnage), triés par "
        "volume total.",
        "Méthode de comptage validée exacte contre le rapport ATIH officiel \"Activité CSARR par "
        "intervenant, année N\".",
    )
    m["activite_choix"] = notes.add(
        "warn",
        "Séjours en erreur de groupage inclus dans tous les totaux (logique activité, pas facturation). "
        "Détail : annexe §2.",
        "Choix délibéré : un écart avec les chiffres ATIH officiels (qui excluent ces séjours) est donc "
        "attendu dès qu'un séjour est en erreur — c'est volontaire, et sert de signal d'alerte. Libellés "
        "des codes intervenant tirés de la nomenclature CSARR officielle, à vérifier si un intitulé ne "
        "correspond pas à votre export.",
    )
    m["activite_score"] = notes.add(
        "warn",
        "Score de réadaptation GLOBALE = pondérations ATIH de TOUS les actes CSARR+CCAM réalisés (modulateur "
        "de lieu inclus pour le CSARR). SPÉCIALISÉE = même somme, restreinte aux seuls actes marqueurs du GN "
        "du séjour. Décomposés par intervenant sur demande, alors que ce sont officiellement des indicateurs "
        "par séjour/semaine, pas par intervenant.",
        "Le score utilise <code>ponderation_patient</code> (nomenclature ATIH <code>ACTES_ponderations</code>, "
        "CSARR et CCAM) majoré, pour le CSARR uniquement, par le modulateur de LIEU (HW/LJ/XH/L3), individuel "
        "ou collectif selon <code>nombre_reel_patients</code> — voir "
        "<code>section_readaptation_intervenant</code> (src/viz/tableau_de_bord.py). Le filtre \"spécialisée\" "
        "s'appuie sur <code>nomenclature_actes_specialises</code> (fichier ATIH <code>ACTES_listes_SPE.xlsx</code>, "
        "annexe 4 du volume 3 du manuel de groupage GME) : un acte compte dans le score spécialisé du séjour "
        "seulement s'il figure dans la liste de marqueurs du GN de CE séjour (GN pris à sa dernière semaine "
        "connue de la période, comme pour les palmarès). Les GN sans notion de réadaptation spécialisée "
        "(\"PAS DE LISTE\" dans le fichier ATIH, ex. 0103, 0118, 0134) ont donc toujours un score spécialisé "
        "nul. Limite assumée : les actes CCAM n'ont AUCUN code intervenant dans le RHS — leur contribution "
        "est affichée à part, sous \"Actes CCAM (non rattachés à un intervenant)\", jamais répartie sur les "
        "intervenants CSARR. Ce sont des sommes CUMULÉES sur la période (\"par séjour\" au sens du manuel des "
        "GME, ATIH vol.1 §3.3.2), jamais divisées par des jours de présence — donc pas l'intensité par "
        "séjour/jour du score officiel. Pour les codes dont la pondération a changé dans le temps, la valeur "
        "la PLUS RÉCENTE est utilisée pour toutes les années (choix délibéré, cohérent avec le reste du "
        "projet).",
    )
    m["valorisation"] = notes.add(
        "warn",
        "Montant BR SÉJOUR (fact.) = montant_br_gmt + montant_br_gmth SEUL (hors transport/molécules "
        "onéreuses/cancérologie, voir note suivante et \"Suppléments en sus\"). Montant BR estimé PRT = "
        "reconstitution prorata temporis + estimation des séjours en cours. PMCT/PMST/PMJT restent basés "
        "sur le seul prorata temporis RÉEL (pas l'estimation), pour rester un tarif moyen observé.",
        "<b>PMCT</b> = Montant BR PRT réel / Nb SSR. <b>PMST</b> = Montant BR PRT réel / Nb RHS. "
        "<b>PMJT</b> = Montant BR PRT réel / Nb journées de présence — ces 3 ratios utilisent le montant "
        "PROUVÉ (sans l'estimation des séjours en cours, voir note suivante), pour rester un tarif moyen "
        "réellement observé plutôt qu'un chiffre qui inclurait sa propre estimation. Depuis le 2026-08-21 "
        "(décision utilisateur), ce tarif moyen est calculé sur <code>montant_br_sej</code> exclusivement "
        "— les suppléments (transport, molécules onéreuses, cancérologie) ne sont PAS lissés au jour, ce "
        "sont des versements ponctuels sans rapport avec la durée du séjour ; les y inclure aurait faussé "
        "le prix/jour d'un séjour qui en bénéficie ponctuellement.",
    )
    m["valorisation_non_fact"] = notes.add(
        "warn",
        "(fact.) = facturé : figure officielle ATIH (arrêté de versement), qui exclut déjà les séjours "
        "en anomalie (chaînage, en attente de droits, non facturable à l'AM).",
        "<b>Montant BR SÉJOUR (fact.)</b> = <code>montant_br_sej</code> (= <code>montant_br_gmt</code> + "
        "<code>montant_br_gmth</code>, colonne calculée — voir "
        "<code>src/storage/valorisation_store.py</code>), sommé par CAMPAGNE (année de transmission), en "
        "excluant les séjours marqués <code>nv_chain</code> (chaînage), <code>nv_attente_dts</code> (en "
        "attente de droits) ou <code>nv_nonfactam</code> (non facturable à l'Assurance Maladie) — voir "
        "<code>EXCLUSION_MONTANT_OFFICIEL</code> dans <code>src/viz/valorisation.py</code>. Ces 3 "
        "exclusions ont été trouvées empiriquement (2026-08-05) en reproduisant EXACTEMENT au centime près "
        "deux totaux d'un tableau ATIH externe fourni par l'utilisateur (deux établissements, campagne "
        "2026), puis confirmées sur les autres établissements. D'autres variables NV_* du fichier "
        "VisualValoSejours existent (nv_cm90, nv_nonclos, nv_pie, nv_varano, nv_article51, nv_telereadapt, "
        "nv_evcepr, nv_gmt9999, nv_horsperiode) mais n'ont montré aucune contribution sur ces cas de test "
        "— non exclues, faute de preuve empirique. Avant le 2026-08-21, ce montant incluait aussi les "
        "suppléments transport/molécules onéreuses/cancérologie (alors appelé <code>montant_br_tot - "
        "montant_br_trans</code>) — désormais tous exclus d'ici et affichés à part (voir \"Suppléments en "
        "sus\" ci-dessous). <b>Dans un TDB secondaire par type d'hospitalisation</b> (HC/HTP), ce montant "
        "est ventilé EXACTEMENT via la colonne native <code>valorisation_sejour.type_hospitalisation</code> "
        "(C/P — indépendante du champ RHS). <b>Dans un TDB secondaire par UF</b>, aucune colonne "
        "équivalente n'existe : ce montant devient une APPROXIMATION (marquée \"≈\") égale à Montant BR "
        "PRT reproraté par jour de présence — fiable pour les séjours mono-UF (majoritaires), "
        "approximative pour les séjours multi-UF.",
    )
    m["supplements"] = notes.add(
        "warn",
        "Transport, molécules onéreuses (MO/MED) et supplément cancérologie : facturés EN SUS du séjour, "
        "pas lissés au prorata des journées (contrairement au Montant BR SÉJOUR ci-dessus).",
        "<code>montant_br_supplements_campagne_comparable</code> (src/viz/valorisation.py) — même filtre "
        "de comparabilité campagne/semaine limite et même exclusion d'anomalies "
        "(<code>EXCLUSION_MONTANT_OFFICIEL</code>) que le Montant BR SÉJOUR ci-dessus, pour que "
        "\"séjour + suppléments\" reste interprétable comme la décomposition du montant BR TOT brut ATIH. "
        "Décision utilisateur 2026-08-21 : séparés du prix par journée (PMJT) car ce sont des versements "
        "ponctuels sans rapport avec la durée du séjour.",
    )
    m["non_valorises"] = notes.add(
        "warn",
        "Séjours actifs sur la période sans aucun montant BR séjour connu, groupés par cause.",
        "<code>sejours_non_valorises_campagne</code> (src/viz/valorisation.py) — séjours dont la dernière "
        "semaine RHS connue est ≤ la semaine limite de comparabilité de la période (donc \"devraient\" "
        "déjà avoir un montant s'ils étaient clos) mais dont <code>montant_br_sej</code> reste nul sur "
        "TOUTES leurs lignes valorisation_sejour. Cause retenue par ordre de priorité si plusieurs "
        "s'appliquent : <code>nv_chain</code>, <code>nv_attente_dts</code>, <code>nv_nonfactam</code>, "
        "erreur de groupage (GME <code>9096ZZ0</code>), sinon \"en cours\" (séjour &lt;90j pas encore "
        "clos — le financement SMR ne se déclenche qu'à la clôture ou au seuil de 90j).",
    )
    m["estimation_en_cours"] = notes.add(
        "warn",
        "ESSAI : Montant BR PRT (prorata temporis réel) + une estimation de la recette des séjours "
        "&lt;90j non clos sans anomalie connue, au tarif moyen déjà observé (PMJT) — à titre indicatif, "
        "pas une donnée ATIH. Écart = Montant BR SÉJOUR (fact.) − Montant BR estimé PRT.",
        "<b>Montant BR PRT</b> (pro rata temporis, calcul \"maison\") = somme des valeurs journalières "
        "réparties uniformément sur les jours de présence RHS réels d'un séjour déjà facturé (voir "
        "<code>src/viz/valorisation.py</code>), agrégées par ANNÉE CIVILE RÉELLE des jours dont le jour "
        "tombe dans la période. <b>+ estimation</b> : pour les séjours actifs sur la période sans AUCUN "
        "<code>montant_br_tot</code> connu (donc &lt;90j, pas encore clos — le financement SMR ne se "
        "déclenche qu'à la clôture ou au seuil de 90j) ET sans anomalie <code>nv_chain</code>/"
        "<code>nv_attente_dts</code>/<code>nv_nonfactam</code> (voir "
        "<code>sejours_non_factures_sans_anomalie</code>) — distinction trouvée nécessaire en creusant un "
        "écart signalé par l'utilisateur : sur un établissement réel, la grande majorité des séjours "
        "\"jamais facturés\" étaient en fait marqués <code>nv_chain</code>, pas de simples séjours en attente. Le montant "
        "appliqué à leurs journées de présence RHS est le PMJT déjà calculé (montant_br_pt / nb journées "
        "observées, voir PMCT/PMST/PMJT) — jamais recalculé à partir de cette estimation, pour éviter "
        "toute boucle. <b>Écart</b> = Montant BR TOT (fact.) − Montant BR estimé PRT : un grand écart en "
        "cours d'année est normal (année pas terminée, estimation partielle), pas une anomalie de calcul. "
        "Essai, décision utilisateur 2026-08-05, à évaluer.",
    )
    m["palmares"] = notes.add(
        "warn",
        "Top 5 classé sur l'effectif cumulé toutes années confondues (mêmes 5 codes pour chaque colonne). "
        "% = part du code dans le total (tous codes) de sa colonne, à 1 décimale.",
        "Un séjour compte pour le code (CM/GN) de sa DERNIÈRE semaine RHS connue dans la période — "
        "utile si un séjour est re-groupé d'une semaine à l'autre. Valorisation = <code>montant_br_sej</code> "
        "(hors transport/molécules onéreuses/cancérologie, cf. note 8), avec le même filtre de "
        "comparabilité campagne/semaine limite que la section 6 (Montant BR SÉJOUR) — pour un séjour à "
        "cheval sur plusieurs semaines de la période, la valorisation est rattachée au code de sa dernière "
        "semaine, pas répartie code par code au prorata.",
    )
    m["structure_gme"] = notes.add(
        "warn",
        "Type de rééducation (GR), groupe de lourdeur (GL) et sévérité, TOUTES CM/GN confondues (pas un "
        "top N). Sévérité : 0 = HTP, 1 = HC sans sévérité, 2 = HC avec sévérité.",
        "Même méthode d'attribution séjour→code et même filtre de comparabilité valorisation que les "
        "palmarès CM/GN. La ligne \"Erreur de groupage\" regroupe les séjours dont le type GR n'est pas "
        "reconnu (ex. <code>9096ZZ0</code>, code_gme placeholder d'un séjour en erreur de groupage "
        "bloquante) — comptés à part dans les 3 blocs plutôt que classés à tort sous une vraie catégorie "
        "(ex. sévérité \"0\", qui a par ailleurs un sens réel pour les vrais séjours HTP).",
    )
    return m


def render(
    data: dict,
    axis_label: str | None = None,
    signalisation_couleur: bool = False,
    apparence: dict | None = None,
) -> str:
    """`axis_label` (optionnel, ex. "UF 3001" ou "type d'hospitalisation
    Hospitalisation complète (HC)", 2026-08-04) : ajouté au sous-titre et au
    titre de la page quand ce TDB est un TDB secondaire (un par valeur d'axe,
    voir generate_axis_reports()) plutôt que le TDB principal non filtré.

    `signalisation_couleur` (option avant génération, 2026-09-12) : colore
    chaque cellule comparable à une valeur de la période précédente, avec le
    même dégradé hausse/baisse que l'Explorateur — voir _trend_td.

    `apparence` (option avant génération, 2026-09-12, clés optionnelles
    "fond"/"police"/"cadre") : personnalise la couleur de fond de page, la
    police et la couleur des cadres de section — voir _apparence_style."""
    years = data["years"]
    periods_by_year = {p["year"]: p for p in data["periods"]}

    def prev_year(y: str) -> str | None:
        idx = years.index(y)
        return years[idx - 1] if idx > 0 else None

    def td(value, formatted: str, prev_value=None, is_pct: bool = False) -> str:
        """Cellule de tableau, avec dégradé hausse/baisse si la signalisation
        couleur est active ET qu'une valeur de comparaison est fournie."""
        if not signalisation_couleur or prev_value is None:
            return f"<td>{formatted}</td>"
        return _trend_td(formatted, _trend_delta(value, prev_value, is_pct))

    # ---------- section 1 : patients ----------
    patients_rows = ""
    for y in years:
        p = data["patients"].get(y)
        if not p:
            continue
        pp = data["patients"].get(prev_year(y))
        patients_rows += (
            f"<tr><td>{periods_by_year[y]['label']}</td>"
            + td(p["f"], fmt_int(p["f"]), pp and pp["f"])
            + td(p["m"], fmt_int(p["m"]), pp and pp["m"])
            + f"<td><b>{fmt_int(p['total'])}</b></td>"
            + td(p["pct_f"], fmt(p["pct_f"], 1, " %"), pp and pp["pct_f"], is_pct=True)
            + td(p["pct_m"], fmt(p["pct_m"], 1, " %"), pp and pp["pct_m"], is_pct=True)
            + "<td><b>100,0 %</b></td>"
            + td(p["age_f"], fmt(p["age_f"]), pp and pp["age_f"])
            + td(p["age_m"], fmt(p["age_m"]), pp and pp["age_m"])
            + f"<td><b>{fmt(p['age_total'])}</b></td></tr>"
        )

    # ---------- section 2 : séjours ----------
    sejours_rows = ""
    for y in years:
        s = data["sejours"][y]
        sp = data["sejours"].get(prev_year(y))
        sejours_rows += (
            f"<tr><td>{periods_by_year[y]['label']}</td>"
            + td(s["nb_ssr"], fmt_int(s["nb_ssr"]), sp and sp["nb_ssr"])
            + td(s["nb_rhs"], fmt_int(s["nb_rhs"]), sp and sp["nb_rhs"])
            + td(s["nb_journees"], fmt_int(s["nb_journees"]), sp and sp["nb_journees"])
            + td(s["dmh"], fmt(s["dmh"], 2), sp and sp["dmh"])
            + td(s["nb_lits_moy"], fmt(s["nb_lits_moy"], 1), sp and sp["nb_lits_moy"])
            + td(s["exh"], fmt(s["exh"], 2, " %"), sp and sp["exh"], is_pct=True)
            + "</tr>"
        )

    # ---------- section 3 : journées par semaine (SVG) ----------
    all_weeks = sorted({w for y in years for w in data["journees_semaine"][y]})
    all_vals = [v for y in years for v in data["journees_semaine"][y].values()]
    raw_min, raw_max = min(all_vals, default=0), max(all_vals, default=1)
    # Échelle RELATIVE (zoomée sur la plage réelle des données, pas 0→max) :
    # essai demandé par l'utilisateur pour mieux voir les variations
    # hebdomadaires, à revenir en arrière si ça s'avère trompeur. On ajoute
    # une marge de 10 % et on GARDE des graduations avec leurs vraies
    # valeurs affichées (voir y_ticks) pour ne pas induire en erreur sur
    # l'amplitude — l'axe ne part délibérément pas de zéro.
    val_range = max(raw_max - raw_min, 1)
    axis_pad = val_range * 0.12
    axis_min = max(0, raw_min - axis_pad)
    axis_max = raw_max + axis_pad
    axis_span = max(axis_max - axis_min, 1)
    avg_val = sum(all_vals) / len(all_vals) if all_vals else 0
    chart_w, chart_h, pad_l, pad_r, pad_b = 720, 248, 48, 60, 48
    plot_w, plot_h = chart_w - pad_l - pad_r, chart_h - pad_b - 10

    def y_for(v: float) -> float:
        return 10 + plot_h - ((v - axis_min) / axis_span) * plot_h

    def points_for(year_series: dict) -> list[tuple[float, float]]:
        n = len(all_weeks)
        pts = []
        for i, w in enumerate(all_weeks):
            v = year_series.get(w)
            if v is None:
                continue
            x = pad_l + (i / max(n - 1, 1)) * plot_w
            pts.append((x, y_for(v)))
        return pts

    def smooth_path(pts: list[tuple[float, float]]) -> str:
        """Courbe lissée (spline Catmull-Rom convertie en Bézier cubique)
        passant exactement par chaque point — plus lisible que la ligne
        brisée d'origine sur une série hebdomadaire bruitée."""
        if not pts:
            return ""
        if len(pts) == 1:
            return f"M {pts[0][0]:.1f},{pts[0][1]:.1f}"
        n = len(pts)
        d = f"M {pts[0][0]:.1f},{pts[0][1]:.1f} "
        for i in range(n - 1):
            p0 = pts[i - 1] if i - 1 >= 0 else pts[i]
            p1 = pts[i]
            p2 = pts[i + 1]
            p3 = pts[i + 2] if i + 2 < n else pts[i + 1]
            c1x, c1y = p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6
            c2x, c2y = p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6
            d += f"C {c1x:.1f},{c1y:.1f} {c2x:.1f},{c2y:.1f} {p2[0]:.1f},{p2[1]:.1f} "
        return d.strip()

    # Chaque année est encodée par une COULEUR *et* un style de trait/marqueur
    # distincts (pas la couleur seule) : le graphe reste lisible imprimé en
    # noir et blanc / niveaux de gris, où les couleurs peuvent devenir
    # indiscernables. Couleurs dédiées (--line-1/2/3, pas --muted/--vid/--rhs)
    # pour un contraste plus marqué que les tons d'accent génériques de l'UI.
    year_colors = {"2024": "var(--line-1)", "2025": "var(--line-2)", "2026": "var(--line-3)"}
    DASH_PATTERNS = ["", "7 4", "2 3", "1 3 6 3"]

    def marker_svg(shape: int, cx: float, cy: float, color: str) -> str:
        if shape == 0:
            return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="{color}" stroke="var(--surface)" stroke-width="1.2" />'
        if shape == 1:
            s = 7
            return (
                f'<rect x="{cx - s / 2:.1f}" y="{cy - s / 2:.1f}" width="{s}" height="{s}" '
                f'fill="{color}" stroke="var(--surface)" stroke-width="1.2" />'
            )
        s = 6.5
        return (
            f'<polygon points="{cx:.1f},{cy - s:.1f} {cx - s:.1f},{cy + s * 0.7:.1f} {cx + s:.1f},{cy + s * 0.7:.1f}" '
            f'fill="{color}" stroke="var(--surface)" stroke-width="1.2" />'
        )

    lines_svg = ""
    markers_svg = ""
    endpoints = []  # (last_x, last_y, color, label) — étiquettes posées après coup, espacées
    for idx, y in enumerate(years):
        series = data["journees_semaine"][y]
        color = year_colors.get(y, "var(--rhs)")
        dash = DASH_PATTERNS[idx % len(DASH_PATTERNS)]
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        pts = points_for(series)
        lines_svg += (
            f'<path d="{smooth_path(pts)}" fill="none" '
            f'stroke="{color}" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"{dash_attr} />'
        )
        if pts:
            last_x, last_y = pts[-1]
            shape = idx % 3
            markers_svg += marker_svg(shape, last_x, last_y, color)
            endpoints.append((last_x, last_y, color, y))  # étiquette courte (année) : la légende donne le détail

    # Espacement vertical mini. entre étiquettes de fin de ligne pour éviter
    # qu'elles se chevauchent quand deux séries finissent à des valeurs proches.
    MIN_LABEL_GAP = 12
    endpoints.sort(key=lambda e: e[1])
    for i in range(1, len(endpoints)):
        px, py, pc, pl = endpoints[i - 1]
        x, y_pos, c, lbl = endpoints[i]
        if y_pos - py < MIN_LABEL_GAP:
            endpoints[i] = (x, py + MIN_LABEL_GAP, c, lbl)
    labels_svg = "".join(
        f'<text x="{x + 8:.1f}" y="{y_pos + 3:.1f}" font-size="10" '
        f'font-weight="700" fill="{c}">{lbl}</text>'
        for x, y_pos, c, lbl in endpoints
    )
    gridlines = "".join(
        f'<line x1="{pad_l}" y1="{10 + plot_h * frac:.1f}" x2="{chart_w - pad_r + 8}" '
        f'y2="{10 + plot_h * frac:.1f}" stroke="var(--grid)" stroke-width="1" />'
        for frac in (0, 0.25, 0.5, 0.75, 1)
    )
    # Étiquettes de valeur sur chaque graduation : l'axe étant volontairement
    # zoomé (pas de 0 en bas), afficher les vraies valeurs évite toute
    # ambiguïté sur l'amplitude réelle.
    y_ticks = "".join(
        f'<text x="{pad_l - 6:.1f}" y="{10 + plot_h * (1 - frac) + 3:.1f}" font-size="9" '
        f'fill="var(--muted)" text-anchor="end">{round(axis_min + axis_span * frac)}</text>'
        for frac in (0, 0.25, 0.5, 0.75, 1)
    )
    # Axe secondaire à droite : nombre de lits = journées de présence / 7
    # (même échelle que l'axe de gauche, juste une lecture en unité "lits").
    y_ticks_right = "".join(
        f'<text x="{chart_w - pad_r + 8:.1f}" y="{10 + plot_h * (1 - frac) + 3:.1f}" font-size="9" '
        f'fill="var(--muted)" text-anchor="start">{(axis_min + axis_span * frac) / 7:.1f}</text>'
        for frac in (0, 0.25, 0.5, 0.75, 1)
    )
    right_axis_title = (
        f'<text x="{chart_w - pad_r + 8:.1f}" y="{chart_h - pad_b + 14:.1f}" font-size="8.5" '
        f'fill="var(--muted)" text-anchor="start">lits</text>'
    )
    # Lignes de référence horizontales : moyenne (trait plein), min et max
    # (pointillés) — lisibles à la fois en journées (axe gauche) et en lits
    # (axe droit, valeur/7) puisque c'est une transformation linéaire.
    # Pas d'étiquette accrochée à la ligne elle-même (ça finissait toujours
    # par chevaucher une courbe ou une étiquette de série) : une petite
    # légende compacte, à position FIXE en haut à gauche du tracé, explique
    # les 3 traits indépendamment de où ils tombent dans les données.
    ref_specs = [
        (avg_val, "", f"moyenne : {avg_val:.0f} j ({avg_val / 7:.1f} lits)"),
        (raw_max, "3 3", f"max : {raw_max:.0f} j ({raw_max / 7:.1f} lits)"),
        (raw_min, "3 3", f"min : {raw_min:.0f} j ({raw_min / 7:.1f} lits)"),
    ]
    ref_lines_svg = ""
    for value, dash, _ in ref_specs:
        ry = y_for(value)
        dash_attr_ref = f' stroke-dasharray="{dash}"' if dash else ""
        ref_lines_svg += (
            f'<line x1="{pad_l:.1f}" y1="{ry:.1f}" x2="{chart_w - pad_r + 4:.1f}" y2="{ry:.1f}" '
            f'stroke="var(--muted)" stroke-width="1" opacity="0.5"'
            f'{dash_attr_ref} />'
        )
    ref_legend_bg = f'<rect x="{pad_l:.1f}" y="10" width="172" height="36" fill="var(--surface)" opacity="0.85" rx="4" />'
    ref_legend_svg = ""
    for i, (_, dash, lbl) in enumerate(ref_specs):
        ly = 20 + i * 11
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        ref_legend_svg += (
            f'<line x1="{pad_l + 4:.1f}" y1="{ly:.1f}" x2="{pad_l + 20:.1f}" y2="{ly:.1f}" '
            f'stroke="var(--muted)" stroke-width="1.4"{dash_attr} />'
            f'<text x="{pad_l + 24:.1f}" y="{ly + 3:.1f}" font-size="8" fill="var(--muted)">{lbl}</text>'
        )
    # Grille verticale secondaire : une ligne pointillée PAR SEMAINE (demande
    # utilisateur 2026-07-30, remplace le détail semaine par semaine qui
    # figurait auparavant dans le texte d'en-tête du TDB). Rendue plus visible
    # après retour utilisateur (2026-07-30) : couleur/opacité/épaisseur
    # relevées — l'ancienne version (var(--grid), 0.75px, opacity implicite
    # ~1 mais couleur trop proche du fond) se voyait à peine.
    week_gridlines = "".join(
        f'<line x1="{pad_l + (i / max(len(all_weeks) - 1, 1)) * plot_w:.1f}" y1="10" '
        f'x2="{pad_l + (i / max(len(all_weeks) - 1, 1)) * plot_w:.1f}" y2="{10 + plot_h:.1f}" '
        f'stroke="var(--muted)" stroke-width="1" stroke-dasharray="2 2" opacity="0.55" />'
        for i in range(len(all_weeks))
    )
    # Chaque semaine a désormais son libellé sur l'axe X (demande utilisateur
    # 2026-07-30, remplace l'affichage 1 semaine sur 4) — texte pivoté 90°
    # pour rester lisible malgré l'espacement serré quand il y a beaucoup de
    # semaines dans la période.
    week_ticks = "".join(
        f'<text x="0" y="0" font-size="8" fill="var(--muted)" text-anchor="end" '
        f'transform="translate({pad_l + (i / max(len(all_weeks) - 1, 1)) * plot_w:.1f},{10 + plot_h + 18:.1f}) rotate(-60)">{w}</text>'
        for i, w in enumerate(all_weeks)
    )

    def legend_preview(idx: int, y: str) -> str:
        color = year_colors.get(y, "var(--rhs)")
        dash = DASH_PATTERNS[idx % len(DASH_PATTERNS)]
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        marker = marker_svg(idx % 3, 17, 6, color)
        return (
            '<span class="key"><svg width="28" height="12" viewBox="0 0 28 12">'
            f'<line x1="0" y1="6" x2="28" y2="6" stroke="{color}" stroke-width="2.4"{dash_attr} />{marker}</svg>'
            f'{periods_by_year[y]["label"]}</span>'
        )

    legend_svg = "".join(legend_preview(idx, y) for idx, y in enumerate(years))

    # ---------- section 4 : indicateurs ----------
    indic_rows = ""
    for y in years:
        i = data["indicateurs"][y]
        ip = data["indicateurs"].get(prev_year(y))
        indic_rows += (
            f"<tr><td>{periods_by_year[y]['label']}</td>"
            + td(i["avq_phys_moy"], fmt(i["avq_phys_moy"]), ip and ip["avq_phys_moy"])
            + td(i["avq_cogn_moy"], fmt(i["avq_cogn_moy"]), ip and ip["avq_cogn_moy"])
            + td(i["nb_csarr"], fmt_int(i["nb_csarr"]), ip and ip["nb_csarr"])
            + td(i["nb_diag_approx"], fmt_int(i["nb_diag_approx"]), ip and ip["nb_diag_approx"])
            + td(i["nb_das_moy_rhs"], fmt(i["nb_das_moy_rhs"]), ip and ip["nb_das_moy_rhs"])
            + td(i["nb_moy_interv_rhs"], fmt(i["nb_moy_interv_rhs"]), ip and ip["nb_moy_interv_rhs"])
            + td(i["nb_moy_csarr_j"], fmt(i["nb_moy_csarr_j"], 2), ip and ip["nb_moy_csarr_j"])
            + "</tr>"
        )

    # ---------- section 5 : activité CSARR — comparaison par intervenant ----------
    # Restructuré (2026-07-30, demande utilisateur) : au lieu d'un classement
    # séparé par année (rangs/visibilité différents d'une année à l'autre,
    # difficile à comparer), UNE table par intervenant avec ses 3 années
    # côte à côte. "Nb réalisations" reste un COMPTE BRUT (validé exact contre
    # ATIH, ne pas toucher).
    # 2026-09-11 (demande utilisateur, suite vérification de la formule
    # officielle du Manuel des GME) : l'ancien "score pondéré" unique est
    # remplacé par les deux scores officiels — GLOBALE (tous actes CSARR+CCAM)
    # et SPÉCIALISÉE (seuls les actes marqueurs du GN du séjour) — voir
    # section_readaptation_intervenant. Les CCAM n'ayant pas de code
    # intervenant dans le RHS, leur contribution apparaît à part, sous le
    # pseudo-intervenant CCAM_PSEUDO_INTERVENANT (cf. tableau_de_bord.py).
    from src.viz.tableau_de_bord import CCAM_PSEUDO_INTERVENANT, CCAM_PSEUDO_LABEL

    intervenant_labels: dict[str, str] = {}
    n_by_code_year: dict[str, dict[str, int]] = {}
    for y in years:
        for r in data["activite_csarr"][y]:
            intervenant_labels[r["code"]] = r["label"]
            n_by_code_year.setdefault(r["code"], {})[y] = r["n"]
    score_by_code_year = data["readaptation_intervenant"]
    if any(CCAM_PSEUDO_INTERVENANT in score_by_code_year.get(y, {}) for y in years):
        intervenant_labels[CCAM_PSEUDO_INTERVENANT] = CCAM_PSEUDO_LABEL
        for y in years:
            n_ccam = score_by_code_year.get(y, {}).get(CCAM_PSEUDO_INTERVENANT, {}).get("n")
            if n_ccam:
                n_by_code_year.setdefault(CCAM_PSEUDO_INTERVENANT, {})[y] = round(n_ccam)

    codes_sorted = sorted(
        intervenant_labels,
        key=lambda c: sum(n_by_code_year.get(c, {}).values()),
        reverse=True,
    )

    def csarr_cell(code: str, y: str) -> tuple[float | None, float | None, float | None]:
        n = n_by_code_year.get(code, {}).get(y)
        if n is None:
            return None, None, None
        s = score_by_code_year.get(y, {}).get(code, {})
        return n, round(s.get("globale", 0.0)), round(s.get("specialisee", 0.0))

    def _metric_cells(raw_per_year: list, fmt_fn=fmt_int) -> list[str]:
        # Comparaison d'une métrique à l'ANNÉE PRÉCÉDENTE DE LA MÊME LIGNE
        # (pas la ligne précédente comme pour les tableaux "1 ligne = 1
        # année") — même formule de dégradé (_trend_td), appliquée ici entre
        # colonnes d'un même groupe de métrique plutôt qu'entre lignes.
        cells = []
        for idx, v in enumerate(raw_per_year):
            if v is None:
                cells.append("<td>—</td>")
                continue
            prev = raw_per_year[idx - 1] if idx > 0 else None
            cells.append(td(v, fmt_fn(v), prev))
        return cells

    csarr_comparison_rows = ""
    for code in codes_sorted:
        # Regroupé PAR MÉTRIQUE (toutes les années sous "Nb réalisations",
        # puis toutes sous "Score globale", etc.) pour matcher l'en-tête à
        # colonnes groupées — comparer les années entre elles doit se lire
        # sans sauter d'une métrique à l'autre.
        per_year = [csarr_cell(code, y) for y in years]
        n_cells = _metric_cells([c[0] for c in per_year])
        globale_cells = _metric_cells([c[1] for c in per_year])
        specialisee_cells = _metric_cells([c[2] for c in per_year])
        cells = "".join(n_cells + globale_cells + specialisee_cells)
        csarr_comparison_rows += f"<tr><td>{code} - {intervenant_labels[code]}</td>{cells}</tr>"

    # Ligne de total (tous intervenants confondus), en pied de table.
    n_tot_per_year = [sum(n_by_code_year.get(c, {}).get(y, 0) for c in codes_sorted) for y in years]
    globale_tot_per_year = [
        round(sum(s.get("globale", 0.0) for s in score_by_code_year.get(y, {}).values())) for y in years
    ]
    specialisee_tot_per_year = [
        round(sum(s.get("specialisee", 0.0) for s in score_by_code_year.get(y, {}).values())) for y in years
    ]
    csarr_total_row = "".join(
        _metric_cells(n_tot_per_year) + _metric_cells(globale_tot_per_year) + _metric_cells(specialisee_tot_per_year)
    )
    csarr_total_row = f"<tr><td>Total</td>{csarr_total_row}</tr>"

    # ---------- section 6 : valorisation ----------
    valorisation_rows = ""
    for y in years:
        v = data["valorisation"][y]
        vp = data["valorisation"].get(prev_year(y))
        estim = v["estimation_en_cours"]
        estim_cell = fmt(v["montant_br_pt_avec_estimation"], 2, " €")
        if estim and estim["nb_sejours"]:
            estim_cell += f" <small>({fmt_int(estim['nb_sejours'])} séj., {fmt_int(estim['nb_journees'])} j)</small>"
        ecart = v["montant_br_tot"] - v["montant_br_pt_avec_estimation"]
        # Par axe UF (2026-08-05, demande utilisateur) : pas de colonne
        # équivalente dans valorisation_sejour, donc montant_br_tot y est une
        # APPROXIMATION (= montant_br_pt reproraté par jour de présence, bon
        # proxy car la majorité des séjours restent mono-UF) — marquée "≈" au
        # lieu du montant officiel exact. Par type d'hospitalisation, c'est
        # une vraie ventilation exacte (colonne native C/P), pas de marquage.
        tot_cell = fmt(v["montant_br_tot"], 2, " €")
        if not v["montant_br_tot_exact"]:
            tot_cell = f"<span title=\"Montant officiel réparti au prorata des journées de présence par UF (toutes campagnes confondues) — aucune colonne UF dans valorisation_sejour, mais la somme sur toutes les UF reproduit exactement le total établissement\">≈ {tot_cell}</span>"
        valorisation_rows += (
            f"<tr><td>{periods_by_year[y]['label']}</td>"
            + td(v["montant_br_tot"], tot_cell, vp and vp["montant_br_tot"])
            + td(v["montant_br_pt_avec_estimation"], estim_cell, vp and vp["montant_br_pt_avec_estimation"])
            + f"<td>{fmt(ecart, 2, ' €')}</td>"
            + td(v["pmct"], fmt(v["pmct"], 2, " €"), vp and vp["pmct"])
            + td(v["pmst"], fmt(v["pmst"], 2, " €"), vp and vp["pmst"])
            + td(v["pmjt"], fmt(v["pmjt"], 2, " €"), vp and vp["pmjt"])
            + "</tr>"
        )

    # Suppléments "en sus" (2026-08-21, demande utilisateur) : transport,
    # molécules onéreuses, cancérologie — jamais mélangés au montant BR
    # séjour ci-dessus (voir le Guide TDB), affichés dans leur propre sous-tableau.
    supplements_rows = ""
    for y in years:
        s = data["valorisation"][y]["supplements"]
        if s is None:
            continue
        sp_wrap = data["valorisation"].get(prev_year(y))
        sp = sp_wrap["supplements"] if sp_wrap else None
        supplements_rows += (
            f"<tr><td>{periods_by_year[y]['label']}</td>"
            + td(s["transport"], fmt(s["transport"], 2, " €"), sp and sp["transport"])
            + td(s["molecules_onereuses"], fmt(s["molecules_onereuses"], 2, " €"), sp and sp["molecules_onereuses"])
            + td(s["supp_cancero"], fmt(s["supp_cancero"], 2, " €"), sp and sp["supp_cancero"])
            + td(s["total"], fmt(s["total"], 2, " €"), sp and sp["total"])
            + "</tr>"
        )

    # Séjours non valorisés par cause (2026-08-21, demande utilisateur) :
    # rows = cause, colonnes = période, pour rester lisible même avec
    # plusieurs années comparées (même patron que la section 9 structure GME).
    non_valorises_causes: list[tuple[str, str]] = []
    seen_causes: set[str] = set()
    for y in years:
        nv = data["valorisation"][y]["non_valorises"]
        if nv is None:
            continue
        for row in nv["rows"]:
            if row["cause"] not in seen_causes:
                seen_causes.add(row["cause"])
                non_valorises_causes.append((row["cause"], row["libelle"]))
    non_valorises_rows = ""
    for cle, libelle in non_valorises_causes:
        raw = []
        for y in years:
            nv = data["valorisation"][y]["non_valorises"]
            n = 0
            if nv is not None:
                n = next((r["effectif"] for r in nv["rows"] if r["cause"] == cle), 0)
            raw.append(n)
        non_valorises_rows += f"<tr><td>{libelle}</td>{''.join(_metric_cells(raw))}</tr>"
    non_valorises_total_row = ""
    if non_valorises_causes:
        raw_tot = []
        for y in years:
            nv = data["valorisation"][y]["non_valorises"]
            raw_tot.append(nv["total"] if nv else 0)
        non_valorises_total_row = f"<tr><td><b>Total</b></td>{''.join(_metric_cells(raw_tot))}</tr>"


    # ---------- sections 7-8 : palmarès CM / GN ----------
    # Section 9 "Palmarès GME" retirée (demande utilisateur 2026-08-03) :
    # jugée peu apporter par rapport à CM/GN et risque de surcharger le TDB.
    def _cell2(value: str, pct: float, cur: float | None = None, prev: float | None = None) -> str:
        # Valeur + % sur 2 lignes (demande utilisateur 2026-08-03) plutôt que
        # "valeur (pct %)" sur une seule ligne : permet une police plus
        # grande dans les sections 7-9 (classe CSS .palmares, cf.
        # STYLE_BLOCK) tout en tenant dans la largeur de colonne. `cur`/`prev`
        # (2026-09-12, signalisation couleur) : delta vs l'année précédente
        # DE LA MÊME LIGNE (même code), pas la ligne précédente du tableau.
        inner = f'{value}<br><span class="pct">({fmt(pct, 1, " %")})</span>'
        delta = _trend_delta(cur, prev) if (signalisation_couleur and prev is not None) else None
        return _trend_td(inner, delta)

    def _palmares_section(numero: int, titre: str, palmares: dict) -> str:
        rows_html = ""
        for row in palmares["rows"]:
            cells = ""
            for y in years:
                d = row["data"].get(y)
                if not d:
                    cells += "<td>—</td><td>—</td>"
                    continue
                dp = row["data"].get(prev_year(y))
                cells += _cell2(fmt_int(d["effectif"]), d["pct_effectif"], d["effectif"], dp and dp["effectif"])
                cells += _cell2(
                    fmt(d["valorisation"], 2, " €"), d["pct_valorisation"], d["valorisation"], dp and dp["valorisation"]
                )
            rows_html += f"<tr><td>{row['code']} — {row['libelle']}</td>{cells}</tr>"
        year_headers = "".join(f"<th>{periods_by_year[y]['label']}</th>" for y in years)
        return (
            f'<section>\n    <h2>{numero} · {titre}</h2>\n'
            '    <div class="table-wrap wide palmares">\n      <table>\n        <thead>\n'
            f'          <tr><th rowspan="2">Code — Libellé</th>'
            + "".join(f'<th colspan="2">{periods_by_year[y]["label"]}</th>' for y in years)
            + "</tr>\n"
            f'          <tr>{"<th>Effectif</th><th>Valorisation</th>" * len(years)}</tr>\n'
            f"        </thead>\n        <tbody>{rows_html}</tbody>\n      </table>\n    </div>\n  </section>"
        )

    # ---------- section 9 : structure GME (GR / GL / Sévérité, concaténées) ----------
    def _structure_section(numero: int, structure: dict) -> str:
        def block_rows(bloc: dict) -> str:
            html = f'<tr class="group-row"><td colspan="{1 + 2 * len(years)}"><b>{bloc["titre"]}</b></td></tr>'
            for row in bloc["rows"]:
                cells = ""
                for y in years:
                    d = row["data"][y]
                    dp = row["data"].get(prev_year(y))
                    cells += _cell2(fmt_int(d["effectif"]), d["pct_effectif"], d["effectif"], dp and dp["effectif"])
                    cells += _cell2(
                        fmt(d["valorisation"], 2, " €"), d["pct_valorisation"], d["valorisation"], dp and dp["valorisation"]
                    )
                is_total = row["code"] is None
                label = f"<b>{row['libelle']}</b>" if is_total else f"{row['code']} — {row['libelle']}"
                row_class = ' class="total-row"' if is_total else ""
                html += f"<tr{row_class}><td>{label}</td>{cells}</tr>"
            return html

        rows_html = block_rows(structure["gr"]) + block_rows(structure["gl"]) + block_rows(structure["sev"])
        return (
            f'<section>\n    <h2>{numero} · Structure de groupage (GR / GL / Sévérité)</h2>\n'
            '    <div class="table-wrap wide palmares">\n      <table>\n        <thead>\n'
            f'          <tr><th rowspan="2">Catégorie</th>'
            + "".join(f'<th colspan="2">{periods_by_year[y]["label"]}</th>' for y in years)
            + "</tr>\n"
            f'          <tr>{"<th>Effectif</th><th>Valorisation</th>" * len(years)}</tr>\n'
            f"        </thead>\n        <tbody>{rows_html}</tbody>\n      </table>\n    </div>\n  </section>"
        )

    supplements_section = ""
    if supplements_rows:
        supplements_section = (
            "<div class=\"table-wrap\">"
            "<table><caption>Suppléments \"en sus\" (hors du montant BR séjour ci-dessus)</caption>"
            "<thead><tr><th>Période</th><th>Transport</th><th>Molécules onéreuses</th>"
            "<th>Suppl. cancérologie</th><th>Total suppléments</th></tr></thead>"
            f"<tbody>{supplements_rows}</tbody></table></div>"
        )

    non_valorises_section = ""
    if non_valorises_rows:
        year_headers_nv = "".join(f"<th>{periods_by_year[y]['label']}</th>" for y in years)
        non_valorises_section = (
            "<div class=\"table-wrap\">"
            "<table><caption>Séjours non valorisés</caption>"
            f"<thead><tr><th>Cause</th>{year_headers_nv}</tr></thead>"
            f"<tbody>{non_valorises_rows}</tbody>"
            f"<tfoot>{non_valorises_total_row}</tfoot></table></div>"
        )

    palmares_html = "\n\n  ".join([
        _palmares_section(7, "Palmarès CM", data["palmares_cm"]),
        _palmares_section(8, "Palmarès GN", data["palmares_gn"]),
        _structure_section(9, data["structure_gme"]),
    ])

    subtitle = _period_subtitle(data["finess"], data["periods"])
    if axis_label:
        subtitle += f" · {axis_label}"

    trend_legend = ""
    if signalisation_couleur:
        trend_legend = (
            '<div class="trend-legend">'
            f'<span class="key"><span class="trend-arrow" style="color:{TREND_COLOR_POS}">▲</span>hausse vs période précédente</span>'
            f'<span class="key"><span class="trend-arrow" style="color:{TREND_COLOR_NEG}">▼</span>baisse vs période précédente</span>'
            '<span class="key">intensité du fond = ampleur de la variation (plafonnée à 15 %)</span>'
            "</div>"
        )

    body = HTML_TEMPLATE.format(
        apparence_style=_apparence_style(apparence),
        trend_legend=trend_legend,
        period_subtitle=subtitle,
        patients_rows=patients_rows,
        sejours_rows=sejours_rows,
        lines_svg=lines_svg,
        markers_svg=markers_svg,
        labels_svg=labels_svg,
        gridlines=gridlines,
        y_ticks=y_ticks,
        y_ticks_right=y_ticks_right,
        right_axis_title=right_axis_title,
        ref_lines_svg=ref_lines_svg,
        ref_legend_bg=ref_legend_bg,
        ref_legend_svg=ref_legend_svg,
        week_ticks=week_ticks,
        week_gridlines=week_gridlines,
        legend_svg=legend_svg,
        chart_w=chart_w,
        chart_h=chart_h,
        indic_rows=indic_rows,
        csarr_comparison_rows=csarr_comparison_rows,
        csarr_total_row=csarr_total_row,
        csarr_year_headers="".join(f"<th>{y}</th>" for y in years) * 3,
        csarr_group_colspan=len(years),
        valorisation_rows=valorisation_rows,
        supplements_section=supplements_section,
        non_valorises_section=non_valorises_section,
        palmares_html=palmares_html,
        guide_html=GUIDE_TDB_HTML,
    )
    title = "PMSI-SMR — Tableau de bord"
    if axis_label:
        title += f" ({axis_label})"
    return _wrap_page(title, body)


def render_annexe(data: dict) -> str:
    """Document SÉPARÉ du tableau de bord principal (choix utilisateur
    2026-07-30) : dédié à l'identification d'erreurs/incohérences, pas à la
    lecture d'activité — ne doit donc pas être mélangé avec le TDB. Réutilise
    le même style visuel (STYLE_BLOCK) pour rester cohérent, mais c'est un
    fichier HTML autonome, généré et distribué à part."""
    years = data["years"]
    periods_by_year = {p["year"]: p for p in data["periods"]}

    incoherences = data["incoherences_vidhosp_rhs"]
    incoherences_rows = "".join(
        f"<tr><td>{a['numero_admin_sejour']}</td><td>{a['nir'] or '—'}</td>"
        f"<td>{a['vidhosp_entree'] or '—'}</td><td>{a['vidhosp_sortie'] or '—'}</td>"
        f"<td>{a['rhs_derniere_semaine']}</td><td>{a['type']}</td></tr>"
        for a in incoherences
    )
    if not incoherences:
        incoherences_rows = '<tr><td colspan="6" style="text-align:center;color:var(--muted)">Aucune incohérence détectée</td></tr>'

    erreurs_activite_rows = ""
    for y in years:
        e = data["erreurs_activite"][y]
        erreurs_activite_rows += (
            f"<tr><td>{periods_by_year[y]['label']}</td><td>{fmt_int(e['nb_sejours_erreur'])}</td>"
            f"<td>{fmt_int(e['nb_rhs_erreur'])}</td><td>{fmt_int(e['nb_diag_erreur'])}</td>"
            f"<td>{fmt_int(e['nb_csarr_erreur'])}</td><td>{fmt_int(e['nb_csar_erreur'])}</td></tr>"
        )

    body = ANNEXE_TEMPLATE.format(
        period_subtitle=_period_subtitle(data["finess"], data["periods"]),
        incoherences_rows=incoherences_rows,
        erreurs_activite_rows=erreurs_activite_rows,
    )
    return _wrap_page("PMSI-SMR — Annexe (identification d'erreurs)", body)


def _wrap_page(title: str, body: str) -> str:
    """Assemble un document HTML autonome (titre + CSS partagé STYLE_BLOCK +
    corps). STYLE_BLOCK est interpolé comme valeur de variable (f-string),
    donc ses accolades CSS n'ont pas besoin d'être doublées comme dans les
    templates .format() ci-dessous — évite d'avoir à dupliquer ~110 lignes de
    CSS entre le TDB principal et l'annexe."""
    return (
        f'<meta charset="utf-8">\n<title>{title}</title>\n'
        f'<meta name="color-scheme" content="light dark">\n<style>\n{STYLE_BLOCK}\n</style>\n\n{body}'
    )


STYLE_BLOCK = """
  .viz-root {
    color-scheme: light;
    --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e;
    --muted: #898781; --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
    --rhs: #2a78d6; --vid: #1baf7a; --warn: #fab219; --warn-ink: #6b4c00;
    --line-1: #3a3a35; --line-2: #0e8f5c; --line-3: #1755a6;
  }
  /* Anciennement un vrai thème sombre : remplacé par un fond vert pâle
     ("oeuf d'oie") avec du texte noir — l'utilisateur n'aime pas le mode
     foncé sur ce TDB. Reste piloté par les mêmes déclencheurs (préférence
     système ou data-theme="dark") pour ne rien casser côté intégration,
     mais le rendu n'est plus "sombre". */
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: light;
      --page: #e7ecc8; --surface: #eef2d9; --ink: #0a0a0a; --ink-2: #262b16;
      --muted: #5b6144; --grid: #cdd6a4; --border: rgba(10,10,10,0.14);
      --rhs: #1f5fb0; --vid: #16875c; --warn: #b8790a; --warn-ink: #3a2900;
      --line-1: #24261a; --line-2: #0b6b3f; --line-3: #103d7a;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: light;
    --page: #e7ecc8; --surface: #eef2d9; --ink: #0a0a0a; --ink-2: #262b16;
    --muted: #5b6144; --grid: #cdd6a4; --border: rgba(10,10,10,0.14);
    --rhs: #1f5fb0; --vid: #16875c; --warn: #b8790a; --warn-ink: #3a2900;
    --line-1: #24261a; --line-2: #0b6b3f; --line-3: #103d7a;
  }
  /* Impression : le TDB reste en couleur à l'écran ; à l'impression, une
     palette en NUANCES DE GRIS (pas un noir/blanc binaire — jugé trop dur
     visuellement, retour utilisateur 2026-07-30) tout en gardant assez de
     contraste pour rester lisible sur une imprimante grayscale standard.
     Les formes/styles de trait du graphique (dasharray, marqueurs) restent
     la vraie garantie de lisibilité si l'imprimante ne rend même pas les
     niveaux de gris — le gris est un choix esthétique, pas la seule ligne
     de défense. */
  @media print {
    /* !important sur chaque variable : sans ça, le sélecteur
       ":root[data-theme=dark] .viz-root" (thème sombre choisi manuellement)
       est plus spécifique que ".viz-root" ici et gagnerait quand même à
       l'impression si l'utilisateur est en thème sombre — texte blanc sur
       fond blanc, illisible. !important passe devant peu importe la
       spécificité. */
    /* Sans ces 3 propriétés, la plupart des navigateurs (Chrome/Edge en tête)
       ignorent silencieusement les couleurs de fond ET peuvent désaturer les
       couleurs de premier plan vers un noir pur à l'impression/aperçu — ce
       qui aplatit toutes les nuances de gris volontairement choisies
       ci-dessous en un simple noir sur blanc. `exact` force le navigateur à
       respecter les couleurs telles que définies. Il faut aussi les 3 formes
       (standard + préfixée + héritée) car le support diffère selon le
       moteur de rendu. */
    * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; color-adjust: exact !important; }
    .viz-root {
      color-scheme: light !important;
      --page: #ffffff !important; --surface: #f6f6f6 !important; --ink: #1a1a1a !important; --ink-2: #444444 !important;
      --muted: #6e6e6e !important; --grid: #d4d4d4 !important; --border: #b0b0b0 !important;
      --rhs: #2e2e2e !important; --vid: #5c5c5c !important; --warn: #7a7a7a !important; --warn-ink: #1a1a1a !important;
      --line-1: #1a1a1a !important; --line-2: #5c5c5c !important; --line-3: #949494 !important;
      background: #ffffff !important; color: #1a1a1a !important;
      padding: 0; max-width: none;
    }
    .viz-root section { break-inside: avoid; }
    .viz-root table th, .viz-root table td { border-bottom: 1px solid #d4d4d4; }
    .viz-root table thead tr:last-child th { border-bottom: 2px solid #1a1a1a; }
    .viz-root table tfoot td, .viz-root table tfoot th { border-top: 2px solid #1a1a1a; }
    .viz-root .table-wrap { border: 1px solid #d4d4d4; }
    .viz-root section > h2 { background: #ececec; border: none; }
    .viz-root .callout { background: #f6f6f6 !important; border: 1px solid #c2c2c2; }
    .viz-root .callout.warn { border-style: dashed; }
    .viz-root .callout.ok { border-style: solid; }
    .viz-root .callout .ico { background: #dcdcdc !important; color: #1a1a1a !important; border: none; }
    .viz-root .note-ref a { background: #dcdcdc !important; color: #1a1a1a !important; }
    /* La barre de défilement horizontale (.table-wrap { overflow-x: auto })
       n'a pas de sens à l'impression : une page ne se fait pas défiler, le
       surplus de largeur serait juste coupé. Les tables larges (ex. section 5
       "Activité CSARR par intervenant", jusqu'à 13 colonnes avec 3 années)
       sont donc rétrécies (police + espacement) pour tenir sur une page A4
       portrait au lieu d'être coupées ou de laisser un défilement inutile. */
    .viz-root .table-wrap { overflow: visible; }
    .viz-root .table-wrap.wide table { font-size: 8.5px; }
    .viz-root .table-wrap.wide table th, .viz-root .table-wrap.wide table td { padding: 3px 4px; }
    /* Sections 7-9 (palmarès CM/GN, structure GR/GL/Sévérité) : demande
       utilisateur 2026-08-03, valeur et % sur 2 lignes par cellule (cf.
       _cell2() dans render()) au lieu d'une seule ligne "valeur (pct %)" —
       permet une police plus grande que le 8.5px générique des tables
       "wide" tout en tenant dans la largeur de colonne. Règle plus
       spécifique que .wide, donc prioritaire malgré l'ordre. */
    .viz-root .table-wrap.wide.palmares table { font-size: 10.5px; }
    .viz-root .table-wrap.wide.palmares table th, .viz-root .table-wrap.wide.palmares table td { padding: 4px 6px; }
  }
  .viz-root {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page); color: var(--ink);
    padding: 32px clamp(16px, 4vw, 48px) 56px; max-width: 1080px; margin: 0 auto;
  }
  .viz-root * { box-sizing: border-box; }
  header.top { margin-bottom: 24px; }
  header.top h1 { font-size: clamp(20px, 3vw, 27px); font-weight: 700; margin: 0 0 4px; text-wrap: balance; }
  header.top .subtitle { font-size: 14px; font-weight: 600; color: var(--ink-2); margin: 0 0 12px; }
  header.top p { font-size: 13px; color: var(--ink-2); margin: 0; max-width: 72ch; }
  header.top code { font-size: 12px; background: var(--surface); border: 1px solid var(--border); padding: 1px 5px; border-radius: 4px; }

  section { margin-bottom: 26px; }
  section > h2 {
    font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: .03em;
    color: var(--ink); background: color-mix(in srgb, var(--rhs) 12%, var(--surface));
    padding: 8px 12px; border-radius: 8px; margin: 0 0 12px;
  }
  table { width: 100%; border-collapse: collapse; font-size: 13px; background: var(--surface); }
  table th, table td { padding: 7px 10px; text-align: right; border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; background: var(--surface); color: var(--ink); }
  table td:first-child { text-align: left; }
  /* nowrap sur le CONTENU des cellules uniquement (colonnes de données) —
     pas sur les en-têtes ni sur la 1ʳᵉ colonne (libellés de ligne, parfois
     longs, ex. "0874 — Lésions traumatiques…") : leur forcer nowrap
     élargirait toute la colonne et écraserait la taille de police du reste
     du tableau (retour utilisateur 2026-08-03, revert de la tentative
     précédente qui appliquait nowrap + police réduite partout). */
  table td:not(:first-child) { white-space: nowrap; }
  table th { font-size: 11px; text-transform: uppercase; letter-spacing: .03em; color: var(--ink); font-weight: 700; text-align: center; }
  table thead tr:last-child th { border-bottom: 2.5px solid var(--ink); }
  table tbody tr:last-child td { border-bottom: none; }
  /* Lignes de total (tfoot ou .total-row, ex. "Sous-total" section 9) : fond
     un peu plus FONCÉ que le contenu courant (pas juste --surface, sinon
     elles se fondent dans le reste du tableau) — même traitement que les
     regroupements de section ci-dessous, demande utilisateur 2026-09-12. */
  table tfoot td, table tfoot th, table tr.total-row td {
    font-weight: 700; border-top: 2.5px solid var(--ink); border-bottom: none;
    background: color-mix(in srgb, #000 14%, var(--surface));
  }
  .table-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 4px 6px; }
  .table-wrap + .table-wrap { margin-top: 14px; }
  table caption { caption-side: top; text-align: left; font-size: 12px; font-weight: 700; color: var(--ink); padding: 6px 4px 8px; }
  table tr.group-row td { background: color-mix(in srgb, #000 14%, var(--surface)); text-align: left; font-size: 12px; }
  table td .pct { display: block; font-size: 0.82em; color: var(--muted); margin-top: 1px; }

  .legend { display: flex; gap: 14px; font-size: 12px; color: var(--ink-2); margin: 0 0 6px; }
  .legend .key { display: inline-flex; align-items: center; gap: 6px; }

  /* Signalisation couleur (option avant génération, 2026-09-12) : dégradé de
     fond posé en style inline par cellule (_trend_td) — cette classe ne fixe
     que la taille/l'alignement de la flèche, jamais sa couleur (déjà en
     inline, propre à chaque cellule). */
  .trend-arrow { font-size: 0.85em; margin-right: 2px; }
  .trend-legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 11.5px; color: var(--ink-2); margin: 0 0 14px; }
  .trend-legend .key { display: inline-flex; align-items: center; gap: 5px; }

  .callout { display: flex; gap: 10px; align-items: flex-start; border-radius: 10px; padding: 12px 14px; font-size: 12.5px; margin-top: 10px; }
  .callout.warn { background: color-mix(in srgb, var(--warn) 14%, var(--surface)); border: 1px solid color-mix(in srgb, var(--warn) 40%, var(--border)); }
  .callout.ok { background: color-mix(in srgb, var(--vid) 12%, var(--surface)); border: 1px solid color-mix(in srgb, var(--vid) 35%, var(--border)); }
  .callout .ico { flex: none; width: 18px; height: 18px; border-radius: 50%; font-weight: 700; font-size: 12px; display: flex; align-items: center; justify-content: center; }
  .callout.warn .ico { background: var(--warn); color: var(--warn-ink); }
  .callout.ok .ico { background: var(--vid); color: #fff; }

  footer.note { margin-top: 26px; font-size: 11.5px; color: var(--muted); border-top: 1px solid var(--grid); padding-top: 12px; }
  footer.note ul { margin: 6px 0 0; padding-left: 18px; }

  /* Bouton "Guide TDB" + boîte de dialogue (remplace, 2026-09-11, l'ancienne
     liste de notes numérotées en fin de TDB — demande utilisateur : le
     détail pédagogique est désormais regroupé dans UN seul guide, ouvert à
     la demande, plutôt que dispersé en callouts + renvois numérotés. Reste
     entièrement embarqué dans le fichier HTML du TDB (aucune requête
     externe) : <dialog> natif, pas de librairie JS. */
  .top-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
  .guide-btn {
    flex: none; background: var(--rhs); color: #fff; border: none; border-radius: 8px;
    padding: 9px 16px; font-size: 13px; font-weight: 600; cursor: pointer; font-family: inherit;
  }
  .guide-btn:hover { filter: brightness(1.08); }
  .guide-dialog {
    width: min(760px, 92vw); max-height: 85vh; padding: 0; border: 1px solid var(--border);
    border-radius: 12px; color: var(--ink);
    background: color-mix(in srgb, var(--rhs) 5%, var(--surface));
  }
  .guide-dialog::backdrop { background: rgba(0,0,0,0.45); }
  .guide-head {
    position: sticky; top: 0; display: flex; align-items: center; justify-content: space-between;
    gap: 12px; padding: 14px 18px; background: color-mix(in srgb, var(--rhs) 14%, var(--surface));
    border-bottom: 1px solid var(--border);
  }
  .guide-head h2 { margin: 0; font-size: 15px; font-weight: 700; }
  .guide-close {
    flex: none; width: 26px; height: 26px; border-radius: 50%; border: none; cursor: pointer;
    background: var(--surface); color: var(--ink); font-size: 13px; line-height: 1;
  }
  .guide-body {
    padding: 6px 20px 20px; overflow-y: auto; max-height: calc(85vh - 56px);
    font-family: Arial, Verdana, "Segoe UI", sans-serif; font-size: 13px; line-height: 1.5;
  }
  .guide-body h3 {
    font-size: 12.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .02em;
    color: var(--ink); background: color-mix(in srgb, var(--rhs) 10%, var(--surface));
    padding: 6px 10px; border-radius: 6px; margin: 20px 0 8px;
  }
  .guide-body h3:first-child { margin-top: 8px; }
  .guide-body p.guide-intro { color: var(--ink-2); margin: 0 0 8px; }
  .guide-body dl { margin: 0 0 4px; }
  .guide-body dt { font-weight: 700; margin-top: 6px; }
  .guide-body dd { margin: 1px 0 0 0; color: var(--ink-2); }
  .notes-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
  .notes-list li { scroll-margin-top: 16px; }
  .notes-list li:target { outline: 2px solid var(--rhs); outline-offset: 2px; border-radius: 10px; }
  .note-back { margin-left: 6px; color: var(--muted); text-decoration: none; font-weight: 700; }
  @media print {
    .guide-btn, .guide-dialog { display: none !important; }
  }
"""


# Contenu statique du Guide TDB (2026-09-11, demande utilisateur) : remplace
# l'ancienne liste de notes numérotées en bas de page. Un seul guide,
# identique pour tous les établissements, rédigé pour un public NON
# spécialiste du PMSI (aussi bien médical que gestion) — chaque tableau et
# chaque colonne y est expliqué en langage courant. Le détail technique
# (méthodologie exacte, sources, dates de validation, limites) reste dans le
# document Journal séparé (render_journal), destiné au debug — le Guide, lui,
# doit rester lisible et compact (embarqué dans CHAQUE fichier TDB généré).
GUIDE_TDB_HTML = """
<p class="guide-intro">Ce tableau de bord regroupe, pour un ou plusieurs établissements et sur une ou
plusieurs périodes comparables (mêmes semaines de l'année), les principaux chiffres d'activité et de
valorisation financière d'un service de Soins Médicaux et de Réadaptation (SMR, anciennement SSR). Il compare
toujours des périodes calées sur les mêmes semaines calendaires (semaine 01 à N), pas des années civiles
complètes, pour que la comparaison entre années soit honnête même en cours d'année. Deux indicateurs officiels,
deux notions officielles de classification n'apparaissent pas ici : le classement en type de réadaptation
(HC : pédiatrique/spécialisée/globale/autre ; HTP : pédiatrique/modérée/intense/très intense/indifférenciée)
et la majoration de valorisation qui en découle pour l'établissement. Ces deux notions reposent sur un calcul
officiel précis (Manuel des groupes médico-économiques GME, ATIH, volume 1, section 3.3.2 "Calcul des
scores") : la somme des pondérations de chaque acte de réadaptation codé (CSARR + CCAM), modulateurs de lieu
compris, sert de base à deux indicateurs, un par séjour (HC) ou par semaine (HTP), l'autre ce même total
divisé par le nombre de jours de présence en semaine (lundi-vendredi). Cet outil n'applique pas les seuils
de classification officiels (variables selon le type de prise en charge), mais reconstruit et affiche cette
même somme de pondérations — voir la section 5 ci-dessous, qui la décompose par intervenant.</p>

<h3>1 · Patients</h3>
<p class="guide-intro">Combien de patients différents ont été pris en charge sur la période, et leur
répartition par sexe et par âge. Un même patient n'est compté qu'une seule fois par période, même si son
séjour s'étend sur plusieurs semaines.</p>
<dl>
  <dt>F / M / Total</dt><dd>Nombre de patientes, de patients, et le total des deux — un patient est identifié
  par son identifiant patient (IPP), pas par son numéro de sécurité sociale (qui peut être celui de l'assuré,
  donc parfois partagé entre plusieurs personnes d'un même foyer).</dd>
  <dt>% F / % M / % Total</dt><dd>Part de chaque sexe dans le total de la période (le % Total vaut toujours
  100 %, rappelé pour la lisibilité).</dd>
  <dt>Âge moy. F / M / Total</dt><dd>Âge moyen des patientes, des patients, et de l'ensemble, à la date de
  début de leur séjour.</dd>
</dl>

<h3>2 · Séjours</h3>
<p class="guide-intro">Volume d'activité de la période, exprimé en séjours, en semaines transmises et en
journées réellement occupées.</p>
<dl>
  <dt>Nb SSR</dt><dd>Nombre de séjours SMR distincts sur la période (un patient peut avoir plusieurs séjours
  dans l'année).</dd>
  <dt>Nb RHS</dt><dd>Nombre de résumés hebdomadaires standardisés transmis — en pratique, une ligne par
  semaine de séjour et par patient : un séjour de 6 semaines produit 6 RHS.</dd>
  <dt>Nb journées</dt><dd>Nombre total de journées où un patient était réellement présent dans l'établissement
  (voir aussi la section 3, qui détaille ce chiffre semaine par semaine).</dd>
  <dt>DMH</dt><dd>Durée Moyenne d'Hospitalisation : nombre moyen de journées de présence par séjour sur la
  période.</dd>
  <dt>NbLits moy</dt><dd>Nombre moyen de lits occupés sur la période, obtenu en divisant le nombre de
  journées de présence par le nombre de jours calendaires de la période.</dd>
  <dt>EXH</dt><dd>Taux d'occupation (Exploitation Hospitalière) : NbLits moy rapporté à la capacité en lits de
  l'établissement, en pourcentage.</dd>
</dl>

<h3>3 · Journées de présence par semaine</h3>
<p class="guide-intro">Le graphique compare, semaine ISO par semaine ISO (semaine 01, 02, 03…), le nombre de
journées de présence de chaque année sélectionnée — une courbe par année, avec sa propre couleur et son
propre style de trait pour rester lisible même imprimé en noir et blanc. L'axe vertical de gauche est
volontairement <b>zoomé sur la plage des valeurs observées</b> (il ne part pas de zéro) pour mieux voir les
variations d'une semaine à l'autre — les graduations affichent les vraies valeurs pour éviter toute
impression trompeuse sur l'ampleur des écarts. L'axe de droite convertit la même échelle en <b>nombre de
lits</b> (journées de présence divisées par 7). Trois lignes de repère horizontales indiquent la moyenne
(trait plein) ainsi que le minimum et le maximum de la période (pointillés).</p>

<h3>4 · Indicateurs</h3>
<p class="guide-intro">Indicateurs médicaux et d'activité complémentaires, en moyenne ou en cumul sur la
période.</p>
<dl>
  <dt>AVQ phys. moy. / AVQ cogn. moy.</dt><dd>Moyenne des scores de dépendance physique et cognitive des
  patients (Activités de la Vie Quotidienne) — plus le score est élevé, plus le patient est dépendant.</dd>
  <dt>Nb CSARR</dt><dd>Nombre d'actes de rééducation-réadaptation (nomenclature CSARR) réalisés sur la
  période, en évitant de compter plusieurs fois un doublon de transmission (un même acte transmis 3 fois ou
  plus le même jour n'est compté que 2 fois, ce qui correspond à une réalisation matin ET après-midi).</dd>
  <dt>Nb diag.</dt><dd>Nombre de diagnostics associés distincts (couples séjour/code diagnostic), une fois
  les doublons de transmission retirés.</dd>
  <dt>Nb moy. DAS/RHS</dt><dd>Nombre moyen de diagnostics associés par semaine transmise (RHS).</dd>
  <dt>Nb moy. interv./RHS (approx.)</dt><dd>Nombre moyen d'actes de rééducation (CSARR + actes non
  rééducatifs CSAR) par semaine transmise — indicateur approximatif, à confirmer.</dd>
  <dt>Nb moy. CSARR/j</dt><dd>Nombre moyen d'actes CSARR par journée de présence.</dd>
</dl>

<h3>5 · Activité CSARR par intervenant</h3>
<p class="guide-intro">Détaille l'activité de rééducation-réadaptation par métier (kinésithérapeute,
ergothérapeute, etc. — identifiés par leur code intervenant CSARR officiel), avec les 3 périodes comparées
côte à côte pour chaque métier.</p>
<dl>
  <dt>Nb réalisations</dt><dd>Comptage brut du nombre d'actes réalisés par ce métier, sans aucun retraitement
  — c'est la colonne dont la méthode de calcul a été vérifiée à l'identique du rapport officiel ATIH
  correspondant.</dd>
  <dt>Score de réadaptation globale</dt><dd>Chaque acte de rééducation-réadaptation réalisé par ce métier
  (actes CSARR, majorés selon leur lieu de réalisation le cas échéant) est valorisé par une pondération
  officielle ATIH, puis ces valorisations sont additionnées — cumulées sur toute la période. C'est la
  définition officielle du score "global", à ceci près qu'il est ici décomposé par métier plutôt que laissé
  au niveau du séjour.</dd>
  <dt>Score de réadaptation spécialisée</dt><dd>Même pondération que le score global, mais comptée en plus
  dans ce score UNIQUEMENT si l'acte est un "marqueur" reconnu de la pathologie du séjour. La liste officielle
  ATIH indique, pour chaque type de pathologie (GN — ex. "AVC avec hémiplégie"), quels actes comptent comme
  marqueurs de sa rééducation ; un même acte peut être marqueur pour un GN et pas pour un autre, donc la
  vérification se fait séjour par séjour, sur le GN de ce séjour précis (le même que celui utilisé pour les
  palmarès CM/GN). Certains types de pathologie n'ont aucune liste de marqueurs définie par l'ATIH : leurs
  séjours ont alors un score spécialisé toujours nul, même avec beaucoup d'actes de rééducation. Le score
  spécialisé est donc toujours inférieur ou égal au score global : les actes non marqueurs (évaluations
  courantes, actes plus généraux) comptent dans le global mais jamais dans le spécialisé.</dd>
  <dt>Actes CCAM (non rattachés à un intervenant)</dt><dd>Les scores officiels comptent aussi certains actes
  médicaux (nomenclature CCAM) en plus des actes CSARR. Mais contrairement au CSARR, un acte CCAM n'est
  jamais rattaché à un métier précis dans les données transmises — sa contribution au score (globale et
  spécialisée) apparaît donc sur cette ligne à part, plutôt que d'être arbitrairement attribuée à un
  professionnel ou ignorée.</dd>
</dl>
<p class="guide-intro">Ce tableau inclut délibérément les séjours en erreur de groupage bloquante dans tous
ses totaux (logique d'activité réellement réalisée, pas de facturation) — un écart avec les statistiques ATIH
officielles (qui excluent ces séjours) est donc normal dès qu'un séjour est en erreur, et sert volontairement
de signal d'alerte plutôt que d'être masqué.</p>

<h3>6 · Valorisation</h3>
<p class="guide-intro">Traduit l'activité de la période en montants financiers (base de remboursement ATIH,
avant tout autre ajustement).</p>
<dl>
  <dt>Montant BR SÉJOUR (fact.)</dt><dd>Montant de base de remboursement déjà facturé et reconnu par l'ATIH
  sur cette période, hors transport, molécules onéreuses et supplément cancérologie (voir "Suppléments en
  sus" ci-dessous) et hors séjours en anomalie de facturation (chaînage, en attente de droits, non
  facturables à l'Assurance Maladie).</dd>
  <dt>Montant BR estimé PRT</dt><dd>Un essai de reconstitution du même montant, réparti au prorata des
  journées réellement présentes de chaque séjour, complété par une estimation du montant des séjours encore
  en cours (non facturés car pas encore clôturés). C'est un indicateur À TITRE INDICATIF, pas un chiffre
  officiel ATIH — un grand écart en cours d'année est normal (année pas terminée), pas une anomalie.</dd>
  <dt>Écart</dt><dd>Différence entre les deux montants ci-dessus.</dd>
  <dt>PMCT</dt><dd>Prix Moyen du Cas Traité : montant moyen par séjour (basé sur le montant réellement prouvé,
  sans l'estimation des séjours en cours).</dd>
  <dt>PMST</dt><dd>Prix Moyen de la Semaine Traitée : montant moyen par semaine transmise (RHS).</dd>
  <dt>PMJT</dt><dd>Prix Moyen de la Journée Traitée : montant moyen par journée de présence — le tarif moyen
  observé par jour d'hospitalisation.</dd>
</dl>
<p class="guide-intro"><b>Suppléments "en sus"</b> : transport, molécules onéreuses (médicaments coûteux) et
supplément cancérologie sont des versements ponctuels, facturés en plus du séjour et sans rapport avec sa
durée — ils sont donc toujours affichés à part, jamais mélangés au montant BR séjour ni lissés au prix par
journée (PMJT).</p>
<p class="guide-intro"><b>Séjours non valorisés</b> : liste, par cause, les séjours actifs sur la période qui
n'ont encore aucun montant BR connu alors qu'ils "devraient" déjà en avoir un — les causes principales sont
une anomalie de chaînage, une attente de droits à l'Assurance Maladie, une non-facturabilité à l'Assurance
Maladie, une erreur de groupage, ou simplement un séjour encore en cours (moins de 90 jours, pas encore
clôturé).</p>

<h3>7-8 · Palmarès CM / GN</h3>
<p class="guide-intro">Classement des 5 types de prise en charge (CM = Catégorie Majeure, GN = Groupe
Nosologique) les plus fréquents, en nombre de séjours et en montant financier. Le même classement (mêmes 5
codes) est utilisé pour toutes les périodes comparées, pour rendre la comparaison directe.</p>
<dl>
  <dt>Code — Libellé</dt><dd>Code officiel du type de prise en charge et son intitulé.</dd>
  <dt>Effectif</dt><dd>Nombre de séjours rattachés à ce code sur la période (un séjour est rattaché au code de
  sa toute dernière semaine connue).</dd>
  <dt>Valorisation</dt><dd>Montant BR séjour (hors suppléments) rattaché à ce code sur la période.</dd>
  <dt>% (sous chaque valeur)</dt><dd>Part de ce code dans le total, tous codes confondus, de sa colonne.</dd>
</dl>

<h3>9 · Structure de groupage (GR / GL / Sévérité)</h3>
<p class="guide-intro">Répartition de TOUS les séjours (pas seulement un top 5) selon trois axes de
classification médicale, toutes catégories de prise en charge confondues.</p>
<dl>
  <dt>GR</dt><dd>Type de rééducation dont relève le séjour.</dd>
  <dt>GL</dt><dd>Groupe de lourdeur (charge en soins du patient).</dd>
  <dt>Sévérité</dt><dd>0 = hospitalisation à temps partiel (HTP), 1 = hospitalisation complète sans sévérité
  associée, 2 = hospitalisation complète avec sévérité associée.</dd>
  <dt>Erreur de groupage</dt><dd>Regroupe à part les séjours dont le code de groupage n'a pas été reconnu,
  plutôt que de les classer à tort dans une vraie catégorie.</dd>
</dl>
"""

HTML_TEMPLATE = """<div class="viz-root">
  {apparence_style}
  <header class="top">
    <div class="top-row">
      <div>
        <h1>Tableaux de bord SMR</h1>
        <p class="subtitle">{period_subtitle}</p>
      </div>
      <button type="button" class="guide-btn" onclick="document.getElementById('guide-tdb').showModal()">Guide TDB</button>
    </div>
  </header>

  <dialog id="guide-tdb" class="guide-dialog">
    <div class="guide-head">
      <h2>Guide du tableau de bord</h2>
      <button type="button" class="guide-close" onclick="document.getElementById('guide-tdb').close()" aria-label="Fermer">✕</button>
    </div>
    <div class="guide-body">
      {guide_html}
    </div>
  </dialog>

  {trend_legend}

  <section>
    <h2>1 · Patients</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Période</th><th>F</th><th>M</th><th>Total</th><th>% F</th><th>% M</th><th>% Total</th><th>Âge moy. F</th><th>Âge moy. M</th><th>Âge moy. Total</th></tr></thead>
        <tbody>{patients_rows}</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>2 · Séjours</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Période</th><th>Nb SSR</th><th>Nb RHS</th><th>Nb journées</th><th>DMH</th><th>NbLits moy</th><th>EXH</th></tr></thead>
        <tbody>{sejours_rows}</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>3 · Journées de présence par semaine</h2>
    <div class="table-wrap" style="padding:14px 16px">
      <div class="legend">{legend_svg}</div>
      <svg viewBox="0 0 {chart_w} {chart_h}" width="100%" style="max-width:100%">
        {gridlines}
        {week_gridlines}
        {ref_lines_svg}
        {lines_svg}
        {markers_svg}
        {labels_svg}
        {y_ticks}
        {y_ticks_right}
        {right_axis_title}
        {week_ticks}
        {ref_legend_bg}
        {ref_legend_svg}
      </svg>
      <p style="font-size:10.5px;color:var(--muted);margin:8px 0 0">Échelle verticale zoomée sur la plage des valeurs observées (l'axe ne part pas de zéro) — graduations chiffrées ci-contre pour lire l'amplitude réelle. Axe de droite : nombre de lits (journées de présence / 7). Lignes horizontales : moyenne (trait plein), min/max (pointillés).</p>
    </div>
  </section>

  <section>
    <h2>4 · Indicateurs</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Période</th><th>AVQ phys. moy.</th><th>AVQ cogn. moy.</th><th>Nb CSARR</th><th>Nb diag.</th><th>Nb moy. DAS/RHS</th><th>Nb moy. interv./RHS (approx.)</th><th>Nb moy. CSARR/j</th></tr></thead>
        <tbody>{indic_rows}</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>5 · Activité CSARR par intervenant</h2>
    <div class="table-wrap wide">
      <table>
        <thead>
          <tr><th rowspan="2">Intervenant</th><th colspan="{csarr_group_colspan}">Nb réalisations</th><th colspan="{csarr_group_colspan}">Score de réadaptation globale</th><th colspan="{csarr_group_colspan}">Score de réadaptation spécialisée</th></tr>
          <tr>{csarr_year_headers}</tr>
        </thead>
        <tbody>{csarr_comparison_rows}</tbody>
        <tfoot>{csarr_total_row}</tfoot>
      </table>
    </div>
  </section>

  <section>
    <h2>6 · Valorisation</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Période</th><th>Montant BR SÉJOUR (fact.)</th>
        <th>Montant BR estimé PRT</th><th>Écart</th>
        <th>PMCT</th><th>PMST</th><th>PMJT</th></tr></thead>
        <tbody>{valorisation_rows}</tbody>
      </table>
    </div>
    {supplements_section}
    {non_valorises_section}
  </section>

  {palmares_html}

  <footer class="note">Sources : RHS groupé, VID-HOSP, VisualValoSéjours.</footer>
</div>
"""

ANNEXE_TEMPLATE = """<div class="viz-root">
  <header class="top">
    <h1>Tableaux de bord SMR — Annexe</h1>
    <p class="subtitle">{period_subtitle}</p>
    <p>
      Document <b>séparé du tableau de bord principal</b> (choix délibéré) : dédié à l'identification
      d'erreurs et d'incohérences dans les données transmises, pas à la lecture d'activité. À consulter en
      complément du TDB, pas à sa place.
    </p>
  </header>

  <section>
    <h2>1 · Incohérences VID-HOSP / RHS</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>N° admin séjour</th><th>N° sécu</th><th>VID-HOSP entrée</th><th>VID-HOSP sortie</th><th>Dernière semaine RHS</th><th>Type</th></tr></thead>
        <tbody>{incoherences_rows}</tbody>
      </table>
    </div>
    <div class="callout warn"><span class="ico">i</span><div>Séjours pour lesquels le RHS groupé continue d'être transmis plusieurs semaines après la date de sortie déclarée en VID-HOSP (signe d'un dossier PMSI non clôturé), ou dont aucun enregistrement VID-HOSP n'existe du tout. Un écart de quelques jours pour un séjour encore en cours (date de sortie provisoire de fin de mois) n'est pas signalé ici — seuls les écarts de plus de 3 semaines le sont.</div></div>
  </section>

  <section>
    <h2>2 · Contenu séjours en erreur</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Période</th><th>Nb séjours en erreur</th><th>Nb RHS en erreur</th><th>Nb diag (dans séjours en erreur)</th><th>Nb CSARR (dans séjours en erreur)</th><th>Nb CSAR (dans séjours en erreur)</th></tr></thead>
        <tbody>{erreurs_activite_rows}</tbody>
      </table>
    </div>
    <div class="callout warn"><span class="ico">i</span><div>Décompte des actes/diagnostics portés par des séjours en erreur de groupage bloquante (<code>indicateur_erreur</code> rempli). Pourquoi le TDB les garde quand même dans ses totaux d'activité : voir le Guide TDB (bouton "Guide TDB" du tableau de bord principal), section 5 « Choix délibéré ».</div></div>
  </section>
</div>
"""


def render_journal(data: dict) -> str:
    """Troisième document, séparé du TDB et de l'annexe (demande utilisateur
    2026-07-30) : le détail technique complet de chaque note du TDB (dates de
    validation, sources, méthodologie, limites) — pour le debug, pas pour la
    lecture d'activité. Même numérotation que les notes du TDB (chaque note
    "détails ↗" du TDB pointe vers l'ancre #note-N correspondante ici). Le
    contenu des notes est statique (indépendant des données de l'établissement),
    donc identique d'un FINESS à l'autre — généré par FINESS uniquement pour
    rester à côté du TDB/annexe qu'il documente (sous-titre période incluse)."""
    notes = NoteCollector()
    _populate_notes(notes)
    body = JOURNAL_TEMPLATE.format(
        period_subtitle=_period_subtitle(data["finess"], data["periods"]),
        journal_items=notes.render_journal(),
    )
    return _wrap_page("PMSI-SMR — Journal (détails techniques)", body)


JOURNAL_TEMPLATE = """<div class="viz-root">
  <header class="top">
    <h1>Tableaux de bord SMR — Journal</h1>
    <p class="subtitle">{period_subtitle}</p>
    <p>
      Troisième document, <b>séparé du TDB et de l'annexe</b> : le détail complet de chaque note du
      tableau de bord (dates de validation, sources, méthodologie, limites connues) — pour le debug, pas
      pour la lecture d'activité. Même numérotation que les notes du TDB.
    </p>
  </header>

  <section>
    <h2>Détails des notes</h2>
    <ol class="notes-list">{journal_items}</ol>
  </section>
</div>
"""


AXIS_CHAMP = {
    "uf": "numero_unite_medicale",
    "type_hospitalisation": "type_hospitalisation",
}

AXIS_TITLE = {
    "uf": "UF",
    "type_hospitalisation": "type d'hospitalisation",
}


def generate_axis_reports(
    finess: str,
    years: list[str] | None,
    axis: str,
    mois_fin: int | None = None,
    groupes: dict[str, list[str]] | None = None,
    selection: list[str] | None = None,
    signalisation_couleur: bool = False,
    apparence: dict | None = None,
) -> list[dict]:
    """TDB secondaire (2026-08-04, décision utilisateur) : PAS une section
    résumé en plus du TDB principal, mais un TDB COMPLET (sections 1-9,
    mêmes gabarits que render()) par valeur de l'axe choisi — un par UF, ou
    un par type d'hospitalisation (HC/HTP). `axis` = "uf" ou
    "type_hospitalisation" (clés d'AXIS_CHAMP).

    `groupes` (optionnel, uniquement pour axis == "uf", 2026-08-06) :
    regroupement de plusieurs UF en un "service" défini par l'UTILISATEUR
    (nom de groupe -> liste de codes UF), saisi côté page tdb-choix.html et
    persisté en localStorage — jamais codé en dur ici, la notion de
    "service" n'existe pas dans le PMSI. Pour chaque groupe, un seul TDB
    complet est généré (axis_filter sur la liste d'UF, IN (...) — voir
    tableau_de_bord._period_filter) avec le nom du groupe comme libellé.

    `selection` (optionnel, uniquement pour axis == "uf", 2026-08-25) :
    liste explicite de codes UF (non regroupées) pour lesquelles générer un
    TDB individuel — les cases à cocher de tdb-choix.html servent aussi de
    FILTRE, pas seulement à composer un groupe.

    Dès qu'au moins un groupe est défini OU qu'une sélection explicite est
    fournie (même vide) pour cet établissement (2026-08-25, décision
    utilisateur) : SEULS les groupes et les UF listées dans `selection`
    génèrent un TDB — toute UF ni groupée ni sélectionnée n'en génère plus
    du tout. Si ni groupe ni sélection ne sont fournis (paramètres absents/
    None), comportement historique inchangé : chaque UF génère son propre
    TDB individuel.

    Limites assumées (voir docstrings de tableau_de_bord.section_patients et
    section_valorisation) : la section Patients restreint aux séjours ayant
    ≥1 semaine RHS dans le filtre (proxy, VID-HOSP n'a pas cette notion), et
    `montant_br_tot` (montant officiel ATIH, non ventilable par séjour) est
    absent — seul `montant_br_pt` (notre calcul prorata) est reproraté par
    axe. Rubrique nouvelle, non issue d'un tableau ATIH de référence.

    `mois_fin` (optionnel, 1-12, 2026-08-05) : voir
    tableau_de_bord.compute_reporting_periods."""
    from src.viz.tableau_de_bord import build, compute_reporting_periods, connect, valeurs_axe

    if axis not in AXIS_CHAMP:
        raise ValueError(f"axe inconnu : {axis!r} (attendu : {list(AXIS_CHAMP)})")
    champ = AXIS_CHAMP[axis]

    # Connexion partagée sur toute la boucle par valeur d'axe ci-dessous
    # (2026-08-25, correctif de performance) : plusieurs helpers de
    # valorisation.py mettent en cache leur résultat par IDENTITÉ de
    # connexion (voir _rhs_presence_days_by_sejour) — une connexion par
    # appel à build() (comportement précédent) invalidait ce cache à chaque
    # UF et recalculait tout depuis zéro pour chacune.
    conn = connect()
    periods = compute_reporting_periods(conn, finess, years, mois_fin)
    values = valeurs_axe(conn, periods, finess, champ)

    from src.viz.tableau_de_bord import TYPE_HOSPITALISATION_LABELS

    labels = TYPE_HOSPITALISATION_LABELS if axis == "type_hospitalisation" else {}

    GENERATED_DIR = OUT_DIR / "generated"
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "-".join(years) if years else "toutes"
    if mois_fin:
        suffix += f"-M{mois_fin:02d}"

    entries: list[tuple[str, str, str | list[str]]] = []  # (slug_base, libelle, valeur_filtre)
    groupees: set[str] = set()
    a_un_filtre = axis == "uf" and (bool(groupes) or selection is not None)
    if axis == "uf" and groupes:
        for nom_groupe, ufs in groupes.items():
            ufs_valides = [u for u in ufs if u in values]
            if not ufs_valides:
                continue
            groupees.update(ufs_valides)
            entries.append((nom_groupe, nom_groupe, ufs_valides))
    if a_un_filtre:
        selection_set = set(selection or [])
        for value in values:
            if value in groupees or value not in selection_set:
                continue
            label = labels.get(value, value)
            entries.append((value, label, value))
    else:
        for value in values:
            if value in groupees:
                continue
            label = labels.get(value, value)
            entries.append((value, label, value))

    reports = []
    for slug_base, label, valeur_filtre in entries:
        data = build(finess, years, axis_filter=(champ, valeur_filtre), mois_fin=mois_fin, conn=conn)
        if not data["years"]:
            continue
        html = render(
            data,
            axis_label=f"{AXIS_TITLE[axis]} {label}",
            signalisation_couleur=signalisation_couleur,
            apparence=apparence,
        )
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", slug_base)
        path = GENERATED_DIR / f"tableau_de_bord_{finess}_{suffix}_{axis}-{slug}.html"
        path.write_text(html, encoding="utf-8")
        reports.append({"value": slug_base, "libelle": label, "url": f"/generated/{path.name}"})
    conn.close()
    return reports


def main(finess: str | None = None, years: list[str] | None = None) -> None:
    import sys

    from src.viz.tableau_de_bord import connect, list_finess

    if finess is None:
        finess = sys.argv[1] if len(sys.argv) > 1 else None
    if finess is None:
        conn = connect()
        finess = list_finess(conn)[0]
        conn.close()

    data = build(finess, years)
    html = render(data)
    out_path = OUT_DIR / f"tableau_de_bord_{finess}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Écrit : {out_path}")

    annexe_html = render_annexe(data)
    annexe_path = OUT_DIR / f"annexe_{finess}.html"
    annexe_path.write_text(annexe_html, encoding="utf-8")
    print(f"Écrit : {annexe_path}")

    journal_html = render_journal(data)
    journal_path = OUT_DIR / f"journal_{finess}.html"
    journal_path.write_text(journal_html, encoding="utf-8")
    print(f"Écrit : {journal_path}")


if __name__ == "__main__":
    main()
