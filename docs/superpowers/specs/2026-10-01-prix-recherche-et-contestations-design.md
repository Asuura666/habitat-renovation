# Onglet Prix : recherche internet à la demande, contestations visibles et résumées

*Spécification du 01/10/2026 — demandes d'Ilane du même jour. Branche
`feature/prix-contestations-recherche` (depuis `dev`, `8c4d27a`).*

## 1. Demandes et décisions

Demandes d'Ilane (01/10/2026) :

1. Sur l'onglet Prix, un bouton pour rechercher le prix d'un produit sur
   internet avec l'IA.
2. Quand un prix est contesté, la contestation et son commentaire doivent se
   voir dans la grille de prix du fournisseur, avec l'historique des
   contestations du produit.
3. Les contestations doivent faire partie du résumé de la semaine fait par
   l'IA.

Décisions d'Ilane (01/10/2026, questions posées en séance) :

- **D1** : le bouton est sur **toutes les rangées** de l'onglet Prix (toutes
  les alertes de prix R19 à R25), pas seulement « Produit absent de la
  grille ».
- **D2** : **démo seulement** pour l'IA : le code est livré partout, mais le
  bouton et le résumé ne fonctionnent que là où l'IA est allumée. L'IA reste
  éteinte en production tant que l'avenant §15 n'est pas confirmé.
- **D3** : dans la grille, **rangée + section** : un lien « N contestations »
  sur la rangée du produit déplie son historique ; une section « Contestations
  de prix » sous le tableau liste tout, y compris les produits absents de la
  grille.
- **D4** : **contestations seulement** : les prix « ignorés » n'apparaissent
  ni dans la grille ni dans le résumé.

Cette demande lève le gel de l'IA du 29/09 pour ces deux usages seulement
(bouton, résumé) ; rien d'autre ne change dans l'IA.

## 2. Ce qui existe déjà (dev, 8c4d27a)

- `ingest.ia_prix.rechercher_prix` interroge l'agent `habitat-prix` (jusqu'à
  cinq offres, contrôles par offre, HT). `chercher_prix_internet` (commande
  `ia-prix`, non planifiée) ne cherche que R22 sans dernier prix utile, avec
  un cache de 30 jours et au plus 3 échecs par produit sur 7 jours, et écrit
  une ligne `PrixInternet` par produit cherché.
- `GET /api/ia/prix-internet?anomalie_ids=…` (`prix_internet_des_anomalies`)
  rend, pour les rangées R22, le dernier résultat `trouve`/`non_verifiable`
  de moins de 30 jours ; la colonne « Internet » de `/prix` n'existe que si
  `ia_active` ; `PrixInternetCellule` affiche un tiret hors R22.
- Le Laboratoire IA lance ses essais en tâche de fond
  (`fastapi.BackgroundTasks`, `ingest.ia_labo`) et garde leur état en
  mémoire du processus.
- « Contester » (`ingest.prix_bl.contester_prix`) ferme toutes les alertes
  du groupe au statut `traitee`, commentaire `« Contesté : <texte> »`,
  `traitee_par`/`traitee_le` renseignés, journal `anomalie_traitee` par
  alerte et `prix_conteste` pour l'action ; la grille n'est pas touchée.
  Une alerte fermée n'est jamais rouverte (`synchroniser_anomalies`, L4-D12).
- `ingest.prix_bl._cle_groupe` donne la clé produit de grille d'une ligne en
  alerte (`normalize.prix.cle_produit`), la même que `valider_prix` utilise.
- La synthèse de la semaine (`ingest.ia_synthese`) envoie à l'agent
  `habitat-synthese` les commentaires de lignes de la semaine (`[cN]`, sans
  auteur), garde la réponse avec `extract.reponses_ia.lire_synthese`
  (références valides imposées) et écrit `SyntheseCommentaires` +
  `SyntheseAction` (`commentaire_ids`, `document_ids`). Semaine sans
  commentaire : aucune sollicitation de l'IA.

## 3. Partie A — Recherche internet à la demande

### 3.1 Serveur

- **Route** `POST /api/ia/prix-internet/recherches` (admin), corps
  `{"anomalie_id": "<uuid>"}` → `202` `{"etat": "lancee" | "deja_en_cours"}`.
  - `404` : anomalie introuvable, non `ouverte`, hors R19–R25, ou masquée
    (même sélection que la lecture groupée, §3.2).
  - `409` « IA éteinte » si `ia_active()` est faux.
  - `409` « Plafond du jour atteint » si le plafond d'appels du jour est
    déjà atteint au moment du clic.
