// Catalogue des variables proposables dans le constructeur de TDB, par table source.
// Chaque dimension référence soit une colonne SQL directe ("col"), soit une fonction "derive(row)"
// calculée côté JS. Une dimension avec "libCol"/"libDerive" a une variante libellé disponible :
// l'utilisateur choisit alors, dans l'interface, le mode Code / Libellé / Code — Libellé.

const SOURCES = {
  rhs: {
    label: "RHS groupé",
    table: "rhs_groupe r",
    sql: `SELECT r.*, gme.libelle_long AS lib_gme, gn.libelle_long AS lib_gn,
                 err.libelle AS lib_erreur, err.type AS type_erreur,
                 dp.libelle_complet AS lib_dp, ae.libelle_complet AS lib_ae
          FROM rhs_groupe r
          LEFT JOIN nomenclature_gme gme ON gme.code = r.code_gme AND gme.kind = 'GME'
          LEFT JOIN nomenclature_gme gn ON gn.code = substr(r.code_gme,1,4) AND gn.kind = 'GN'
          LEFT JOIN nomenclature_gme_erreurs err
                 ON err.code = CASE WHEN r.code_retour_groupage GLOB '[0-9]*'
                                     THEN CAST(CAST(r.code_retour_groupage AS INTEGER) AS TEXT)
                                     ELSE r.code_retour_groupage END
          LEFT JOIN nomenclature_diagnostics dp ON dp.code = r.manifestation_morbide_principale
          LEFT JOIN nomenclature_diagnostics ae ON ae.code = r.affection_etiologique
          WHERE r.finess_epmsi IN (%FINESS%) AND (%PERIOD%)`,
    periodKind: "semaine", // filtre par numero_semaine (semaine ISO + année)
    dims: [
      { id: "finess", label: "Établissement (FINESS)", col: "finess_epmsi" },
      { id: "sexe", label: "Sexe", col: "sexe" },
      { id: "type_hosp", label: "Type hospitalisation (HC/HP)", col: "type_hospitalisation" },
      { id: "annee_periode", label: "Année (période sélectionnée)", derive: r => r._periode_annee },
      { id: "gme", label: "GME", col: "code_gme", libCol: "lib_gme" },
      { id: "gn", label: "GN (groupe nosologique)", derive: r => (r.code_gme || "").substring(0, 4), libCol: "lib_gn" },
      { id: "erreur", label: "Erreur de groupage", col: "code_retour_groupage",
        libDerive: r => r.lib_erreur || (r.code_retour_groupage === "0" || r.code_retour_groupage === "000" ? "Aucune" : null) },
      { id: "erreur_type", label: "Erreur de groupage (bloquant/non)", col: "type_erreur" },
      { id: "dp", label: "Diagnostic principal", col: "manifestation_morbide_principale", libCol: "lib_dp" },
      { id: "ae", label: "Affection étiologique", col: "affection_etiologique", libCol: "lib_ae" },
      { id: "mode_entree_um", label: "Mode d'entrée UM", col: "mode_entree_um" },
      { id: "provenance", label: "Provenance", col: "provenance" },
      { id: "mode_sortie", label: "Mode de sortie", col: "mode_sortie" },
      { id: "destination", label: "Destination", col: "destination" },
      { id: "unite_medicale", label: "Unité médicale", col: "numero_unite_medicale" },
      { id: "type_autorisation_um", label: "Type d'autorisation UM", col: "type_autorisation_um" },
      { id: "type_unite_specifique", label: "Type d'unité spécifique", col: "type_unite_specifique" },
      { id: "lits_dedies", label: "Lits/places dédiés", col: "lits_places_dedies" },
    ],
    measures: [
      { id: "nb_rhs", label: "Nombre de RHS (lignes)", derive: r => 1 },
      { id: "nb_sejours", label: "Nombre de séjours (distincts)", distinctKey: r => r.finess_epmsi + "|" + r.numero_admin_sejour },
      { id: "nb_journees", label: "Nombre de journées présentes", derive: r => (String(r.jours_hors_weekend||"") + String(r.jours_weekend||"")).split("").filter(c => c === "1").length },
      { id: "dep_habillage", label: "Dépendance habillage/toilette (1-4)", col: "dependance_habillage_toilette", numeric: true },
      { id: "dep_deplacement", label: "Dépendance déplacement (1-4)", col: "dependance_deplacement", numeric: true },
      { id: "dep_alimentation", label: "Dépendance alimentation (1-4)", col: "dependance_alimentation", numeric: true },
      { id: "dep_continence", label: "Dépendance continence (1-4)", col: "dependance_continence", numeric: true },
      { id: "dep_comportement", label: "Dépendance comportement (1-4)", col: "dependance_comportement", numeric: true },
      { id: "dep_relation", label: "Dépendance relation (1-4)", col: "dependance_relation", numeric: true },
      { id: "avq_phys", label: "AVQ physique (somme habillage+déplacement+alim.+continence)", numeric: true,
        derive: r => sumNum(r.dependance_habillage_toilette, r.dependance_deplacement, r.dependance_alimentation, r.dependance_continence) },
      { id: "avq_cogn", label: "AVQ cognitif (somme comportement+relation)", numeric: true,
        derive: r => sumNum(r.dependance_comportement, r.dependance_relation) },
      { id: "nb_das", label: "Nombre de diagnostics associés (DAS)", col: "n1_nb_das", numeric: true },
      { id: "nb_csarr", label: "Nombre d'actes CSARR (bloc)", col: "n2_nb_csarr", numeric: true },
      { id: "nb_csar", label: "Nombre d'actes CSAR (bloc)", col: "n3_nb_csar", numeric: true },
      { id: "nb_ccam", label: "Nombre d'actes CCAM (bloc)", col: "n4_nb_ccam", numeric: true },
    ],
  },

  vidhosp: {
    label: "VID-HOSP",
    table: "vid_hosp v",
    sql: `SELECT v.* FROM vid_hosp v WHERE v.finess_epmsi IN (%FINESS%) AND (%PERIOD%)`,
    periodKind: "dates", // filtre par chevauchement [date_entree, date_sortie]
    dims: [
      { id: "finess", label: "Établissement (FINESS)", col: "finess_epmsi" },
      { id: "sexe_b", label: "Sexe (bénéficiaire)", col: "sexe_beneficiaire" },
      { id: "annee_periode", label: "Année (période sélectionnée)", derive: r => r._periode_annee },
      { id: "code_grand_regime", label: "Régime (code grand régime)", col: "code_grand_regime" },
      { id: "nature_assurance", label: "Nature d'assurance", col: "nature_assurance" },
      { id: "type_contrat", label: "Type de contrat", col: "type_contrat" },
      { id: "cmu", label: "Bénéficiaire CMU-C", col: "patient_beneficiaire_cmu" },
      { id: "sejour_facturable", label: "Séjour facturable AM", col: "sejour_facturable_am" },
      { id: "motif_non_fact", label: "Motif de non-facturation AM", col: "motif_non_facturation_am" },
      { id: "tranche_age", label: "Tranche d'âge (à l'entrée)", derive: r => tranche_age(ageAns(r.date_naissance_beneficiaire, r.date_entree)) },
      { id: "etab_transfert", label: "Établissement de transfert", col: "etablissement_transfert" },
      { id: "etab_retour", label: "Établissement de retour", col: "etablissement_retour" },
    ],
    measures: [
      { id: "nb_lignes", label: "Nombre de lignes VID-HOSP", derive: r => 1 },
      { id: "nb_patients", label: "Nombre de patients (distincts, par IPP)", distinctKey: r => r.numero_ipp },
      { id: "age_moyen", label: "Âge (années, à l'entrée)", numeric: true, derive: r => ageAns(r.date_naissance_beneficiaire, r.date_entree) },
      { id: "mnt_tm", label: "Montant ticket modérateur (€)", col: "montant_facturer_tm", numeric: true, scale: 0.01 },
      { id: "mnt_fj", label: "Montant forfait journalier (€)", col: "montant_facturer_fj", numeric: true, scale: 0.01 },
      { id: "mnt_amo", label: "Montant total séjour remboursable AMO (€)", col: "montant_total_sejour_remboursable_amo", numeric: true, scale: 0.01 },
      { id: "mnt_amc", label: "Montant total séjour remboursable AMC (€)", col: "montant_total_sejour_remboursable_amc", numeric: true, scale: 0.01 },
      { id: "mnt_base_remb", label: "Montant base de remboursement (€)", col: "montant_base_remboursement", numeric: true, scale: 0.01 },
      { id: "nb_disciplines", label: "Nombre de disciplines de prestations", col: "nombre_disciplines_prestations", numeric: true },
    ],
  },

  valo: {
    label: "Valorisation",
    table: "valorisation_sejour va",
    sql: `SELECT va.* FROM valorisation_sejour va WHERE va.finess_epmsi IN (%FINESS%) AND (%PERIOD%)`,
    periodKind: "campagne", // filtre par colonne campagne = année
    dims: [
      { id: "finess", label: "Établissement (FINESS)", col: "finess_epmsi" },
      { id: "type_hosp", label: "Type hospitalisation (HC/HP)", col: "type_hospitalisation" },
      { id: "campagne", label: "Année (campagne)", col: "campagne" },
      { id: "type_um", label: "Type d'UM", col: "type_um" },
      { id: "mode_entree", label: "Mode d'entrée", col: "mode_entree" },
      { id: "mode_sortie", label: "Mode de sortie", col: "mode_sortie" },
      { id: "type_suite", label: "Type de suite (séjour)", col: "type_suite" },
      { id: "cas_30j", label: "Cas < 30 jours", col: "cas_30j" },
      { id: "gme", label: "GME", col: "code_gme", libCol: "libelle_gme" },
      { id: "gn", label: "GN", col: "code_gn", libCol: "libelle_gn" },
      { id: "gr", label: "GR", col: "code_gr", libCol: "libelle_gr" },
      { id: "niveau_lourdeur", label: "Niveau de lourdeur (GR)", col: "niveau_lourdeur" },
      { id: "code_gmt", label: "Code GMT", col: "code_gmt" },
      { id: "code_gmth", label: "Code GMTH (> 90j)", col: "code_gmth" },
      { id: "zone_valorisation", label: "Zone de valorisation", col: "zone_valorisation" },
    ],
    measures: [
      { id: "nb_lignes", label: "Nombre de lignes de valorisation", derive: r => 1 },
      { id: "nb_sejours", label: "Nombre de séjours (distincts)", distinctKey: r => r.finess_epmsi + "|" + r.numero_admin_sejour },
      { id: "montant_br_tot", label: "Montant brut total (€)", col: "montant_br_tot", numeric: true },
      { id: "montant_am_tot", label: "Montant Assurance Maladie total (€)", col: "montant_am_tot", numeric: true },
      { id: "montant_br_gmt", label: "Montant brut GMT (≤90j) (€)", col: "montant_br_gmt", numeric: true },
      { id: "montant_br_gmth", label: "Montant brut GMTH (>90j) (€)", col: "montant_br_gmth", numeric: true },
      { id: "nb_jours_gmt", label: "Nb jours valorisés GMT (≤90j)", col: "nb_jours_valorises_gmt", numeric: true },
      { id: "nb_jours_gmth", label: "Nb jours valorisés GMTH (>90j)", col: "nb_jours_valorises_gmth", numeric: true },
      { id: "score_rr", label: "Score RR", col: "score_rr", numeric: true },
      { id: "score_rr_spe", label: "Score RR spécialisé", col: "score_rr_spe", numeric: true },
      { id: "coeff_spe", label: "Coefficient de spécialisation", col: "coeff_spe", numeric: true },
      { id: "nb_supplements", label: "Nombre de suppléments", col: "nb_supplements", numeric: true },
      { id: "reste_a_charge", label: "Reste à charge détenu (€)", col: "reste_a_charge_detenu", numeric: true },
    ],
  },
};

