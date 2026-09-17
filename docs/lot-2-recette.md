# Recette du lot 2 (Collecte) — Contrôle BL & factures

Branche `lot-2-collecte` (worktree `/home/debian/habitat_reno-wt-l2`), tâches
L2-T1 à L2-T8, suivies de la vague de correction finale issue de la revue
complète de la branche (`9254ffe..44ba9d7`, voir §6). Aucune donnée réelle
(numéro, chantier, montant, nom, identifiant Telegram réel, secret) dans ce
document : comptes et écarts uniquement, comme `docs/lot-1-recette.md`.
**Rien n'est fusionné ni poussé** — cette recette reste sur la branche du
worktree.

## À lire d'abord (Ilane)

- **Revue finale de branche close** (§6) : 6 points relevés par la revue
  complète (`9254ffe..44ba9d7`), tous corrigés en 4 commits
  (`9973b02`, `97f740d`, `6298a9d`, et ce commit). `uv run pytest -q` → **359
  passed** (341 avant la vague finale, +18 par les corrections qui ajoutent
  un comportement testé — découpage sans changement de comportement, cf.
  §6). Le lot 2 reste fonctionnellement complet côté code, sous réserve des
  vérifications encore manuelles listées en §4 (Telegram réel, rendu
  visuel, dépôt avec OCR réel), inchangées par cette vague.
- **Revue de L2-T7 close** (mise à jour après ce document) : 1 Important
  relevé (Ruling L2-R8 — voir §2) et corrigé en `2e06aa8`
  (`api: confirmation explicite des BL déposés`). **Approved** après
  correction.
- **Testé réellement ce soir (2026-09-17)** : `uv run pytest -q` → **341
  passed** (336 puis +5 pour la correction L2-R8) ; `npm --prefix web run
  typecheck` → propre ; `npm --prefix web run build` → propre (236,81 kB /
  74,23 kB gzip après correction) ; `uv run pre-commit run --all-files` →
  tous les hooks verts (voir §6). Migrations 0002 à 0004 déjà appliquées sur
  la base `bl` du worktree (`alembic check` : aucune dérive), base vérifiée
  vide de toute donnée de test.
- **Vérifié uniquement par L2-T7 ce soir** (pas rejoué par cette tâche) :
  parcours API réel sans navigateur (login, `/api/moi`, `/api/factures`,
  `/api/factures/{id}`, `/api/documents`, dépôt 422/413) sur une instance
  locale sans Docker ; dépôt de facture réel testé uniquement via le service
  interne avec un OCR **simulé** (fixture rejouée, aucun appel réseau).
- **Jamais testé** : Telegram de bout en bout (deux groupes, boutons, 20
  dépôts consécutifs), rendu visuel réel (aucun navigateur cette nuit,
  mobile 375 px compris), dépôt d'une facture avec un **vrai** appel Mistral
  OCR depuis l'écran.
- **Décisions à valider** : L2-D1 à L2-D17 (`docs/plan-lot-2.md` §4) et
  L2-R1 à L2-R8 (§3 ci-dessous) — toutes prises en autonomie cette nuit,
  aucune n'a de conséquence irréversible en base de production (rien n'est
  déployé).