- **Service** `ingest.ia_prix.lancer_recherche_prix(sessions, http,
  background_tasks, anomalie_id)` : calcule la clé internet de l'anomalie
  (`_cle_produit_pour_anomalie`, désignation et code du bon, fournisseur du
  document) ; si une recherche de cette clé est déjà en cours, rend
  `deja_en_cours` sans rien lancer ; sinon l'inscrit en cours et lance la
  tâche de fond.
- **Tâche de fond** : `rechercher_prix` puis **le même enregistrement que
  `chercher_prix_internet`** (factorisé dans une fonction commune, jamais
  dupliqué) : ligne `PrixInternet` `trouve`/`non_verifiable`, ou `echec`
  (`ErreurIA`, réponse invalide). Un clic **ignore le cache de 30 jours et la
  limite de 3 échecs** (décision humaine), mais **respecte le plafond
  quotidien** (`IAIndisponible("plafond")` : rien n'est écrit).
- **État en mémoire** (un seul processus, comme le Laboratoire) : par clé,
  `en_cours` puis, à la fin, `termine` ou `echec` avec un message court en
  français (« Plafond du jour atteint », « IA éteinte », « La recherche a
  échoué ») gardé 15 minutes. Un redémarrage de l'API efface cet état (la
  recherche en cours est perdue, la cellule revient à son bouton).
- La commande `ia-prix` ne change pas (toujours R22 sans dernier prix).

### 3.2 Lecture groupée

`prix_internet_des_anomalies` (et donc `GET /api/ia/prix-internet`) couvre
**toutes les alertes de prix ouvertes R19–R25** non masquées, plus seulement
R22. Pour chaque anomalie, la réponse ajoute `recherche` :
`null`, ou `{"etat": "en_cours" | "echec", "message": str | null}` (état en
mémoire de sa clé ; `termine` n'est pas renvoyé : le résultat est alors en
base). `avis_ia_anomalie` (encart de la page d'un problème) ne change pas.

### 3.3 Écran (`/prix`, ordinateur et téléphone)

Colonne « Internet », visible seulement si `ia_active` (inchangé), sur
**toutes** les rangées :

| Situation | Affichage |
|---|---|
| Aucun résultat, rien en cours | bouton « Chercher sur internet » |
| `recherche.etat = en_cours` | « Recherche en cours… » (bouton désactivé) |
| Résultat `trouve` | affichage actuel (« dès … HT · N sources », liens) + lien « Relancer » |
| Résultat `non_verifiable` | « introuvable » (raison en `title`) + « Relancer » |
| `recherche.etat = echec` | message court + « Réessayer » |

- Le bouton envoie le **premier identifiant de la rangée** (même règle que
  la lecture actuelle, ruling T10b).
- Tant qu'au moins une rangée est `en_cours`, la lecture groupée est relue
  toutes les 10 secondes (TanStack Query `refetchInterval`), puis s'arrête.
- Erreur `409` au clic : son message s'affiche dans la cellule.

## 4. Partie B — Contestations dans la grille du fournisseur

### 4.1 Serveur

- **Service** `ingest.prix_bl.contestations_du_fournisseur(session,
  fournisseur_id) -> list[ContestationVue]` : anomalies `traitee` dont le
  commentaire commence par `« Contesté : »`, règle R19–R25, document de ce
  fournisseur non archivé. **Une contestation = une ligne de bon** (R19 et
  R20 sur la même ligne donnent une seule entrée). Plus récentes d'abord,
  500 au plus.
- `ContestationVue` : `conteste_le` (`traitee_le`), `auteur` (nom de
  l'utilisateur), `document_id`, `numero_bon`, `date_bon`, `produit`
  (désignation du bon), `code`, `prix_bon`, `unite_bon`, `prix_grille` (celui
  de l'alerte, s'il existe), `ecart_pct` (s'il existe), `alertes` (libellés
  des règles), `commentaire` (sans le préfixe « Contesté : »), `cle_produit`
  (même calcul que `_cle_groupe`), `dans_la_grille` (la clé correspond à un
  produit **actuellement** dans la grille du fournisseur).
- **Route** `GET /api/grilles/fournisseurs/{fournisseur_id}/contestations`
  (admin) ; `404` si le fournisseur n'existe pas.
- Aucune migration : tout est lu dans `anomalie`, `ligne`, `document`,
  `utilisateur` et `grille_prix`. Les contestations déjà faites apparaissent.

### 4.2 Écran (`/fournisseurs/:id/prix`)

- Sur chaque produit de la grille ayant des contestations (même
  `cle_produit`) : lien « ⚑ N contestation(s) » qui déplie, sous la rangée
  (tableau) ou dans la carte (téléphone), l'historique : date · bon (lien
  vers la page du bon) · prix du bon · auteur, puis le commentaire.
- Sous le tableau, section **« Contestations de prix (N) »** : toutes les
  contestations, regroupées par produit (`cle_produit`), les produits absents
  de la grille marqués « absent de la grille ». Section absente si N = 0.
- La recherche de la grille ne filtre pas cette section.

## 5. Partie C — Contestations dans le résumé de la semaine

- `ia_synthese` charge, en plus des commentaires, les **contestations de la
  semaine** (`traitee_le` dans la semaine, heure de Paris), regroupées par
  (fournisseur, `cle_produit`, commentaire) : une contestation sur trois bons
  du même produit donne **une** entrée. 50 au plus (les plus récentes), avec
  une phrase de troncature comme pour les commentaires.
- Chacune part vers l'IA sous une référence `[pN]` : jour, fournisseur,
  produit, numéros des bons, prix du bon, prix de grille s'il existe,
  commentaire. **Jamais l'auteur**, ni le chantier, ni le client (même
  minimisation que les commentaires).
