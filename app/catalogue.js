// Catalogue des variables proposables dans le constructeur de TDB, par table source.
// Chaque dimension référence soit une colonne SQL directe ("col"), soit une fonction "derive(row)"
// calculée côté JS. Une dimension avec "libCol"/"libDerive" a une variante libellé disponible :
// l'utilisateur choisit alors, dans l'interface, le mode Code / Libellé / Code — Libellé.

const SOURCES = {
  rhs: {
    label: "RHS groupé",
    short: "RHS",
    table: "rhs_groupe r",
    // Exclusion 680000973/M1C+M1B/2026 (2026-08-24, même correctif que
    // _period_filter dans src/viz/tableau_de_bord.py — voir sa docstring) :
    // bug de transmission WEB100T confirmé, lignes M1C/M1B résiduelles non
    // reconnues par ATIH pour cet établissement en 2026 uniquement (M1C
    // reste le format légitime 2023-2025, ne pas exclure ces années-là).
    sql: `SELECT r.*, gme.libelle_long AS lib_gme, gn.libelle_long AS lib_gn,
                 cm.libelle_long AS lib_cm,
                 err.libelle AS lib_erreur, err.type AS type_erreur,
                 dp.libelle_complet AS lib_dp, ae.libelle_complet AS lib_ae
          FROM rhs_groupe r
          LEFT JOIN nomenclature_gme gme ON gme.code = r.code_gme AND gme.kind = 'GME'
          LEFT JOIN nomenclature_gme gn ON gn.code = substr(r.code_gme,1,4) AND gn.kind = 'GN'
          LEFT JOIN nomenclature_gme cm ON cm.code = substr(r.code_gme,1,2) AND cm.kind = 'CM'
          LEFT JOIN nomenclature_gme_erreurs err
                 ON err.code = CASE WHEN r.code_retour_groupage GLOB '[0-9]*'
                                     THEN CAST(CAST(r.code_retour_groupage AS INTEGER) AS TEXT)
                                     ELSE r.code_retour_groupage END
          LEFT JOIN nomenclature_diagnostics dp ON dp.code = r.manifestation_morbide_principale
          LEFT JOIN nomenclature_diagnostics ae ON ae.code = r.affection_etiologique
          WHERE r.finess_epmsi IN (%FINESS%) AND (%PERIOD%)
                AND NOT (r.finess_epmsi = '680000973' AND r.version_format_rhs_groupe IN ('M1C', 'M1B')
                         AND substr(r.numero_semaine,3,4) = '2026')`,
    periodKind: "semaine", // filtre par numero_semaine (semaine ISO + année)
    dims: [
      { id: "finess", label: "Établissement (FINESS)", col: "finess_epmsi" },
      { id: "nda", label: "N° Dossier administratif (NDA)", col: "numero_admin_sejour" },
      { id: "sexe", label: "Sexe", col: "sexe" },
      { id: "type_hosp", label: "Type hospitalisation (HC/HP)", col: "type_hospitalisation" },
      { id: "annee_periode", label: "Année (période sélectionnée)", derive: r => r._periode_annee },
      // sortKey en AAAASS (année puis semaine, ex. 202405) : numero_semaine est stocké SSAAAA
      // (semaine puis année) — trier dessus tel quel mélangerait les années (toutes les "S05" de
      // chaque année se retrouveraient groupées avant les "S12", quelle que soit l'année).
      { id: "semaine", label: "Semaine RHS (identifie la ligne)", derive: r => r.numero_semaine ? `S${r.numero_semaine.slice(0, 2)}-${r.numero_semaine.slice(2, 6)}` : null, sortKey: r => r.numero_semaine ? Number(r.numero_semaine.slice(2, 6) + r.numero_semaine.slice(0, 2)) : null },
      { id: "gme", label: "GME", col: "code_gme", libCol: "lib_gme" },
      // Hiérarchie GME (nomenclature_gme, plate CM->GN->GR->GL->GME) : CM et GN restent le code
      // cumulé (troncature du code GME, longueurs fixes CM=2, GN=4 — cf. gme.schema.json), avec
      // libellé résolu par jointure sur nomenclature_gme. GR/GL/Sévérité, en revanche, ne sont PAS
      // les codes cumulés (5/6/7 caractères) mais le seul CARACTÈRE ajouté à ce niveau (le "type"
      // GR ex. S/T/U, le "type" GL ex. A/B/C, le chiffre de sévérité ex. 0/1/2) — comparable d'un GN
      // à l'autre, contrairement au code cumulé qui inclut le GN et n'est donc jamais le même d'un
      // groupe à l'autre. Pas de libellé possible : la nomenclature ATIH ne référence que les codes
      // cumulés complets, pas ces caractères isolés.
      { id: "cm", label: "CM (catégorie majeure)", derive: r => (r.code_gme || "").substring(0, 2), libCol: "lib_cm" },
      { id: "gn", label: "GN (groupe nosologique)", derive: r => (r.code_gme || "").substring(0, 4), libCol: "lib_gn" },
      { id: "gr", label: "Type GR", derive: r => (r.code_gme || "").charAt(4) || null },
      { id: "gl", label: "GL", derive: r => (r.code_gme || "").charAt(5) || null },
      { id: "severite", label: "Sévérité (GME)", derive: r => (r.code_gme || "").charAt(6) || null },
      { id: "erreur", label: "Erreur de groupage", col: "code_retour_groupage",
        libDerive: r => r.lib_erreur || (r.code_retour_groupage === "0" || r.code_retour_groupage === "000" ? "Aucune" : null) },
      { id: "erreur_type", label: "Erreur de groupage (bloquant/non)", col: "type_erreur" },
      // MMP + AE = "morbidité principale" (MP) au sens du guide de production PMSI-SMR.
      { id: "dp", label: "Manifestation morbide principale (MMP)", col: "manifestation_morbide_principale", libCol: "lib_dp" },
      { id: "dp_chapitre", label: "Chapitre CIM-10 (MMP)", derive: r => { const n = diagAncestorOfKind(r.manifestation_morbide_principale, "chapter"); return n ? n.code : null; },
        libDerive: r => { const n = diagAncestorOfKind(r.manifestation_morbide_principale, "chapter"); return n ? n.libelle : null; } },
      { id: "dp_bloc", label: "Bloc/sous-chapitre CIM-10 (MMP)", derive: r => { const n = diagAncestorOfKind(r.manifestation_morbide_principale, "block"); return n ? n.code : null; },
        libDerive: r => { const n = diagAncestorOfKind(r.manifestation_morbide_principale, "block"); return n ? n.libelle : null; } },
      { id: "ae", label: "Affection étiologique (AE)", col: "affection_etiologique", libCol: "lib_ae" },
      { id: "ae_chapitre", label: "Chapitre CIM-10 (AE)", derive: r => { const n = diagAncestorOfKind(r.affection_etiologique, "chapter"); return n ? n.code : null; },
        libDerive: r => { const n = diagAncestorOfKind(r.affection_etiologique, "chapter"); return n ? n.libelle : null; } },
      { id: "ae_bloc", label: "Bloc/sous-chapitre CIM-10 (AE)", derive: r => { const n = diagAncestorOfKind(r.affection_etiologique, "block"); return n ? n.code : null; },
        libDerive: r => { const n = diagAncestorOfKind(r.affection_etiologique, "block"); return n ? n.libelle : null; } },
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
    short: "VID-HOSP",
    table: "vid_hosp v",
    sql: `SELECT v.* FROM vid_hosp v WHERE v.finess_epmsi IN (%FINESS%) AND (%PERIOD%)`,
    periodKind: "dates", // filtre par chevauchement [date_entree, date_sortie]
    dims: [
      { id: "finess", label: "Établissement (FINESS)", col: "finess_epmsi" },
      { id: "nda", label: "N° Dossier administratif (NDA)", col: "numero_admin_sejour" },
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
    short: "Valo",
    table: "valorisation_sejour va",
    // Séjours non valorisables (nv_chain/nv_attente_dts/nv_nonfactam, mêmes 3
    // anomalies que EXCLUSION_MONTANT_OFFICIEL côté TDB, src/viz/valorisation.py)
    // exclus ICI, directement dans la source — PAS via un filtre global
    // cross-fichier (décision utilisateur 2026-08-21, "exclure dès le début").
    // Un filtre global cross-fichier a été essayé puis retiré : son index par
    // séjour est reconstruit PAR PÉRIODE (cf. buildForeignIndex), donc un
    // séjour valorisé sous une AUTRE campagne que celle affichée (ex. séjour
    // à cheval sur deux ans) n'avait aucune ligne candidate dans l'index de la
    // période courante — le filtre l'excluait alors même que "Oui" ET "Non"
    // étaient tous deux cochés, faisant disparaître à tort des lignes RHS/VID-
    // HOSP de séjours par ailleurs parfaitement valides (constaté empiriquement
    // 2026-08-21 : 97 lignes RHS 680000973/2026 disparaissaient ainsi). Exclure
    // directement ici, dans la table SOURCE, ne touche que les lignes Valo
    // elles-mêmes et ne peut plus jamais fausser un comptage RHS/VID-HOSP.
    sql: `SELECT va.*, cm.libelle_long AS lib_cm
          FROM valorisation_sejour va
          LEFT JOIN nomenclature_gme cm ON cm.code = substr(va.code_gme,1,2) AND cm.kind = 'CM'
          WHERE va.finess_epmsi IN (%FINESS%) AND (%PERIOD%)
                AND COALESCE(va.nv_chain,0) = 0 AND COALESCE(va.nv_attente_dts,0) = 0
                AND COALESCE(va.nv_nonfactam,0) = 0`,
    periodKind: "campagne", // filtre par colonne campagne = année
    dims: [
      { id: "finess", label: "Établissement (FINESS)", col: "finess_epmsi" },
      { id: "nda", label: "N° Dossier administratif (NDA)", col: "numero_admin_sejour" },
      { id: "type_hosp", label: "Type hospitalisation (HC/HP)", col: "type_hospitalisation" },
      { id: "campagne", label: "Année (campagne)", col: "campagne" },
      { id: "type_um", label: "Type d'UM", col: "type_um" },
      { id: "mode_entree", label: "Mode d'entrée", col: "mode_entree" },
      { id: "mode_sortie", label: "Mode de sortie", col: "mode_sortie" },
      { id: "type_suite", label: "Type de suite (séjour)", col: "type_suite" },
      { id: "cas_30j", label: "Cas < 30 jours", col: "cas_30j" },
      { id: "gme", label: "GME", col: "code_gme", libCol: "libelle_gme" },
      { id: "cm", label: "CM (catégorie majeure)", derive: r => (r.code_gme || "").substring(0, 2), libCol: "lib_cm" },
      { id: "gn", label: "GN", col: "code_gn", libCol: "libelle_gn" },
      // Type GR/GL/Sévérité = le seul caractère ajouté à ce niveau (comparable d'un GN à l'autre),
      // pas le code cumulé — même principe que côté RHS (voir le commentaire équivalent plus haut).
      // "niveau_lourdeur" (déjà présent dans le fichier Valo) EST le type GL : même valeur, vérifié
      // (ex. code_gme "0145JA0" -> niveau_lourdeur "A" = le 6e caractère) — pas de dérivation propre
      // à refaire, c'est directement la bonne colonne.
      { id: "gr", label: "Type GR", derive: r => (r.code_gr || "").slice(-1) || null },
      { id: "gl", label: "GL", col: "niveau_lourdeur" },
      { id: "severite", label: "Sévérité (GME)", derive: r => (r.code_gme || "").charAt(6) || null },
      { id: "niveau_lourdeur", label: "Niveau de lourdeur (GR)", col: "niveau_lourdeur" },
      { id: "code_gmt", label: "Code GMT", col: "code_gmt" },
      { id: "code_gmth", label: "Code GMTH (> 90j)", col: "code_gmth" },
      { id: "zone_valorisation", label: "Zone de valorisation", col: "zone_valorisation" },
    ],
    measures: [
      { id: "nb_lignes", label: "Nombre de lignes de valorisation", derive: r => 1 },
      { id: "nb_sejours", label: "Nombre de séjours (distincts)", distinctKey: r => r.finess_epmsi + "|" + r.numero_admin_sejour },
      { id: "montant_br_tot", label: "Montant brut total (€)", col: "montant_br_tot", numeric: true },
      // montant_br_sej = montant_br_gmt + montant_br_gmth SEUL, sans aucun
      // supplément (transport, molécules onéreuses, cancérologie) — colonne
      // calculée (GENERATED ALWAYS AS, cf. src/storage/valorisation_store.py),
      // à utiliser pour tout calcul de prix par journée/séjour/semaine dans
      // ce requêteur plutôt que montant_br_tot, qui reste pollué par ces
      // suppléments (décision utilisateur 2026-08-21, cf. TDB simple section 6).
      { id: "montant_br_sej", label: "Montant BR séjour (hors suppléments) (€)", col: "montant_br_sej", numeric: true },
      { id: "montant_br_trans", label: "Montant transport (BR) (€)", col: "montant_br_trans", numeric: true },
      { id: "montant_br_supp_cancero", label: "Montant supplément cancérologie (BR) (€)", col: "montant_br_supp_cancero", numeric: true },
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
      { id: "montant_am_med", label: "Montant molécules onéreuses (AM) (€)", col: "montant_am_med", numeric: true },
      { id: "montant_am_trans", label: "Montant transport (AM) (€)", col: "montant_am_trans", numeric: true },
    ],
  },

  // Les 4 sources suivantes donnent accès au détail des actes/diagnostics associés
  // (une ligne = une occurrence, ex. un acte CSARR précis), rattachés à leur RHS parent
  // (finess, séjour, semaine). Elles permettent de ventiler par établissement/année et de
  // compter le nombre d'occurrences (contrairement à rhs.nb_das/nb_csarr/... qui ne donnent
  // qu'un total par RHS, sans détail par code ou par intervenant).
  das: {
    label: "Diagnostics associés (DAS)",
    short: "DAS",
    table: "rhs_groupe_das d",
    sql: `SELECT d.*, r.finess_epmsi, r.numero_admin_sejour, r.numero_semaine, r.type_hospitalisation,
                 dp.libelle_complet AS lib_das
          FROM rhs_groupe_das d
          JOIN rhs_groupe r ON r.id = d.parent_id
          LEFT JOIN nomenclature_diagnostics dp ON dp.code = d.code_das
          WHERE r.finess_epmsi IN (%FINESS%) AND (%PERIOD%)`,
    periodKind: "semaine",
    dims: [
      { id: "finess", label: "Établissement (FINESS)", col: "finess_epmsi" },
      { id: "nda", label: "N° Dossier administratif (NDA)", col: "numero_admin_sejour" },
      { id: "annee_periode", label: "Année (période sélectionnée)", derive: r => r._periode_annee },
      // sortKey en AAAASS (année puis semaine, ex. 202405) : numero_semaine est stocké SSAAAA
      // (semaine puis année) — trier dessus tel quel mélangerait les années (toutes les "S05" de
      // chaque année se retrouveraient groupées avant les "S12", quelle que soit l'année).
      { id: "semaine", label: "Semaine RHS (identifie la ligne)", derive: r => r.numero_semaine ? `S${r.numero_semaine.slice(0, 2)}-${r.numero_semaine.slice(2, 6)}` : null, sortKey: r => r.numero_semaine ? Number(r.numero_semaine.slice(2, 6) + r.numero_semaine.slice(0, 2)) : null },
      { id: "type_hosp", label: "Type hospitalisation (HC/HP)", col: "type_hospitalisation" },
      { id: "code_das", label: "Diagnostic associé (DAS)", col: "code_das", libCol: "lib_das" },
      { id: "das_chapitre", label: "Chapitre CIM-10 (DAS)", derive: r => { const n = diagAncestorOfKind(r.code_das, "chapter"); return n ? n.code : null; },
        libDerive: r => { const n = diagAncestorOfKind(r.code_das, "chapter"); return n ? n.libelle : null; } },
      { id: "das_bloc", label: "Bloc/sous-chapitre CIM-10 (DAS)", derive: r => { const n = diagAncestorOfKind(r.code_das, "block"); return n ? n.code : null; },
        libDerive: r => { const n = diagAncestorOfKind(r.code_das, "block"); return n ? n.libelle : null; } },
    ],
    measures: [
      { id: "nb_das", label: "Nombre de DAS", derive: r => 1 },
    ],
  },

  csarr: {
    label: "Actes CSARR",
    short: "CSARR",
    table: "rhs_groupe_csarr c",
    sql: `SELECT c.*, r.finess_epmsi, r.numero_admin_sejour, r.numero_semaine, r.type_hospitalisation,
                 nom.libelle AS lib_csarr, interv.libelle AS lib_intervenant,
                 chap.code AS code_csarr_chap, chap.libelle AS lib_csarr_chap,
                 sschap.code AS code_csarr_sschap, sschap.libelle AS lib_csarr_sschap
          FROM rhs_groupe_csarr c
          JOIN rhs_groupe r ON r.id = c.parent_id
          LEFT JOIN nomenclature_csarr nom ON nom.code = c.code_principal
          LEFT JOIN nomenclature_csarr_intervenants interv ON interv.code = c.code_intervenant
          LEFT JOIN nomenclature_csarr_hierarchie chap ON chap.code = substr(nom.parent_code,1,2) AND chap.kind = 'chapitre'
          LEFT JOIN nomenclature_csarr_hierarchie sschap ON sschap.code = substr(nom.parent_code,1,5) AND sschap.kind = 'sous_chapitre'
          WHERE r.finess_epmsi IN (%FINESS%) AND (%PERIOD%)`,
    periodKind: "semaine",
    dims: [
      { id: "finess", label: "Établissement (FINESS)", col: "finess_epmsi" },
      { id: "nda", label: "N° Dossier administratif (NDA)", col: "numero_admin_sejour" },
      { id: "annee_periode", label: "Année (période sélectionnée)", derive: r => r._periode_annee },
      // sortKey en AAAASS (année puis semaine, ex. 202405) : numero_semaine est stocké SSAAAA
      // (semaine puis année) — trier dessus tel quel mélangerait les années (toutes les "S05" de
      // chaque année se retrouveraient groupées avant les "S12", quelle que soit l'année).
      { id: "semaine", label: "Semaine RHS (identifie la ligne)", derive: r => r.numero_semaine ? `S${r.numero_semaine.slice(0, 2)}-${r.numero_semaine.slice(2, 6)}` : null, sortKey: r => r.numero_semaine ? Number(r.numero_semaine.slice(2, 6) + r.numero_semaine.slice(0, 2)) : null },
      { id: "type_hosp", label: "Type hospitalisation (HC/HP)", col: "type_hospitalisation" },
      { id: "code_csarr", label: "Acte CSARR (code principal)", col: "code_principal", libCol: "lib_csarr" },
      // Hiérarchie CSARR (nomenclature_csarr_hierarchie, codes pointés "07.01.01…") : le chapitre/
      // sous-chapitre est une troncature du CodeHier de classement de l'acte (nom.parent_code),
      // fiable quelle que soit sa profondeur réelle (2 à 4 niveaux) puisque tout code commence par
      // le chapitre (2 car.) puis ".XX" pour le sous-chapitre (5 car.) — cf. csarr_hierarchie.schema.json.
      { id: "csarr_chapitre", label: "Chapitre CSARR", col: "code_csarr_chap", libCol: "lib_csarr_chap" },
      { id: "csarr_sous_chapitre", label: "Sous-chapitre CSARR", col: "code_csarr_sschap", libCol: "lib_csarr_sschap" },
      { id: "intervenant", label: "Type d'intervenant", col: "code_intervenant", libCol: "lib_intervenant" },
    ],
    measures: [
      { id: "nb_csarr", label: "Nombre d'actes CSARR", derive: r => 1 },
      { id: "nb_realisations", label: "Nombre de réalisations (cumulé)", col: "nombre_realisations", numeric: true },
    ],
  },

  csar: {
    label: "Actes CSAR",
    short: "CSAR",
    table: "rhs_groupe_csar c",
    sql: `SELECT c.*, r.finess_epmsi, r.numero_admin_sejour, r.numero_semaine, r.type_hospitalisation,
                 nom.libelle AS lib_csar, interv.libelle AS lib_intervenant
          FROM rhs_groupe_csar c
          JOIN rhs_groupe r ON r.id = c.parent_id
          LEFT JOIN nomenclature_csar nom ON nom.code = c.code_principal
          LEFT JOIN nomenclature_csar_intervenants interv ON interv.code = c.code_intervenant
          WHERE r.finess_epmsi IN (%FINESS%) AND (%PERIOD%)`,
    periodKind: "semaine",
    dims: [
      { id: "finess", label: "Établissement (FINESS)", col: "finess_epmsi" },
      { id: "nda", label: "N° Dossier administratif (NDA)", col: "numero_admin_sejour" },
      { id: "annee_periode", label: "Année (période sélectionnée)", derive: r => r._periode_annee },
      // sortKey en AAAASS (année puis semaine, ex. 202405) : numero_semaine est stocké SSAAAA
      // (semaine puis année) — trier dessus tel quel mélangerait les années (toutes les "S05" de
      // chaque année se retrouveraient groupées avant les "S12", quelle que soit l'année).
      { id: "semaine", label: "Semaine RHS (identifie la ligne)", derive: r => r.numero_semaine ? `S${r.numero_semaine.slice(0, 2)}-${r.numero_semaine.slice(2, 6)}` : null, sortKey: r => r.numero_semaine ? Number(r.numero_semaine.slice(2, 6) + r.numero_semaine.slice(0, 2)) : null },
      { id: "type_hosp", label: "Type hospitalisation (HC/HP)", col: "type_hospitalisation" },
      { id: "code_csar", label: "Acte CSAR (code principal)", col: "code_principal", libCol: "lib_csar" },
      { id: "intervenant", label: "Type d'intervenant", col: "code_intervenant", libCol: "lib_intervenant" },
    ],
    measures: [
      { id: "nb_csar", label: "Nombre d'actes CSAR", derive: r => 1 },
      { id: "nb_realisations", label: "Nombre de réalisations (cumulé)", col: "nombre_realisations", numeric: true },
    ],
  },

  ccam: {
    label: "Actes CCAM",
    short: "CCAM",
    table: "rhs_groupe_ccam k",
    sql: `SELECT k.*, r.finess_epmsi, r.numero_admin_sejour, r.numero_semaine, r.type_hospitalisation,
                 nom.libelle AS lib_ccam
          FROM rhs_groupe_ccam k
          JOIN rhs_groupe r ON r.id = k.parent_id
          LEFT JOIN nomenclature_ccam nom ON nom.code = k.code_ccam
          WHERE r.finess_epmsi IN (%FINESS%) AND (%PERIOD%)`,
    periodKind: "semaine",
    dims: [
      { id: "finess", label: "Établissement (FINESS)", col: "finess_epmsi" },
      { id: "nda", label: "N° Dossier administratif (NDA)", col: "numero_admin_sejour" },
      { id: "annee_periode", label: "Année (période sélectionnée)", derive: r => r._periode_annee },
      // sortKey en AAAASS (année puis semaine, ex. 202405) : numero_semaine est stocké SSAAAA
      // (semaine puis année) — trier dessus tel quel mélangerait les années (toutes les "S05" de
      // chaque année se retrouveraient groupées avant les "S12", quelle que soit l'année).
      { id: "semaine", label: "Semaine RHS (identifie la ligne)", derive: r => r.numero_semaine ? `S${r.numero_semaine.slice(0, 2)}-${r.numero_semaine.slice(2, 6)}` : null, sortKey: r => r.numero_semaine ? Number(r.numero_semaine.slice(2, 6) + r.numero_semaine.slice(0, 2)) : null },
      { id: "type_hosp", label: "Type hospitalisation (HC/HP)", col: "type_hospitalisation" },
      { id: "code_ccam", label: "Acte CCAM (code)", col: "code_ccam", libCol: "lib_ccam" },
      { id: "code_activite", label: "Code activité", col: "code_activite" },
    ],
    measures: [
      { id: "nb_ccam", label: "Nombre d'actes CCAM", derive: r => 1 },
      { id: "nb_realisations", label: "Nombre de réalisations (cumulé)", col: "nombre_realisations", numeric: true },
    ],
  },
};

// Ordre d'affichage des sources dans les sélecteurs de variables (lignes/colonnes).
const SOURCE_ORDER = ["rhs", "vidhosp", "valo", "das", "csarr", "csar", "ccam"];

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
