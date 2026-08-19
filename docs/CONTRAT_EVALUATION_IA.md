# Contrat d'évaluation IA comparative

## Objet

Ce contrat encadre le premier classement IA comparatif. La proposition IA reste
consultative : elle ne remplace ni les filtres mécaniques, ni le classement
manuel, ni une décision utilisateur, et ne constitue jamais une candidature.

La capture 2 (15 opportunités couvrant 17 identifiants) est seulement le
benchmark actuel. Le code doit lire le numéro de capture, les comptes, les
identifiants et les versions depuis les artefacts, sans jamais les coder en dur.

## Invariants de sécurité

- Ouvrir SQLite avec `mode=ro` et `PRAGMA query_only=ON` ; ne modifier aucune
  table d'offres, filtres, trajets ou doublons.
- Laisser `KEEP`, `REVIEW` et `EXCLUDE` sous l'autorité exclusive des filtres
  mécaniques.
- Conserver le classement manuel comme référence locale immuable. Seul le
  comparateur peut le lire, après fermeture et validation complète de
  l'exécution IA.
- Ne transmettre à l'évaluateur aucun classement, priorité ou motif manuel.
- Ne jamais stocker la proposition IA comme verdict mécanique, manuel ou final.
- Imposer `scope: "specific_offer_only"` à chaque résultat. `out_of_scope`
  exclut l'offre précise, jamais automatiquement son secteur.
- Évaluer chaque opportunité isolément : aucune offre ne doit influencer le
  classement d'une autre.
- Exclure secrets, `.env`, identifiants administratifs et données personnelles
  inutiles. Les artefacts privés restent sous `data/`, donc hors Git.

## Profil IA minimisé

Le futur `data/profil_evaluation_ia.json` est dérivé du profil validé et contient
seulement : compétences avec contexte de preuve, expériences généralisées,
diplômes et formations, langues, limites techniques, préférences, critères
métier et informations manquantes utiles au classement.

Il ne contient aucun nom personnel ou d'entreprise, chiffre d'affaires,
clientèle identifiable, contact, identifiant administratif ou détail inutile.
Une aptitude informatique personnelle ne peut pas devenir une expérience
professionnelle spécialisée.

### `ai_evaluation_profile` v1

```json
{
  "schema_version": 1,
  "artifact_type": "ai_evaluation_profile",
  "source": {
    "validation_date": "<date>",
    "source_artifact_sha256": "<sha256>"
  },
  "manual_review": {
    "status": "pending",
    "reviewed_at_utc": null,
    "approved_for_evaluation": false,
    "approved_for_external_evaluation": false,
    "privacy_checks": {}
  },
  "evaluation_profile": {
    "skills": [],
    "generalized_experiences": [],
    "education": [],
    "languages": [],
    "technical_boundaries": [],
    "preferences": {},
    "decision_criteria": {},
    "unknowns": []
  },
  "integrity": {"evaluation_profile_sha256": "<sha256>"}
}
```

`manual_review.status` accepte uniquement `pending` ou `approved`. La
préparation échoue tant que le statut n'est pas `approved`, que
`approved_for_evaluation` n'est pas vrai, qu'un contrôle de confidentialité
n'est pas réussi ou que le hash du profil source a changé. La validation
automatique ne remplace pas la relecture humaine du contenu minimisé.

Un adaptateur cloud refuse en plus toute exécution lorsque
`approved_for_external_evaluation` n'est pas vrai. Un adaptateur entièrement
local n'exige pas cette autorisation externe, mais exige toujours la relecture
humaine, le statut `approved` et `approved_for_evaluation: true`.

## Données d'offres

### Liste blanche

- Identifiant source, titre et description nettoyée.
- Employeur public ou caractère anonyme, taille et secteur.
- Contrat, temps de travail, horaires et indicateurs nuit, décalé, week-end,
  samedi et dimanche.
- Salaire mensuel brut normalisé, libellé nettoyé et compléments structurés.
- Zone publique de travail, bande, durée et distance de trajet calculées.
- Déplacements, expérience, qualification, compétences, formations,
  permis/habilitations et qualités demandés.
