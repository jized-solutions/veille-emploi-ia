# Instructions permanentes — Veille emploi IA

## Périmètre

Ce dépôt appartient exclusivement au projet ChatGPT « Julien Pro », branche
« Reconversion et recherche emploi », projet « Veille emploi automatisée et
assistée par IA ». Ne jamais le mélanger avec LDTF, Assistance technique,
Freelance ou un autre projet.

La racine locale officielle est :
`F:\Julien\Pro\Reconversion\Veille emploi IA\`

Windows 11 est l'environnement V1. Linux reste consultatif. Un NAS ou un
fonctionnement H24 sera étudié plus tard, pas intégré par anticipation.

## Autorité et prudence

- Distinguer faits confirmés, hypothèses, suggestions, tests et décisions de
  Julien.
- Une offre analysée n'est jamais une candidature envoyée.
- Aucune candidature automatique ni action externe au nom de Julien.
- Avant toute écriture, vérifier le chemin et l'état Git. Préserver les fichiers
  et données existants ; ne pas écraser une modification de l'utilisateur.
- Expliquer simplement les changements envisagés avant une nouvelle étape.
- Après une modification importante, vérifier le résultat et montrer le bilan.
- Ne jamais afficher, enregistrer dans Git ou transmettre les secrets de `.env`.
- Ne jamais versionner les captures, bases SQLite ou rapports générés.
- Utiliser des opérations réversibles et des commandes Git non destructives.
  Ne jamais employer `reset --hard`, `clean -fd` ou une suppression récursive
  sans demande explicite et vérification précise de la cible.

## Objectif fonctionnel V1

- Source initiale : API officielle France Travail.
- Acquisition manuelle d'un petit lot ciblé.
- Normalisation dans SQLite.
- Filtres mécaniques explicables.
- Temps de trajet TomTom depuis Baillargues.
- Détection non destructive des quasi-doublons.
- Rapports HTML et CSV.
- IA seulement après validation manuelle de la qualité du pipeline.
- Historique durable et automatisation quotidienne seulement après validation.

Pipeline actuel :

1. `app/fetch_france_travail.py --profiles`
2. `app/normalize_france_travail.py <capture.json>`
3. `app/filter_offers.py --capture-id <id>`
4. `app/evaluate_travel.py --capture-id <id>`
5. `app/detect_duplicates.py --capture-id <id>`
6. `app/generate_reports.py --capture-id <id>`

## Règles métier validées

- Trajet réel depuis Baillargues : au plus 35 minutes = cible ; 35 à 60 minutes
  seulement si l'offre est forte ; plus de 60 minutes = hors cible.
- Rémunération connue sous 2 500 € brut mensuels globaux crédibles = exclusion.
- Une fourchette atteignant 2 500 € est conservée.
- Fixe et variable crédible peuvent être additionnés avec prudence.
- Primes, intéressement et participation peuvent compter quand ils sont
  quantifiés ou suffisamment crédibles. Titres-restaurant, paniers, mutuelle,
  CSE et remboursement de transport ne sont pas du salaire.
- Salaire absent = à vérifier, jamais exclusion automatique pour ce seul motif.
- CDI, CDD et intérim sont acceptés.
- Samedi, déplacements et astreintes ponctuelles sont acceptables.
- Les horaires décalés sont pénalisés, pas automatiquement exclus.
- Exclusions principales : comptabilité pure, administratif pur, direction ou
  commercial en grande distribution alimentaire, activité entrepreneuriale ou
  non salariée présentée comme emploi.
- Prudence face aux grandes équipes mal structurées.
- Verdicts futurs : 🎯 candidature crédible, 👀 candidature audacieuse,
  🚀 piste d'évolution, ❌ hors cible.
- Deux horizons : accessible maintenant ; évolution après VAE ou formation.

## Discipline technique et architecture

Rester « tech-aware » sans suivre les modes. À l'apparition d'un besoin, d'une
friction ou d'une dépendance importante, comparer : conserver l'existant,
l'améliorer, en remplacer une partie, ou adopter une nouvelle solution. Évaluer
simplicité, robustesse, fiabilité, coût, maintenance, sécurité, dépendance
fournisseur, tests, compatibilité V1 et bénéfice réel.

Réévaluer notamment lors d'une nouvelle source, d'une API limitée, d'une hausse
de volume, d'un besoin de planification/monitoring/permissions, de l'ajout d'un
agent ou d'une alternative qui simplifierait nettement le système. Après une
interruption significative, vérifier seulement les informations susceptibles
d'avoir changé et nécessaires à l'étape courante.

Effectuer un checkpoint d'architecture après la première source réelle, lorsque
le pipeline complet est validé, avant l'automatisation récurrente, avant une
logique agentique importante et avant le passage à une version durable. Conclure
par l'un des statuts suivants :

- ✅ CONSERVER L'ARCHITECTURE
- 🧪 TESTER UNE ALTERNATIVE
- 🔧 ADAPTER L'ARCHITECTURE
- 🔄 REPENSER UNE PARTIE DU PROJET

La décision actuelle est : ✅ CONSERVER L'ARCHITECTURE Python standard + API
France Travail + SQLite + TomTom + HTML/CSV. Ne pas introduire MCP, cloud,
orchestrateur ou agent autonome sans besoin démontré.

## Git et validation

- Le dépôt contient le code, la configuration non secrète et la documentation.
- Avant une modification : lire ce fichier et `docs/ETAT_PROJET.md`, puis lancer
  `git status --short --branch`.
- Après une modification Python : compiler les scripts concernés et exécuter le
  test reproductible le plus petit possible.
- Examiner `git diff` avant tout commit. Faire des commits petits et explicites.
- Ne pousser vers GitHub qu'après validation locale et accord de Julien lorsque
  le contenu ou la portée a changé de manière significative.

## Reprise immédiate

Lire intégralement `docs/ETAT_PROJET.md`. La prochaine étape n'est pas de créer
une architecture supplémentaire : elle consiste à installer ce dépôt comme
projet local, vérifier l'état réel, régénérer le rapport corrigé de la capture
#2, puis valider manuellement la pertinence métier avant l'ajout de l'IA.
