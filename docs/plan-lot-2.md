# Plan — Lot 2 (Collecte)

**Objectif (CDC §11) :** un BL déposé depuis le terrain dans le groupe Telegram est visible dans l'application. Couvre : groupe Telegram, boutons de confirmation, notifications de supervision, liste blanche, API `/factures` et `/documents`, login, premier écran React (Factures).

**Critères de réception (CDC §10, lot Collecte) :**
- Une photo déposée dans le groupe Telegram est stockée, accusée en réponse et visible dans l'application sous 60 s (20 dépôts consécutifs sans perte).
- Un dépôt par un identifiant non rattaché est ignoré et signalé.

**Architecture :** on s'appuie sur le lot 1 : `Settings` fail-fast, `app.state` (engine, sessions, http), modèles dans `ingest/models.py`, `messaging/base.py` + `telegram.py`, `ingest/service.py` orchestrateur, `extract/unikalo.py` (facture Unikalo lue sur réponse OCR), `extract/ocr.py` + `ingest/mistral.py` (OCR, n° de BL), `app/cli.py`. Ce lot ajoute `core/auth.py` (fastapi-users), `modules/api/` (routers JSON) et `web/` (front React servi par l'API).

**Spec :** `docs/cahier-des-charges.md` (§3, §4.1, §4.2, §4.6, §6, §7, §10, §11).