- La consigne parle des « commentaires et contestations de prix » ; une
  action cite des références `cN` et/ou `pN`. `lire_synthese` reçoit
  l'union des deux ensembles de références valides (signature inchangée).
- `SyntheseAction` : `commentaire_ids` = commentaires cités ; `document_ids`
  = bons des commentaires **et** des contestations cités (les liens « bon »
  de l'accueil marchent donc pour les deux). Aucune migration.
- Semaine **sans commentaire ni contestation** : `vide`, aucune
  sollicitation de l'IA, résumé « Aucun commentaire ni contestation cette
  semaine. ». Une semaine avec seulement des contestations est résumée.
- Le journal `synthese_generee` ajoute `nb_contestations`.
- L'essai de synthèse du Laboratoire IA utilise le même chargement (aucune
  seconde implémentation).
- Les synthèses déjà générées ne sont pas refaites.

## 6. Hors périmètre

Les prix « ignorés » (D4) ; l'encart IA de la page d'un problème ; la
planification de `ia-prix` ou de la synthèse ; l'IA en production (D2) ; un
écran de modification ou d'annulation d'une contestation ; toute
modification de la grille par une contestation.

## 7. Règles à respecter

- Frontières (`tests/test_frontieres.py`) : la logique dans `ingest` ; `api`
  n'importe que `ingest` et `app.core` ; `extract`, `normalize`, `rules`
  restent purs. Aucune règle métier dans le front.
- L'IA ne décide rien : aucun prix internet ni aucune synthèse ne crée, ne
  ferme ou ne modifie une anomalie ou une grille.
- Aucune donnée réelle du client dans les tests, les journaux ou les
  messages de commit.

## 8. Tests

- **A** : lancement (`lancee`, `deja_en_cours`), `404` (inconnue, fermée,
  hors prix, masquée), `409` (IA éteinte, plafond), clic qui ignore le cache
  et la limite d'échecs, plafond atteint pendant la recherche (rien écrit,
  état `echec`), enregistrement identique à `ia-prix` (même fonction), état
  en mémoire expiré après 15 minutes, lecture groupée sur R19–R25 et champ
  `recherche`, accès admin seulement ; écran : bouton, « Recherche en
  cours… », relecture toutes les 10 s puis arrêt, « Relancer »,
  « Réessayer », message d'un `409`.
- **B** : seules les contestations (pas les ignorées, ni les validées, ni
  les autres règles), une entrée par ligne de bon, préfixe retiré, bon
  archivé exclu, autre fournisseur exclu, `dans_la_grille` vrai/faux (dont
  produit retiré), ordre et plafond, `404` fournisseur ; écran : lien et
  dépliage sur la rangée, section avec « absent de la grille », section
  absente sans contestation.
- **C** : contestations de la semaine seulement (bornes heure de Paris),
  regroupement par produit et commentaire, `[pN]` sans auteur, troncature,
  semaine vide (aucune sollicitation) et semaine avec seulement des
  contestations, références `pN` acceptées et `document_ids` complétés,
  `nb_contestations` au journal, essai du Laboratoire identique.

## 9. Livraison

Une branche, une PR vers `dev`, relecture, puis déploiement **sur la démo
seulement**. Le passage en production attend l'accord d'Ilane (la partie B y
serait utile dès que le contrôle des prix sera allumé ; A et C y restent
inactives tant que l'IA est éteinte). README et `docs/dette.md` mis à jour
dans la même PR.
