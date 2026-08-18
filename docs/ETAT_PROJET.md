# État du projet — 17 août 2026

Ce document décrit l'état connu au dernier échange dans ChatGPT Work Cloud. Il
ne remplace pas une vérification du disque local au moment de la reprise.

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

## Point précis à vérifier à la reprise

Le rapport local le plus récent connu a été créé avant la dernière correction
d'affichage des trajets :

`reports\html\rapport_capture_2_2026-08-17_113521Z.html`

Après installation des fichiers corrigés, exécuter de nouveau :

```powershell
python .\app\generate_reports.py --capture-id 2
```

Le résumé attendu pour les offres encore KEEP ou REVIEW est :

- 13 trajets à 35 minutes ou moins ;
- 3 trajets entre 35 et 60 minutes ;
- 0 trajet au-delà de 60 minutes ;
- 1 trajet inconnu.

Ces chiffres sont un résultat de test attendu, pas une décision métier. S'ils
diffèrent, diagnostiquer la base locale en lecture seule avant de modifier le
code ou les données.

## État de l'architecture

Checkpoint après première source réelle et premier pipeline complet :

✅ **CONSERVER L'ARCHITECTURE**

La stack actuelle reste adaptée pour valider rapidement le concept. GitHub sert
à l'historique et à la sauvegarde du code ; il ne doit recevoir ni `.env`, ni la
base SQLite, ni les captures, ni les rapports. Un projet Codex local attaché au
dossier officiel devient l'environnement de modification et de test.

## Prochaine séquence recommandée

1. Vérifier en lecture seule le dossier local, les fichiers, Git et la présence
   des données nécessaires.
2. Installer ou remplacer uniquement les fichiers de code et documentation du
   paquet de transition ; préserver `.env`, `data` et `reports`.
3. Régénérer le rapport corrigé de la capture #2 et comparer aux valeurs
   attendues ci-dessus.
4. Relire manuellement les 17 offres KEEP/REVIEW pour évaluer la qualité des
   profils de recherche et des règles mécaniques.
5. Formaliser le profil professionnel de Julien à partir d'une source validée
   (CV et préférences), puis seulement concevoir un petit test d'évaluation IA.
6. Refaire un checkpoint avant toute automatisation quotidienne.

Ne pas ajouter de nouvelle source, d'agent autonome ou de candidature automatique
à ce stade.
