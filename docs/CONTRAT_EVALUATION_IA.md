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

### Canonicalisation et intégrité

Pour tous les hashes définis par ce contrat, le JSON canonique est encodé en
UTF-8, avec les clés d'objets triées, les caractères Unicode conservés sans
conversion obligatoire en séquences ASCII, l'ordre des tableaux conservé et
des séparateurs JSON compacts. Il ne contient aucun espace ni aucune
indentation non significative.

`input_payload_sha256` est le SHA-256 des octets UTF-8 du JSON canonique de
l'entrée finalisée après retrait du seul champ
`integrity.input_payload_sha256`. Ce champ doit être retiré de l'objet avant la
canonicalisation ; il ne doit être remplacé ni par `null`, ni par une chaîne
vide, ni par une valeur temporaire. Tous les autres champs présents dans
l'entrée finalisée participent au calcul, notamment `schema_version`,
`artifact_type`, la provenance, la politique, le profil, la sélection, les
opportunités et les autres hashes du bloc `integrity`.

La validation doit appliquer exactement la même transformation : retirer le
seul champ `integrity.input_payload_sha256`, canonicaliser l'objet résultant
selon les règles précédentes, recalculer le SHA-256 puis le comparer à la valeur
stockée.

La préparation sélectionne `KEEP` et `REVIEW`, puis les représentants stockés
des quasi-doublons. Elle calcule les comptes depuis les données. Elle ne possède
aucun argument permettant de lire le jeu manuel.

### Clé canonique

```text
"offers:" + "|".join(sorted(unique(offer_ids)))
```

Exemples : `offers:SYNTH-V1-001` et
`offers:SYNTH-V1-002|SYNTH-V1-003|SYNTH-V1-004`. Une clé lisible choisie manuellement n'est pas
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

## Future version v2

La version v1 reste la définition normative des artefacts déjà créés. Elle ne
doit être ni réinterprétée, ni réécrite selon les règles ci-dessous. La version
v2 s'appliquera uniquement aux nouvelles préparations et évaluations après son
implémentation et sa validation synthétique.

Les invariants de sécurité, de confidentialité, d'indépendance du fournisseur,
de portée `specific_offer_only` et de canonicalisation de la v1 restent
obligatoires en v2. Les nouveaux champs participent aux hashes selon la même
canonicalisation JSON UTF-8. La règle de retrait du seul champ
`integrity.input_payload_sha256` reste inchangée pour une entrée v2.

Dans chaque opportunité préparée, la v2 ajoute aux champs v1
`normalized_requirements`, `domain_inputs` et `deterministic_conditions`. Les
JSON Pointers définis ci-dessous sont résolus depuis cette opportunité préparée.
La sortie reproduit les faits préparés pour la traçabilité, sans les modifier.

L'ordre normatif de préparation est : normalisation déterministe des exigences
et des critères mécaniques, segmentation déterministe versionnée, extracteur
local contraint sans profil, validation puis gel de `domain_inputs`, enfin
évaluation métier. Une extraction invalide, incomplète, non traçable ou non
conforme à son schéma interdit l'évaluation de l'opportunité.

La provenance de l'entrée v2 contient obligatoirement un objet
`domain_preparation` avec `segmentation_version`,
`segmentation_rules_sha256`, `segmentation_schema_sha256`,
`extractor_version`, `extractor_instruction_sha256`,
`extractor_schema_sha256`, `extractor_model_identifier` et
`extractor_model_sha256`. Son bloc `integrity` contient en plus
`domain_extraction_payload_sha256` et `domain_inputs_payload_sha256`. Le
premier est le hash de l'artefact d'extraction finalisé après retrait du seul
champ `integrity.domain_extraction_payload_sha256`; le second est le hash du
tableau gelé `domain_inputs`. Les deux calculs utilisent le JSON canonique v1.

### Normalisation des exigences

