# Phase 4 — IA : synthèse des commentaires, explication des alertes prix, prix trouvé sur internet — conception (27/09/2026)

Phase 4 de `docs/roadmap-octobre-2026.md` (§7), partie IA : points 4 (« une IA
cherche le prix sur internet », « l'IA ajoute un commentaire pour expliquer
l'écart ») et 6 (« chaque semaine, une IA lit tous les commentaires et envoie
une synthèse à l'accueil, avec les actions à mener ») de la demande du client
(§1.1). Session A, branche `feature/phase-4-ia`. Le contrôle des prix à la
facture (4ᵉ tâche du §7) n'est **pas** dans ce lot : ce n'est pas de l'IA.

Principe inchangé (CDC §1, §5) : **Python décide qu'une anomalie existe.
L'IA explique, recherche et synthétise. L'humain décide de l'action.** Aucune
sortie de l'IA ne crée, ne ferme ni ne modifie une anomalie, un prix de grille
ou un document.

Toutes les données citées ici sont **inventées**.

---

## 1. Décisions d'Ilane (27/09/2026)

| # | Question | Décision |
| --- | --- | --- |
| D1 | Organisation | Une seule spec pour les trois morceaux ; la synthèse d'abord (elle ne dépend que des commentaires) ; l'explication et le prix internet se branchent sur le lot Prix (session B) quand il est fusionné dans `dev`. |
| D2 | Moteur d'IA | **OpenCode** (`opencode serve`, conteneur interne) connecté à **l'abonnement ChatGPT Plus/Pro d'Ilane** (OAuth), selon son document « Choix IA — OpenCode pour Habitat & Rénovation ». Choisi contre la recommandation de Claude (API Mistral en direct, déjà dans la stack, hébergée en UE) : risques consignés au §9. Mistral reste l'OCR. |
| D3 | Recherche sur internet | **Gratuite.** Ilane demandait Firecrawl ; la version stable d'OpenCode (1.18.32) ne le prend pas en charge : son outil `websearch` passe par le service MCP public d'**Exa**, sans clé (`OPENCODE_ENABLE_EXA=1`). Une clé Exa gratuite (`EXA_API_KEY`, 10 $ de crédit par mois) peut être ajoutée plus tard si le service public limite. |
| D4 | Actions de la synthèse | **À cocher** : chaque action peut être marquée « faite » (qui, quand) ou remise « à faire » ; les actions non faites des semaines précédentes restent affichées (« Encore à faire »). |
| D5 | Déclenchement des travaux sur les prix | **Automatique**, en arrière-plan, par une tâche planifiée ; résultats gardés (prix internet : 30 jours) ; plafond d'appels par jour. |
| D6 | Mise en route | « Go, implémente déjà tout, je rajouterai l'abonnement après » : tout est construit et testé sans abonnement ; l'IA reste éteinte (`IA_ACTIVE=false`) tant qu'Ilane ne l'allume pas. |

Reprises du document d'Ilane : l'IA n'est jamais le moteur métier ;
réponses en JSON strict ; `prix_non_verifiable` plutôt qu'un prix inventé ;
source et date toujours gardées ; pas de nouvelle recherche à chaque bon
(cache) ; une panne de l'IA ne bloque jamais un bon ; essai sur une vingtaine
de produits réels avant de se fier au prix internet (§8) ; OpenCode jamais
exposé, sans accès à la base ni au dépôt.

Écart assumé avec ce document : pas de classe `AIProvider` à plusieurs
implémentations (`CLAUDE.md` interdit les abstractions « pour plus tard ») ;
l'isolation est un **module unique**, `ingest/opencode.py`, seul à parler au
moteur d'IA : changer de fournisseur = réécrire ce module.

---

## 2. Vue d'ensemble

```
                         réseau Docker interne « habitat_ia » (jamais publié)
 api (prod / démo) ──httpx──► opencode serve ──► OpenAI (abonnement ChatGPT, OAuth)
        │                        │  agents : habitat-synthese, habitat-explication (aucun outil)
        │                        │           habitat-prix (websearch + webfetch seulement)
        │                        └──► Exa (recherche web, service public)
        │
 timers systemd (phase 2) : python -m app.cli synthese-commentaires   (chaque jour, 07:00)
                            python -m app.cli ia-prix                 (chaque heure, 07:10 → 20:10)
```

| Module | Contenu | Pur ? |
| --- | --- | --- |
| `extract/reponses_ia.py` | schémas JSON demandés à l'IA ; lecture et validation des réponses ; gardes contre l'invention (chiffres, prix, références) | oui |
| `ingest/opencode.py` | client HTTP d'OpenCode : session, message, sortie structurée, suppression de la session ; plafond d'appels ; journal technique `appel_ia` | orchestrateur (seul appel réseau vers l'IA) |
| `ingest/ia_synthese.py` | synthèse hebdomadaire, actions à cocher, vue de l'accueil | orchestrateur |
| `ingest/ia_prix.py` | explication des alertes prix, prix internet et son cache, essai | orchestrateur |
| `api/ia.py` | routes `/api/ia/…` | entrée |
| `web/src/components/SyntheseCommentaires.tsx`, `web/src/components/AvisIA.tsx` | carte de l'accueil, encart du détail d'un problème | front |
| `deploy/opencode/`, `deploy/docker-compose.ia.yml` | conteneur OpenCode, rattachement de l'API au réseau `habitat_ia` | exploitation |

Frontières (`tests/test_frontieres.py`) : `extract/reponses_ia.py` n'importe
ni httpx, ni SQLAlchemy, ni FastAPI ; `api/ia.py` n'importe que `ingest` et
`app.core` ; aucune règle `rules/` n'est touchée.

---

## 3. Socle

### 3.1 OpenCode (`deploy/opencode/`)

- **Image** `deploy/opencode/Dockerfile` : `node:22-slim`, `npm install -g
  opencode-ai@1.18.32` (version figée ; montée de version = geste
  volontaire), utilisateur non root `opencode` (uid 10002), `HOME=/home/opencode`,
  configuration copiée dans `/home/opencode/.config/opencode/opencode.json`,
  répertoire de travail vide `/srv/vide`, commande `opencode serve --hostname
  0.0.0.0 --port 4096`.
- **Compose** `deploy/opencode/docker-compose.yml` (projet `habitat_ia`) :
  service `opencode`, réseau `habitat_ia` (`name: habitat_ia`, créé par ce
  compose), **aucun port publié**, `restart: unless-stopped`,
  `no-new-privileges`, `cap_drop: ALL`, `pids_limit: 200`, `mem_limit: 512m`,
  volume `opencode-donnees` sur `/home/opencode/.local/share/opencode`
  (contient `auth.json`, le jeton de l'abonnement : secret, jamais lu ni
  copié par Claude). Variables : `OPENCODE_SERVER_PASSWORD` (obligatoire),
  `OPENCODE_ENABLE_EXA=1`, `OPENCODE_WEBSEARCH_PROVIDER=exa`, `EXA_API_KEY`
  (facultative), lues depuis `deploy/opencode/.env` (ignoré par git, modèle
  `deploy/opencode/exemple.env`). Pas de socket Docker, pas de base, pas de
  dépôt monté.
- **Configuration** `deploy/opencode/opencode.json` :
  - `autoupdate: false`, `share: "disabled"`, permission globale `{"*": "deny"}` ;
  - agent `habitat-synthese` : `mode: primary`, modèle `openai/gpt-5.4-mini`,
    permission `{"*": "deny"}`, `steps: 3`, consigne : résumer des
    commentaires de chantier en français simple, ne rien décider, ne citer
    que les références fournies ;
  - agent `habitat-explication` : idem, consigne : expliquer en une à trois
    phrases un écart de prix déjà calculé, sans jamais donner un chiffre
    absent des données fournies, sans dire si le prix est bon ou mauvais ;
  - agent `habitat-prix` : modèle `openai/gpt-5.4`, permission `{"*":
    "deny", "websearch": "allow", "webfetch": "allow"}`, `steps: 8`,
    consigne reprise du §10 du document d'Ilane (plusieurs résultats,
    fabricant ou revendeur identifiable, **ouvrir la page source avec
    webfetch**, vérifier référence, conditionnement et unité, sinon
    `prix_non_verifiable`, jamais de prix sans source).
  Vérifié le 27/09/2026 sur un conteneur d'essai : les règles se lisent de la
  dernière à la première (la dernière qui correspond gagne) ; `"*": "deny"`
  ferme tout, y compris `read`, `bash`, `edit`, `task`.
- **Connexion à l'abonnement** (Ilane, une fois) : `docker compose -f
  deploy/opencode/docker-compose.yml run --rm opencode opencode auth login`
  → OpenAI → « ChatGPT Pro/Plus (headless) » → ouvrir
  `https://auth.openai.com/codex/device` sur n'importe quel appareil et
  saisir le code affiché. Le jeton va dans le volume. **Avant** : dans
  ChatGPT, Paramètres → Contrôle des données → désactiver « Améliorer le
  modèle pour tout le monde » (sinon les données du client peuvent servir à
  l'entraînement). Modèles admis par OpenCode avec l'abonnement (1.18.32) :
  `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.3-codex-spark`.

### 3.2 Rattachement de l'API (`deploy/docker-compose.ia.yml`)

Surcouche **facultative**, ajoutée aux commandes compose d'une instance
seulement quand l'IA y est installée :

```
-f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml -f deploy/docker-compose.ia.yml
```

Elle rattache `api` au réseau externe `habitat_ia` (en plus du sien) et lui
passe `IA_ACTIVE`, `OPENCODE_URL` (`http://opencode:4096`),
`OPENCODE_MOT_DE_PASSE` et `IA_APPELS_MAX_JOUR`. Sans elle, rien ne change
pour une instance (l'IA est éteinte). Un seul conteneur OpenCode sert la
production et la démo (mémoire du VPS) ; la démo garde `IA_ACTIVE=false` sauf
décision contraire.

### 3.3 Réglages (`app/core/config.py`)

| Variable | Type | Défaut | Rôle |
| --- | --- | --- | --- |
| `IA_ACTIVE` | booléen | `false` | interrupteur général ; faux = aucune requête vers OpenCode, les tâches ne font rien et l'écran le dit |
| `OPENCODE_URL` | texte | aucun | adresse d'OpenCode ; **obligatoire si `IA_ACTIVE`** (refus de démarrer sinon) |
| `OPENCODE_MOT_DE_PASSE` | secret | aucun | mot de passe du serveur OpenCode (authentification HTTP Basic, utilisateur `opencode`) ; obligatoire si `IA_ACTIVE` |
| `IA_APPELS_MAX_JOUR` | entier ≥ 1 | 40 | plafond de requêtes à l'IA par jour (heure de Paris), toutes tâches confondues, pour ménager l'abonnement |

Fonction `ia_active() -> bool` dans `ingest/opencode.py` : seule lecture de
`IA_ACTIVE` (même principe que `regles_desactivees`).

### 3.4 Client (`ingest/opencode.py`)

`async def interroger(session, http, *, usage, agent, texte, schema, delai) ->
ReponseIA` — `usage` ∈ `{"synthese", "explication", "prix"}` :

1. si `ia_active()` est faux → `IAIndisponible("éteinte")` ;
2. si le nombre de lignes `appel_ia` du jour (heure de Paris) atteint
   `IA_APPELS_MAX_JOUR` → `IAIndisponible("plafond")` (aucune requête) ;
3. `POST {url}/session` (`{"title": "habitat-<usage>"}`) ;
4. `POST {url}/session/{id}/message` avec `{"agent": agent, "parts":
   [{"type": "text", "text": texte}], "format": {"type": "json_schema",
   "schema": schema, "retryCount": 1}}` (sortie structurée d'OpenCode) ;
5. réponse : `info.error` présent → `ErreurIA` (nom de l'erreur seulement :
   `ProviderAuthError` = abonnement déconnecté, `APIError` avec statut 429 =
   quota…) ; sinon `info.structured` (le JSON demandé) et, pour les parties
   de type `tool` terminées (`state.status == "completed"`), la liste des
   pages lues : `(tool, state.input.url ou state.input.query,
   state.output)` ;
6. `DELETE {url}/session/{id}` dans tous les cas (rien ne s'accumule côté
   OpenCode ; échec de suppression ignoré) ;
7. une ligne `appel_ia` (usage, statut `ok`/`erreur`, durée, nom d'erreur)
   **dans sa propre transaction** (le plafond compte aussi les échecs).

Authentification HTTP Basic (`opencode` / mot de passe). Délai : 90 s par
défaut, 240 s pour `prix`. Les messages d'`ErreurIA`/`IAIndisponible` ne
contiennent jamais le mot de passe, ni le texte envoyé, ni la réponse (même
principe qu'`ErreurOCR`). Le texte envoyé et la réponse ne sont jamais
écrits dans un log.

`ReponseIA(structure: Any, pages: tuple[PageLue, ...], modele: str | None,
duree_ms: int)`.

### 3.5 Lecture des réponses (`extract/reponses_ia.py`, pur)

Pour chaque usage : la constante du schéma JSON envoyé (§4.3, §5.2, §6.2) et
une fonction `lire_…(structure, …) -> …Lue` qui refuse
(`ReponseIAInvalide`, message court) toute réponse hors schéma : type
inattendu, champ manquant, texte vide ou trop long. Tout ce que l'application
enregistre est passé par ces fonctions.

---

## 4. Synthèse hebdomadaire des commentaires

### 4.1 Période et déclenchement

- Semaine = du lundi 00:00 au dimanche 23:59, heure de Paris.
- `python -m app.cli synthese-commentaires` : prend la **dernière semaine
  complète** ; si une synthèse existe déjà pour elle, ne fait rien ; si l'IA
  est éteinte, écrit « IA éteinte » et sort avec le code 0. Option `--semaine
  AAAA-MM-JJ` (un lundi) pour une semaine précise.
- Timer `synthese` : **chaque jour à 07:00** (prod) / 07:20 (démo). Le premier
  passage du lundi produit la synthèse ; si l'IA échoue, le passage du
  lendemain réessaie (idempotent).
- Semaine sans commentaire : synthèse enregistrée avec `statut = "vide"`,
  sans appel à l'IA (« Aucun commentaire cette semaine. »).

### 4.2 Données envoyées (minimisées)

Commentaires de la semaine (`commentaire.created_at` dans la période), du plus
ancien au plus récent, numérotés `c1`, `c2`… Pour chacun : la référence,
le jour (`lundi 21/09`), le **nom du fournisseur**, le **numéro du bon**, le
libellé de la ligne (`ligne_libelle`) et le **texte**. **Jamais** : le nom de
l'auteur, le chantier ni le client (le nom d'un chantier est souvent celui
d'un particulier), aucun identifiant. Plafond : 200 commentaires (les plus
récents) ; au-delà, la synthèse le dit (`nb_commentaires` réel gardé).

### 4.3 Réponse demandée (`SCHEMA_SYNTHESE`)

```json
{"resume": "texte, 1 200 caractères au plus",
 "actions": [{"texte": "texte, 300 caractères au plus",
              "commentaires": ["c1", "c3"]}]}
```

`lire_synthese(structure, references_valides)` : `resume` non vide ;
10 actions au plus (au-delà : les 10 premières) ; une action sans texte est
écartée ; ses références inconnues sont retirées ; une action dont **aucune**
référence n'est valide est écartée (toute action doit s'appuyer sur un
commentaire réel).

### 4.4 Données — tables

`synthese_commentaires` : `id`, `semaine_debut` (date, **unique**),
`semaine_fin` (date), `statut` (`ok` / `vide`, `CHECK`), `resume` (texte),
`nb_commentaires` (entier), `modele` (texte, nullable), `created_at`.

`synthese_action` : `id`, `synthese_id` (FK, `ON DELETE CASCADE`), `ordre`,
`texte`, `commentaire_ids` (JSONB : liste d'UUID en texte),
`document_ids` (JSONB : bons concernés, déduits des commentaires à
l'enregistrement), `faite_le` (horodatage, nullable), `faite_par` (FK
`utilisateur`, nullable), `created_at`.

Journal : `synthese_generee` (système, `apres` : semaine, statut,
nombre de commentaires et d'actions) ; `synthese_action_faite`,
`synthese_action_a_faire` (auteur, `apres` : texte de l'action, semaine).

### 4.5 Service (`ingest/ia_synthese.py`)

- `generer_synthese(session, http, *, semaine_debut) -> ResultatSynthese`
  (`creee`, `deja_faite`, `vide`, `ia_eteinte`, `echec`) ;
- `vue_accueil(session) -> SyntheseAccueil` : `ia_active`, la **dernière**
  synthèse (période, statut, résumé, nombre de commentaires, ses actions avec
  état et bons liés : `document_id` + numéro), puis `encore_a_faire` : les
  actions **non faites** des synthèses précédentes (20 au plus, les plus
  récentes d'abord, avec leur semaine) ;
- `marquer_action(session, action_id, *, faite: bool, utilisateur_id)` :
  idempotent, journalisé, 404 si inconnue.

### 4.6 API et écran

| Route | Accès | Rôle |
| --- | --- | --- |
| `GET /api/ia/synthese` | admin | `SyntheseAccueil` |
| `POST /api/ia/synthese/actions/{id}/faite` | admin | coche |
| `POST /api/ia/synthese/actions/{id}/a-faire` | admin | décoche |

Carte « Commentaires de la semaine » sur la Vue d'ensemble
(`SyntheseCommentaires.tsx`, montée par **une ligne** dans `VueEnsemble.tsx`),
sous les chiffres du mois :
- titre avec la période (« du 21 au 27 septembre ») et la mention discrète
  « Rédigé par l'IA — à vérifier » ;
- le résumé ; puis les actions, une case à cocher chacune (44 px),
  « faite par Léa le 28/09 » quand cochée, liens « Bon 1234 » vers les bons ;
- « Encore à faire » (repliable) : actions non faites des semaines
  précédentes, avec leur semaine ;
- aucune synthèse et IA allumée : « La synthèse des commentaires de la
  semaine arrive chaque lundi matin. » ; IA éteinte et aucune synthèse : la
  carte n'est pas affichée ;
- aucun mot technique (« IA » est le seul terme gardé : le client l'emploie).

---

## 5. Explication des alertes prix

### 5.1 Quelles alertes

Anomalies **ouvertes**, de catégorie `prix` (`CATEGORIES_REGLE`), **non
masquées** (`condition_regles_actives` : aujourd'hui R07-R09 sont masquées
tant que `CONTROLE_PRIX_ACTIF=false` ; demain R19-R25 selon les
interrupteurs du lot Prix), sans explication ou dont l'explication a été
faite sur un autre détail (empreinte SHA-256 du `detail` JSON canonique).
Les plus récentes d'abord, dans la limite du plafond du jour.

### 5.2 Données envoyées et réponse

Envoyé : le titre de la règle en mots (`ui`/`libelles` n'étant pas côté
serveur, un titre court par règle de prix dans `ingest/ia_prix.py`, repli
« Écart de prix »), le nom du fournisseur et le `detail` de l'anomalie (clé :
valeur). Rien d'autre.

`SCHEMA_EXPLICATION` : `{"explication": "texte, 400 caractères au plus"}`.

`lire_explication(structure, detail)` : texte non vide ; **garde des
chiffres** : chaque nombre écrit dans l'explication (`12,34`, `12.34`, `5`,
`5,3 %`) doit figurer parmi les nombres du `detail` (mêmes règles de lecture,
virgule ou point) — sinon la réponse est refusée (« chiffre absent des
données »). L'IA ne peut donc pas inventer un montant.

### 5.3 Données — table `explication_alerte`

`id`, `anomalie_id` (FK `anomalie`, `ON DELETE CASCADE`, **unique**),
`empreinte_detail`, `statut` (`ok` / `echec`), `texte` (nullable),
`echecs` (entier, défaut 0), `modele`, `created_at`, `updated_at`. Après 3
échecs sur le même détail, l'alerte n'est plus retentée (évite de brûler le
plafond) ; un nouveau détail remet le compteur à zéro.

---

## 6. Prix trouvé sur internet

### 6.1 Quels produits

Anomalies **ouvertes non masquées** de la règle **R22** (« Produit absent de
la grille », lot Prix) : constante `REGLES_PRIX_INTERNET = frozenset({"R22"})`.
Si le détail porte un dernier prix facturé (`dernier_prix` différent de
« — »), le produit a une référence interne : pas de recherche. Tant que le
lot Prix n'est pas fusionné, aucune anomalie R22 n'existe et rien ne part
(le code est prêt et testé sur des anomalies inventées).

Produit recherché : fournisseur (nom), désignation (`produit`), code
(`code`), unité (`unite_bon`), prix du bon (`prix_bon`, **non envoyé** à
l'IA : la recherche ne doit pas être orientée).

Clé de cache : fournisseur + code normalisé si présent, sinon désignation
normalisée (`normaliser_libelle`). Réutilisation d'un résultat `trouve` ou
`non_verifiable` de moins de **30 jours** ; après 3 `echec` en 7 jours, plus
de tentative pour ce produit pendant 7 jours.

### 6.2 Réponse demandée (`SCHEMA_PRIX_INTERNET`)

```json
{"statut": "trouve | prix_non_verifiable",
 "produit_trouve": "…", "prix": 12.34, "devise": "EUR", "taxes": "HT | TTC | inconnu",
 "unite": "…", "conditionnement": "…",
 "source_url": "https://…", "confiance": "faible | moyenne | elevee",
 "raison": "… (si non vérifiable)"}
```

`lire_prix_internet(structure, pages)` — gardes, dans l'ordre :
1. `statut = prix_non_verifiable` → résultat non vérifiable (raison gardée) ;
2. `prix > 0`, `devise = EUR`, `source_url` en `https://`, `produit_trouve`
   et `confiance` présents — sinon non vérifiable (« réponse incomplète ») ;
3. **la page `source_url` a réellement été lue** dans cette session
   (`webfetch` terminé sur la même adresse, à la barre oblique finale près)
   — sinon non vérifiable (« source non ouverte ») ;
4. **le prix figure dans le texte de cette page** (`12,34`, `12.34`,
   `12,34 €`, espace des milliers) — sinon non vérifiable (« prix absent de
   la page »).
Seul un résultat qui passe les quatre gardes est `trouve`. Jamais de prix
estimé.

### 6.3 Données — table `prix_internet`

`id`, `fournisseur_id` (FK, nullable), `cle`, `designation`, `code`
(nullable), `statut` (`trouve` / `non_verifiable` / `echec`), `prix`
(numérique, nullable), `devise`, `taxes` (`HT`/`TTC`, nullable : un prix public est souvent TTC, celui du bon HT — l'écran le dit), `unite`, `conditionnement`,
`produit_trouve`, `source_url`, `confiance`, `raison`, `modele`,
`consulte_le` (horodatage), `created_at`. Historique : une ligne par
recherche, jamais modifiée ; la plus récente fait foi.

### 6.4 Tâche, API et écran

- `python -m app.cli ia-prix` : d'abord les explications (§5), puis les
  prix internet (§6), dans la limite du plafond du jour ; résumé en sortie
  (« 3 explications, 1 prix trouvé, 1 non vérifiable ») ; code 0 même si
  une alerte échoue (l'échec est dans `appel_ia` et `explication_alerte`),
  code 1 seulement si tout échoue faute d'IA joignable (le timer alerte
  alors sur Telegram, phase 2).
- Timer `ia-prix` : **chaque heure de 07:10 à 20:10** (prod) / 07:40 → 20:40
  (démo).
- `GET /api/ia/anomalies/{id}` (admin) → `{ia_active, explication: {texte,
  cree_le} | null, prix_internet: {statut, prix, devise, unite,
  conditionnement, produit_trouve, source_url, confiance, raison,
  consulte_le} | null}` ; 404 si l'anomalie est inconnue ou masquée.
- `AvisIA.tsx`, monté par **une ligne** dans `ProblemeDetail.tsx` pour la
  catégorie « prix » : encart « Avis de l'IA — à titre indicatif » avec
  l'explication, puis « Prix trouvé sur internet : 12,34 € (seau de 15 L),
  consulté le 28/09 — voir la source » (lien externe, `rel="noopener
  noreferrer"`) ou « Prix introuvable sur internet : raison ». Rien si l'IA
  n'a encore rien produit.
- **Page « Prix à vérifier » (`/prix`, lot Prix)** : la 3ᵉ colonne « Internet »
  s'ajoutera quand le lot Prix sera dans `dev` (tâche T10 du plan, qui lira
  le même service). Hors de ce lot tant que la page n'existe pas.

---

## 7. Essai avant de se fier au prix internet (document d'Ilane §16)

`python -m app.cli essai-prix-internet --fichier produits.csv` : une ligne
par produit (`fournisseur;designation;code;unite`), pour chacun une recherche
(sans cache, comptée dans le plafond), sortie CSV sur la console :
produit, statut, prix, unité, conditionnement, source, confiance, raison,
durée. Rien n'est enregistré hors `appel_ia`. Le fichier de produits réels
reste hors du dépôt (`tests/fixtures/` ou dossier personnel). Critères
d'Ilane : aucun faux prix présenté comme sûr, échecs explicites, majorité
des produits vraiment en vente publique retrouvés, chaque prix vérifiable par
sa source. La comparaison avec les grilles se fait à la main, chez nous : les
prix des grilles ne partent jamais vers l'IA.

---

## 8. Données — migration `0014_ia`

Tables `appel_ia` (`id`, `usage` `CHECK IN ('synthese','explication','prix')`,
`statut` `CHECK IN ('ok','erreur')`, `erreur` texte nullable, `duree_ms`,
`created_at`, index sur `created_at`), `synthese_commentaires`,
`synthese_action`, `explication_alerte`, `prix_internet` (§4.4, §5.3, §6.3).
`down_revision = "0012"` (commentaires). Le lot Prix ajoute `0013` en
parallèle : **la branche qui fusionne dans `dev` en second** remet la chaîne
en ligne (roadmap §2.4) ; `tests/test_migrations.py` le vérifie.

---

## 9. Sous-traitants, RGPD et risques (avenant au CDC, à confirmer par Ilane)

Nouveaux sous-traitants (CDC §8) :

| Sous-traitant | Usage | Localisation | Données |
| --- | --- | --- | --- |
| OpenAI (via l'abonnement ChatGPT d'Ilane) | synthèse, explication, recherche de prix | États-Unis | texte des commentaires sans nom d'auteur ni chantier ; fournisseur, désignations, codes et unités des produits ; chiffres des alertes prix |
| Exa (service public de recherche d'OpenCode) | recherche web | États-Unis | requêtes de recherche (désignations de produits) |

Risques consignés :
1. **Conditions d'utilisation.** L'abonnement ChatGPT est personnel ; OpenAI
   n'a pas dit clairement qu'un serveur pouvait s'en servir pour
   l'application d'un client. Un compte suspendu = IA indisponible (le reste
   de l'application continue). Parade : `IA_ACTIVE=false` coupe tout ;
   remplacer le moteur = réécrire `ingest/opencode.py` (API OpenAI ou
   Mistral payantes à l'usage).
2. **Compte personnel d'Ilane** : l'usage du client consomme son quota ; sur
   le serveur dédié au client, prévoir un abonnement ou une clé au nom du
   client.
3. **Transfert hors UE** (ci-dessus) : à inscrire au registre du client.
4. **Mémoire du VPS** : un conteneur de plus (plafonné à 512 Mo).
5. **Prix internet** : prix public, pas le prix d'Habitat ; toujours affiché
   comme indicatif, jamais utilisé par une règle.

---

## 10. Tests

- **Purs** : `extract/tests/test_reponses_ia.py` — synthèse (références
  inconnues retirées, action sans référence écartée, bornes), explication
  (garde des chiffres : chiffre présent accepté, chiffre inventé refusé,
  virgule/point), prix internet (chacune des quatre gardes, prix au format
  français dans la page, barre oblique finale).
- **Client** : `ingest/tests/test_opencode.py` avec `httpx.MockTransport`
  (session, message, sortie structurée, pages lues, erreur du fournisseur,
  401, délai dépassé, suppression de session, plafond atteint = aucune
  requête, IA éteinte = aucune requête, secrets absents des messages).
- **Base** : synthèse (semaine vide, idempotence, données envoyées sans
  auteur ni chantier — vérifié sur le texte envoyé au faux client, actions
  et bons liés, cocher/décocher journalisés, « encore à faire ») ;
  explication (sélection, empreinte, 3 échecs, alerte masquée ignorée) ;
  prix internet (R22 seulement, cache 30 jours, dernier prix présent = pas de
  recherche, échecs répétés) ; API (admin seulement, 404).
- **Config** : `IA_ACTIVE=true` sans URL ou sans mot de passe → refus de
  démarrer.
- **Exploitation** : `tests/test_installer_taches.py` (tâches `synthese` et
  `ia-prix`, horaires) ; `opencode.json` valide (JSON, permission globale
  `deny`, outils des agents).
- **Front** : typecheck, build, tests texte existants.
- **Sans abonnement**, aucun test ne touche le réseau ; l'essai de bout en
  bout se fait après la connexion de l'abonnement (§7).

## 11. Hors périmètre

Contrôle des prix à la facture (phase 4, non IA) ; colonne « Internet » de
la page Prix (après fusion du lot Prix, T10) ; notification Telegram de la
synthèse ; régénération manuelle d'une synthèse depuis l'écran ; mémoire de
l'IA d'une semaine à l'autre.
