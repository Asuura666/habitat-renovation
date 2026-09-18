# Plan — Lot 5 (Restitution)

> **Pour les agents :** exécuté par `superpowers:subagent-driven-development` (une fiche par tâche, implémenteur Sonnet, relecteur Sonnet). Chaque tâche = un commit (plus d'éventuels commits de correction).

**Objectif (CDC §11) :** donner à voir ce que le système a compris. Deux écrans — **Chantiers & fournisseurs** et **Bilan** —, la navigation chantier → fournisseur → BL → document source, l'export CSV, la synchronisation Google Drive, l'écran de journal et le paramétrage des seuils. Ce que le client voit à la fin du lot : **le bilan d'août reconstitué, consultable sur téléphone**.

**Critères de réception (CDC §10, lot Restitution) :**
- Le Bilan d'un mois se parcourt du chantier jusqu'au document source en trois taps, sur téléphone, sans défilement horizontal.
- À chaque niveau, les quatre montants (facturé HT, rapproché, en écart, non justifié) et le nombre d'anomalies ouvertes sont affichés et cohérents avec les écrans Factures et Anomalies.
- L'export CSV d'un mois s'ouvre dans Excel en français sans manipulation.
- Chaque document déposé est retrouvable dans le Drive du client sous `Fournisseurs/<fournisseur>/<AAAA-MM>/`.
- Toute action d'un utilisateur est retrouvable dans le journal, avec auteur et horodatage.

**Architecture :** on s'appuie sur les lots 1 à 4. Ce lot ajoute un service de lecture agrégée dans `ingest` (`bilan.py`, `referentiels_vue.py`), les routes `api/bilan.py`, `api/journal.py`, `api/parametres.py`, les écrans `web/src/pages/Bilan.tsx` et `web/src/pages/Chantiers.tsx`, le paquet `app/modules/jobs/` (qui n'existe pas encore) pour la synchronisation Drive, et deux migrations (`0008`, `0009`).

**Spec :** `docs/cahier-des-charges.md` (§4.6, §4.7, §6, §8, §10, §11). À lire aussi : `docs/passation-lot-4.md`, `docs/lot-4-recette.md`, `docs/dette.md`, `docs/exploitation-lot-4.md`.