// Fonctions d'agrégation disponibles pour les expressions (mesure + fonction).
const AGG_DEFS = [
  { id: "count", label: "Nombre (count)", short: "Nb" },
  { id: "sum", label: "Somme", short: "Somme" },
  { id: "avg", label: "Moyenne", short: "Moy." },
  { id: "median", label: "Médiane", short: "Méd." },
  { id: "min", label: "Minimum", short: "Min" },
  { id: "max", label: "Maximum", short: "Max" },
  { id: "pct_total", label: "% du total général", short: "% total" },
  { id: "pct_row", label: "% du total ligne", short: "% ligne" },
  { id: "pct_col", label: "% du total colonne", short: "% col." },
];

function sumNum(...vals) {
  let s = 0, any = false;
  for (const v of vals) { const n = Number(v); if (!isNaN(n) && v !== null && v !== undefined && v !== "") { s += n; any = true; } }
  return any ? s : null;
}

function ageAns(dateNaissance, dateRef) {
  if (!dateNaissance || !dateRef) return null;
  const n = new Date(dateNaissance), r = new Date(dateRef);
  if (isNaN(n) || isNaN(r)) return null;
  return (r - n) / (1000 * 60 * 60 * 24 * 365.25);
}

function tranche_age(age) {
  if (age === null || age === undefined || isNaN(age)) return "Inconnu";
  if (age < 18) return "< 18 ans";
  if (age < 45) return "18-44 ans";
  if (age < 65) return "45-64 ans";
  if (age < 75) return "65-74 ans";
  if (age < 85) return "75-84 ans";
  return "85 ans et +";
}