Le préparateur v2 transforme chaque exigence transmise au modèle en un objet
de `normalized_requirements`. Il ne fusionne pas deux exigences distinctes et
ne change jamais leur nature :

```json
{
  "requirement_id": "req:<sha256>",
  "source_path": "/offer/requirements/skills/0",
  "kind": "skill",
  "label": "Libellé source synthétique",
  "source_code": "CODE-SYNTH",
  "expectation_source_code": "E",
  "expectation": "required",
  "centrality": "core"
}
```

`source_path` est un JSON Pointer RFC 6901 résoluble depuis la racine de
l'opportunité transmise. `requirement_id` vaut littéralement `req:` suivi du
SHA-256 hexadécimal minuscule des octets UTF-8 de la concaténation :

```text
source_path + "\n" + kind + "\n" + (source_code ou "") + "\n" + (expectation_source_code ou "") + "\n" + label
```

Le validateur recalcule cet identifiant. Toute collision ou duplication fait
échouer la préparation.

`kind` accepte uniquement :

- `education` ;
- `licence_or_authorization` ;
- `certification` ;
- `skill` ;
- `experience` ;
- `responsibility` ;
- `working_condition` ;
- `other`.

`other` est réservé à une catégorie résiduelle explicitement prévue par le
schéma source et qui ne relève d'aucune nature plus précise ci-dessus. Il ne
sert jamais de valeur de repli pour une nature inconnue ou non reconnue, ni
pour une certification. Toute nature non reconnue fait échouer la préparation.

`label` conserve le libellé source sans en changer la catégorie. `source_code`
conserve le code métier éventuel de l'élément source et vaut `null` en son
absence. `expectation_source_code` conserve sans modification le code brut qui
porte le niveau d'exigence et vaut `null` en son absence. `expectation` accepte
uniquement `required`, `desired` ou `unknown`. La correspondance normative est :

- `E` devient `required` ;
- `S` devient `desired` ;
- toute autre valeur, valeur absente ou valeur non documentée devient
  `unknown`.

`centrality` est calculée avant l'évaluation par une règle déterministe
versionnée et hashée dans `domain_preparation`. Elle accepte uniquement `core`,
`supporting` ou `unknown`. Elle ne dépend jamais du profil ni de la proposition
du modèle. `unknown` est traité comme `core` par toute barrière qui décide si
`credible` est possible. L'évaluateur ne peut ni abaisser, ni relever, ni
omettre cette valeur.

Le modèle ne peut jamais présenter une exigence `desired` ou `unknown` comme
obligatoire. Il ne peut pas transformer un permis ou une autorisation en
diplôme, une compétence en certification, ni aucune autre valeur de `kind` en
une nature différente.

### Couverture exhaustive des exigences

Chaque résultat v2 contient `requirement_coverage`. Chaque
`requirement_id` transmis apparaît exactement une fois et aucun identifiant
supplémentaire n'est accepté :

```json
{
  "requirement_id": "req:<sha256>",
  "source_path": "/offer/requirements/skills/0",
  "kind": "skill",
  "label": "Libellé source synthétique",
  "expectation": "required",
  "assessment": "transferable",
  "profile_evidence_paths": ["/skills/0"],
  "reason": "Socle exercé, mais contexte différent.",
  "centrality": "core"
}
```

Les champs `source_path`, `kind`, `label` et `expectation` reproduisent sans
modification l'exigence normalisée correspondante. `profile_evidence_paths`
contient uniquement des JSON Pointers RFC 6901 résolubles depuis la racine du
snapshot de profil ; le tableau peut être vide. `centrality` reproduit
exactement celle de l'exigence normalisée : ce n'est pas une proposition de
l'évaluateur.

`assessment` accepte uniquement :

- `established` : une preuve explicite existe dans le profil avec une
  correspondance de nature, de périmètre et de niveau ;
- `transferable` : un socle réellement exercé existe, mais le contexte, le
  niveau, l'échelle ou le domaine diffère ;