**Statut :** plan écrit en autonomie (mandat d'Ilane, nuit du 2026-09-16), exécuté sans validation préalable. Chaque décision prise sans Ilane est listée en §4 avec son coût si elle est mauvaise.

---

## 1. Contraintes globales

Celles du lot 1 (`docs/plan-lot-1.md` §1 et `CLAUDE.md`) s'appliquent toutes. En plus :
- Front : React 18, TypeScript strict, Vite, React Router, TanStack Query (seul gestionnaire d'état serveur), Tailwind en `theme.extend` uniquement, types générés par `openapi-typescript`. Pas de CORS, pas de JWT, pas de localStorage pour l'auth.
- Auth : fastapi-users, transport cookie (httpOnly, SameSite=Lax, Secure en prod), stratégie base de données (session serveur révocable), hash argon2, `slowapi` sur `/api/auth/login`, déconnexion après 12 h d'inactivité.
- Deux rôles seulement : `admin`, `agent`. Un agent voit les BL qu'il a déposés ; les factures sont réservées à l'admin.
- Toute action utilisateur qui modifie une donnée métier est journalisée (`journal` : auteur, action, cible, avant, après, horodatage).
- Aucune règle métier dans les routers ni dans le front.
- Interface en français.

## 2. Constats (état attendu à la fin du lot 1)

1. `utilisateur` suit les noms du CDC (`mdp_hash`, `actif`), pas ceux attendus par fastapi-users (`hashed_password`, `is_active`, `is_superuser`, `is_verified`).
2. Le garde de frontières (T1) traite tout module sauf `ingest` comme « métier ». Or `api/` (routers) doit appeler `ingest/service.py`, qui est le seul orchestrateur.
3. La table `document` n'a pas de colonne de total : or la liste des factures et, au lot 4, la règle R10 ont besoin du total HT lu sur la facture.
4. Le CDC demande de répondre au dépôt avec un « numéro interne du document » lisible, et de marquer les photos compressées. Aucune colonne n'existe pour l'un ou l'autre.
5. L'écran « À traiter », où apparaissent normalement les BL déposés, n'arrive qu'au lot 3. Or le critère du lot 2 exige qu'un dépôt soit « visible dans l'application ».
6. Lot 1 : la seule facture fournie est un scan. Les factures sont donc lues via Mistral OCR puis `extract/unikalo.py` (rulings R16/R17 du lot 1), à travers `ingest/service.py::lire_facture(contenu_pdf, ocr)`.

## 3. Questions à Ilane (non bloquantes, décisions provisoires en §4)

- Q1 : qui peut cliquer « Quantités vérifiées » / « Écart constaté » ? Le déposant seulement, ou tout agent rattaché ? (provisoire : tout utilisateur rattaché actif)
- Q2 : que doit déclencher « Écart constaté » au-delà de la trace ? (provisoire : document passé « à vérifier » + journal)
- Q3 : gestion des utilisateurs par l'admin. Le CDC dit « gère les utilisateurs », mais aucun des 5 écrans ne la porte. (provisoire : commandes CLI au lot 2)
- Q4 : identifiants des deux groupes Telegram (« BL chantiers » et supervision) et vrai bot, pour la recette.

## 4. Décisions prises en autonomie

| # | Décision | Pourquoi | Coût si faux |
| --- | --- | --- | --- |
| L2-D1 | Les colonnes du CDC gardent leur nom : les attributs fastapi-users sont mappés dessus (`hashed_password` → `mdp_hash`, `is_active` → `actif`). `is_verified` et `is_superuser` sont dérivés (toujours vérifié ; superuser ⇔ `role = 'admin'`) plutôt qu'ajoutés en colonnes, sauf si la bibliothèque l'impose — auquel cas colonnes ajoutées et notées dans `docs/dette.md` | Une seule source de vérité pour le rôle | Une migration de colonnes |
| L2-D2 | Sessions serveur : `DatabaseStrategy` de fastapi-users, table `jeton_session` (token, utilisateur_id, created_at). Expiration glissante : `created_at` est rafraîchi au plus toutes les 5 min par la dépendance « utilisateur courant », durée de vie 12 h. Cookie de session sans `max_age` | CDC §4.6 : « session côté serveur, déconnexion après 12 h d'inactivité » | Réglage |
| L2-D3 | `api` et `jobs` sont des couches d'entrée : elles peuvent importer `ingest` (et `app.core`), jamais `extract`/`normalize`/`rules`/`messaging` directement. Les modules métier purs (`extract`, `normalize`, `rules`) et `messaging` n'importent aucun autre module. Le garde de frontières est mis à jour | `ingest/service.py` reste le seul orchestrateur, les routers l'appellent | Garde à ajuster |
| L2-D4 | `core/auth.py` importe le modèle `Utilisateur` depuis `ingest/models.py` | Arborescence imposée (auth dans core, modèles dans ingest) | Déplacement de modèle |
| L2-D5 | Migration 0002 : table `jeton_session`. Migration 0003 : `document.numero_interne` (bigint identity, unique), `document.photo_compressee` (bool, nullable), `document.total_ht` (numeric, nullable) | Constats 3 et 4 | Colonnes à retirer |
| L2-D6 | Le bot ne traite que le groupe configuré `TELEGRAM_CHAT_BL_ID`. Tout autre chat est ignoré sans écriture ni réponse | CDC §4.1 : un groupe « BL chantiers » ; minimisation | Une condition |
| L2-D7 | Un expéditeur non rattaché (aucun `utilisateur` actif avec ce `telegram_user_id`) : aucun document créé, aucun fichier téléchargé, pas de réponse dans le groupe, un message dans le groupe de supervision (`TELEGRAM_CHAT_SUPERVISION_ID`) avec l'identifiant et le nom Telegram | CDC §3, §4.1 | — |
| L2-D8 | Ligne de supervision par dépôt : `Document n° <interne> · BL <n° détecté ou « non détecté »> · fournisseur — · chantier — · <déposant> · <HH:MM> · <statut>`. Fournisseur et chantier restent à « — » jusqu'au lot 3. Les erreurs de traitement d'un dépôt (téléchargement, OCR, écriture) sont aussi signalées en supervision, sans contenu | CDC §4.1, §9 | Texte |
| L2-D9 | Réponse au dépôt : `Reçu — document n° <numero_interne>` avec deux boutons en ligne, « Quantités vérifiées » (`v:<numero_interne>`) et « Écart constaté » (`e:<numero_interne>`) | CDC §4.1 | Texte |
| L2-D10 | Clic : n'importe quel utilisateur rattaché actif peut cliquer ; le premier clic fait foi, les suivants reçoivent « déjà enregistré ». « Vérifiées » → `confirme_le`, `confirme_par`. « Écart » → `statut = 'a_verifier'` + `confirme_le`, `confirme_par`. Journal dans les deux cas (`quantites_verifiees` / `ecart_constate`). Accusé via `answerCallbackQuery`, puis le message du bot est édité pour afficher le résultat et retirer les boutons | Q1, Q2 | Règle d'autorisation |
| L2-D11 | Dépôt de facture traité dans la requête (synchrone) : contrôle `%PDF-`, puis `lire_facture` (OCR Mistral + parseur Unikalo, délai max 90 s), puis contrôle de doublon. Seul le format Unikalo est reconnu : `FactureIllisible` → 422 « format non pris en charge », rien n'est stocké. Échec OCR → 502 « lecture impossible, réessayer ». Fournisseur « Unikalo » créé s'il n'existe pas (normalisation SIRET/TVA au lot 3). Doublon (même fournisseur, même numéro) → 409 avec l'id de l'original, aucun fichier stocké. Réponse OCR brute conservée dans `document.ocr_brut`. Taille max 20 Mo | CDC §4.2 ; 20 factures par mois, une attente de 20 s est acceptable pour l'admin | Passage en tâche de fond si trop lent |
| L2-D12 | Le statut « BL reçu / non reçu » d'un bloc est calculé à la lecture (même correspondance que la CLI du lot 1), pas persisté dans `bl_document_id`. La persistance appartient au rapprochement du lot 4 | Toujours à jour quand une photo arrive après la facture | Une requête |
| L2-D13 | L'écran « Factures » a deux onglets : « Factures » (admin) et « BL déposés » (admin : tous ; agent : les siens), rafraîchi toutes les 15 s | Constat 5 ; critère « visible sous 60 s » | Onglet à déplacer dans « À traiter » au lot 3 |
| L2-D14 | Création des utilisateurs par CLI : `python -m app.cli utilisateur-creer` (mot de passe saisi via `getpass`) et `utilisateur-desactiver` | Q3 | Écran au lot 5 si demandé |
| L2-D15 | Types front générés depuis le schéma OpenAPI exporté sans serveur (`python -m app.cli openapi > web/openapi.json`, puis `openapi-typescript`). Appels via un petit helper `fetch` typé, sans bibliothèque cliente supplémentaire | Stack : openapi-typescript seul | Ajout d'openapi-fetch |
| L2-D16 | Service du front : `StaticFiles` sur `/assets` et renvoi d'`index.html` pour toute route hors `/api`, `/tg`, `/health`, `/docs`, `/openapi.json`. Montage seulement si le dossier du build existe (tests sans build). Dockerfile multi-étage (Node puis Python) | CDC §7 | — |
| L2-D17 | Contrôles front : `tsc --noEmit` strict et `vite build` dans pre-commit. Pas de tests unitaires front (aucun outil de test front dans la stack) | Stack imposée | Dette notée |

## 5. Structure des fichiers

```
app/core/auth.py                      L2-T1  fastapi-users, stratégie DB, dépendances utilisateur/role
app/core/tests/test_auth.py           L2-T1
app/modules/ingest/models.py          L2-T1 (JetonSession, mapping), L2-T3 (colonnes document)
migrations/versions/0002_*.py         L2-T1
migrations/versions/0003_*.py         L2-T3
app/cli.py                            L2-T1 (utilisateurs), L2-T6 (openapi)
app/modules/messaging/base.py         L2-T2 (envoyer), L2-T3 (boutons, clic)
app/modules/messaging/telegram.py     L2-T2, L2-T3
app/modules/ingest/router.py          L2-T2, L2-T3, L2-T4
app/modules/ingest/service.py         L2-T2, L2-T3, L2-T4, L2-T5
app/modules/api/__init__.py           L2-T5
app/modules/api/schemas.py            L2-T5  modèles Pydantic de réponse
app/modules/api/factures.py           L2-T4 (POST), L2-T5 (GET)
app/modules/api/documents.py          L2-T5
app/modules/api/moi.py                L2-T1
app/modules/api/tests/                L2-T4, L2-T5
tests/test_frontieres.py              L2-T5 (règle L2-D3)
web/                                  L2-T6, L2-T7
Dockerfile                            L2-T6 (multi-étage)
docs/lot-2-recette.md                 L2-T8
```

## 6. Tâches

### L2-T1 — `auth: connexion par cookie, sessions en base, limitation du login`
- Dépendances : `fastapi-users[sqlalchemy]`, `slowapi`, `python-multipart`, et argon2 via le hachage fourni par fastapi-users (pwdlib[argon2]).
- Config : `COOKIE_SECURE` (bool, obligatoire ; `true` en prod, `false` en dev).
- Modèles : mapping `Utilisateur` (L2-D1), `JetonSession` ; migration 0002.
- Routes : `POST /api/auth/login` (formulaire `username`/`password`) et `POST /api/auth/logout` via fastapi-users. `GET /api/moi` → `{id, email, nom, role, agence}`.
- Limitation : 5 tentatives par minute par IP sur le login → 429.
- Dépendances FastAPI : `utilisateur_courant` (actif, expiration glissante L2-D2) et `admin_requis`.
- (La création d'utilisateurs en CLI est la tâche L2-T1b, faite après l'intégration de la CLI du lot 1.)
- Tests :
  - login correct → 204/200 + cookie httpOnly `SameSite=Lax` ; mauvais mot de passe → 400 ; compte inactif → 400 ;
  - 6ᵉ tentative dans la minute → 429 ;
  - `/api/moi` sans cookie → 401, avec cookie → 200 ;
  - logout → jeton supprimé, `/api/moi` → 401 ;
  - jeton sans activité depuis plus de 12 h → 401 ; activité à 11 h 59 → prolongé ;
  - hash stocké au format `$argon2id$` ;
  - `admin_requis` refuse un agent (403).

### L2-T1b — `auth: commandes de gestion des utilisateurs`
- Dans `app/cli.py` (créé au lot 1) : `utilisateur-creer --email --nom --role {admin,agent} --agence [--telegram-id]` (mot de passe via `getpass`, confirmation, hash argon2 via le gestionnaire fastapi-users) et `utilisateur-desactiver --email`.
- Tests : création, refus d'un email en double, rôle invalide refusé, désactivation, mot de passe jamais affiché.

### L2-T2 — `messaging: liste blanche, groupe BL et notifications de supervision`
- Config : `TELEGRAM_CHAT_BL_ID`, `TELEGRAM_CHAT_SUPERVISION_ID` (entiers, obligatoires).
- `Messagerie.envoyer(chat_id, texte)` + implémentation Telegram (`sendMessage`).
- Webhook : autre chat → 200, rien n'est écrit (L2-D6). Expéditeur non rattaché → update dédoublonné, aucun document, aucun téléchargement, message de supervision (L2-D7).
- `traiter_fichier` : `deposant_id` toujours renseigné ; ligne de supervision après traitement (L2-D8) ; erreurs signalées en supervision.
- Tests :
  - chat étranger ignoré ;
  - expéditeur inconnu → 0 document, 0 appel de téléchargement, 1 message de supervision contenant l'id Telegram, puis rejeu du même update → aucun second message ;
  - expéditeur inactif traité comme inconnu ;
  - dépôt valide → 1 ligne de supervision au format L2-D8 ;
  - échec de téléchargement → message de supervision sans token ni contenu.

### L2-T3 — `messaging: numéro interne et boutons de confirmation`
- Migration 0003 (L2-D5). `photo_compressee` renseignée depuis `FichierEntrant.compresse`.
- Réponse au dépôt avec numéro interne et boutons (L2-D9). `Messagerie.repondre` accepte des boutons optionnels (liste de `(libellé, donnée)`).
- `lire_update` renvoie aussi les clics : dataclass `ClicBouton(update_id, callback_id, chat_id, message_id, expediteur_id, action, numero_interne)`. `Messagerie.accuser_clic(callback_id, texte)` et `Messagerie.editer_message(chat_id, message_id, texte)`.
- Service `traiter_clic` (L2-D10), avec journal.
- Tests :
  - `lire_update` sur un `callback_query` valide ou invalide (données malformées → None) ;
  - clic « vérifiées » par un utilisateur rattaché → `confirme_le`/`confirme_par` + journal + accusé + édition ;
  - clic « écart » → `a_verifier` + journal ;
  - second clic → « déjà enregistré », aucune écriture ;
  - clic d'un inconnu → refus + supervision ;
  - `numero_interne` inexistant → accusé « document introuvable » ;
  - rejeu du même `update_id` → ignoré ;
  - réponse au dépôt contenant le numéro interne et les deux boutons avec leurs données.

### L2-T4 — `ingest: dépôt de facture PDF Unikalo`
- Service `deposer_facture(session, contenu, deposant, docs_dir, ocr) -> FactureDeposee` : magie `%PDF-`, `lire_facture` (L2-D11), fournisseur get-or-create, contrôle de doublon, stockage `<uuid>.pdf`, insertion `document` (type `facture`, source `upload`, numero, date_doc, total_ht, statut `recu`, ocr_brut), `bloc_facture` (commentaire = lignes COMMENTAIRE jointes par « \n ») et `ligne`, journal `facture_deposee`. Erreurs typées : `FormatNonPrisEnCharge`, `FactureEnDouble(original_id)`, `FichierInvalide`, `LectureImpossible`.
- Router `POST /api/factures` (admin, multipart, 20 Mo max) → 201 `{id}` ; 409 `{detail, original_id}` ; 422 format ; 413 taille.
- Tests (base de test ; OCR remplacé par une fonction qui renvoie la réponse OCR sauvegardée en fixture, skip si absente ; réponses synthétiques pour les erreurs ; aucun appel réseau) :
  - dépôt réel → nombres de blocs et de lignes en base égaux à ceux d'`analyser_facture_unikalo` ;
  - OCR en échec → 502, rien de stocké ;
  - second dépôt du même PDF → 409 avec l'id original, aucun fichier supplémentaire ;
  - fichier non PDF → 422 ; réponse OCR non reconnue → 422, rien de stocké ;
  - agent → 403 ; journal écrit.

### L2-T5 — `api: factures et documents en lecture`
- `GET /api/factures` (admin) : liste triée par date décroissante `{id, numero, fournisseur, date_doc, total_ht, nb_blocs, nb_blocs_recus, cree_le}`.
- `GET /api/factures/{id}` (admin) : en-tête, puis blocs `{numero_bl, date_bl, numero_commande, chantier_brut, commentaire, montant_ht, bl_recu, bl_document_id, lignes[...]}` (L2-D12).
- `GET /api/documents` : admin → tous les BL/enlèvements ; agent → ceux qu'il a déposés. Champs `{id, numero_interne, type, numero, statut, deposant, cree_le, confirme_le, confirme_par, photo_compressee}`. Filtre `?depuis=`.
- `GET /api/documents/{id}/fichier` (admin : tout ; agent : ses documents ; sinon 404) → `FileResponse` avec le bon type MIME.
- La correspondance numéro BL ↔ document est factorisée dans `ingest/service.py`, partagée avec la CLI du lot 1 (même règle : `strip` + majuscules).
- Garde de frontières mis à jour (L2-D3) avec ses tests négatifs et positifs.
- Tests : droits admin/agent sur chaque route ; bloc reçu/non reçu ; photo arrivée après la facture → bloc reçu à la lecture suivante ; document archivé ignoré ; fichier d'un autre agent → 404 ; schémas OpenAPI présents.

### L2-T6 — `web: socle React, connexion et service statique`
- `web/` : Vite + React 18 + TypeScript strict, React Router, TanStack Query, Tailwind (`theme.extend`), `openapi-typescript` (script `npm run api:types` via `uv run python -m app.cli openapi`), helper `fetch` typé qui gère 401 → page de connexion.
- Pages : connexion (email, mot de passe, message d'erreur, 429 « trop de tentatives »), gabarit de l'application (en-tête avec le nom, le rôle et « Se déconnecter »), route protégée.
- API : montage statique et renvoi d'index (L2-D16) + tests pytest avec un faux dossier de build.
- Dockerfile multi-étage (`node:24-alpine` → `python:3.11-slim`) ; `.dockerignore` mis à jour.
- pre-commit : `npm --prefix web run typecheck` et `build` sur les fichiers `web/`.
- Vérifications :
  - `npm ci && npm run typecheck && npm run build` ;
  - build de l'image ;
  - image lancée en local : `/` sert l'app, `/api/moi` → 401, `/health` → 200.

### L2-T7 — `web: écran Factures et onglet BL déposés`
- Onglet « Factures » (admin) :
  - liste en tableau avec défilement horizontal sur mobile ;
  - dépôt de PDF avec messages d'erreur 409 (lien vers l'original), 422 et 413 ;
  - détail : en-tête, blocs avec pastille de couleur reçu (vert) / non reçu (rouge), lien vers la photo si reçu, lignes du bloc, lien vers le PDF.
- Onglet « BL déposés » (admin et agent) : cartes sur mobile, tableau sur ordinateur, rafraîchi toutes les 15 s, lien vers la photo, badge « photo compressée », état de confirmation.
- Navigation selon le rôle : un agent ne voit que « BL déposés ».
- Vérifications :
  - `typecheck` et `build` ;
  - parcours manuel sur l'image locale avec un admin et un agent de test créés par CLI, en données inventées : connexion, dépôt de la facture d'août, détail, BL déposés, mobile simulé à 375 px (captures non commitées) ;
  - rapport des vérifications.

### L2-T8 — `docs: recette du lot 2`
- `docs/lot-2-recette.md` :
  - ce qui est fait ;
  - la vérification commande par commande (création des utilisateurs, groupes Telegram, setWebhook, 20 dépôts, expéditeur non rattaché, boutons, dépôt de facture, écran, mobile) ;
  - ce qui manque et les questions Q1 à Q4 ;
  - `docs/dette.md` à jour.

## 7. Récapitulatif des tests

| Zone | Sans base | Avec base | Manuel |
| --- | --- | --- | --- |
| Auth, sessions, limitation | | L2-T1 | connexion navigateur (L2-T7) |
| Liste blanche, supervision | L2-T2 (lire_update) | L2-T2 | groupe réel (recette) |
| Boutons | L2-T3 (parsing) | L2-T3 | clic réel (recette) |
| Dépôt facture | | L2-T4 | écran (L2-T7) |
| API lecture, droits | | L2-T5 | écran (L2-T7) |
| Front | typecheck, build | service statique (L2-T6) | parcours admin/agent, mobile |
