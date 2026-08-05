"""Génère app/tableau_de_bord.html à partir des agrégats de tableau_de_bord.build().

Reprend la structure du tableau de bord PMSI de référence (fourni par
l'utilisateur, FINESS [etablissement anonymise]) : sections 1 (Patients), 2 (Séjours),
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
        "Score pondéré = pondérations ATIH par acte, majorées selon le modulateur de lieu — PAS le score "
        "RR/GR officiel. Score / journée et Score / séjour = moyenne à l'échelle de l'établissement, pas "
        "la charge individuelle d'un professionnel.",
        "Le score utilise <code>ponderation_patient</code> (nomenclature ATIH <code>ACTES_ponderations</code>) "
        "majoré par le modulateur de LIEU (HW/LJ/XH/L3), individuel ou collectif selon "
        "<code>nombre_reel_patients</code>, quand applicable. N'intègre pas le filtrage par liste d'actes "
        "spécialisés par GN ni les autres règles de groupage du score RR/GR officiel. Pour les codes dont "
        "la pondération a changé dans le temps, la valeur la PLUS RÉCENTE est utilisée pour toutes les "
        "années (choix délibéré, cohérent avec le reste du projet) — un score recalculé avec le barème "
        "actuel peut donc différer d'un score RR historique réel.",
    )
    m["valorisation"] = notes.add(
        "warn",
        "Montant BR TOT (fact.) = figure officielle ATIH déjà facturée. Montant BR estimé PRT = "
        "reconstitution prorata temporis + estimation des séjours en cours. PMCT/PMST/PMJT restent basés "
        "sur le seul prorata temporis RÉEL (pas l'estimation), pour rester un tarif moyen observé.",
        "<b>PMCT</b> = Montant BR PRT réel / Nb SSR. <b>PMST</b> = Montant BR PRT réel / Nb RHS. "
        "<b>PMJT</b> = Montant BR PRT réel / Nb journées de présence — ces 3 ratios utilisent le montant "
        "PROUVÉ (sans l'estimation des séjours en cours, voir note suivante), pour rester un tarif moyen "
        "réellement observé plutôt qu'un chiffre qui inclurait sa propre estimation.",
    )
    m["valorisation_non_fact"] = notes.add(
        "warn",
        "(fact.) = facturé : figure officielle ATIH (arrêté de versement), qui exclut déjà les séjours "
        "en anomalie (chaînage, en attente de droits, non facturable à l'AM).",
        "<b>Montant BR TOT (fact.)</b> = <code>montant_br_tot</code> officiel ATIH, sommé par CAMPAGNE "
        "(année de transmission), en excluant les séjours marqués <code>nv_chain</code> (chaînage), "
        "<code>nv_attente_dts</code> (en attente de droits) ou <code>nv_nonfactam</code> (non facturable "
        "à l'Assurance Maladie) — voir <code>EXCLUSION_MONTANT_OFFICIEL</code> dans "
        "<code>src/viz/valorisation.py</code>. Ces 3 exclusions ont été trouvées empiriquement (2026-08-05) "
        "en reproduisant EXACTEMENT au centime près deux totaux d'un tableau ATIH externe fourni par "
        "l'utilisateur ([etablissement anonymise] et [etablissement anonymise], campagne 2026), puis confirmées sur les 2 autres "
        "établissements. D'autres variables NV_* du fichier VisualValoSejours existent (nv_cm90, "
        "nv_nonclos, nv_pie, nv_varano, nv_article51, nv_telereadapt, nv_evcepr, nv_gmt9999, "
        "nv_horsperiode) mais n'ont montré aucune contribution sur ces cas de test — non exclues, faute "
        "de preuve empirique.",
    )
    m["estimation_en_cours"] = notes.add(
        "warn",
        "ESSAI : Montant BR PRT (prorata temporis réel) + une estimation de la recette des séjours "
        "&lt;90j non clos sans anomalie connue, au tarif moyen déjà observé (PMJT) — à titre indicatif, "
        "pas une donnée ATIH. Écart = Montant BR TOT (fact.) − Montant BR estimé PRT.",
        "<b>Montant BR PRT</b> (pro rata temporis, calcul \"maison\") = somme des valeurs journalières "
        "réparties uniformément sur les jours de présence RHS réels d'un séjour déjà facturé (voir "
        "<code>src/viz/valorisation.py</code>), agrégées par ANNÉE CIVILE RÉELLE des jours dont le jour "
        "tombe dans la période. <b>+ estimation</b> : pour les séjours actifs sur la période sans AUCUN "
        "<code>montant_br_tot</code> connu (donc &lt;90j, pas encore clos — le financement SMR ne se "
        "déclenche qu'à la clôture ou au seuil de 90j) ET sans anomalie <code>nv_chain</code>/"
        "<code>nv_attente_dts</code>/<code>nv_nonfactam</code> (voir "
        "<code>sejours_non_factures_sans_anomalie</code>) — distinction trouvée nécessaire en creusant un "
        "écart signalé par l'utilisateur : sur [etablissement anonymise]/2026, 18 des 20 séjours \"jamais facturés\" "
        "étaient en fait marqués <code>nv_chain</code>, pas de simples séjours en attente. Le montant "
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
        "utile si un séjour est re-groupé d'une semaine à l'autre. Valorisation = <code>montant_br_tot</code> "
        "(hors transport), avec le même filtre de comparabilité campagne/semaine limite que la section 6 "
        "(Montant BR TOT) — pour un séjour à cheval sur plusieurs semaines de la période, la valorisation "
        "est rattachée au code de sa dernière semaine, pas répartie code par code au prorata.",
    )
    m["structure_gme"] = notes.add(
        "warn",
        "Type de rééducation (GR), niveau de dépendance (GL) et sévérité, TOUTES CM/GN confondues (pas un "
        "top N). Sévérité : 0 = HTP, 1 = HC sans sévérité, 2 = HC avec sévérité.",
        "Même méthode d'attribution séjour→code et même filtre de comparabilité valorisation que les "
        "palmarès CM/GN. La ligne \"Erreur de groupage\" regroupe les séjours dont le type GR n'est pas "
        "reconnu (ex. <code>9096ZZ0</code>, code_gme placeholder d'un séjour en erreur de groupage "
        "bloquante) — comptés à part dans les 3 blocs plutôt que classés à tort sous une vraie catégorie "
        "(ex. sévérité \"0\", qui a par ailleurs un sens réel pour les vrais séjours HTP).",
    )
    return m


def render(data: dict, axis_label: str | None = None) -> str:
    """`axis_label` (optionnel, ex. "UF 3001" ou "type d'hospitalisation
    Hospitalisation complète (HC)", 2026-08-04) : ajouté au sous-titre et au
    titre de la page quand ce TDB est un TDB secondaire (un par valeur d'axe,
    voir generate_axis_reports()) plutôt que le TDB principal non filtré."""
    years = data["years"]
    periods_by_year = {p["year"]: p for p in data["periods"]}
    notes = NoteCollector()

    # ---------- section 1 : patients ----------
    patients_rows = ""
    for y in years:
        p = data["patients"].get(y)
        if not p:
            continue
        patients_rows += (
            f"<tr><td>{periods_by_year[y]['label']}</td>"
            f"<td>{fmt_int(p['f'])}</td><td>{fmt_int(p['m'])}</td><td><b>{fmt_int(p['total'])}</b></td>"
            f"<td>{fmt(p['pct_f'], 1, ' %')}</td><td>{fmt(p['pct_m'], 1, ' %')}</td><td><b>100,0 %</b></td>"
            f"<td>{fmt(p['age_f'])}</td><td>{fmt(p['age_m'])}</td><td><b>{fmt(p['age_total'])}</b></td></tr>"
        )

    # ---------- section 2 : séjours ----------
    sejours_rows = ""
    for y in years:
        s = data["sejours"][y]
        sejours_rows += (
            f"<tr><td>{periods_by_year[y]['label']}</td><td>{fmt_int(s['nb_ssr'])}</td><td>{fmt_int(s['nb_rhs'])}</td>"
            f"<td>{fmt_int(s['nb_journees'])}</td><td>{fmt(s['dmh'], 2)}</td>"
            f"<td>{fmt(s['nb_lits_moy'], 1)}</td><td>{fmt(s['exh'], 2, ' %')}</td></tr>"
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
        ref_lines_svg += (
            f'<line x1="{pad_l:.1f}" y1="{ry:.1f}" x2="{chart_w - pad_r + 4:.1f}" y2="{ry:.1f}" '
            f'stroke="var(--muted)" stroke-width="1" opacity="0.5"'
            f'{f" stroke-dasharray=\"{dash}\"" if dash else ""} />'
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
        indic_rows += (
            f"<tr><td>{periods_by_year[y]['label']}</td><td>{fmt(i['avq_phys_moy'])}</td><td>{fmt(i['avq_cogn_moy'])}</td>"
            f"<td>{fmt_int(i['nb_csarr'])}</td><td>{fmt_int(i['nb_diag_approx'])}</td>"
            f"<td>{fmt(i['nb_das_moy_rhs'])}</td><td>{fmt(i['nb_moy_interv_rhs'])}</td>"
            f"<td>{fmt(i['nb_moy_csarr_j'], 2)}</td></tr>"
        )

    # ---------- section 5 : activité CSARR — comparaison par intervenant ----------
    # Restructuré (2026-07-30, demande utilisateur) : au lieu d'un classement
    # séparé par année (rangs/visibilité différents d'une année à l'autre,
    # difficile à comparer), UNE table par intervenant avec ses 3 années
    # côte à côte. "Nb réalisations" reste un COMPTE BRUT (validé exact contre
    # ATIH, ne pas toucher). Les moyennes /jour et /séjour, elles, sont basées
    # sur le SCORE PONDÉRÉ (ponderation_patient × modulateur de lieu éligible,
    # cf. section_ponderation_csarr) et non plus sur le compte brut — choix
    # explicite de l'utilisateur (2026-07-30) après clarification : ces
    # moyennes doivent refléter la pondération ATIH, pas juste un décompte
    # d'actes. Ce sont des moyennes à l'échelle de l'ÉTABLISSEMENT (score de
    # cet intervenant / nb journées ou séjours TOTAUX de la période) — pas la
    # charge individuelle d'un professionnel, faute de savoir quels jours il
    # a personnellement travaillé.
    intervenant_labels: dict[str, str] = {}
    n_by_code_year: dict[str, dict[str, int]] = {}
    for y in years:
        for r in data["activite_csarr"][y]:
            intervenant_labels[r["code"]] = r["label"]
            n_by_code_year.setdefault(r["code"], {})[y] = r["n"]
    score_by_code_year = data["ponderation_csarr"]

    codes_sorted = sorted(
        intervenant_labels,
        key=lambda c: sum(n_by_code_year[c].values()),
        reverse=True,
    )

    def csarr_cell(code: str, y: str) -> tuple[str, str, str, str]:
        n = n_by_code_year.get(code, {}).get(y)
        if n is None:
            return "—", "—", "—", "—"
        score = score_by_code_year.get(y, {}).get(code, 0.0)
        sej = data["sejours"][y]
        moy_jour = score / sej["nb_journees"] if sej["nb_journees"] else None
        moy_sejour = score / sej["nb_ssr"] if sej["nb_ssr"] else None
        return fmt_int(n), fmt_int(round(score)), fmt(moy_jour, 2), fmt(moy_sejour, 2)

    csarr_comparison_rows = ""
    for code in codes_sorted:
        # Regroupé PAR MÉTRIQUE (toutes les années sous "Nb réalisations",
        # puis toutes sous "Score pondéré", etc.) pour matcher l'en-tête à
        # colonnes groupées — comparer les années entre elles doit se lire
        # sans sauter d'une métrique à l'autre.
        per_year = [csarr_cell(code, y) for y in years]
        n_cells = [c[0] for c in per_year]
        score_cells = [c[1] for c in per_year]
        j_cells = [c[2] for c in per_year]
        s_cells = [c[3] for c in per_year]
        cells = "".join(f"<td>{v}</td>" for v in n_cells + score_cells + j_cells + s_cells)
        csarr_comparison_rows += f"<tr><td>{code} - {intervenant_labels[code]}</td>{cells}</tr>"

    # Ligne de total (tous intervenants confondus), en pied de table.
    csarr_total_cells = []
    for y in years:
        n_tot = sum(n_by_code_year[c].get(y, 0) for c in codes_sorted)
        score_tot = sum(score_by_code_year.get(y, {}).values())
        sej = data["sejours"][y]
        moy_jour_tot = score_tot / sej["nb_journees"] if sej["nb_journees"] else None
        moy_sejour_tot = score_tot / sej["nb_ssr"] if sej["nb_ssr"] else None
        csarr_total_cells.append((fmt_int(n_tot), fmt_int(round(score_tot)), fmt(moy_jour_tot, 2), fmt(moy_sejour_tot, 2)))
    csarr_total_row = "".join(
        f"<td>{v}</td>"
        for group in range(4)
        for v in (csarr_total_cells[i][group] for i in range(len(years)))
    )
    csarr_total_row = f"<tr><td>Total</td>{csarr_total_row}</tr>"

    # ---------- section 6 : valorisation ----------
    valorisation_rows = ""
    for y in years:
        v = data["valorisation"][y]
        estim = v["estimation_en_cours"]
        estim_cell = fmt(v["montant_br_pt_avec_estimation"], 2, " €")
        if estim and estim["nb_sejours"]:
            estim_cell += f" <small>({fmt_int(estim['nb_sejours'])} séj., {fmt_int(estim['nb_journees'])} j)</small>"
        ecart = (
            v["montant_br_tot"] - v["montant_br_pt_avec_estimation"]
            if v["montant_br_tot"] is not None
            else None
        )
        valorisation_rows += (
            f"<tr><td>{periods_by_year[y]['label']}</td>"
            f"<td>{fmt(v['montant_br_tot'], 2, ' €')}</td>"
            f"<td>{estim_cell}</td>"
            f"<td>{fmt(ecart, 2, ' €')}</td>"
            f"<td>{fmt(v['pmct'], 2, ' €')}</td>"
            f"<td>{fmt(v['pmst'], 2, ' €')}</td>"
            f"<td>{fmt(v['pmjt'], 2, ' €')}</td></tr>"
        )

    # ---------- sections 7-8 : palmarès CM / GN ----------
    # Section 9 "Palmarès GME" retirée (demande utilisateur 2026-08-03) :
    # jugée peu apporter par rapport à CM/GN et risque de surcharger le TDB.
    def _cell2(value: str, pct: float) -> str:
        # Valeur + % sur 2 lignes (demande utilisateur 2026-08-03) plutôt que
        # "valeur (pct %)" sur une seule ligne : permet une police plus
        # grande dans les sections 7-9 (classe CSS .palmares, cf.
        # STYLE_BLOCK) tout en tenant dans la largeur de colonne.
        return f'<td>{value}<br><span class="pct">({fmt(pct, 1, " %")})</span></td>'

    def _palmares_section(numero: int, titre: str, palmares: dict, note_ref: str) -> str:
        rows_html = ""
        for row in palmares["rows"]:
            cells = ""
            for y in years:
                d = row["data"].get(y)
                if not d:
                    cells += "<td>—</td><td>—</td>"
                    continue
                cells += _cell2(fmt_int(d["effectif"]), d["pct_effectif"])
                cells += _cell2(fmt(d["valorisation"], 2, " €"), d["pct_valorisation"])
            rows_html += f"<tr><td>{row['code']} — {row['libelle']}</td>{cells}</tr>"
        year_headers = "".join(f"<th>{periods_by_year[y]['label']}</th>" for y in years)
        return (
            f'<section>\n    <h2>{numero} · {titre}{note_ref}</h2>\n'
            '    <div class="table-wrap wide palmares">\n      <table>\n        <thead>\n'
            f'          <tr><th rowspan="2">Code — Libellé</th>'
            + "".join(f'<th colspan="2">{periods_by_year[y]["label"]}</th>' for y in years)
            + "</tr>\n"
            f'          <tr>{"<th>Effectif</th><th>Valorisation</th>" * len(years)}</tr>\n'
            f"        </thead>\n        <tbody>{rows_html}</tbody>\n      </table>\n    </div>\n  </section>"
        )

    # ---------- section 9 : structure GME (GR / GL / Sévérité, concaténées) ----------
    def _structure_section(numero: int, structure: dict, note_ref: str) -> str:
        def block_rows(bloc: dict) -> str:
            html = f'<tr class="group-row"><td colspan="{1 + 2 * len(years)}"><b>{bloc["titre"]}</b></td></tr>'
            for row in bloc["rows"]:
                cells = ""
                for y in years:
                    d = row["data"][y]
                    cells += _cell2(fmt_int(d["effectif"]), d["pct_effectif"])
                    cells += _cell2(fmt(d["valorisation"], 2, " €"), d["pct_valorisation"])
                label = f"<b>{row['libelle']}</b>" if row["code"] is None else f"{row['code']} — {row['libelle']}"
                html += f"<tr><td>{label}</td>{cells}</tr>"
            return html

        rows_html = block_rows(structure["gr"]) + block_rows(structure["gl"]) + block_rows(structure["sev"])
        return (
            f'<section>\n    <h2>{numero} · Structure de groupage (GR / GL / Sévérité){note_ref}</h2>\n'
            '    <div class="table-wrap wide palmares">\n      <table>\n        <thead>\n'
            f'          <tr><th rowspan="2">Catégorie</th>'
            + "".join(f'<th colspan="2">{periods_by_year[y]["label"]}</th>' for y in years)
            + "</tr>\n"
            f'          <tr>{"<th>Effectif</th><th>Valorisation</th>" * len(years)}</tr>\n'
            f"        </thead>\n        <tbody>{rows_html}</tbody>\n      </table>\n    </div>\n  </section>"
        )

    # ---------- notes (renvoyées en fin de TDB, numérotées dans l'ordre des sections) ----------
    nm = _populate_notes(notes)
    note1, note2 = nm["patients"], nm["sejours"]
    note3, note4 = nm["indic_ok"], nm["indic_warn"]
    note5, note6, note7 = nm["activite_ok"], nm["activite_choix"], nm["activite_score"]
    note8 = nm["valorisation"]
    note11 = nm["valorisation_non_fact"]
    note_estim = nm["estimation_en_cours"]
    note9 = nm["palmares"]
    note10 = nm["structure_gme"]
    notes_section = notes.render(data["finess"])

    palmares_html = "\n\n  ".join([
        _palmares_section(7, "Palmarès CM", data["palmares_cm"], note9),
        _palmares_section(8, "Palmarès GN", data["palmares_gn"], note9),
        _structure_section(9, data["structure_gme"], note10),
    ])

    subtitle = _period_subtitle(data["finess"], data["periods"])
    if axis_label:
        subtitle += f" · {axis_label}"

    body = HTML_TEMPLATE.format(
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
        csarr_year_headers="".join(f"<th>{y}</th>" for y in years) * 4,
        csarr_group_colspan=len(years),
        valorisation_rows=valorisation_rows,
        palmares_html=palmares_html,
        note1=note1, note2=note2, note3=note3, note4=note4,
        note5=note5, note6=note6, note7=note7, note8=note8, note9=note9, note10=note10, note11=note11,
        note_estim=note_estim,
        notes_section=notes_section,
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
  table tfoot td, table tfoot th { font-weight: 700; border-top: 2.5px solid var(--ink); border-bottom: none; }
  .table-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 4px 6px; }
  table tr.group-row td { background: var(--grid); text-align: left; font-size: 12px; }
  table td .pct { display: block; font-size: 0.82em; color: var(--muted); margin-top: 1px; }

  .legend { display: flex; gap: 14px; font-size: 12px; color: var(--ink-2); margin: 0 0 6px; }
  .legend .key { display: inline-flex; align-items: center; gap: 6px; }


  .callout { display: flex; gap: 10px; align-items: flex-start; border-radius: 10px; padding: 12px 14px; font-size: 12.5px; margin-top: 10px; }
  .callout.warn { background: color-mix(in srgb, var(--warn) 14%, var(--surface)); border: 1px solid color-mix(in srgb, var(--warn) 40%, var(--border)); }
  .callout.ok { background: color-mix(in srgb, var(--vid) 12%, var(--surface)); border: 1px solid color-mix(in srgb, var(--vid) 35%, var(--border)); }
  .callout .ico { flex: none; width: 18px; height: 18px; border-radius: 50%; font-weight: 700; font-size: 12px; display: flex; align-items: center; justify-content: center; }
  .callout.warn .ico { background: var(--warn); color: var(--warn-ink); }
  .callout.ok .ico { background: var(--vid); color: #fff; }

  footer.note { margin-top: 26px; font-size: 11.5px; color: var(--muted); border-top: 1px solid var(--grid); padding-top: 12px; }
  footer.note ul { margin: 6px 0 0; padding-left: 18px; }

  /* Renvois de note (superscripts à côté des titres de section) et la
     liste de notes numérotées en fin de TDB qu'ils pointent vers. */
  .note-ref { font-size: 10px; margin-left: 3px; vertical-align: super; }
  .note-ref a {
    display: inline-block; min-width: 14px; padding: 0 3px; text-align: center;
    background: var(--rhs); color: #fff; border-radius: 6px; font-weight: 700;
    text-decoration: none; line-height: 15px;
  }
  section.notes > h2 { background: color-mix(in srgb, var(--muted) 14%, var(--surface)); }
  .notes-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
  .notes-list li { scroll-margin-top: 16px; }
  .notes-list li:target { outline: 2px solid var(--rhs); outline-offset: 2px; border-radius: 10px; }
  .note-back { margin-left: 6px; color: var(--muted); text-decoration: none; font-weight: 700; }
  /* Notes = contenu facultatif à l'impression (demande utilisateur
     2026-07-30) : démarre sur une nouvelle page pour rester détachable —
     qui imprime peut s'arrêter avant sans rien couper au milieu. */
  @media print {
    section.notes { break-before: page; page-break-before: always; }
  }
"""

HTML_TEMPLATE = """<div class="viz-root">
  <header class="top">
    <h1>Tableaux de bord SMR</h1>
    <p class="subtitle">{period_subtitle}</p>
  </header>

  <section>
    <h2>1 · Patients{note1}</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Période</th><th>F</th><th>M</th><th>Total</th><th>% F</th><th>% M</th><th>% Total</th><th>Âge moy. F</th><th>Âge moy. M</th><th>Âge moy. Total</th></tr></thead>
        <tbody>{patients_rows}</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>2 · Séjours{note2}</h2>
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
    <h2>4 · Indicateurs{note3}{note4}</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Période</th><th>AVQ phys. moy.</th><th>AVQ cogn. moy.</th><th>Nb CSARR</th><th>Nb diag.</th><th>Nb moy. DAS/RHS</th><th>Nb moy. interv./RHS (approx.)</th><th>Nb moy. CSARR/j</th></tr></thead>
        <tbody>{indic_rows}</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>5 · Activité CSARR par intervenant{note5}{note6}{note7}</h2>
    <div class="table-wrap wide">
      <table>
        <thead>
          <tr><th rowspan="2">Intervenant</th><th colspan="{csarr_group_colspan}">Nb réalisations</th><th colspan="{csarr_group_colspan}">Score pondéré</th><th colspan="{csarr_group_colspan}">Score / journée présence</th><th colspan="{csarr_group_colspan}">Score / séjour</th></tr>
          <tr>{csarr_year_headers}</tr>
        </thead>
        <tbody>{csarr_comparison_rows}</tbody>
        <tfoot>{csarr_total_row}</tfoot>
      </table>
    </div>
  </section>

  <section>
    <h2>6 · Valorisation{note8}</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Période</th><th>Montant BR TOT (fact.){note11}</th>
        <th>Montant BR estimé PRT{note_estim}</th><th>Écart</th>
        <th>PMCT</th><th>PMST</th><th>PMJT</th></tr></thead>
        <tbody>{valorisation_rows}</tbody>
      </table>
    </div>
  </section>

  {palmares_html}

  {notes_section}

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
    <div class="callout warn"><span class="ico">i</span><div>Décompte des actes/diagnostics portés par des séjours en erreur de groupage bloquante (<code>indicateur_erreur</code> rempli). Pourquoi le TDB les garde quand même dans ses totaux d'activité : voir la note "Choix délibéré" (section 5) du tableau de bord principal.</div></div>
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
    finess: str, years: list[str] | None, axis: str, mois_fin: int | None = None
) -> list[dict]:
    """TDB secondaire (2026-08-04, décision utilisateur) : PAS une section
    résumé en plus du TDB principal, mais un TDB COMPLET (sections 1-9,
    mêmes gabarits que render()) par valeur de l'axe choisi — un par UF, ou
    un par type d'hospitalisation (HC/HTP). `axis` = "uf" ou
    "type_hospitalisation" (clés d'AXIS_CHAMP).

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

    conn = connect()
    periods = compute_reporting_periods(conn, finess, years, mois_fin)
    values = valeurs_axe(conn, periods, finess, champ)
    conn.close()

    from src.viz.tableau_de_bord import TYPE_HOSPITALISATION_LABELS

    labels = TYPE_HOSPITALISATION_LABELS if axis == "type_hospitalisation" else {}

    GENERATED_DIR = OUT_DIR / "generated"
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "-".join(years) if years else "toutes"
    if mois_fin:
        suffix += f"-M{mois_fin:02d}"

    reports = []
    for value in values:
        label = labels.get(value, value)
        data = build(finess, years, axis_filter=(champ, value), mois_fin=mois_fin)
        if not data["years"]:
            continue
        html = render(data, axis_label=f"{AXIS_TITLE[axis]} {label}")
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", value)
        path = GENERATED_DIR / f"tableau_de_bord_{finess}_{suffix}_{axis}-{slug}.html"
        path.write_text(html, encoding="utf-8")
        reports.append({"value": value, "libelle": label, "url": f"/generated/{path.name}"})
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
