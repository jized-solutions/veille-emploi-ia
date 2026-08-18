# Passer du Work Cloud au projet local + GitHub

## Résultat visé

- Codex travaille directement dans
  `F:\Julien\Pro\Reconversion\Veille emploi IA\`.
- Le dépôt GitHub `jized-solutions/veille-emploi-ia` conserve l'historique du
  code et de la documentation.
- `.env`, SQLite, captures et rapports restent uniquement sur le PC.

## 1. Installer le paquet de transition

Fermer les scripts Python du projet. Décompresser le paquet fourni dans :

`F:\Julien\Pro\Reconversion\`

Le dossier contenu dans l'archive est `Veille emploi IA`. Accepter le
remplacement des fichiers de code présents dans l'archive. L'archive ne contient
pas `.env`, `data` ni `reports` : ces éléments locaux ne doivent pas être
remplacés.

## 2. Ouvrir le vrai dossier dans Codex

Dans l'application ChatGPT/Codex pour Windows :

1. ouvrir Codex ;
2. ajouter ou ouvrir le dossier local
   `F:\Julien\Pro\Reconversion\Veille emploi IA` ;
3. choisir le mode **Local** ;
4. conserver un accès limité au dossier du projet ;
5. utiliser PowerShell pour les commandes Windows.

Premier message conseillé :

> Lis intégralement AGENTS.md et docs/ETAT_PROJET.md. Vérifie en lecture seule le
> chemin courant, git status, la liste des fichiers suivis et la présence de
> .env/data/reports sans afficher leurs secrets ou leur contenu privé. Ne modifie
> rien avant de me donner un bilan et le plan minimal pour relier proprement ce
> dossier à https://github.com/jized-solutions/veille-emploi-ia.

## 3. Vérifier les outils locaux

Dans PowerShell :

```powershell
Set-Location -LiteralPath 'F:\Julien\Pro\Reconversion\Veille emploi IA'
git --version
gh --version
```

`cd /d` appartient à `cmd.exe` ; dans PowerShell, utiliser `Set-Location` ou
simplement `cd 'F:\chemin'`.

Si `gh` est installé mais non connecté :

```powershell
gh auth login
```

Ne jamais coller un mot de passe, un jeton ou le contenu de `.env` dans le chat.

## 4. Relier GitHub sans écrasement

Le dépôt distant peut être vide ou contenir un commit initial. Le projet local
doit donc commencer par une inspection, pas par un `push --force`.

Demander au Codex local de :

1. lancer `git status --short --branch` et `git remote -v` ;
2. initialiser Git uniquement si `.git` n'existe pas ;
3. ajouter le remote `origin` uniquement s'il n'existe pas ;
4. exécuter `git fetch origin` ;
5. comparer l'historique local et distant ;
6. proposer la fusion la plus petite si le distant possède déjà un README ;
7. contrôler `git status --ignored` et le contenu indexé avant tout commit ;
8. demander validation avant le premier push.

URL du dépôt :

`https://github.com/jized-solutions/veille-emploi-ia.git`

Interdictions : `push --force`, `reset --hard`, suppression de `.git`, ajout de
`.env`, `data` ou `reports`.

## 5. Contrôle avant le premier commit

Les commandes suivantes ne doivent afficher aucun secret ou fichier de données
parmi les éléments à versionner :

```powershell
git status --short
git check-ignore -v .env data\veille_emploi.sqlite
git diff -- . ':!data' ':!reports'
```

Le premier commit doit contenir seulement : `app`, `config`, `docs`,
`AGENTS.md`, `README.md`, `.gitignore`, `.env.example` et `requirements.txt`.

## 6. Première validation locale

Après liaison et avant de poursuivre le développement :

```powershell
python -m compileall .\app
python .\app\generate_reports.py --capture-id 2
```

Comparer ensuite le résumé des trajets au résultat attendu dans
`docs/ETAT_PROJET.md`. Ne pas relancer l'acquisition France Travail tant que ce
test de reprise n'est pas validé.