**Statut :** plan écrit en autonomie (mandat d'Ilane du 17/09/2026 : fusionner le lot fini dans `main` puis enchaîner le lot suivant sans redemander). Chaque décision prise sans Ilane est listée en §4 avec son coût si elle est mauvaise.

---

## 1. Contraintes globales

Celles des lots 1 à 4 (`docs/plan-lot-4.md` §1, `CLAUDE.md`) s'appliquent toutes. Les plus exposées ici :

- `extract`, `normalize` et `rules` restent **purs** : ni FastAPI, ni SQLAlchemy, ni httpx, ni log, aucun import d'un autre module de `app.modules`. Ce lot n'a aucune raison d'y toucher.
- `ingest` est le seul orchestrateur. `api` et `jobs` sont des **couches d'entrée** : elles n'importent que `ingest` et `app.core` (décision L2-D3). `jobs` n'est pas une exception parce qu'il est nouveau.
- **Aucune règle métier dans le front ni dans les routers.** Un agrégat de bilan est une somme, pas une règle : il vit dans `ingest`, le router le sérialise, le front le met en forme. Le front ne calcule ni total, ni pourcentage, ni écart.
- Montants, quantités, taux : `Decimal`, jamais `float`. Y compris dans les agrégats SQL et dans l'export CSV.
- Toute action d'un utilisateur qui modifie une donnée métier est journalisée ; les décisions automatiques le sont avec `utilisateur_id = NULL`.
- Données client : aucune valeur réelle dans le code, les tests, les commits, les logs ou les messages. Les fixtures réelles restent dans `tests/fixtures/` (hors dépôt) ; un test qui les lit fait `pytest.skip` si absentes et n'affirme que des booléens calculés d'avance (Ruling R7 du lot 3).
- Front : React 18 + TypeScript + Vite, React Router, TanStack Query, Tailwind (`extend`), types générés par `openapi-typescript`. Interdits : tout autre state manager, `localStorage` pour l'auth, CORS, JWT, toute nouvelle dépendance npm.
- Interface en français. **Les écrans Bilan et Anomalies sont conçus pour téléphone d'abord** ; Factures et Chantiers & fournisseurs restent lisibles sur téléphone avec défilement horizontal des tableaux (CDC §4.6).
- Un seul processus pytest à la fois par base de test (`bl_test`, `bl_test_wt` pour un second arbre de travail).

## 2. Constats (état au début du lot 5, `main` @ `c9f51a5`)

1. **Le rapprochement est persisté.** `bloc_facture.bl_document_id` et `bloc_facture.statut_rapprochement` (`recu` / `non_recu` / `pas_de_bon`) sont écrits par `ingest/rapprochement.py` (L4-D4). La navigation chantier → fournisseur → BL peut s'appuyer dessus sans rien recalculer.
2. **Le chantier vit à deux endroits** : `document.chantier_id` (BL et enlèvements, migration 0005) et `bloc_facture.chantier_id` (blocs de facture). Un bilan par chantier doit lire les deux, jamais un seul.
3. **Les anomalies sont lisibles** : `ingest/anomalies.py::lister_anomalies` et `GET /api/anomalies` existent, avec filtres règle/gravité/statut/chantier/fournisseur/période. `CHANTIER_ID_RESOLU` (`COALESCE(Anomalie.chantier_id, BlocFacture.chantier_id, Document.chantier_id)`) est la seule expression qui résout le chantier d'une anomalie : le bilan doit la réutiliser, pas en écrire une deuxième.
4. **Les seuils sont en base** : table `parametre` (clé texte, valeur texte, `modifie_par`, `modifie_le`), neuf clés créées avec leur valeur par défaut au premier rapprochement (L4-D10) : `tolerance_total_ht` (0,05), `seuil_prix_pct` (5), `seuil_prix_fort_pct` (15), `occurrences_prix_min` (3), `delai_ligne_bl_non_facturee_j` (45), `delai_alias_non_resolu_h` (48), `delai_confirmation_bl_h` (24), `delai_chantier_silencieux_j` (7), `duree_ignorance_j` (90). **Aucun écran ne permet de les modifier.** `lire_parametre_decimal` existe (`ingest/referentiels.py`).
5. **Le journal est écrit mais jamais lu** : table `journal` (append-only : `utilisateur_id` nullable, `action`, `cible_table`, `cible_id`, `avant`/`apres` en JSONB, `horodatage`). Aucune route, aucun écran.
6. **`app/modules/jobs/` n'existe pas.** `document.drive_url` existe en base (migration 0001) et n'est jamais renseigné. Aucune dépendance Google n'est installée.
7. **Le fuseau est nommé** : `app/core/fuseau.py::FUSEAU_PARIS` (lot 4). Tout regroupement par mois ou par jour doit s'y référer — le serveur tourne en UTC.
8. **Le référentiel existe en écriture** : `GET /api/chantiers`, `POST /api/chantiers`, `GET /api/fournisseurs`, validation d'alias et d'article (`api/referentiels.py`). Il manque la **vue** : dépôts par agent sur 30 jours, chantiers sans dépôt depuis plus de 7 jours.
9. **Deux écrans du CDC §4.6 sont livrés** (Factures, Anomalies) et un troisième existe partiellement (À traiter). Le lot 5 livre les deux derniers.
10. **Aucun document réel supplémentaire ne viendra** (Ilane, 17/09) : le bilan sera démontré sur la facture d'août et les trois BL correspondants, plus des données inventées pour les cas que ces documents ne couvrent pas.

## 3. Questions à Ilane (non bloquantes, décisions provisoires en §4)

- **Q1 — Google Drive.** Le lot 5 a besoin d'un compte de service Google et d'un dossier cible. Rien n'a été fourni. Provisoire : la synchronisation est construite et testée contre un faux client, mais **non activée** faute de secret (L5-D7). Si le Drive n'arrive pas, les quatre autres livrables partent sans lui.
- **Q2 — Définition des quatre montants.** « Facturé HT », « rapproché », « en écart », « non justifié » ne sont pas définis dans le CDC. Provisoire : L5-D3. C'est **la** question à poser en priorité : tout le Bilan en dépend.
- **Q3 — Contenu de l'export CSV.** Le détail par BL, ou seulement les niveaux agrégés ? Provisoire : un export par niveau affiché, mêmes colonnes que l'écran (L5-D5).
- **Q4 — Qui voit le journal ?** Provisoire : admin seulement, comme l'écran Anomalies.
- **Q5 — Verdicts d'août.** Q6 du lot 4 reste ouverte : le classement reçu / non reçu / pas de bon des 28 blocs n'a pas été confirmé. Le Bilan les présentera tels quels, avec la même réserve dans la recette.
- **Q6 — Agences.** Le CDC demande un filtre « par agence » sur le Bilan. `chantier.agence` est un texte libre, jamais renseigné à ce jour. Provisoire : le filtre existe et liste les valeurs distinctes présentes, vide tant que personne ne renseigne le champ (L5-D6).

## 4. Décisions prises en autonomie

- **L5-D1 — Les agrégats vivent dans `ingest`.** Un service de lecture (`ingest/bilan.py`) produit des dataclasses ; le router sérialise ; le front met en forme. Aucune somme dans un router ni dans le front. *Si faux : du code à déplacer, pas à réécrire.*
- **L5-D2 — Pas de table d'agrégat, pas de cache.** Les montants sont calculés à la demande par des requêtes SQL agrégées. Un seul client, un mois à la fois, quelques milliers de lignes. *Si faux : une lenteur mesurable, à corriger par un index ou une vue matérialisée — noté dans `docs/dette.md` si la mesure de recette dépasse une seconde.*
- **L5-D3 — Définition des quatre montants.** Au périmètre considéré (un chantier, ou un fournisseur dans un chantier, ou un mois) :
  - **facturé HT** = somme des `montant_ht` des lignes de type `article` et `eco` des blocs du périmètre ;
  - **rapproché** = même somme, restreinte aux blocs dont `statut_rapprochement = 'recu'` ;
  - **en écart** = même somme, restreinte aux blocs portant au moins une anomalie **ouverte** de quantité ou de prix (R03, R04, R05, R06, R07, R08, R09) ;
  - **non justifié** = même somme, restreinte aux blocs dont `statut_rapprochement` vaut `non_recu` ou `pas_de_bon`.
  Ces quatre montants **ne forment pas une partition** : un bloc reçu peut être en écart. L'écran doit le dire en toutes lettres, sinon le client additionnera. *Si faux : quatre requêtes à réécrire, aucune donnée perdue.*
- **L5-D4 — Le mois d'un bloc est celui de sa facture.** `document.date_doc` de la facture, faute de quoi `document.created_at` converti en Europe/Paris. Pas `date_bl` : un BL de fin de mois facturé le mois suivant appartient au mois de facturation, qui est ce que le client rapproche de ses comptes. *Si faux : un regroupement à changer, visible immédiatement sur le bilan d'août.*
- **L5-D5 — Export CSV : le niveau affiché, rien de plus.** Une route par niveau, mêmes colonnes que le tableau, même filtre. `text/csv; charset=utf-8` avec BOM, séparateur `;`, virgule décimale (Excel français ouvre le fichier sans assistant d'importation). Généré côté serveur, jamais reconstitué par le front. *Si faux : des colonnes à ajouter.*
- **L5-D6 — Le filtre par agence liste l'existant.** Les valeurs distinctes non nulles de `chantier.agence`, triées. Aucune table d'agences, aucune saisie. *Si faux : une table à créer plus tard, sans migration de données.*
- **L5-D7 — Drive : une commande, pas un service.** Pas de Redis, pas de Celery (interdits). Une commande CLI `drive-sync` appelée par cron, sur le modèle de `controles-differes` (lot 4). L'état de synchronisation est porté par le document (migration 0009 : `drive_sync_le`, `drive_sync_echec_le`, `drive_sync_erreur`). Réessai à chaque passage, signalement sur le canal de supervision Telegram après 24 h d'échec. *Si faux : une commande à transformer en boucle, sans changer le modèle.*
- **L5-D8 — Le client Drive est derrière une interface.** `jobs/drive.py` définit un protocole minimal (`televerser(chemin, dossier, nom) -> url`) et une implémentation Google ; les tests utilisent une implémentation en mémoire. C'est la seule abstraction « pour plus tard » autorisée de ce lot, et elle l'est pour la même raison que `messaging/base.py` : sans elle, aucun test ne peut tourner sans réseau. *Si faux : une indirection à retirer.*
- **L5-D9 — Paramétrage : les neuf clés connues, pas une de plus.** L'écran liste les neuf clés du lot 4, chacune avec son libellé français, son unité et ses bornes. Une clé inconnue n'est pas créable depuis l'écran. Les bornes sont validées **dans le service**, pas dans le front. Toute écriture est journalisée avec l'ancienne et la nouvelle valeur. *Si faux : des bornes à ajuster.*
- **L5-D10 — Le journal est lu en pagination simple.** Filtres : auteur, action, table cible, période. Pas de recherche plein texte dans `avant`/`apres` (JSONB, coûteux, non demandé). Plafond de pagination comme pour les anomalies. *Si faux : un filtre à ajouter.*
- **L5-D11 — La navigation du Bilan passe par l'URL.** `/bilan`, `/bilan/:chantierId`, `/bilan/:chantierId/:fournisseurId`. Un niveau = une route, donc un lien partageable et un retour navigateur qui fonctionne. Les filtres (mois, agence) sont des paramètres de requête. *Si faux : des routes à aplatir.*
- **L5-D12 — Sur téléphone, un niveau par écran.** Cartes empilées, fil d'Ariane en tête, les quatre montants et le nombre d'anomalies visibles sans défilement horizontal (CDC §4.6, explicite). Le tableau complet et l'export n'apparaissent qu'à partir de `md`. *Si faux : de la mise en page à refaire.*

## 5. Structure des fichiers

```
app/
  core/
    fuseau.py                    (existe)
  modules/
    ingest/
      bilan.py                   NOUVEAU — agrégats des trois niveaux, vue inverse
      referentiels_vue.py        NOUVEAU — dépôts par agent, chantiers silencieux, agences
      journal.py                 NOUVEAU — lecture paginée du journal
      parametres.py              NOUVEAU — lecture/écriture des neuf seuils, journalisée
      export.py                  NOUVEAU — sérialisation CSV des vues de bilan
      tests/
    api/
      bilan.py                   NOUVEAU
      journal.py                 NOUVEAU
      parametres.py              NOUVEAU
      referentiels.py            (étendu : routes de vue)
      schemas.py                 (étendu)
    jobs/                        NOUVEAU PAQUET
      __init__.py
      drive.py                   protocole + client Google
      drive_sync.py              orchestration d'un passage
      tests/
web/src/
  pages/
    Bilan.tsx                    NOUVEAU
    BilanFournisseur.tsx         NOUVEAU
    Chantiers.tsx                NOUVEAU
    Journal.tsx                  NOUVEAU
    Reglages.tsx                 NOUVEAU
  api/
    bilan.ts, journal.ts, parametres.ts, referentiels.ts   NOUVEAUX
  lib/
    formats.ts                   (étendu si besoin)
migrations/versions/
  0008_anomalie_bloc_origine.py  NOUVEAU (L5-T1, tour 2 — Ruling L5-R6)
  0009_drive_sync.py             NOUVEAU (L5-T11)
docs/
  plan-lot-5.md                  (ce document)
  lot-5-recette.md               NOUVEAU (L5-T12)
  passation-lot-5.md             NOUVEAU (L5-T12)
  exploitation-lot-5.md          NOUVEAU (L5-T11, ligne cron Drive)
```

## 6. Tâches

### L5-T1 — `ingest: agrégats du bilan par chantier`
Crée `ingest/bilan.py`. Dataclasses `MontantsBilan(facture_ht, rapproche, en_ecart, non_justifie, nb_anomalies_ouvertes)` (tous `Decimal`, sauf le compte) et `LigneBilanChantier(chantier_id, nom_canonique, agence, montants)`. Fonction `async def bilan_par_chantier(session, *, mois: date | None, agence: str | None) -> list[LigneBilanChantier]`, triée par montant facturé décroissant. Les quatre montants suivent L5-D3 ; le mois suit L5-D4 ; le chantier d'un bloc est `COALESCE(bloc_facture.chantier_id, document.chantier_id)` (constat 2). Réutilise l'ensemble de règles de quantité/prix défini une seule fois, nommé, dans ce module.
Tests avec base : un chantier avec un bloc reçu sans anomalie, un avec un bloc non reçu, un avec un bloc reçu portant une anomalie de quantité ouverte (donc compté deux fois : rapproché **et** en écart — c'est le point du L5-D3), un mois voisin exclu par le filtre, une anomalie traitée qui ne compte pas, un bloc de facture archivée exclu.

### L5-T2 — `ingest: niveaux fournisseur et BL, vue inverse`
Étend `bilan.py` : `bilan_par_fournisseur(session, *, chantier_id, mois, agence)` et `bilan_par_bl(session, *, chantier_id, fournisseur_id, mois)`, mêmes montants, plus `LigneBilanBl(bloc_id, numero_bl, date_bl, statut_rapprochement, bl_document_id, facture_id, montants)`. Ajoute la vue inverse `bilan_par_fournisseur_global` et `bilan_chantiers_du_fournisseur`. Factorise les quatre agrégats dans une seule expression paramétrée par le regroupement — une duplication verbatim entre les cinq fonctions est un défaut.
Tests : cohérence entre niveaux (la somme des fournisseurs d'un chantier égale le chantier), un bloc sans chantier résolu (regroupé sous « chantier non résolu », jamais ignoré silencieusement), la vue inverse qui retrouve les mêmes montants.

### L5-T3 — `api: routes du bilan`
`api/bilan.py` : `GET /api/bilan/chantiers`, `GET /api/bilan/chantiers/{chantier_id}/fournisseurs`, `GET /api/bilan/chantiers/{chantier_id}/fournisseurs/{fournisseur_id}/bl`, `GET /api/bilan/fournisseurs` (vue inverse). Filtres `mois` (type `date`, premier jour du mois, converti en journée parisienne comme au lot 4 — **pas** de chaîne libre) et `agence`. Admin uniquement. Schémas Pydantic dans `api/schemas.py`, montants sérialisés en chaînes décimales (jamais `float`).

**Pas de route d'agences ici** (Ruling L5-R10) : la liste des agences est déjà rendue par `GET /api/referentiels/agences` (L5-T7). Une même liste exposée par deux routes, c'est une divergence programmée ; l'écran Bilan appelle celle des référentiels pour son filtre.
Tests d'API : 401 anonyme, 403 agent, 200 admin, filtre par mois, filtre par agence, 422 sur un mois mal formé, chantier inconnu → liste vide et non 404 (c'est une vue, pas une ressource).

### L5-T4 — `ingest/api: export CSV`
`ingest/export.py` : `csv_bilan_chantiers(lignes) -> str`, une fonction par niveau, sortie en mémoire (`io.StringIO`, module `csv` de la bibliothèque standard, `delimiter=";"`). Virgule décimale, BOM UTF-8 ajouté par le router. Route `GET /api/bilan/<niveau>.csv` avec les mêmes filtres et le même service que la vue JSON — jamais une deuxième requête.
Tests : en-têtes et ordre des colonnes, séparateur, virgule décimale, présence du BOM dans la réponse HTTP, `Content-Disposition` avec un nom de fichier parlant, valeurs absentes rendues par une cellule vide et non par « None ».

### L5-T5 — `web: écran Bilan, niveau chantier (ordinateur et téléphone)`
`web/src/pages/Bilan.tsx`, `web/src/api/bilan.ts`. Filtres mois et agence dans l'URL (L5-D11). Tableau à partir de `md`, cartes empilées en dessous (L5-D12) : une carte par chantier, les quatre montants et le nombre d'anomalies visibles sans défilement horizontal. Une phrase fixe, sous les filtres, dit que les quatre montants ne s'additionnent pas. Bouton d'export visible seulement à partir de `md`. État vide explicite. Régénère `openapi.json` et les types.
Vérification visuelle à 375 px et 1280 px, données inventées, captures dans `var/captures/`.

### L5-T6 — `web: niveaux fournisseur et BL, navigation et vue inverse`
`BilanFournisseur.tsx` et le niveau BL. Fil d'Ariane chantier → fournisseur → BL à tous les niveaux, chaque segment cliquable. Depuis un BL : un lien vers la photo d'origine (`bl_document_id`) ou vers le bloc de facture, et un lien vers ses anomalies (l'écran Anomalies existe, filtré — pas de duplication). Bascule « vue par fournisseur ».
Vérification visuelle des trois niveaux aux deux largeurs, et du parcours complet en trois taps sur téléphone (critère de réception).

### L5-T7 — `ingest/api: vue des référentiels`
`ingest/referentiels_vue.py` : `depots_par_agent(session, *, jours=30)`, `chantiers_sans_depot(session, *, jours)` (le seuil vient du paramètre `delai_chantier_silencieux_j`, pas d'une constante), `agences_connues(session)`. Routes dans `api/referentiels.py`.
Tests : un agent sans dépôt apparaît avec zéro, un chantier fermé n'est pas signalé comme silencieux, le seuil est bien lu depuis la table `parametre`.

### L5-T8 — `web: écran Chantiers & fournisseurs`
`Chantiers.tsx` : référentiel chantiers (avec création, qui existe déjà côté API), fournisseurs et leurs agences, alias en attente de validation (route existante), dépôts par agent sur 30 jours, chantiers sans dépôt. Tableaux, lisibles sur téléphone avec défilement horizontal (CDC §4.6 : cet écran est « ordinateur »).
Vérification visuelle aux deux largeurs.

### L5-T9 — `ingest/api/web: journal consultable`
`ingest/journal.py::lister_journal(session, *, utilisateur_id, action, cible_table, depuis, jusqu_a, limite)` (L5-D10), route admin, écran `Journal.tsx`. Les valeurs `avant`/`apres` sont affichées telles quelles, sans interprétation métier. Les actions ont un libellé français (même principe que `lib/regles.ts` : mise en forme uniquement).
Tests : filtres, plafond de pagination, 403 agent, une décision automatique (auteur nul) affichée comme telle.

### L5-T10 — `ingest/api/web: paramétrage des seuils`
`ingest/parametres.py` : `lister_parametres(session)`, `modifier_parametre(session, cle, valeur, *, auteur_id)` avec validation des bornes **dans le service** (L5-D9) et journalisation `parametre_modifie` (avant/après). Route admin, écran `Reglages.tsx` : une ligne par clé, libellé français, unité, bornes affichées.
Tests : clé inconnue refusée, valeur hors bornes refusée, écriture journalisée, la valeur modifiée est bien celle relue par le rapprochement au passage suivant.

### L5-T11 — `jobs/migration/cli: synchronisation Drive`
Migration `0009_drive_sync.py` (`document.drive_sync_le`, `drive_sync_echec_le`, `drive_sync_erreur`). Paquet `app/modules/jobs/` : `drive.py` (protocole `ClientDrive` + implémentation Google, L5-D8), `drive_sync.py::synchroniser_documents(session, client, *, limite)` — chemin `Fournisseurs/<fournisseur>/<AAAA-MM>/`, nom `<type>_<numero>_<chantier>.<ext>`, `document.drive_url` renseigné, échec réessayé au passage suivant, signalement sur le canal de supervision après 24 h. Commande CLI `drive-sync`. `docs/exploitation-lot-5.md` avec la ligne cron.
Rappel de frontière : `jobs` n'importe que `ingest` et `app.core`. Tests avec un client en mémoire, sans réseau : nom normalisé (accents, espaces, caractères interdits), idempotence (un document déjà synchronisé n'est pas renvoyé), échec puis succès au passage suivant, signalement après 24 h et une seule fois.
**Si le secret Google n'est pas fourni** (Q1), la commande refuse de démarrer avec un message clair — `app/core/config.py` est en *fail-fast*, on ne démarre pas à moitié.

### L5-T12 — `docs: recette et passation du lot 5`
`docs/lot-5-recette.md` (ce qui est fait, vérification commande par commande, **le bilan d'août reconstitué** avec ses comptes — jamais de valeur client —, ce qui n'est pas vérifiable, décisions L5-D1 à L5-D12, questions Q1 à Q6), `docs/passation-lot-5.md` (même forme que `docs/passation-lot-4.md`, avec le point de départ du lot 6), `docs/dette.md` complété, section « Où en est le projet » de `CLAUDE.md` mise à jour.

## 7. Récapitulatif des tests

| Zone | Sans base | Avec base | Manuel |
| --- | --- | --- | --- |
| Agrégats chantier | | L5-T1 | bilan d'août (contrôleur) |
| Niveaux fournisseur et BL, vue inverse | | L5-T2 | |
| Routes du bilan | | L5-T3 | |
| Export CSV | L5-T4 (sérialisation) | L5-T4 (route) | ouverture dans un tableur |
| Bilan (front) | typecheck, build | | parcours 3 taps à 375 px |
| Vue des référentiels | | L5-T7 | |
| Chantiers & fournisseurs (front) | typecheck, build | | 375 px et 1280 px |
| Journal | | L5-T9 | |
| Paramétrage | | L5-T10 | |
| Drive | L5-T11 (client en mémoire) | L5-T11 (état en base) | non activable sans secret (Q1) |
