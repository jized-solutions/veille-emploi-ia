# Veille emploi IA

Prototype local de veille d'offres d'emploi pour la reconversion de Julien.
La V1 récupère des offres depuis l'API officielle France Travail, les normalise
dans SQLite, applique des filtres explicables, évalue les trajets depuis
Baillargues avec TomTom, annote les quasi-doublons et produit des rapports HTML
et CSV.

Le projet n'envoie aucune candidature.

## Environnement

- Windows 11
- Python 3.11 ou plus récent
- bibliothèque standard Python uniquement pour la V1 actuelle
- identifiants API France Travail et clé TomTom dans un `.env` local

Copier `.env.example` vers `.env`, puis renseigner les valeurs localement. Ne
jamais versionner ce fichier.

## Exécution manuelle

Depuis PowerShell, à la racine du projet :

```powershell
python .\app\fetch_france_travail.py --profiles
python .\app\normalize_france_travail.py .\data\france_travail_brut_A_REMPLACER.json
python .\app\filter_offers.py --capture-id 2
python .\app\evaluate_travel.py --capture-id 2
python .\app\detect_duplicates.py --capture-id 2
python .\app\generate_reports.py --capture-id 2
```

Remplacer le nom de capture et son identifiant par ceux affichés par les scripts.

## Documentation de reprise

- `AGENTS.md` : règles permanentes pour Codex et garde-fous du projet.
- `docs/ETAT_PROJET.md` : état technique et prochaines étapes.
- `docs/DEMARRAGE_LOCAL.md` : installation locale et liaison GitHub sécurisée.

Les dossiers `data` et `reports` ainsi que `.env` sont volontairement exclus de
Git.