- Statut mécanique `KEEP` ou `REVIEW`, motifs de revue, avertissements et
  pénalité horaire.
- Groupe de quasi-doublons et représentant déjà enregistrés.

Les textes libres retirent courriels, téléphones, URL de candidature, noms de
contacts et instructions de candidature. Une valeur absente signifie « non
renseigné », jamais « compétence absente ».

### Liste noire

- Identifiants SQLite internes, latitude, longitude et origine personnelle du
  trajet.
- URL source, URL de candidature, `raw_offer_json` et réponses brutes de
  fournisseur.
- Secrets, jetons, clés, contenu ou chemin de `.env`.
- Classement, priorité ou justification manuelle.
- Statut de candidature, score arbitraire ou `final_verdict`.
- Toute donnée extérieure à la liste blanche.

## Entrée IA

### `ai_comparative_input` v1

```json
{
  "schema_version": 1,
  "artifact_type": "ai_comparative_input",
  "provenance": {
    "capture_id": "<lu>",
    "capture_source_sha256": "<sha256>",
    "filter_rules_version": "<version>",
    "duplicate_detection_version": "<version>"
  },
  "policy": {
    "policy_version": "comparative-classification-v1",
    "classification_definitions": {},
    "guardrails": []
  },
  "profile": {
    "profile_schema_version": 1,
    "profile_payload_sha256": "<sha256>",
    "snapshot": {}
  },
  "selection": {
    "eligible_mechanical_statuses": ["KEEP", "REVIEW"],
    "duplicate_policy": "stored_representative_only",
    "opportunity_count": "<calculé>",
    "covered_offer_id_count": "<calculé>"
  },
  "opportunities": [],
  "integrity": {
    "policy_payload_sha256": "<sha256>",
    "profile_payload_sha256": "<sha256>",
    "opportunities_payload_sha256": "<sha256>",
    "input_payload_sha256": "<sha256>"
  }
}
```

La préparation sélectionne `KEEP` et `REVIEW`, puis les représentants stockés
des quasi-doublons. Elle calcule les comptes depuis les données. Elle ne possède
aucun argument permettant de lire le jeu manuel.

### Clé canonique

```text
"offers:" + "|".join(sorted(unique(offer_ids)))
```

Exemples : `offers:211QPQZ` et
`offers:5201825|5589373|5684878`. Une clé lisible choisie manuellement n'est pas
une clé technique.

## Catégories validées

- `credible` — candidature crédible immédiatement : le socle essentiel du
  poste précis est déjà exercé et aucun écart majeur ne bloque une candidature
  immédiate.
- `audacious` — candidature audacieuse mais défendable : des correspondances
  établies et compétences transférables permettent une candidature immédiate
  malgré des écarts significatifs à expliquer et vérifier.
- `evolution` — piste d'évolution : le poste précis n'est pas accessible
  immédiatement, mais un socle exercé fournit une passerelle crédible après
  formation ciblée ou expérience intermédiaire réelle.
- `out_of_scope` — hors cible pour l'offre précise : incompatibilité avec les
  critères validés ou expertise technique, sectorielle ou principalement
  manuelle déjà requise et non compensable par une simple formation.

Une formation ou une VAE ne peut pas effacer une absence totale d'expérience
technique spécialisée. L'ouverture à un secteur reste indépendante du résultat
d'une offre précise.

## Exécution et sortie IA

L'exécuteur traite une opportunité à la fois avec le même profil, la même
politique et les mêmes paramètres. Il peut reprendre seulement les résultats
partiels manquants ou invalides. Ces résultats de travail ne sont ni finaux, ni
comparables au jeu manuel.

La finalisation exige toutes les opportunités attendues, uniques, valides et
liées au même hash d'entrée. Elle crée ensuite un nouvel artefact en mode
exclusif, sans écraser ni compléter un fichier final existant.

### `ai_opportunity_evaluation` v1

