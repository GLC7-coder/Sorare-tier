# Sorare tier watch

Chaque jour, récupère le tier Sorare Set (Reserve → Roster → Key → Star → Icon) de **tous les joueurs**
de Ligue 1, Bundesliga, LALIGA et Premier League (environ 2 200 joueurs), repère ceux que tu possèdes,
et t'envoie un rapport des changements.

## Installation (10 min)

1. Mets ton pseudo Sorare dans `config.json` → `"sorare_user"`. C'est la fin de l'URL de ta galerie :
   `sorare.com/fr/football/my-club/<pseudo>` (déjà rempli : `glc7`). Ta galerie est publique, donc aucun mot de passe n'est nécessaire.
2. Crée un dépôt GitHub et pousse-y ce dossier tel quel.
3. *(Facultatif)* Crée une clé API gratuite sur https://sorare.com/settings/developer, puis dans le dépôt :
   Settings → Secrets and variables → Actions → New repository secret `SORARE_API_KEY`.
   Sans clé, une exécution prend environ 5 minutes. Avec une clé, moins d'une minute.
4. Onglet **Actions** → « Sorare tier watch » → *Run workflow*. Cette première exécution enregistre
   l'état de référence et ouvre une première issue avec la liste de tes joueurs.
   Ensuite, le script tourne seul chaque matin vers 6-7 h.

Tu reçois les rapports par e-mail via les notifications GitHub, sous forme d'issues.

## Ce que tu reçois

- **Rapport quotidien** (issue) :
  1. la section « 🎯 Mes joueurs » (montées et descentes de tes joueurs) ;
  2. la section « 🌍 Tous les joueurs » (tous les changements, avec ✅ sur ceux que tu possèdes).
- **Tableau de bord** `docs/index.html` : recherche, filtres par championnat et par tier,
  case « Mes joueurs », date depuis laquelle chaque joueur a son tier, onglet « Changements récents » (30 jours).
  Pour l'avoir en ligne : Settings → Pages → *Deploy from branch* → `main` / `/docs`
  (gratuit si le dépôt est public, sinon il faut GitHub Pro). Tu peux aussi télécharger le fichier et l'ouvrir.
- **Historique complet** `data/history.csv`, ouvrable dans Excel.

## Options de `config.json`

| Clé | Rôle |
|---|---|
| `competitions` | Championnats suivis (slugs Sorare) |
| `sorare_user` | Ton pseudo. Tes joueurs sont ceux dont tu as au moins une carte Set |
| `set_slug` | `"auto"` (défaut) = Set le plus récent de ta galerie. `null` = tous tes Sets. Ou un slug précis, par exemple `"divination"` |
| `extra_my_players` | Slugs de joueurs à ajouter à « mes joueurs » (par exemple une liste de souhaits) |
| `notify` | `"all"` = une issue dès qu'un joueur change. `"mine"` = seulement si un de tes joueurs change |

## Correspondance des tiers (API → Set)

`DNP` = Reserve · `ROSTER` = Roster · `IMPACT` = Key · `STAR` = Star · `GOAT` = Icon.
Les variantes `_PLUS` apparaissent avec un « + ».
