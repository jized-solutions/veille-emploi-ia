# État du projet — 19 août 2026

Ce document décrit l'état vérifié dans le projet Codex local au 19 août 2026.
Il ne remplace pas une nouvelle vérification du disque local lors d'une reprise
ultérieure.

## État confirmé

Le projet local se trouve dans
`F:\Julien\Pro\Reconversion\Veille emploi IA\` sur Windows 11.

La V1 fonctionne manuellement avec :

- l'API officielle France Travail et OAuth client credentials ;
- Python et sa bibliothèque standard, sans paquet externe requis ;
- SQLite pour la normalisation et les résultats ;
- TomTom pour les temps routiers historiques en voiture ;
- des rapports HTML et CSV ;
- une détection déterministe et non destructive des quasi-doublons.

Les secrets France Travail et TomTom sont dans le `.env` local. Ils ne doivent
jamais être lus à haute voix, copiés dans un rapport, joints à une conversation
ou ajoutés à Git.

## Fichiers de code actuels

- `app/fetch_france_travail.py`
- `app/normalize_france_travail.py`
- `app/filter_offers.py`
- `app/evaluate_travel.py`
- `app/detect_duplicates.py`
- `app/generate_reports.py`
- `config/search_profiles.json`
- `.env.example`
- `.gitignore`
- `requirements.txt`

## Dernier essai réel

Capture France Travail #2, réalisée le 17 août 2026 :

- 29 offres uniques issues des quatre profils métiers ciblés ;
- 3 doublons exacts regroupés lors de l'acquisition ;
- 19 salaires structurés, dont 18 convertibles en équivalent mensuel ;
- résultat des filtres mécaniques v1.2 : 5 KEEP, 12 REVIEW, 12 EXCLUDE ;
- trajets calculés avant le dernier refiltrage : 17 à 35 minutes ou moins,
  4 entre 35 et 60 minutes, 0 au-delà de 60 minutes et 2 inconnus ;
- un groupe de quasi-doublons, sans suppression : groupe
  `DUP-02a2fe7d1edb`, représentant France Travail `5684878`, membres
  `5201825`, `5589373`, `5684878`.

Aucune offre n'a été transformée en candidature et aucune candidature n'a été
envoyée.

## Corrections déjà intégrées au code fourni

- Les salaires mensuels au-dessus de 20 000 € sont considérés comme
  invraisemblables plutôt que convertis arbitrairement.
- Les fourchettes incohérentes sont rejetées.
- La mention « sur 13 mois » est annualisée correctement.
- Les avantages repas, mutuelle, CSE et transport ne compensent pas un salaire
  insuffisant ; les primes et dispositifs d'intéressement restent évaluables.
- Les compléments non quantifiés ne peuvent compenser qu'un écart maximal de
  250 € avec le seuil.
- Les coordonnées manquantes n'interrompent plus toute l'évaluation des trajets :
  les offres concernées passent en erreur/inconnu.
- Les quasi-doublons sont annotés, jamais supprimés.
- Le générateur de rapports ignore désormais les anciens trajets rattachés à
  des offres devenues EXCLUDE et affiche « Non calculé (offre exclue) ».

## Checkpoint de validation manuelle — 19 août 2026

Le dernier rapport validé est :

`reports\html\rapport_capture_2_2026-08-17_114131Z.html`

Il contient 29 offres :

- 5 KEEP ;
- 12 REVIEW ;
- 12 EXCLUDE.

Pour les offres KEEP ou REVIEW, le résumé des trajets est :

- 13 à 35 minutes ou moins ;
- 3 entre 35 et 60 minutes ;
- 0 au-delà de 60 minutes ;
- 1 inconnu.

Les 17 offres KEEP ou REVIEW représentent 15 opportunités uniques après le
regroupement des quasi-doublons. Le classement manuel validé est :

- 0 `credible` ;
- 6 `audacious` ;
- 4 `evolution` ;
- 5 `out_of_scope`.

Ces catégories manuelles ne remplacent ni ne modifient les verdicts mécaniques.
Une exclusion concerne l'offre précise évaluée et n'exclut pas automatiquement
son secteur d'activité pour d'autres fonctions compatibles.

Le profil professionnel validé et le jeu de référence manuel sont conservés
uniquement dans les fichiers locaux suivants :

- `data/profil_professionnel.md` ;
- `data/evaluations/capture_2_manual.json`.

Ces fichiers restent ignorés par Git et leur contenu ne doit pas être recopié
dans les fichiers suivis.

## État de l'architecture

Checkpoint après première source réelle, pipeline complet et validation
manuelle du jeu de référence :

✅ **CONSERVER L'ARCHITECTURE**

La stack actuelle reste adaptée pour valider rapidement le concept. GitHub sert
à l'historique et à la sauvegarde du code ; il ne doit recevoir ni `.env`, ni la
base SQLite, ni les captures, ni les rapports. Un projet Codex local attaché au
dossier officiel devient l'environnement de modification et de test.

## Prochain jalon

Concevoir un premier classement IA en mode strictement comparatif. Il devra :

1. lire le résultat des filtres mécaniques sans le remplacer ;
2. produire une proposition distincte, comparable au jeu de référence manuel ;
3. rendre visibles les accords, désaccords et informations manquantes ;
4. ne jamais modifier les verdicts mécaniques ou manuels ;
5. ne jamais se substituer à une décision utilisateur.

Le résultat devra être évalué sur le petit jeu de référence local avant tout
élargissement, automatisation ou intégration au pipeline principal.

Ne pas ajouter de nouvelle source, d'agent autonome ou de candidature automatique
à ce stade.