- `gap` : l'exigence est identifiée dans l'offre mais n'est pas établie dans le
  profil ;
- `missing` : les informations fournies ne permettent pas de conclure. Ce code
  ne signifie ni présence ni absence de compétence.

Une classification globale est interdite si une exigence manque dans la
couverture, apparaît plusieurs fois ou n'est pas reliée à son objet normalisé.

Une aptitude générale à apprendre, une curiosité sectorielle ou une autonomie
informatique ne peut jamais transformer automatiquement un `gap` en
`established` ou `transferable`. La sortie distingue obligatoirement une
compétence exercée, un transfert défendable, un apprentissage futur possible et
une certification ou autorisation formelle.

### Préparation et couverture des domaines du poste

Le segmenter déterministe reçoit les champs d'offre déjà autorisés et produit
des unités de texte ordonnées. Chaque unité possède `unit_id`, `source_path` et
`source_excerpt`; les deux derniers sont résolus depuis l'opportunité préparée.
Son périmètre, ses règles et son schéma sont figés par les versions et hashes de
`domain_preparation`.

L'extracteur reçoit exclusivement ce tableau d'unités : ni profil, ni verdict,
ni classement manuel, ni autre opportunité. Il est local et contraint par une
instruction et un schéma versionnés. Son artefact final contient les unités
reçues, les `domain_inputs` proposés, sa provenance complète et son auto-hash
calculé après retrait de son seul champ d'auto-hash. Le validateur vérifie les
pointeurs, les extraits exacts, les identifiants, les types et la centralité,
puis gèle les `domain_inputs`. L'évaluation métier ne peut commencer qu'après
cette validation.

Chaque `domain_inputs` contient `domain_id`, `domain`, `source_unit_ids`,
`source_path`, `source_excerpt` et `centrality`. `domain_id` est stable dans
l'artefact d'extraction; aucune entrée ne peut être retirée, ajoutée ou
reformulée par l'évaluateur. `centrality` suit la même règle déterministe,
versionnée et conservatrice que pour les exigences.

La sortie contient exactement une entrée `domain_coverage` pour chaque domaine
transmis :

```json
{
  "domain_id": "domain:<stable-id>",
  "domain": "specialized_public_procurement",
  "source_unit_ids": ["segment:<stable-id>"],
  "source_path": "/offer/description_cleaned",
  "source_excerpt": "Extrait synthétique relatif à une procédure publique.",
  "centrality": "core",
  "assessment": "gap",
  "profile_evidence_paths": [],
  "reason": "Aucune pratique de ce domaine spécialisé n'est établie."
}
```

`domain_id`, `domain`, `source_unit_ids`, `source_path`, `source_excerpt` et
`centrality` reproduisent exactement le `domain_inputs` correspondant. Le validateur exige
que l'extrait soit réellement présent à `source_path` après le même nettoyage
que l'entrée. Une centralité `unknown` est traitée comme `core` pour les
barrières de `credible`.

Une compétence générique ne remplace jamais silencieusement un domaine
spécialisé. Exemples entièrement synthétiques :

- achats privés ≠ commande publique ;
- conformité opérationnelle générale ≠ réglementation ERP ;
- maintenance de premier niveau ≠ expertise BTP ;
- encadrement d'une petite équipe ≠ management établi d'un service technique
  de taille inconnue ;
- comptabilité courante ≠ élaboration budgétaire publique.

### Critères déterministes obligatoires

Le préparateur calcule un bloc fermé `deterministic_conditions`. L'entrée
contient uniquement ses faits; elle ne contient jamais `business_comment`, pas
même avec la valeur `null`. La sortie reprend exactement ces mêmes faits et
ajoute, pour chaque condition, le seul champ produit par le modèle :
`business_comment`, chaîne non vide et non normative. Le commentaire ne peut
ni modifier, ni masquer, ni contredire un fait préparé ou un verdict mécanique.
Le bloc contient obligatoirement :