- **Questions ouvertes** : Q1 à Q5 de `docs/plan-lot-2.md` §3 (§5
  ci-dessous) — notamment Q4 (identifiants des deux groupes Telegram et vrai
  bot) et Q5 (format d'un avoir Unikalo), bloquantes pour le test Telegram
  et pour le typage des avoirs respectivement.
- **Aucun secret ni donnée réelle dans ce document** : `.env` du worktree
  reste en 600, jamais affiché ; les résultats OCR/Telegram sont donnés en
  comptes, jamais en valeur.

## 1. Ce qui est fait

| Tâche | Commit(s) | Résultat de revue (`progress.md`) |
| --- | --- | --- |
| L2-T1 | c7808ca | `auth: connexion par cookie, sessions en base, limitation du login`. Revue → spec ✅, **Approved**, 3 minor (deferred). Complete. |
| L2-T1b | 83e4e1d + correction de92252 | `auth: commandes de gestion des utilisateurs`. Revue → 1 Important (unicité e-mail sensible à la casse vs login insensible, corrigé en de92252), 2 Minor. Re-revue → 3 addressed, 0 open. Complete. |
| L2-T2 | 3baa083 | `messaging: liste blanche, groupe BL et notifications de supervision`. Revue → spec ✅, **Approved**, 3 minor (deferred). Complete. |
| L2-T3 | 92ecf47 + correction a097ac6 | `messaging: numéro interne et boutons de confirmation`. Revue → **1 Critical** (`_numero_interne_valide` sans borne : entrée malformée ou hors bigint → 500 webhook), 1 Important (« Écart » écrasait un document `archive`), 2 Minor. Corrigé en a097ac6, re-revue → 2 addressed, 0 open. Complete. |
| L2-T4 | 5ab195b + correction 4bb3d56 | `ingest: dépôt de facture PDF Unikalo`. Revue → 2 Important (« confiance réduite » §4.2 non représentée ; avoirs non traités — Ruling L2-R5), 2 Minor. Corrigé/documenté en 4bb3d56, re-revue → 3 addressed, 0 open. Complete. |
| L2-T5 | 8a438c8 | `api: factures et documents en lecture`. Revue → spec ✅, **Approved**, 4 minor (deferred). Complete. |
| L2-T6 | 8741881 | `web: socle React, connexion et service statique`. Revue → 1 Important (proxy Vite dev sur le port de vérification isolée 8460 au lieu du port de dev 8450 — Ruling L2-R3), 2 Minor. Corrigé (amendé), re-revue → 3 addressed, 0 open. Complete. |
| L2-T7 | e352a98 + correction 2e06aa8 | `web: écran Factures et onglet BL déposés`. Implémenteur : 336 passed, `typecheck`/`build` propres, parcours local sans Docker (§4). Revue → **1 Important** (le libellé « Vérifié / Écart » de l'onglet BL déposés était dérivé côté front de `statut`+`confirme_le` — faux pour un document `a_verifier` d'origine OCR confirmé ensuite « Quantités vérifiées » ; règle métier dans le front — Ruling L2-R8), 3 Minor (commentaire ECMA-402 sur-évalué, contraste du badge « écart » à vérifier, badge ajouté). Corrigé en 2e06aa8 (`api: confirmation explicite des BL déposés`, champ `confirmation` explicite sur `GET /api/documents`, 5 tests ajoutés, 341 passed). Re-revue → **Approved**, 0 open. Complete. |
| L2-T8 | (ce commit) | Cette recette. |

## 2. Décisions prises en autonomie

### Décisions du plan (`docs/plan-lot-2.md` §4)

| # | Décision (résumé) | Coût si faux |
| --- | --- | --- |
| L2-D1 | Colonnes CDC conservées, attributs fastapi-users mappés dessus (`hashed_password`→`mdp_hash`, `is_active`→`actif`) ; `is_verified`/`is_superuser` dérivés, pas de colonne ajoutée | Une migration de colonnes |
| L2-D2 | Sessions serveur `DatabaseStrategy` (table `jeton_session`), expiration glissante 12 h rafraîchie au plus toutes les 5 min | Réglage |
| L2-D3 | `api`/`jobs` importent `ingest`/`core` seulement, jamais `extract`/`normalize`/`rules`/`messaging` directement ; garde de frontières mis à jour | Garde à ajuster |
| L2-D4 | `core/auth.py` importe `Utilisateur` depuis `ingest/models.py` | Déplacement de modèle |
| L2-D5 | Migration 0002 (`jeton_session`) ; migration 0003 (`document.numero_interne`, `photo_compressee`, `total_ht`) | Colonnes à retirer |
| L2-D6 | Le bot ne traite que `TELEGRAM_CHAT_BL_ID` ; tout autre chat ignoré sans écriture ni réponse | Une condition |
| L2-D7 | Expéditeur non rattaché : aucun document/téléchargement/réponse, un message en supervision avec id + nom Telegram | — |
| L2-D8 | Ligne de supervision par dépôt : `Document n° <interne> · BL <n° ou « non détecté »> · fournisseur — · chantier — · <déposant> · <HH:MM> · <statut>` (fournisseur/chantier « — » jusqu'au lot 3) | Texte |
| L2-D9 | Réponse au dépôt : `Reçu — document n° <numero_interne>` + boutons « Quantités vérifiées » (`v:<n>`) / « Écart constaté » (`e:<n>`) | Texte |
| L2-D10 | Premier clic fait foi (tout utilisateur rattaché actif) ; « Écart » → `statut=a_verifier` ; journal dans les deux cas ; accusé + édition du message | Règle d'autorisation |
| L2-D11 | Dépôt de facture synchrone : `%PDF-`, `lire_facture` (délai 90 s), doublon (même fournisseur/numéro) → 409 ; seul Unikalo reconnu ; 20 Mo max | Passage en tâche de fond si trop lent |
| L2-D12 | Statut BL reçu/non reçu calculé à la lecture, jamais persisté (persistance = rapprochement lot 4) | Une requête |
| L2-D13 | Écran « Factures » : deux onglets (Factures admin / BL déposés admin+agent), rafraîchi 15 s | Onglet à déplacer au lot 3 |
| L2-D14 | Création des utilisateurs par CLI (`utilisateur-creer`/`utilisateur-desactiver`, mot de passe via `getpass`) | Écran au lot 5 si demandé |
| L2-D15 | Types front via schéma OpenAPI + `openapi-typescript` — **remplacé en pratique par le Ruling L2-R1** (script npm, pas de sous-commande CLI) | Ajout d'openapi-fetch |
| L2-D16 | Service front : `StaticFiles` sur `/assets` + fallback `index.html` (hors `/api`,`/tg`,`/health`,`/docs`,`/redoc`,`/openapi.json`), monté seulement si `web/dist` existe | — |
| L2-D17 | Contrôles front en pre-commit : `tsc --noEmit` + `vite build`, pas de tests unitaires front | Dette notée |
| L2-D18 | CSRF (vague finale du lot 2, point 2) : `SameSite=Lax` + pas de CORS + contrôle d'origine (`app/core/origine.py`), pas de jeton CSRF — refuse (403) toute requête modifiante sur `/api/*` dont `Origin` diffère de l'origine du service ou dont `Sec-Fetch-Site` vaut `cross-site` ; absence des deux en-têtes acceptée ; `/tg/webhook` non concerné | Un jeton CSRF classique, sans bénéfice ici (même origine, pas de CORS) |

### Rulings du journal (`progress.md`)

| # | Décision | Coût si faux |
| --- | --- | --- |
| L2-R1 | Export OpenAPI via un script npm (`api:schema`, `uv run --env-file`) plutôt qu'une sous-commande `app.cli` — évite un conflit avec `app/cli.py` créé en parallèle par T7 du lot 1 | Ajouter la sous-commande plus tard |
| L2-R2 | Plus de `pre-commit install` depuis un worktree (hooks partagés) : le hook est installé une fois depuis l'arbre principal | Commits bloqués après suppression d'un worktree |
| L2-R3 | Proxy Vite de dev sur le port 8450 (documenté, `docker-compose.dev.yml`) ; le port 8460 est réservé aux vérifications isolées (conteneur ou uvicorn direct hors Docker) | Une ligne à corriger |
| L2-R4 | Migration 0003 (`numero_interne`, `photo_compressee`, `total_ht`) avancée dans L2-T2 (la ligne de supervision en a besoin dès ce commit) | Aucun |
| L2-R5 | « Confiance réduite » (§4.2) et avoirs non implémentés au lot 2 : entrées explicites dans `docs/dette.md` (score de confiance = lot 3 ; format d'avoir Unikalo inconnu faute d'exemple) + question Q5 à Ilane | À implémenter au lot 3 |
| L2-R6 | Un seul implémenteur à la fois lance `pytest` dans le worktree (base de test partagée `habitat_reno_pg_l2:5454`, TRUNCATE concurrents instables) | Nuit plus lente |
| L2-R7 | Migration 0004 (`bloc_facture.ordre`) acceptée : sans elle, l'ordre de lecture des blocs d'une facture serait indéterministe (même `created_at`, insertion en une transaction) | Une colonne à retirer |
| L2-R8 | Revue L2-T7 (tour 1/5, Important corrigé) : `GET /api/documents` expose `confirmation: "verifiee" \| "ecart" \| null`, calculé dans `lister_documents` depuis la **dernière entrée du journal** (`quantites_verifiees`/`ecart_constate` ciblant le document, `DISTINCT ON` + jointure externe, une seule requête) — le front (`BlDeposes.tsx`) l'affiche tel quel et ne dérive plus rien de `statut`, qui suit une tout autre logique (OCR) | Un champ à recalculer si le front redevenait divergent |

## 3. Vérification commande par commande

**Prérequis** : lot 1 terminé (`docs/lot-1-recette.md`), migrations 0002 à
0004 (0001 = lot 1). Ne jamais lancer `uv run pre-commit install` depuis ce
worktree (Ruling L2-R2) — le hook est déjà actif, installé depuis l'arbre
principal.

### Installation et configuration

```bash
uv sync
npm --prefix web ci
cp .env.example .env   # sur un clone neuf uniquement — déjà fait dans ce worktree
chmod 600 .env
```

Variables **ajoutées au lot 2** dans `.env` (en plus de celles du lot 1,
voir `docs/lot-1-recette.md`) — toutes obligatoires (`app/core/config.py`) :

- `COOKIE_SECURE` — `false` en dev local (HTTP), `true` en prod (HTTPS
  derrière Traefik).
- `TELEGRAM_CHAT_BL_ID` — identifiant (entier signé, négatif pour un groupe)
  du groupe « BL chantiers » ; tout autre chat est ignoré (L2-D6).
- `TELEGRAM_CHAT_SUPERVISION_ID` — identifiant du groupe de supervision.

### Base et migrations

```bash
docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d postgres
uv run alembic upgrade head
uv run alembic check
```

Vérifié ce soir sur la base `bl` du worktree (127.0.0.1:5454) : `alembic
current` → `0004 (head)`, `alembic check` → « No new upgrade operations
detected. » (aucune dérive). Base vérifiée vide de toute donnée
(`utilisateur`, `document`, `fournisseur` : 0 ligne chacune).

### Comptes de test (CLI, L2-D14)

```bash
uv run python -m app.cli utilisateur-creer \
  --email admin@exemple.invalid --nom "Prénom Nom" --role admin --agence "Agence de test"
# Mot de passe : <saisi via getpass, deux fois, jamais affiché>

uv run python -m app.cli utilisateur-creer \
  --email agent@exemple.invalid --nom "Prénom Nom" --role agent --agence "Agence de test" \
  --telegram-id <identifiant Telegram numérique de l'agent, obtenu ci-dessous>

uv run python -m app.cli utilisateur-desactiver --email agent@exemple.invalid
```

`--role` n'accepte que `admin`/`agent` (refus sinon) ; `--telegram-id` est
optionnel (nécessaire pour qu'un agent soit reconnu par le bot, L2-D7).

### Front et service local (sans build Docker, décision du contrôleur pour cette recette)

```bash
npm --prefix web run api:schema   # nécessite l'API démarrable (lit app.main via uv run) ; déjà généré, à refaire seulement après un changement de schéma
npm --prefix web run api:types
npm --prefix web run typecheck
npm --prefix web run build
uv run --env-file .env uvicorn app.main:app --host 127.0.0.1 --port 8460
```

Port 8460 (Ruling L2-R3, vérification isolée hors Docker) — le flux de dev
normal (`npm --prefix web run dev`) proxie vers le port 8450 publié par
`docker-compose.dev.yml`, qui suppose l'image `api` construite (`docker
compose ... up -d --build api`, déjà validée par L2-T6, **non rejouée ce
soir** — aucun build Docker cette nuit).

### Connexion, factures, documents (vérifié par L2-T7 ce soir, comptes/fixture jetables déjà supprimés)

```bash
curl -i -c cookie-admin.txt -X POST http://127.0.0.1:8460/api/auth/login \
  -d "username=admin@exemple.invalid" -d "password=..."
curl -i -b cookie-admin.txt http://127.0.0.1:8460/api/moi
curl -i -b cookie-admin.txt http://127.0.0.1:8460/api/factures
curl -i -b cookie-admin.txt http://127.0.0.1:8460/api/factures/<id>
curl -i -b cookie-admin.txt http://127.0.0.1:8460/api/documents
curl -i -b cookie-admin.txt -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8460/
```

Résultats obtenus par L2-T7 (rapport, §« Vérifications ») : login → 204 ;
`/api/moi` → 200 rôle correct ; `/api/factures` (admin) → 200, 1 facture
(28 blocs, déposée via `deposer_facture` avec un OCR **simulé**, aucun appel
réseau) ; `/api/factures` (agent) → 403 ; `/api/documents` → portée par rôle
correcte (admin : tous, agent : les siens) ; `/`, `/factures`, `/bl` → 200
`index.html` du build réel. Dépôt non-PDF → 422 `{"detail":"Le fichier
n'est pas un PDF."}` ; dépôt de 21 Mo → 413 `{"detail":"Fichier trop
volumineux (20 Mo maximum)."}` — vérifiés en direct par `curl` réel sur le
routeur.

**Dépôt réel de la facture d'août par l'écran** (bouton « Déposer une
facture », `POST /api/factures` avec le vrai fichier
`tests/fixtures/unikalo/facture_2026-08.pdf`) : **déclenche un vrai appel
Mistral OCR** — non fait cette nuit ni par L2-T7 (interdit), **à faire par
Ilane** dans un navigateur, sur l'instance locale démarrée ci-dessus.
Attendu : message d'attente (« Lecture de la facture en cours… »), puis
redirection vers le détail avec **28 blocs**, badge « BL reçus 0/28 » (gris,
aucune photo BL déposée), messages 409 (« Facture déjà déposée. » + lien
vers l'original) si rejouée.

### Telegram — procédure de bout en bout (jamais exécutée, à faire avec Ilane)

Nouveauté du lot 2 par rapport au lot 1 : **deux** groupes à créer (le bot
ne traite plus que le chat configuré, L2-D6), boutons de confirmation, et
un critère quantitatif (20 dépôts consécutifs sans perte).

1. Bot de test (@BotFather, réutiliser celui du lot 1 si conservé),
   `TELEGRAM_BOT_TOKEN` dans `.env`.
2. Créer les **deux groupes** : « BL chantiers » (agents) et « Supervision »
   (admin). Ajouter le bot dans les deux.
3. Récupérer les deux `chat_id` (négatifs pour un groupe) : envoyer un
   message dans chaque groupe, puis (avant tout `setWebhook`, ou après un
   `deleteWebhook` temporaire) :
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
   Lire `result[].message.chat.id` pour chaque groupe. Renseigner
   `TELEGRAM_CHAT_BL_ID` et `TELEGRAM_CHAT_SUPERVISION_ID` dans `.env`,
   redémarrer l'API.
4. Générer `TELEGRAM_WEBHOOK_SECRET`, le mettre dans `.env`.
5. Démarrer l'API derrière une URL HTTPS publique (accord préalable
   d'Ilane pour toute modification nginx, comme au lot 1), puis :
   ```bash
   curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d "url=https://<domaine>/tg/webhook" \
     -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
   ```
   Vérifier `{"ok": true}`.
6. Dans le groupe « BL chantiers », avec un compte agent rattaché
   (`--telegram-id` connu) :
   - envoyer **20 photos consécutives** (mélange photo compressée /
     document « en fichier ») → chacune doit apparaître dans l'onglet
     « BL déposés » (`GET /api/documents`, rafraîchi 15 s côté écran) en
     moins de 60 s, avec les boutons « Quantités vérifiées » / « Écart
     constaté » en réponse (`Reçu — document n° <n>`) ;
   - vérifier le badge « Photo compressée » sur les photos envoyées
     compressées (`photo[]`), absent sur celles envoyées « en fichier » ;
   - cliquer « Quantités vérifiées » sur un document → accusé « Quantités
     vérifiées enregistrées », message édité en `Reçu — document n° <n> ·
     Quantités vérifiées par <nom> à <HH:MM>`, boutons retirés ; second clic
     (par n'importe qui) → accusé « Déjà enregistré » ;
   - cliquer « Écart constaté » sur un autre document → accusé « Écart
     enregistré », document passé « à vérifier » côté écran ;
   - envoyer une photo/un clic depuis un compte Telegram **non rattaché**
     (aucun `utilisateur` actif avec ce `telegram_user_id`) → aucune réponse
     dans le groupe BL, aucun document créé, un message dans le groupe
     Supervision : `Expéditeur Telegram non rattaché : id <id> · <nom>` ;
   - vérifier dans le groupe Supervision une ligne par dépôt traité :
     `Document n° <interne> · BL <n° ou « non détecté »> · fournisseur — ·
     chantier — · <déposant> · <HH:MM> · <statut>` ;
   - rejouer un `update_id` déjà traité → 200, aucun nouveau document ni
     nouvelle réponse (dédoublonnage, comme au lot 1).
7. Consigner ici (comptes uniquement) : nombre de dépôts sur 20 reçus sous
   60 s, nombre de doublons/erreurs, texte réel du message « expéditeur non
   rattaché » (minor deferred L2-T2 : à confirmer mot pour mot en recette).

### Mobile (375 px)

À faire par Ilane dans un navigateur (aucun ici cette nuit) :
`FacturesListe`/`FactureDetail` : tableaux à défilement horizontal
(`overflow-x-auto`) ; `BlDeposes` : cartes empilées `< md`, bascule vers un
tableau `≥ md` ; onglets du `Gabarit` toujours accessibles ; focus clavier
visible (`focus-visible:ring-2`) sur le bouton de dépôt et les liens.

## 4. Ce qui manque / reste à faire avec Ilane

- **Revue de L2-T7 close, corrigée** (§1, Ruling L2-R8) : le seul point
  Important relevé (confirmation dérivée à tort de `statut` côté front)
  est corrigé et testé (`2e06aa8`). Plus rien de bloquant côté code pour ce
  point ; les vérifications manuelles ci-dessous restent à faire.
- **Vérification visuelle réelle** : aucun navigateur cette nuit — rendu à
  375 px, couleurs des badges/pastilles, focus clavier, parcours complet du
  dépôt de facture à l'écran (§3).
- **Tests Telegram réels** : deux groupes jamais créés, `setWebhook` jamais
  appelé, 20 dépôts consécutifs jamais mesurés, boutons jamais cliqués en
  conditions réelles (§3).
- **Dépôt réel avec OCR** : la facture d'août n'a été déposée que via un OCR
  simulé (fixture rejouée) ; le vrai bouton « Déposer une facture » n'a
  jamais déclenché un appel Mistral réel (interdit cette nuit, R17 du lot
  1 reconduit ce soir).
- **Questions Q1 à Q5** (`docs/plan-lot-2.md` §3, décisions provisoires en
  §4) :
  - Q1 : qui peut cliquer les boutons de confirmation (provisoire : tout
    utilisateur rattaché actif) ?
  - Q2 : effet d'« Écart constaté » au-delà de la trace (provisoire :
    `a_verifier` + journal) ?
  - Q3 : gestion des utilisateurs par l'admin (provisoire : CLI seulement,
    pas d'écran) ?
  - Q4 : identifiants réels des deux groupes Telegram et vrai bot — **
    bloquant pour le test Telegram ci-dessus**.
  - Q5 : Unikalo émet-il des avoirs, et sous quelle forme (même gabarit
    avec montants négatifs, mention « AVOIR », document distinct) ? Aucun
    exemple disponible ; un avoir déposé aujourd'hui serait typé `facture`
    à tort ou refusé en 422 (`docs/dette.md`, L2-T4).
- **Points mineurs reportés avec un effet visible pour l'utilisateur**
  (journal `progress.md`, tous marqués « minor (deferred) », détaillés ou
  ajoutés dans `docs/dette.md`) :
  - texte exact du message « expéditeur non rattaché » à confirmer en
    recette Telegram (L2-T2) ;
  - un clic refusé (utilisateur non rattaché) n'affiche que l'identifiant
    Telegram en supervision, jamais le nom (L2-T3, déjà dans `docs/dette.md`) ;
  - si l'écriture réussit mais qu'une erreur survient juste après (avant la
    réponse Telegram), l'agent peut voir l'accusé générique d'erreur alors
    que son clic a bien été enregistré (L2-T3, théorique, non observé —
    ajouté à `docs/dette.md` par cette tâche) ;
  - la correspondance numéro de BL ↔ document utilisée par l'écran
    « Factures » filtre en SQL avec un simple `trim()` (espace ASCII) mais
    normalise côté Python avec `strip()` (tous espaces) : un numéro de BL
    lu avec un espace insécable pourrait ne pas matcher (L2-T5, improbable,
    ajouté à `docs/dette.md` par cette tâche) ;
  - le PDF/la photo téléchargés (`GET /api/.../fichier`) n'ont pas de nom de
    fichier explicite (`FileResponse` sans `filename`) : le navigateur
    propose un nom générique au téléchargement (L2-T5, cosmétique).
- **Fichiers de plus de 20 Mo sur Telegram** (dette héritée du lot 1,
  `docs/dette.md` §T6) : toujours aucun message d'erreur explicite à
  l'agent si `getFile` échoue pour un fichier trop volumineux.

## 5. Tests (relancés réellement ce soir, 2026-09-17)

```bash
uv run pytest -q
```
```
336 passed in 75.02s (0:01:15)
```
0 échec, 0 skip inattendu (base de test `habitat_reno_pg_l2:5454` déjà
migrée à `0004`).

**Après correction L2-T7 (Ruling L2-R8, `2e06aa8`)** : 5 tests ajoutés
(4 sur `lister_documents` — vérifiée malgré `statut=a_verifier`, écart, sans
clic, sans N+1 — et 1 sur `GET /api/documents`) →
```
341 passed in 79.44s (0:01:19)
```
`uv run ruff check`, `uv run ruff format --check`, `uv run mypy` → propres.

```bash
npm --prefix web run typecheck
```
Propre (`tsc --noEmit`, aucune sortie).

```bash
npm --prefix web run build
```
Propre : `dist/index.html` 0,44 kB, `dist/assets/index-*.css` 9,87 kB (gzip
2,86 kB), `dist/assets/index-*.js` 236,53 kB (gzip 74,15 kB), « built in
1.30s ». **Après correction** (`web/openapi.json`/`schema.d.ts` régénérés,
badge « écart » ajouté) : `dist/assets/index-*.css` 10,04 kB (gzip 2,89 kB),
`dist/assets/index-*.js` 236,81 kB (gzip 74,23 kB).

```bash
uv run pre-commit run --all-files
```
Tous les hooks **verts** : `ruff check`, `ruff format --check`, `mypy`,
`pytest`, `web typecheck (tsc --noEmit)`, `web build (vite build)` (les
hooks `interdit tout fichier sous tests/fixtures/` et `interdit tout
fichier .env` : *Skipped*, aucun fichier concerné dans ce commit).

`web/dist` supprimé après vérification (ignoré par git, `web/dist/` dans
`.gitignore`) : `git status` reste propre.

## 6. Revue finale de branche (vague finale du lot 2, 2026-09-17)

Revue complète de la branche `lot-2-collecte` (`9254ffe..44ba9d7`), 6 points
relevés, tous corrigés en 4 commits (`docs: revue finale du lot 2` = ce
commit) :

| # | Nature | Corrigé par | Résumé |
| --- | --- | --- | --- |
| 1 | Important | `9973b02` (`ingest: découpage du service en sous-modules`) | `app/modules/ingest/service.py` (1631 lignes, ~6 responsabilités) découpé en `ingest/commun.py` (aides partagées), `ingest/depot_telegram.py` (dédoublonnage, liste blanche, `traiter_fichier`, OCR des photos, supervision, clics), `ingest/factures.py` (lecture/dépôt de facture) et `ingest/lecture.py` (listes/détails, correspondance BL, fichiers servis). Simple déplacement de code (aucun changement de comportement), tous les imports mis à jour (routeurs, `app/cli.py`, tests), aucun module façade. `ingest` reste le seul orchestrateur, `tests/test_frontieres.py` inchangé et vert. |
| 5 | Dette (L2-T5) | `9973b02` (même commit que le point 1) | `documents_bl_par_numeros` : la présélection SQL utilisait `trim()` (espace ASCII seul) alors que la comparaison Python utilise `str.strip()` (tout espace Unicode, dont l'espace insécable U+00A0 et la tabulation). Remplacé par `btrim()` avec la liste explicite de ces trois caractères. 2 tests ajoutés (espace insécable, tabulation) ; entrée de dette retirée. |
| 2 | Important | `97f740d` (`core: contrôle d'origine des requêtes modifiantes et cache du front`) | Défense en profondeur CSRF : `ControleOrigineMiddleware` (`app/core/origine.py`) refuse (403 `{"detail": "Origine refusée."}`) toute requête `POST`/`PUT`/`PATCH`/`DELETE` sur `/api/*` dont `Origin` diffère de l'origine du service ou dont `Sec-Fetch-Site` vaut `cross-site` ; absence des deux en-têtes acceptée ; `/tg/webhook` non concerné. Décision documentée en L2-D18 (`docs/plan-lot-2.md` §4 et §2 ci-dessus). 14 tests ajoutés (middleware isolé + intégration sur `POST /api/auth/login` et `POST /api/factures`). |
| 3 | Mineur | `97f740d` (même commit) | `app/core/front.py::monter_front` : `index.html` renvoyé avec `Cache-Control: no-cache` (référence des fichiers hachés de `assets/` par leur nom) ; `assets/` reste cachable sans limite. 2 tests ajoutés. |
| 4 | Important | `6298a9d` (`deploy: en-têtes de sécurité HTTP`) | Middleware Traefik `headers` (`entetes-securite`) sur le routeur `api` : `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, HSTS (`stsSeconds=31536000`, `stsIncludeSubdomains=true`), `Content-Security-Policy` compatible avec le build Vite réel (vérifié : `web/dist/index.html` ne référence que des fichiers `/assets/*` du même service, aucun script/style externe ni inline). Validé par `docker compose --env-file .env.example -f deploy/docker-compose.yml config`. |
| 6 | Dette + docs | ce commit (`docs: revue finale du lot 2`) | `docs/dette.md` : absence de purge des jetons expirés de `jeton_session` (section « L2-T1 — auth »). `docs/lot-2-recette.md` : cette section. |

**Résultats de tests réels après corrections** (relancés ce soir, dans le
worktree, base de test `habitat_reno_pg_l2:5454`) :

```bash
uv run pytest -q
```
```
359 passed in 79.36s (0:01:19)
```
(341 avant la vague finale ; +2 pour le point 5, +16 pour les points 2 et 3
— le point 1 ne change aucun comportement, le point 4 ne touche aucun code
Python).

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
```
```
All checks passed!
80 files already formatted
Success: no issues found in 66 source files
```

```bash
npm --prefix web run typecheck
```
Propre (`tsc --noEmit`, aucune sortie).

```bash
uv run pre-commit run --all-files
```
Tous les hooks **verts** : `ruff check`, `ruff format --check`, `mypy`,
`pytest`, `web typecheck (tsc --noEmit)`, `web build (vite build)` (les deux
hooks d'interdiction restent *Skipped*, aucun fichier concerné). `web/dist`
supprimé après vérification, `git status` reste propre.

```bash
docker compose --env-file .env.example -f deploy/docker-compose.yml config
```
Rendu sans erreur ; le label `entetes-securite` (dont `contentSecurityPolicy`
avec ses points-virgules et guillemets simples) apparaît tel quel sur le
service `api`.

**Inquiétudes reportées, non bloquantes** :
- La CSP (`style-src 'unsafe-inline'`) est gardée par prudence (aucune
  bibliothèque front actuelle n'écrit de style inline, vérifié sur le
  build) : à resserrer (`'self'` seul) si confirmé inutile après un usage
  réel plus large du front.
- Le contrôle d'origine (point 2) est une défense en profondeur, pas un
  remplacement de `SameSite=Lax` : un navigateur qui n'enverrait ni `Origin`
  ni `Sec-Fetch-Site` sur une requête intersite (très ancien navigateur)
  resterait couvert par `SameSite=Lax` seul, jamais par ce contrôle.
- La dette L2-T1 ajoutée (purge de `jeton_session`) n'a aucun effet
  fonctionnel avant que la table ne grossisse en usage réel ; aucune action
  requise avant le lot 3.