```json
{
  "schema_version": 1,
  "artifact_type": "ai_opportunity_evaluation",
  "run": {
    "run_id": "<uuid>",
    "executed_at_utc": "<date UTC>",
    "execution_mode": "<cloud|local|hybrid>",
    "provider": "<renseigné à l'exécution>",
    "model": "<renseigné à l'exécution>",
    "parameters": {},
    "policy_version": "<version>",
    "evaluation_instruction_sha256": "<sha256>"
  },
  "inputs": {
    "capture_id": "<valeur d'entrée>",
    "capture_source_sha256": "<sha256>",
    "input_payload_sha256": "<sha256>",
    "policy_payload_sha256": "<sha256>",
    "profile_payload_sha256": "<sha256>",
    "opportunities_payload_sha256": "<sha256>"
  },
  "results": [],
  "integrity": {"results_payload_sha256": "<sha256>"}
}
```

Chaque résultat contient `opportunity_key`, les `offer_ids` triés,
`scope: "specific_offer_only"`, `classification_code`, les faits utilisés et
leurs références vers l'entrée, les correspondances établies, compétences
transférables, obstacles, écarts compensables, informations manquantes et une
justification. La V1 ne produit ni score, ni probabilité, ni classement relatif
entre opportunités.

## Comparateur déterministe

Le comparateur est seul autorisé à ouvrir le jeu manuel, après validation et
fermeture du fichier IA final. Il apparie par clé canonique, exige une couverture
identique et échoue avant calcul si une clé manque, est supplémentaire ou
dupliquée.

### `ai_manual_comparison` v1

```json
{
  "schema_version": 1,
  "artifact_type": "ai_manual_comparison",
  "inputs": {
    "manual_artifact_sha256": "<sha256>",
    "ai_artifact_sha256": "<sha256>",
    "capture_id": "<valeur commune>"
  },
  "coverage": {},
  "exact_agreement": {},
  "confusion_matrix": {},
  "per_category": {},
  "disagreements": [],
  "limitations": []
}
```

Métriques descriptives :

- accord exact sous la forme `nombre identique / total`, puis pourcentage ;
- matrice de confusion, lignes manuelles et colonnes IA, dans l'ordre
  `credible`, `audacious`, `evolution`, `out_of_scope` ;
- par catégorie, support manuel, nombre prédit, vrais/faux positifs, faux
  négatifs, précision, rappel et F1 seulement lorsque calculables ;
- liste des désaccords avec codes, justifications et revue humaine requise.

Le benchmark actuel ne compte que 15 opportunités et aucun exemple manuel
`credible`. Le rappel et le F1 de cette catégorie sont donc non calculables, et
sa capacité de détection ne peut pas être évaluée. Aucun score composite, note
sur 100, macro/micro-F1 global ou classement général de modèles ne doit être
produit sur ce petit jeu.

## Composants et commandes prévus

1. `app/ai_contract.py` — versions, validations, canonicalisation et hashes.
2. `app/prepare_ai_input.py` — profil, lecture seule de SQLite et entrée.
3. `app/run_ai_evaluation.py` — exécution isolée, reprise et finalisation.
4. `app/compare_ai_evaluations.py` — accès tardif au manuel et comparaison.

```powershell
python app/prepare_ai_input.py build --database <database> `
  --capture-id <capture_id> --profile <approved_profile> --output-dir <inputs>

python app/run_ai_evaluation.py --input <input.json> `
  --adapter <future_adapter> --work-dir <partials> --output-dir <final_runs>

python app/compare_ai_evaluations.py --manual <manual.json> `
  --ai <closed_ai_run.json> --output-dir <comparisons>
```

Les comptes, identifiants et versions sont lus dans les artefacts ; ces
commandes restent valables pour les captures suivantes.

## Indépendance du fournisseur

La préparation et le comparateur n'importent aucun SDK de modèle et ne lisent
aucune clé. L'exécuteur communique avec un adaptateur futur via une interface
minimale `evaluate(opportunity_payload) -> result`. API cloud, modèle local ou
approche hybride pourront ainsi être testés sans modifier contrats, sélection
ou métriques. Aucun fournisseur ni modèle n'est choisi ici.