- `salary` ;
- `commute` ;
- `schedule` ;
- `contract_type` ;
- `employer_size` ;
- `team_size` ;
- `functional_support`.

Chaque condition d'entrée contient exactement `source_paths`,
`information_status`, `source_values` et `mechanical_assessment`.
`source_paths` est un tableau de JSON Pointers, vide seulement lorsqu'aucun
champ source n'existe. `information_status` vaut `known` ou `unknown`. Les
valeurs absentes sont `null`, jamais une valeur inventée.

Les sous-schémas fermés sont les suivants :

- `salary.source_values` : `monthly_gross_min_eur` et
  `monthly_gross_max_eur` (nombres finis ou `null`), `threshold_eur` (nombre
  fini strictement positif) ; `mechanical_assessment` vaut
  `below_threshold`, `partially_meets_threshold`, `meets_threshold` ou
  `unknown` ;
- `commute.source_values` : `duration_minutes` (entier positif ou `null`) et
  `band` (`UP_TO_35`, `BETWEEN_35_60`, `OVER_60`, `UNKNOWN`) ;
  `mechanical_assessment` vaut `target_condition`, `review_condition`,
  `exclude_condition` ou `unknown` ;
- `schedule.source_values` : `works_shifted_hours`, `works_at_night`,
  `works_weekend`, `works_saturday`, `works_sunday` (booléens ou `null`) ;
  `mechanical_assessment` vaut `no_penalty`, `penalized` ou `unknown` ;
- `contract_type.source_values` : `family`
  (`cdi`, `cdd`, `interim`, `other`, `unknown`) ;
  `mechanical_assessment` vaut `accepted` ou `unknown` ;
- `employer_size.source_values` : `establishment_size_label` (chaîne non vide
  ou `null`) ; `mechanical_assessment` vaut `known` ou `unknown` ;
- `team_size.source_values` : `minimum` et `maximum` (entiers positifs ou
  `null`, avec `minimum <= maximum` lorsque les deux existent) ;
  `mechanical_assessment` vaut `known` ou `unknown` ;
- `functional_support.source_values` : `support_status`
  (`present`, `absent`, `unknown`) et `support_types` (tableau ordonné sans
  doublon de `administrative`, `technical`, `operational`, `other`) ;
  `mechanical_assessment` vaut `known` ou `unknown`.

L'entrée et la sortie utilisent les mêmes sous-schémas fermés; seule la sortie
ajoute `business_comment`. Les valeurs et chemins communs doivent être égaux
selon le JSON canonique, condition par condition.

Pour le salaire, `mechanical_assessment` accepte :

- `below_threshold` si toute la fourchette connue est inférieure au seuil ;
- `partially_meets_threshold` si seule une partie de la fourchette atteint le
  seuil ;
- `meets_threshold` si toute la rémunération crédible connue atteint le seuil ;
- `unknown` si les données ne permettent pas de conclure.

Une borne haute atteignant le seuil ne permet jamais d'affirmer que la
rémunération globale est acquise. Une fourchette entièrement inférieure reste
défavorable ; une fourchette `partially_meets_threshold` reste à vérifier.

Pour le trajet, la durée et la bande mécanique sont toujours reproduites. Une
bande `BETWEEN_35_60` porte obligatoirement la conclusion `review_condition`.
Aucune condition de trajet ne peut être omise.

La taille de l'employeur ne vaut jamais taille de l'équipe. L'existence d'un
supérieur hiérarchique ne prouve pas un appui opérationnel. `team_size` et
`functional_support` restent `unknown` lorsque l'entrée ne fournit pas de fait
explicite.

### Règles de classification globale

La classification v2 conserve les quatre codes et la portée
`specific_offer_only`, avec les barrières suivantes :

- `credible` : aucune exigence `required` évaluée `gap` ou `missing`, aucun
  écart `core` ou de centralité `unknown` non établi, aucune information critique
  inconnue empêchant de juger l'accessibilité immédiate ; les transferts restent
  limités et ne changent pas le cœur du métier ;
- `audacious` : candidature immédiate défendable grâce à un socle transférable
  réel, malgré des écarts centraux importants mais compensables par un
  accompagnement, une formation ou une adaptation réaliste ; aucune expertise
  entièrement étrangère ne constitue le cœur principal du poste ;
- `evolution` : passerelle plausible, mais candidature directe prématurée ; une
  formation, une VAE fondée sur des compétences déjà exercées, une expérience
  intermédiaire ou une première fonction sectorielle est nécessaire avant
  l'accès au poste précis ;
- `out_of_scope` : le cœur du poste repose sur une expertise, une pratique
  technique, une autorisation ou une responsabilité centrale non établie, sans
  passerelle immédiate raisonnablement défendable pour l'offre précise.

Toute exigence `required` évaluée `gap` ou `missing` interdit toujours
`credible`, indépendamment de sa centralité. Lorsque plusieurs domaines `core`
ou de centralité `unknown` sont `transferable` ou `gap`, la justification
doit expliquer explicitement pourquoi la catégorie n'est pas abaissée vers
`audacious`, `evolution` ou `out_of_scope`. Une possibilité d'apprentissage
future ne suffit jamais, à elle seule, à maintenir `credible`.

### Intégrité de la sortie

`evaluation_payload_sha256` est le SHA-256 des octets UTF-8 du JSON canonique
de la sortie finalisée après retrait du seul champ
`integrity.evaluation_payload_sha256`. Ce champ est retiré de l'objet avant la
canonicalisation ; il n'est remplacé ni par `null`, ni par une chaîne vide, ni
par une valeur temporaire. Tous les autres champs de la sortie, y compris les
hashes d'entrée, la provenance de l'extracteur et les `business_comment`,
participent au calcul.

La validation applique exactement la même transformation : elle retire le seul
champ `integrity.evaluation_payload_sha256`, canonicalise l'objet résultant,
recalcule le SHA-256 puis le compare à la valeur stockée. Aucun autre champ ne
peut être retiré, neutralisé ou réordonné hors des règles de canonicalisation
v1.

### Informations manquantes et provenance

`missing_information` devient une collection d'objets structurés :

```json
{
  "subject": "team_size",
  "source_paths": ["/deterministic_conditions/team_size"],
  "reason": "La taille de l'équipe n'est pas fournie.",
  "classification_impact": "immediate_accessibility_uncertain"
}
```

Les `source_paths` de cette collection sont résolus depuis la même opportunité
préparée v2 ; ils peuvent donc viser une exigence, un domaine ou une condition
déterministe. Un tableau vide n'est permis que lorsque l'absence même du champ
source est le fait à signaler.

Les tableaux sémantiques de sortie ne contiennent aucun texte libre dépourvu de
provenance. Une information manquante non liée à l'accessibilité ou à la
classification ne doit pas être ajoutée.

### Invariants validables par code

Le validateur v2 refuse la sortie lorsque l'un des invariants suivants échoue :

- chaque exigence normalisée possède exactement une couverture ;
- aucun `requirement_id` n'est dupliqué ou supplémentaire ;
- chaque `source_path` existe dans l'entrée et chaque extrait correspond à sa
  source ;
- chaque `profile_evidence_paths` existe dans le snapshot du profil ;
- `kind`, `label` et `expectation` sont identiques entre exigence et
  couverture ;
- toute exigence `required` évaluée `gap` ou `missing` est incompatible avec
  `credible` ;
- `centrality` est identique entre les objets préparés et leur couverture, et
  `unknown` est appliqué conservativement ;
- chaque condition déterministe obligatoire est présente et ses faits
  préparés sont inchangés ; aucune entrée ne contient `business_comment` ;
- chaque sortie ajoute un unique `business_comment` par condition, sans autre
  champ produit par le modèle dans le bloc déterministe ;
- aucun niveau `unknown` ou `desired` n'est présenté comme obligatoire ;
- aucune compétence `transferable` n'est formulée comme une expérience
  directement établie ;
- aucun tableau sémantique ne contient d'élément libre sans provenance ;
- aucune classification n'est acceptée tant que les couvertures sont
  incomplètes ou contradictoires.

### Séparation des responsabilités en v2

- Le préparateur normalise les exigences, préserve leur nature et leurs codes,
  segmente l'offre, calcule la centralité et les critères déterministes.
- L'extracteur local contraint ne reçoit que les unités de texte segmentées et
  produit des domaines traçables; le validateur les gèle avant l'évaluation.
- Le modèle évalue les correspondances, transferts, écarts et inconnues sans
  modifier les faits préparés; il produit seulement les commentaires métier des
  conditions déterministes.
- Le validateur refuse toute sortie structurellement incomplète,
  contradictoire, sans provenance ou incompatible avec les barrières de
  classification.
- Le comparateur n'accède au jeu manuel qu'après finalisation, validation et
  gel de la sortie IA.
- Aucune sortie IA ne modifie automatiquement un verdict mécanique, manuel ou
  final.

### Compatibilité et migration

- Les profils, entrées, sorties et comparatifs v1 restent valides
  historiquement et ne sont jamais réécrits.
- Les prochaines expérimentations utilisent v2 uniquement après
  implémentation, tests et qualification synthétique de l'ensemble du chemin.
- Le passage à v2 produit de nouveaux hashes de politique, d'entrée, de schéma
  JSON et de grammaire ; un résultat v1 et un résultat v2 ne sont pas
  interchangeables.
- Une approbation existante n'est jamais transférée automatiquement lorsque le
  contenu minimisé du profil ou la politique change. Le nouveau contenu et ses
  hashes doivent être relus et approuvés selon les barrières locale et externe
  déjà définies.
- Aucune offre réelle n'est réévaluée en v2 avant validation synthétique du
  préparateur, du schéma, de la grammaire, du validateur et de l'extracteur.

### Exemple synthétique v2

L'exemple suivant est entièrement fictif. Il illustre une évaluation d'une
seule opportunité sans donnée professionnelle réelle :

Le bloc `evaluation.deterministic_conditions` ci-dessous est celui de sortie.
Dans l'entrée correspondante, chaque objet de condition est strictement le même
après retrait du seul champ `business_comment` ; aucun autre champ n'est ajouté,
supprimé ou changé.

```json
{
  "schema_version": 2,
  "artifact_type": "ai_opportunity_evaluation",
  "run": {
    "run_id": "00000000-0000-4000-8000-000000000000",
    "executed_at_utc": "2030-01-01T00:00:00Z",
    "execution_mode": "local",
    "provider": "local_runtime",
    "model": "synthetic-model",
    "parameters": {},
    "policy_version": "comparative-classification-v2",
    "evaluation_instruction_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
  },
  "inputs": {
    "input_payload_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
    "policy_payload_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
    "profile_payload_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
    "opportunity_payload_sha256": "4444444444444444444444444444444444444444444444444444444444444444",
    "schema_sha256": "5555555555555555555555555555555555555555555555555555555555555555",
    "grammar_sha256": "6666666666666666666666666666666666666666666666666666666666666666",
    "profile_snapshot": {
      "skills": [{"label": "Planification d'interventions"}]
    }
  },
  "evaluation": {
    "opportunity_key": "offers:SYNTH-001",
    "offer_ids": [
      "SYNTH-001"
    ],
    "scope": "specific_offer_only",
    "offer": {
      "description_cleaned": "Appliquer une réglementation synthétique aux bâtiments publics.",
      "requirements": {
        "skills": [{"code": "SYNTH-SKILL-01", "libelle": "Planifier des interventions techniques", "exigence": "E"}],
        "licences_and_authorizations": [{"libelle": "Autorisation synthétique de conduite", "exigence": "S"}]
      },
      "salary": {"monthly_gross_min": 2400, "monthly_gross_max": 2800},
      "travel": {"duration_minutes": 42, "band": "BETWEEN_35_60"},
      "schedule": {"works_shifted_hours": false, "works_at_night": null, "works_weekend": null, "works_saturday": null, "works_sunday": null},
      "contract": {"family": "cdd"},
      "employer": {"establishment_size": "50 à 99 salariés"}
    },
    "normalized_requirements": [
      {
        "requirement_id": "req:049d498156edcd534270397edd830828425d317ddc926cc247bbd72ecf6736cc",
        "source_path": "/offer/requirements/skills/0",
        "kind": "skill",
        "label": "Planifier des interventions techniques",
        "source_code": "SYNTH-SKILL-01",
        "expectation_source_code": "E",
        "expectation": "required",
        "centrality": "core"
      },
      {
        "requirement_id": "req:824f9708601e9c9c845f0d10a3ab4ec2bff85aed8f384f5ed2d900e98666c0a9",
        "source_path": "/offer/requirements/licences_and_authorizations/0",
        "kind": "licence_or_authorization",
        "label": "Autorisation synthétique de conduite",
        "source_code": null,
        "expectation_source_code": "S",
        "expectation": "desired",
        "centrality": "supporting"
      }
    ],
    "requirement_coverage": [
      {
        "requirement_id": "req:049d498156edcd534270397edd830828425d317ddc926cc247bbd72ecf6736cc",
        "source_path": "/offer/requirements/skills/0",
        "kind": "skill",
        "label": "Planifier des interventions techniques",
        "expectation": "required",
        "assessment": "transferable",
        "profile_evidence_paths": [
          "/skills/0"
        ],
        "reason": "La planification est exercée dans un contexte différent.",
        "centrality": "core"
      },
      {
        "requirement_id": "req:824f9708601e9c9c845f0d10a3ab4ec2bff85aed8f384f5ed2d900e98666c0a9",
        "source_path": "/offer/requirements/licences_and_authorizations/0",
        "kind": "licence_or_authorization",
        "label": "Autorisation synthétique de conduite",
        "expectation": "desired",
        "assessment": "missing",
        "profile_evidence_paths": [],
        "reason": "La possession actuelle de l'autorisation n'est pas renseignée.",
        "centrality": "supporting"
      }
    ],
    "domain_text_units": [
      {
        "unit_id": "segment:description:0",
        "source_path": "/offer/description_cleaned",
        "source_excerpt": "Appliquer une réglementation synthétique aux bâtiments publics."
      }
    ],
    "domain_inputs": [
      {
        "domain_id": "domain:synthetic-public-asset-regulation",
        "domain": "synthetic_public_asset_regulation",
        "source_unit_ids": ["segment:description:0"],
        "source_path": "/offer/description_cleaned",
        "source_excerpt": "Appliquer une réglementation synthétique aux bâtiments publics.",
        "centrality": "core"
      }
    ],
    "domain_coverage": [
      {
        "domain_id": "domain:synthetic-public-asset-regulation",
        "domain": "synthetic_public_asset_regulation",
        "source_unit_ids": ["segment:description:0"],
        "source_path": "/offer/description_cleaned",
        "source_excerpt": "Appliquer une réglementation synthétique aux bâtiments publics.",
        "centrality": "core",
        "assessment": "gap",
        "profile_evidence_paths": [],
        "reason": "Aucune pratique de cette réglementation spécialisée n'est établie."
      }
    ],
    "deterministic_conditions": {
      "salary": {
        "source_paths": [
          "/offer/salary/monthly_gross_min",
          "/offer/salary/monthly_gross_max"
        ],
        "information_status": "known",
        "source_values": {
          "monthly_gross_min_eur": 2400,
          "monthly_gross_max_eur": 2800,
          "threshold_eur": 2500
        },
        "mechanical_assessment": "partially_meets_threshold",
        "business_comment": "Seule une partie de la fourchette atteint le seuil."
      },
      "commute": {
        "source_paths": [
          "/offer/travel/duration_minutes",
          "/offer/travel/band"
        ],
        "information_status": "known",
        "source_values": {
          "duration_minutes": 42,
          "band": "BETWEEN_35_60"
        },
        "mechanical_assessment": "review_condition",
        "business_comment": "Le trajet doit être examiné avec les autres conditions."
      },
      "schedule": {
        "source_paths": [
          "/offer/schedule/works_shifted_hours",
          "/offer/schedule/works_at_night",
          "/offer/schedule/works_weekend",
          "/offer/schedule/works_saturday",
          "/offer/schedule/works_sunday"
        ],
        "information_status": "known",
        "source_values": {
          "works_shifted_hours": false,
          "works_at_night": null,
          "works_weekend": null,
          "works_saturday": null,
          "works_sunday": null
        },
        "mechanical_assessment": "no_penalty",
        "business_comment": "Aucune pénalité horaire n'est identifiée."
      },
      "contract_type": {
        "source_paths": [
          "/offer/contract/family"
        ],
        "information_status": "known",
        "source_values": {
          "family": "cdd"
        },
        "mechanical_assessment": "accepted",
        "business_comment": "Le contrat reste recevable."
      },
      "employer_size": {
        "source_paths": [
          "/offer/employer/establishment_size"
        ],
        "information_status": "known",
        "source_values": {
          "establishment_size_label": "50 à 99 salariés"
        },
        "mechanical_assessment": "known",
        "business_comment": "Cette valeur ne décrit pas la taille de l'équipe."
      },
      "team_size": {
        "source_paths": [],
        "information_status": "unknown",
        "source_values": {
          "minimum": null,
          "maximum": null
        },
        "mechanical_assessment": "unknown",
        "business_comment": "La taille de l'équipe doit être vérifiée."
      },
      "functional_support": {
        "source_paths": [],
        "information_status": "unknown",
        "source_values": {
          "support_status": "unknown",
          "support_types": []
        },
        "mechanical_assessment": "unknown",
        "business_comment": "L'appui opérationnel disponible doit être vérifié."
      }
    },
    "classification_code": "audacious",
    "classification_justification": "Un socle de planification est transférable, mais un domaine central spécialisé reste à acquérir avec un accompagnement réaliste.",
    "missing_information": [
      {
        "subject": "team_size",
        "source_paths": [
          "/deterministic_conditions/team_size"
        ],
        "reason": "La taille de l'équipe n'est pas fournie.",
        "classification_impact": "immediate_accessibility_uncertain"
      },
      {
        "subject": "functional_support",
        "source_paths": [
          "/deterministic_conditions/functional_support"
        ],
        "reason": "L'appui opérationnel n'est pas décrit.",
        "classification_impact": "integration_conditions_uncertain"
      }
    ]
  },
  "provenance": {
    "domain_preparation": {
      "segmentation_version": "synthetic-segmenter-v2",
      "segmentation_rules_sha256": "7777777777777777777777777777777777777777777777777777777777777777",
      "segmentation_schema_sha256": "8888888888888888888888888888888888888888888888888888888888888888",
      "extractor_version": "synthetic-extractor-v2",
      "extractor_instruction_sha256": "9999999999999999999999999999999999999999999999999999999999999999",
      "extractor_schema_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "extractor_model_identifier": "synthetic-local-extractor",
      "extractor_model_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  },
  "integrity": {
    "domain_extraction_payload_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "domain_inputs_payload_sha256": "ca17e77bec2765dff26c1561d4cb428cda5d5f0978f2c0dc0297e9afa7db7c02",
    "evaluation_payload_sha256": "bdb62ccb36aee9c3058c15b11df52811faec6392b2118b9ae3f756a38836cc92"
  }
}
```

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
