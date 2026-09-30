# Architecture : Contrôle BL & factures

Ce document montre l'architecture du projet « Contrôle BL & factures »
(Habitat & Rénovation), surtout par des schémas. Chaque schéma est suivi de
quelques lignes d'explication et de ses sources (`fichier:ligne`). Il ne
remplace ni le cahier des charges (`docs/cahier-des-charges.md`, qui fait
foi) ni la documentation technique détaillée (`infra/README.md`).

- **État décrit** : rédigé le 24/09/2026 (branche `refonte-front` au commit
  `ee28162`, constats sur le VPS du 24/09/2026), **mis à jour le 29/09/2026**
  sur `dev` (commit `28e1600`) pour les phases 1 à 4 d'octobre : §3 (modules),
  §4 (tables et migrations jusqu'à 0015), §7 (routes du front), §8 (règles R01
  à R25) et §9 sont à jour ; les schémas et constats des §2, §4.1, §4.2, §5 et
  §6 décrivent l'état du 24/09/2026 et sont complétés par des encadrés
  « Mise à jour du 29/09/2026 ». Vue d'ensemble à jour : `README.md`.
- **Principe directeur** : l'IA (OCR Mistral, puis, en phase 4, un assistant
  interne qui résume, explique et cherche à titre indicatif) extrait,
  normalise et commente, elle ne décide jamais. Les anomalies (« problèmes » à
  l'écran) viennent de règles déterministes R01 à R25, et chacune porte une
  justification chiffrée.

## Sommaire

1. [Contexte](#1-contexte)
2. [Conteneurs et déploiement](#2-conteneurs-et-déploiement)
3. [Modules applicatifs et frontières](#3-modules-applicatifs-et-frontières)
4. [Modèle de données](#4-modèle-de-données)
5. [Flux](#5-flux)
6. [Cycles de vie](#6-cycles-de-vie)
7. [Front](#7-front)
8. [Règles de contrôle](#8-règles-de-contrôle)
9. [Renvois](#9-renvois)

---

## 1. Contexte

```mermaid
flowchart LR
  agent["Agents travaux et chefs de chantier - rôle agent"]
  admin["Dirigeant et personnes désignées - rôle admin"]
  compta["Comptable, si distinct - rôle admin"]
  presta["Prestataire - accès serveur, sans compte applicatif"]

  subgraph telegram["Telegram"]
    tg_bl["Groupe BL chantiers"]
    tg_sup["Groupe de supervision"]
  end

  nav["Navigateur, ordinateur ou téléphone"]
  appli["Contrôle BL et factures - application web, une instance par usage"]
  mistral["API Mistral OCR"]
  drive["Google Drive - classement des originaux, bloqué"]

  agent -->|"photo du BL"| tg_bl
  tg_bl -->|"webhook"| appli
  appli -->|"accusé et deux boutons"| tg_bl
  appli -->|"une ligne par dépôt, signalements"| tg_sup
  admin --> nav
  compta --> nav
  agent -.->|"consulte ses dépôts"| nav
  nav -->|"HTTPS, cookie de session"| appli
  appli -->|"OCR des photos et des factures"| mistral
  appli -.->|"drive-sync, jamais exécuté en réel"| drive
  presta -.->|"SSH, docker compose, CLI"| appli
```

Deux rôles applicatifs seulement, `admin` et `agent`. Les agents déposent les
photos de BL dans un groupe Telegram et confirment les quantités avec les
boutons du bot. L'admin dépose les factures PDF, traite les problèmes et
valide les référentiels ; le comptable a le même rôle. Mistral OCR est le
seul service qui lit les documents. Google Drive est prévu pour y ranger les
originaux, mais reste bloqué : un compte de service ne peut pas écrire dans
un Drive personnel, et le choix de la solution revient à Ilane.

Sources : `docs/cahier-des-charges.md:50-61`,
`app/modules/ingest/router.py:150-215`, `app/modules/ingest/mistral.py:1-22`,
`infra/README.md:972-985`, `docs/refonte-front-recette.md` §6.

---

## 2. Conteneurs et déploiement

```mermaid
flowchart TB
  navigateur["Navigateurs - admin, comptable, agents"]
  serveurs_tg["Serveurs Telegram - webhook entrant, API Bot sortante"]

  subgraph vps["VPS OVH partagé - Debian 12, Docker Compose"]
    nginx["nginx de l'hôte - 80 et 443, TLS Let's Encrypt, en-têtes, limit_req"]
    traefik["Traefik v3.6 - prévu par docker-compose.yml, désactivé sur le VPS"]

    subgraph inst_prod["Production - projet habitat_prod, .env.prod"]
      api_prod["API FastAPI et front React - habitat.ellumena.fr vers 127.0.0.1:8450"]
      pg_prod[("PostgreSQL 18")]
      docs_prod[("Originaux - habitat-data/prod/docs")]
    end

    subgraph inst_demo["Démonstration - projet habitat_demo, .env.demo"]
      api_demo["API FastAPI et front React - demo.habitat.ellumena.fr vers 127.0.0.1:8451"]
      pg_demo[("PostgreSQL 18")]
      docs_demo[("Originaux fictifs - habitat-data/demo/docs")]
    end

    subgraph inst_dev["Développement - projet habitat_reno"]
      pg_dev[("PostgreSQL 18 - 127.0.0.1:5450, bases de test")]
    end

    cli["CLI python -m app.cli - docker compose exec -T api"]
    cron["crontab : sauvegarde 03:00, controles-differes 06:15, drive-sync à la minute 10"]
    backup["deploy/backup.sh - pg_dump et restic en conteneur, vise le dev par défaut"]
    dumps[("6 pg_dump manuels : 3 prod, 3 démo - même disque, sans les originaux")]
  end

  mistral["API Mistral OCR"]
  drive["Google Drive"]
  s3["Object Storage OVH compatible S3"]

  navigateur -->|"HTTPS"| nginx
  serveurs_tg -->|"HTTPS POST /tg/webhook"| nginx
  nginx --> api_prod
  nginx --> api_demo
  api_prod --> pg_prod
  api_prod --> docs_prod
  api_demo --> pg_demo
  api_demo --> docs_demo
  api_prod -->|"POST /v1/ocr"| mistral
  api_demo -->|"POST /v1/ocr"| mistral
  api_prod -->|"réponses, supervision"| serveurs_tg
  cli -->|"exécutée dans le conteneur api"| api_prod
  cron -.-> cli
  cron -.-> backup
  backup -.-> s3
  cli -.->|"drive-sync"| drive
  pg_prod -.->|"copies manuelles"| dumps
  pg_demo -.->|"copies manuelles"| dumps

  classDef prevu stroke-dasharray: 5 5
  class traefik,cron,backup,s3,drive prevu
```

Le trait plein montre ce qui tourne, le pointillé ce qui est prévu mais pas
posé.

- **Une instance** = un nom de projet Compose et un fichier d'environnement,
  avec sa base, son volume et son dossier de documents. Commande type :
  `docker compose -p habitat_prod --env-file .env.prod -f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml up -d`.
- **nginx** (`deploy/nginx/habitat.conf`, identique à la copie installée)
  aiguille selon le nom d'hôte, termine le TLS avec un seul certificat pour
  les deux noms et pose les en-têtes nosniff, DENY, `same-origin`, HSTS et
  une CSP stricte. Il limite les requêtes à 10 par seconde (zone `general`
  de l'hôte, rafale de 40) et les corps à 25 Mo. Traefik, prévu par la pile
  de base, reste dans un profil jamais activé sur ce VPS.
- **Image** : un étage `node:24-alpine` construit le front, puis
  `python:3.11-slim` avec uv. uvicorn sert l'API et `web/dist` sur le port
  8000, avec l'uid 10001 et `--proxy-headers --forwarded-allow-ips=*`. Le
  port n'est publié que sur la boucle locale.
- **Limite de connexion** : slowapi limite `POST /api/auth/login` à 5
  requêtes par minute et par adresse. L'adresse réelle vient de
  `X-Forwarded-For`, transmis par nginx.
- **Pas de worker ni de file d'attente** : les tâches périodiques sont des
  commandes CLI. `crontab` n'est pas installé (paquet `cron` absent), donc
  aucune ligne cron n'est posée. restic tourne en conteneur
  (`restic/restic:0.19.1` via `docker run`), mais aucun dépôt ni aucune
  variable `RESTIC_*` n'est configuré. `backup.sh` vise le développement par
  défaut (`.env`, projet `habitat_reno`) : pour la production ou la
  démonstration, il faut lui passer `HABITAT_RENO_ENV_FILE` et
  `COMPOSE_PROJECT_NAME`. Les seules copies sont six `pg_dump` manuels sur
  le même disque, trois de la production et trois de la démonstration.
- **Variables** : sont obligatoires `database_url`, `docs_dir`, les quatre
  variables Telegram, `mistral_api_key` et `cookie_secure`. Sont optionnelles
  les deux variables Drive et trois drapeaux à `false` par défaut :
  `CONTROLE_PRIX_ACTIF`, `CONTROLE_LIVRE_NON_FACTURE_ACTIF` et
  `API_DOCS_ACTIVES`. Il manque une variable obligatoire ? L'API refuse de
  démarrer. Compose exige en plus `POSTGRES_USER`, `POSTGRES_PASSWORD`,
  `POSTGRES_DB`, `DOCS_HOST_DIR`, `API_HOST_PORT` (surcouche `vps`),
  `DOMAIN` et `ACME_EMAIL`. Les deux dernières servent à Traefik (label du
  service `api`, commande du service `traefik`), mais Compose les exige
  même sur le VPS, où Traefik est désactivé.
- **Vigilance** : la surcouche de développement publie l'API sur
  127.0.0.1:8450, et le proxy Vite de `npm run dev` vise ce port. Or c'est
  aujourd'hui celui de la production. `deploy/test-restauration.sh` utilise
  8451, celui de la démonstration.

**Mise à jour du 29/09/2026.** Ce schéma et ces constats datent du 24/09.
Depuis : les tâches planifiées sont des **minuteries systemd utilisateur**
(`deploy/installer-taches.sh` : rangement des photos, sauvegarde, contrôles
différés ; `synthese` et `ia-prix` pour l'IA, non posées par défaut), et non
une crontab ; les sauvegardes restic sont posées, dans des **dépôts locaux**
provisoires (`~/sauvegardes-habitat/`), avec une alerte d'échec Telegram
(`deploy/alerte-echec.sh`) ; un **projet Compose supplémentaire `habitat_ia`**
porte le conteneur OpenCode (réseau interne, aucun port publié), rattaché à
l'API par `deploy/docker-compose.ia.yml` quand l'IA est allumée (démo :
allumée ; production : éteinte) ; l'IA appelle OpenAI par le compte ChatGPT
d'Ilane et Exa pour la recherche web. `drive-sync` n'est toujours pas
planifiée (Drive bloqué). Le canal de supervision Telegram a été supprimé le
28/09. Schéma à jour : `README.md` §6.1.

Sources : `deploy/docker-compose.yml:1-115`,
`deploy/docker-compose.vps.yml:1-24`, `deploy/docker-compose.dev.yml:1-14`,
`deploy/nginx/habitat.conf:1-55`, `Dockerfile:1-40`,
`app/core/config.py:69-83`, `app/core/auth.py:221-227`,
`deploy/backup.sh:1-118`, `infra/README.md:822-882`,
`web/vite.config.mts:4-38`, `deploy/test-restauration.sh:2-18`. Constats
`docker ps`, `docker volume ls`, `crontab -l`, `systemctl list-timers`,
`dpkg -l cron`, `ls /home/debian/sauvegardes-habitat/` et
`docker compose config` du 24/09/2026.

---

## 3. Modules applicatifs et frontières

```mermaid
flowchart TB
  web["web/ - React, compilé dans l'image"]

  subgraph entrees["Couches d'entrée"]
    main["app/main.py - lifespan, montage des routeurs, /health"]
    api["api - routeurs JSON sous /api"]
    jobs["jobs - drive, drive_sync"]
    cli["app/cli.py - commandes"]
  end

  ingest["ingest - seul orchestrateur : models.py, /tg/webhook, services, IA"]

  subgraph purs["Modules purs - dataclasses, sans base ni réseau"]
    extract["extract - bl, unikalo, verification, confiance, ocr, grille_excel, reponses_ia"]
    normalize["normalize - fournisseur, chantier, article, unites, appariement, prix, texte"]
    rules["rules - engine, modeles, R01 à R25"]
  end

  messaging["messaging - Protocol Messagerie, client Telegram httpx"]
  core["app/core - config, db, auth, origine, front, fuseau"]

  web -->|"HTTP /api, types openapi-typescript"| api
  main --> api
  main --> ingest
  main --> core
  api --> ingest
  api --> core
  jobs --> ingest
  jobs --> core
  ingest --> extract
  ingest --> normalize
  ingest --> rules
  ingest --> messaging
  ingest --> core
  core -.->|"exception L2-D4 : auth importe ingest.models"| ingest
  cli --> ingest
  cli --> jobs
  cli --> core
  cli -.->|"hors garde"| extract
  cli -.->|"hors garde"| messaging

  classDef pur fill:#eef6ee,stroke:#3a7a3a
  class extract,normalize,rules pur
```

C'est un monolithe modulaire, et `ingest` est le seul module métier qui en
importe d'autres. Il possède le schéma (`models.py`) et le webhook
Telegram : le routeur vit dans `ingest` parce que `messaging` ne peut pas
importer `ingest`. Il enchaîne extraction, normalisation, rapprochement et
règles. `api` et `jobs` sont des couches d'entrée : elles n'importent que
`ingest` et `app.core`. Un routeur valide, appelle un service et sérialise,
sans aucune règle métier.

**Ajouts d'octobre (mise à jour du 29/09/2026).** Tous dans `ingest`, sauf
mention contraire : `rattachement_chantier` et `fusion_chantier` (chantiers
automatiques, R18, fusion), `rangement` (photos rangées), `commentaires`,
`grilles` et `prix_bl` (grilles de prix, contrôle des prix d'un bon, R19 à R25),
`opencode` (seul module qui parle au moteur d'IA), `ia_synthese`, `ia_prix` (avis
sur les alertes de prix, prix internet à plusieurs sources) et `ia_labo`
(Laboratoire IA). Côté modules purs : `extract/grille_excel.py` (lecture des
grilles Excel), `extract/reponses_ia.py` (schémas et gardes contre l'invention
des réponses de l'IA), `normalize/prix.py` (produit, prix net, unités) et
`normalize/texte.py` (ressemblance). Côté `api` : routeurs `comptes`,
`commentaires`, `grilles`, `prix`, `ia`. Les frontières sont inchangées et
toujours vérifiées par le même test.

Interdits, vérifiés par `tests/test_frontieres.py` (analyse `ast` de
`app/modules`, imports placés dans les fonctions compris) :

- `extract`, `normalize` et `rules` n'importent ni `fastapi`, ni `starlette`,
  ni `sqlalchemy`, ni `httpx`, ni `asyncpg`.
- Hors `ingest`, aucun module de `app.modules` n'en importe un autre ;
  `api` et `jobs` peuvent importer `ingest`, et rien d'autre. Cette garde
  couvre donc aussi L4-D1 : `rules` n'importe ni `extract` ni `normalize`,
  et ne réutilise pas leurs dataclasses.

Constat au 24/09/2026, que rien ne garde : une règle n'importe que
`rules.modeles`, plus une règle sœur pour un helper partagé (R01 importe
R02, R04 importe R03, R08 importe R07). La garde ne regarde pas les imports
internes à `rules` : un import d'`engine` ou d'une autre règle ne serait pas
signalé.

Hors garde : `app/core`, `app/main.py` et `app/cli.py` ne sont pas scannés.
C'est ce qui permet à `core/auth.py` d'importer `ingest.models` (exception
assumée) et à `cli.py` d'importer `extract` et `messaging` (en pointillé).

Écarts avec l'arborescence de `CLAUDE.md` : `jobs` ne contient que `drive.py`
et `drive_sync.py`, sans bilan ni rappels ; le bilan est dans
`ingest/bilan.py`. `extract/facture.py` ne définit que les types d'une
facture lue (dataclasses, `TypeLigne`, `FactureIllisible`) : la facture est
lue par `extract/unikalo.py` et le BL par `extract/bl.py`. Plusieurs
renvois citent encore `ingest/service.py`, découpé à la fin du lot 2 : les
docstrings de `messaging/base.py` et d'`api/schemas.py` (lignes 5 et 123),
et les commentaires de `Document.photo_compressee` et de `BlocFacture.ordre`
(`ingest/models.py:293` et `:362`).

Sources : `app/main.py:26-89`, `app/modules/api/__init__.py:3-37`,
`app/modules/ingest/router.py:1-22`, `app/core/auth.py:16-40`,
`app/cli.py:62-129`, `tests/test_frontieres.py:34-183`,
`app/modules/rules/__init__.py:1-13`, `app/modules/rules/rules/R01.py:17`,
`R04.py:24`, `R08.py:25`, `app/modules/extract/facture.py:17-90`,
`app/modules/api/schemas.py:1-8`, `app/modules/jobs/drive_sync.py:1-40`.

---

## 4. Modèle de données

`app/modules/ingest/models.py` est la source de vérité unique du schéma. Il
déclare **23 tables** au 29/09/2026 : les 15 du 24/09/2026 (les 14 du CDC plus
`jeton_session`) et 8 ajoutées en octobre (§4.4). Les vues 4.1 et 4.2
décrivent l'état du 24/09/2026 (tête `0010`).

### 4.1 Cœur métier

```mermaid
erDiagram
  fournisseur ||--o{ agence_fournisseur : "possede"
  fournisseur ||--o{ chantier_alias : "libelles vus"
  fournisseur ||--o{ article : "catalogue"
  fournisseur |o--o{ document : "emet"
  agence_fournisseur |o--o{ document : "agence"
  document ||--o{ bloc_facture : "facture decoupee en blocs"
  document |o--o{ bloc_facture : "BL rapproche"
  document ||--o{ ligne : "lignes"
  bloc_facture |o--o{ ligne : "lignes du bloc"
  article |o--o{ ligne : "article reconnu"
  ligne ||--o{ rapprochement_ligne : "cote facture"
  ligne ||--o{ rapprochement_ligne : "cote BL"
  document |o--o{ anomalie : "portee"
  bloc_facture |o--o{ anomalie : "portee"
  ligne |o--o{ anomalie : "portee"
  article |o--o{ anomalie : "regle des 90 jours"
  chantier_alias |o--o{ anomalie : "portee R14"
  chantier |o--o{ chantier_alias : "resolu en"
  chantier |o--o{ document : "chantier du BL"
  chantier |o--o{ bloc_facture : "chantier du bloc"
  chantier |o--o{ anomalie : "portee R16"

  fournisseur {
    uuid id PK
    text nom
    text siret
    text tva
    text aliases "tableau de text"
  }
  agence_fournisseur {
    uuid id PK
    uuid fournisseur_id FK
    text nom
    text adresse
  }
  chantier {
    uuid id PK
    text nom_canonique
    text agence
    text client "ajout 0010"
    bool actif
    date ouvert_le
    date ferme_le
  }
  chantier_alias {
    uuid id PK
    uuid fournisseur_id FK "unique avec libelle_brut et code_brut"
    text libelle_brut
    text code_brut
    uuid chantier_id FK "NULL tant que non valide"
    uuid valide_par FK
    timestamp valide_le
  }
  article {
    uuid id PK
    uuid fournisseur_id FK "unique avec code"
    text code
    text libelle
    text unite_cdt
    text unite_fact
    numeric ratio
    bool valide "false a la creation"
  }
  document {
    uuid id PK
    int numero_interne UK "bigint identity, affiche"
    text type "bl, enlevement, facture, avoir"
    text source "telegram, upload"
    text statut "recu, a_verifier, archive"
    uuid fournisseur_id FK "unique avec numero"
    text numero
    date date_doc
    uuid agence_fournisseur_id FK
    text chantier_brut "libelle lu, BL"
    uuid chantier_id FK
    uuid deposant_id FK
    bool photo_compressee "ajout 0003"
    uuid confirme_par FK
    timestamp confirme_le
    text fichier_path
    numeric total_ht
    numeric confiance_min
    jsonb ocr_brut
    jsonb extraction "valeurs OCR d origine, immuable"
    jsonb motifs
    text drive_url
    timestamp drive_sync_le
  }
  bloc_facture {
    uuid id PK
    uuid facture_id FK
    int ordre
    text numero_bl
    date date_bl
    text chantier_brut
    uuid chantier_id FK
    text commentaire
    uuid bl_document_id FK "0 ou 1 BL"
    text statut_rapprochement "recu, non_recu, pas_de_bon, NULL"
  }
  ligne {
    uuid id PK
    uuid document_id FK
    uuid bloc_id FK
    uuid article_id FK
    text type_ligne "article, eco, commentaire"
    text code_brut
    text article_brut
    numeric qte_livree "nb de conditionnements"
    numeric qte_totale "quantite"
    text unite_brut
    numeric qte_fact
    numeric pu_ht
    numeric remise_pct
    numeric montant_ht
    numeric confiance
    int ordre
  }
  rapprochement_ligne {
    uuid id PK
    uuid ligne_facture_id FK
    uuid ligne_bl_id FK
    text methode "code, libelle, manuel"
    numeric ecart_qte
  }
  anomalie {
    uuid id PK
    text regle "R01 a R17"
    text gravite "haute, moyenne, basse"
    text statut "ouverte, traitee, ignoree"
    jsonb detail "jamais vide"
    uuid document_id FK
    uuid bloc_id FK
    uuid ligne_id FK
    uuid article_id FK
    uuid chantier_id FK
    uuid alias_id FK
    uuid traitee_par FK
    timestamp traitee_le
    text commentaire
  }
```

Une facture (`document` de type `facture`) se découpe en blocs
« Concerne le B.L. n°… ». Chaque bloc pointe vers 0 ou 1 BL déposé
(`bl_document_id`), et le rapprochement apparie ses lignes à celles du BL
(`rapprochement_ligne`). Une anomalie est identifiée de façon unique par
(`regle`, `document_id`, `bloc_id`, `ligne_id`, `chantier_id`, `alias_id`)
en `NULLS NOT DISTINCT` ; c'est la clé de l'upsert décrit au §5.3. Un alias
de chantier est créé sans `chantier_id` et attend la validation d'un admin.
Un article est créé non validé à la première ligne qui porte un code.

Le schéma ne montre que les colonnes principales. Il omet notamment, sur
`document`, `telegram_message_id`, `numero_commande`, `enleve_par`,
`total_tva`, `total_ttc` et les quatre colonnes `drive_sync_*` de suivi des
échecs (migration 0009) ; sur `ligne`, `pu_cdt` et `tva` ; sur
`bloc_facture`, `numero_commande` ; et partout `created_at`, `updated_at` et
`updated_by`. Sur une ligne, `qte_livree` est le nombre de conditionnements
(colonne QTÉ LIVRÉE) et `qte_totale` la quantité (QTÉ TOTALE), sur un BL
comme sur une facture Unikalo (L3-D24).

### 4.2 Comptes et traçabilité

```mermaid
erDiagram
  utilisateur ||--o{ jeton_session : "sessions actives"
  utilisateur |o--o{ journal : "auteur, NULL si automatique"
  utilisateur |o--o{ parametre : "modifie_par"
  utilisateur |o--o{ document : "deposant_id et confirme_par"
  utilisateur |o--o{ chantier_alias : "valide_par"
  utilisateur |o--o{ anomalie : "traitee_par"

  utilisateur {
    uuid id PK
    text email UK
    text nom
    text mdp_hash "argon2"
    text role "admin, agent"
    text agence
    int telegram_user_id "bigint, liste blanche"
    bool actif
  }
  jeton_session {
    text token PK
    uuid utilisateur_id FK
    timestamp created_at "creation et derniere activite, 12 h"
  }
  journal {
    uuid id PK
    uuid utilisateur_id FK
    text action
    text cible_table
    text cible_id "text pour viser aussi parametre"
    jsonb avant
    jsonb apres
    timestamp horodatage
  }
  parametre {
    text cle PK
    text valeur
    uuid modifie_par FK
    timestamp modifie_le
  }
  telegram_update {
    int update_id PK "bigint, dedoublonnage"
    timestamp recu_le
  }
  document {
    uuid id PK
  }
  chantier_alias {
    uuid id PK
  }
  anomalie {
    uuid id PK
  }
```

Conventions : identifiant UUID généré par la base, sauf `parametre` (`cle`),
`telegram_update` (`update_id`) et `jeton_session` (`token`). `created_at`
est présent partout. `updated_at` et `updated_by` (vers `utilisateur`, non
dessiné) figurent sur les tables modifiables, sauf `parametre`, qui a
`modifie_par` et `modifie_le` ; `journal`, `telegram_update` et
`jeton_session` n'en ont pas. Les listes fermées sont en `text` avec un
`CHECK` nommé, sans ENUM, et les montants en `numeric` (lus en `Decimal`).
Aucune relation ORM, aucune suppression en cascade, aucune suppression
physique de document. `journal` et `telegram_update` ne reçoivent que des
ajouts. Le fuseau d'affichage est Europe/Paris, et tout est stocké en UTC.

### 4.3 Migrations

| Migration | Apport |
| --- | --- |
| 0001 `schema_initial` | Les 14 tables du CDC et leurs contraintes |
| 0002 `jeton_session` | Sessions de la `DatabaseStrategy` fastapi-users |
| 0003 `document_supervision` | `numero_interne`, `photo_compressee`, `total_ht` |
| 0004 `bloc_facture_ordre` | `bloc_facture.ordre` (position dans la facture) |
| 0005 `extraction` | Colonnes d'extraction du document, `ligne.confiance` |
| 0006 `anomalies` | `anomalie.article_id`, première clé d'unicité |
| 0007 `anomalie_chantier` | `chantier_id` et `alias_id`, clé d'unicité à six colonnes |
| 0008 `anomalie_bloc_origine` | Données seules : `bloc_id` complété pour R07, R08, R09, R13, R17 |
| 0009 `drive_sync` | Suivi de la synchronisation Drive sur `document` |
| 0010 `chantier_client` | `chantier.client` |
| 0011 `chantier_auto` | `document.legende`, `chantier.a_completer`, `chantier.fusionne_dans_id`, réglage `seuil_ressemblance_chantier_pct` (avenant du 27/09) |
| 0012 `commentaire` | Table `commentaire` (append-only) |
| 0013 `grilles_prix` | `grille_import`, `grille_prix` (historique inaltérable par déclencheurs PostgreSQL), `anomalie.ligne_id` en cascade |
| 0014 `ia` | `appel_ia`, `synthese_commentaires`, `synthese_action`, `explication_alerte`, `prix_internet` |
| 0015 `prix_internet_offres` | `prix_internet.offres` (JSONB, jusqu'à cinq offres) et reprise des prix déjà trouvés (tête actuelle) |

`tests/test_migrations.py` vérifie que `upgrade head` crée les tables et que
`alembic check` ne voit aucune dérive ; il vérifie aussi que la chaîne 0001 à
0015 est linéaire, avec une seule tête. En production, la révision appliquée
au 29/09/2026 est la `0014` ; la `0015` est appliquée sur la démo. `app/core/db.py` impose pour cela
une convention de nommage des contraintes.

### 4.4 Tables ajoutées en octobre 2026

| Table | Rôle | Migration |
| --- | --- | --- |
| `commentaire` | Commentaire d'un compte sur une ligne de bon ; jamais modifié ni supprimé ; `document_id` en cascade, `ligne_id` en `SET NULL` | 0012 |
| `grille_import` | Trace d'un import Excel de grille (fichier, empreinte, date d'effet, comptes de lignes, auteur) | 0013 |
| `grille_prix` | Historique des prix d'un fournisseur : une ligne par changement (prix catalogue HT, remise, prix net, unité, date d'effet, source saisie, import ou validation) ; UPDATE, DELETE et TRUNCATE refusés par des déclencheurs ; index du prix en vigueur | 0013 |
| `appel_ia` | Journal technique de chaque appel à l'IA (usage, statut, durée, erreur), jamais le texte ; écrit dans une session à part | 0014 |
| `synthese_commentaires` | Synthèse d'une semaine (`semaine_debut` unique, statut `ok` ou `vide`) | 0014 |
| `synthese_action` | Action à cocher d'une synthèse (faite par qui, quand) | 0014 |
| `explication_alerte` | Explication d'une alerte de prix, identifiée par l'empreinte du détail | 0014 |
| `prix_internet` | Une ligne par recherche de prix public ; colonne JSONB `offres` (jusqu'à cinq offres avec prix, HT ou TTC, unité, conditionnement, source), les colonnes d'origine portant l'offre la moins chère en HT | 0014, 0015 |

Sources : `app/modules/ingest/models.py:1-622`, `app/core/db.py:1-49`,
`app/core/fuseau.py:1-9`, `migrations/versions/0001_schema_initial.py` à
`0015_prix_internet_offres.py`, `tests/test_migrations.py:48-66`.

---

## 5. Flux

### 5.1 Dépôt d'un BL par Telegram

```mermaid
sequenceDiagram
  autonumber
  actor agent as Agent terrain
  participant tg as Telegram
  participant wh as ingest/router.py
  participant dep as ingest/depot_telegram.py
  participant fs as Dossier des documents
  participant bdd as PostgreSQL
  participant ocr as Mistral OCR
  participant ext as ingest/extraction_bl.py
  participant rap as ingest/rapprochement.py

  agent->>tg: Photo du BL dans le groupe BL chantiers
  tg->>wh: POST /tg/webhook avec l'en-tête secret
  alt Secret absent ou faux
    wh-->>tg: 403
  else Update vide, autre groupe ou update déjà vu
    wh-->>tg: 200 sans autre écriture
  else Clic sur Quantités vérifiées ou Écart constaté
    wh-->>tg: 200, traiter_clic en tâche de fond
    dep->>bdd: UPDATE conditionnel de confirme_le et confirme_par, journal, commit
    dep->>tg: Accusé du clic, message édité sans les boutons
  else Expéditeur hors liste blanche
    wh-->>tg: 200, signalement au groupe de supervision
  else Photo d'un utilisateur actif rattaché (liste blanche)
    wh-->>tg: 200 immédiat, traiter_fichier en BackgroundTasks
    dep->>tg: Téléchargement du fichier
    dep->>fs: Écriture atomique, fichier tmp puis os.replace
    dep->>bdd: INSERT document type bl, source telegram, statut recu
    dep->>ocr: POST /v1/ocr, annotation JSON, scores par mot, délai 90 s
    alt Échec de l'OCR ou réponse sans pages
      dep->>bdd: Statut a_verifier, motif ocr_echec, journal extraction_bl
    else Réponse exploitable
      ocr-->>dep: Texte, confiances, annotation bon_de_livraison
      dep->>ext: enregistrer_extraction_bl
      alt Annotation illisible
        ext->>bdd: Statut a_verifier, motif annotation_illisible, numéro détecté s'il existe, journal, commit
      else Annotation lisible
        ext->>ext: analyser_bl, verifier_bl, resoudre_fournisseur, puis chantier et articles
        ext->>bdd: En-tête, lignes, extraction, motifs, statut, journal extraction_bl, commit
      end
      opt Numéro de BL trouvé
        ext->>rap: rapprocher_factures_du_bl
      end
      Note over dep,ext: Exception pendant l'extraction : même traitement qu'un échec OCR
    end
    dep->>tg: Ligne de supervision puis Reçu, document n° N, avec deux boutons
  end
```

Le webhook répond toujours vite : le téléchargement, l'OCR et l'extraction
tournent en tâche de fond, dans leur propre session. La liste blanche
accepte tout utilisateur actif qui porte ce `telegram_user_id`, quel que
soit son rôle, admin compris. Le document est
enregistré au statut `recu` avant l'OCR, donc un échec OCR ne perd jamais
le dépôt. `extract` et `normalize` travaillent sans base ni réseau. Un
fournisseur n'est jamais créé à partir de l'OCR. Un libellé de chantier
inconnu crée un alias en attente, et un code article inconnu un article non
validé. « Écart constaté » passe en plus le document en `a_verifier`. Si
le téléchargement, l'écriture ou l'insertion échoue, le fichier est nettoyé,
la supervision est prévenue et l'agent reçoit « Échec de l'enregistrement,
renvoyez la photo. ».

Sources : `app/modules/ingest/router.py:150-215`,
`app/modules/ingest/depot_telegram.py:133-706`,
`app/modules/ingest/extraction_bl.py:164-576`,
`app/modules/extract/bl.py:185-597`,
`app/modules/extract/verification.py:38-326`,
`app/modules/normalize/fournisseur.py:81-129`,
`app/modules/ingest/referentiels.py:130-267`,
`app/modules/messaging/telegram.py:101-107`.

### 5.2 Dépôt d'une facture PDF

```mermaid
sequenceDiagram
  autonumber
  actor admin as Admin
  participant web as Front, page Documents
  participant api as api/factures.py
  participant fac as ingest/factures.py
  participant ocr as Mistral OCR
  participant uni as extract/unikalo.py
  participant fs as Dossier des documents
  participant bdd as PostgreSQL
  participant rap as ingest/rapprochement.py

  admin->>web: Choisit le PDF de la facture
  web->>api: POST /api/factures, multipart, cookie de session
  Note over api: admin_requis, 20 Mo au plus sinon 413
  api->>fac: deposer_facture
  fac->>fac: Vérifie la signature PDF, sinon 422
  fac->>ocr: POST /v1/ocr, délai 90 s, confiance par page
  ocr-->>fac: Pages, tableaux en markdown
  fac->>uni: analyser_facture_unikalo
  uni-->>fac: Facture, blocs et lignes, sinon 422 format non reconnu
  fac->>bdd: Fournisseur Unikalo, créé s'il manque
  fac->>bdd: Recherche d'un doublon fournisseur et numéro
  alt Doublon
    api-->>web: 409 avec original_id
  else Nouvelle facture
    fac->>fac: verifier_facture, somme des blocs contre total HT
    fac->>fs: Écriture atomique du PDF
    fac->>bdd: Document facture, blocs, lignes, alias, articles, journal facture_deposee, commit
    fac->>rap: rapprocher_facture_sans_echec
    rap-->>fac: Un échec est journalisé et avalé
    api-->>web: 201 id, numero, nb_blocs
  end
```

La facture est toujours lue par l'OCR Mistral, puis par le parseur
Unikalo, jamais par pdfplumber : le document disponible est un scan. Il n'y
a pas encore de parseur Point.P, faute de document. Son statut vaut
`a_verifier` si `verifier_facture` trouve un motif, `recu` sinon. Une erreur
OCR donne 502 et une erreur disque un 500 neutre. Le rapprochement suit
immédiatement le commit, et son échec n'annule jamais le dépôt.

Sources : `app/modules/api/factures.py:89-171`,
`app/modules/ingest/factures.py:59-514`,
`app/modules/extract/unikalo.py:552-597`,
`app/modules/extract/verification.py:328-352`,
`web/src/api/factures.ts:52-56`.

### 5.3 Rapprochement, règles et problèmes

```mermaid
sequenceDiagram
  autonumber
  participant dec as Déclencheur
  participant rap as ingest/rapprochement.py
  participant bdd as PostgreSQL
  participant norm as normalize, pur
  participant eng as rules/engine.py, pur
  participant ano as ingest/anomalies.py

  Note over dec: Facture déposée, BL extrait avec numéro, BL validé, ou CLI rapprocher
  dec->>rap: rapprocher_facture
  rap->>bdd: Charge la facture, ses blocs et ses lignes
  alt Facture absente ou pas au statut recu
    rap-->>dec: FactureIntrouvable, ou rien d'écrit
  else Facture recu
    rap->>bdd: Charge en une fois les BL et enlèvements candidats : même fournisseur, numéros normalisés, non archivés
    loop Chaque bloc de la facture
      rap->>rap: Associe le BL du bloc, statut du bloc recu, pas_de_bon ou non_recu
      rap->>norm: convertir_en_unite_fact puis apparier_lignes
      norm-->>rap: Paires de lignes et lignes BL non appariées
    end
    rap->>bdd: Historique de prix sur 6 mois, lignes négatives sans origine, paramètres
    rap->>eng: evaluer_facture avec REGLES_FACTURE moins regles_desactivees
    eng-->>rap: Anomalies pures, règle, gravité, detail chiffré
    rap->>rap: Complète document_id et bloc_id
    rap->>bdd: Réécrit rapprochement_ligne et ligne.qte_fact
    rap->>ano: synchroniser_anomalies, portée facture et règles actives
    ano->>bdd: Met à jour les ouvertes, insère les nouvelles, lève les disparues
    rap->>bdd: Journal facture_rapprochee, un seul commit
  end
```

Le rapprochement est idempotent : on peut le rejouer à chaque nouvel
événement. `synchroniser_anomalies` fait un upsert sur la clé d'identité.
Une anomalie `ouverte` est mise à jour ; une `traitee` ou `ignoree` n'est
jamais touchée. Une nouvelle est insérée, sauf si une anomalie de même
règle, même article et même fournisseur a été ignorée depuis moins de
`duree_ignorance_j` jours (90 par défaut). Une ouverte qui n'est plus
produite est supprimée avec un journal `anomalie_levee`. La portée des
règles est obligatoire : une règle qui n'a pas été recalculée n'est jamais
balayée. Les règles de suivi (R06, R14, R15, R16) passent par le même
mécanisme via la CLI `controles-differes`, sans portée de document.

Sources : `app/modules/ingest/rapprochement.py:1-16`,
`app/modules/ingest/rapprochement.py:376-405`,
`app/modules/ingest/rapprochement.py:569-1113`,
`app/modules/ingest/anomalies.py:17-59`,
`app/modules/ingest/anomalies.py:267-472`,
`app/modules/ingest/suivi.py:366-400`, `app/cli.py:446-532`.

### 5.4 Traitement d'un problème par l'admin

```mermaid
sequenceDiagram
  autonumber
  actor admin as Admin
  participant web as Front, écran À régler
  participant api as api/anomalies.py
  participant svc as ingest/anomalies.py
  participant bdd as PostgreSQL

  admin->>web: Choisit Traité ou Ignoré et écrit un commentaire
  web->>api: POST /api/anomalies/ID/traitement avec statut et commentaire
  Note over api: Contrôle d'origine, puis admin_requis
  alt Commentaire vide, blanc ou de plus de 500 caractères, ou statut invalide
    api-->>web: 422
  else Corps valide
    api->>svc: traiter_anomalie
    svc->>bdd: Lit l'anomalie par son id
    alt Absente, ou sa règle est dans regles_desactivees()
      api-->>web: 404
    else Anomalie déjà traitée ou ignorée
      api-->>web: 409 transition interdite
    else Anomalie ouverte
      svc->>bdd: statut, commentaire, traitee_par, traitee_le
      svc->>bdd: Journal anomalie_traitee ou anomalie_ignoree, avant et après, commit
      svc-->>api: AnomalieLue
      api-->>web: 200
      web->>web: invaliderApresChangementAnomalies
    end
  end
```

Le commentaire est obligatoire, de 1 à 500 caractères, et le schéma
Pydantic de la requête refuse un commentaire blanc ou un statut autre que
`traitee` ou `ignoree` (422). Le service ne passe pas par
`condition_regles_actives` : il lit l'anomalie avec `session.get`, puis
teste sa règle contre `regles_desactivees()`. L'effet est le même. Le
traitement est
définitif : aucune transition ne part de `traitee` ni de `ignoree`. Après
l'écriture, le front invalide les caches TanStack Query des anomalies, de
« À régler » et de son compteur, du tableau de bord, du bilan, des factures
et des documents. Aucun chiffre n'est recalculé côté navigateur.

Sources : `app/modules/api/anomalies.py:152-175`,
`app/modules/api/schemas.py:393-407`,
`app/modules/ingest/anomalies.py:752-822`,
`app/core/origine.py:1-33`, `web/src/pages/ProblemeDetail.tsx:219-225`,
`web/src/api/invalidations.ts:9-38`.

---

## 6. Cycles de vie

### 6.1 Document

```mermaid
stateDiagram-v2
  [*] --> recu : BL Telegram avant l'OCR, ou facture sans motif
  [*] --> a_verifier : facture avec motif
  recu --> a_verifier : motif détecté
  a_verifier --> recu : validation admin, BL seulement
  recu --> archive : archivage commenté
  a_verifier --> archive : archivage commenté
  archive --> [*]
  note left of recu
    Reste recu si l'extraction
    ne trouve aucun motif.
  end note
  note right of a_verifier
    Motif : extraction avec motif, échec OCR,
    Écart constaté, correction qui crée un motif.
    Correction ou relance d'extraction (BL) :
    reste a_verifier. La validation relance
    le rapprochement.
  end note
```

`document.statut` ne prend que trois valeurs : `recu`, `a_verifier` et
`archive`. Correction, validation et relance d'extraction ne concernent que
les BL et enlèvements. Seul un document `a_verifier` peut être validé ou
relancé. Une facture `a_verifier` n'est jamais rapprochée et n'en sort que
par l'archivage : aucun chemin du code ne la repasse en `recu`. Un document
archivé ne peut plus être modifié ni confirmé depuis Telegram. Il n'est
plus candidat au rapprochement. Archiver une facture lève toutes ses
anomalies ouvertes de règles de facture, y compris celles des règles
désactivées (balayage à vide, voir §6.2). Le bouton « Quantités vérifiées » pose
`confirme_le` sans changer le statut.

Sources : `app/modules/ingest/depot_telegram.py:419-426`,
`app/modules/ingest/depot_telegram.py:591-613`,
`app/modules/ingest/extraction_bl.py:445-466`,
`app/modules/ingest/factures.py:368`,
`app/modules/ingest/corrections.py:560-655`,
`app/modules/ingest/corrections.py:977-1117`.

### 6.2 Problème (anomalie)

```mermaid
stateDiagram-v2
  state produite <<choice>>
  state "Masquée des lectures" as masquee
  [*] --> produite : règle déclenchée par le moteur
  produite --> [*] : même règle, article et fournisseur ignorés il y a moins de 90 j
  produite --> ouverte : insertion
  ouverte --> ouverte : rejouée, gravité et detail mis à jour
  ouverte --> [*] : plus produite dans la portée, supprimée, journal anomalie_levee
  ouverte --> traitee : admin, commentaire obligatoire
  ouverte --> ignoree : admin, commentaire obligatoire
  ouverte --> masquee : règle désactivée par .env
  masquee --> ouverte : règle réactivée
  traitee --> [*]
  ignoree --> [*]
  note right of masquee
    Pas un statut en base : la ligne reste ouverte.
    Invisible dans les listes, comptes, bilan et tableau de bord.
    Le traitement renvoie 404.
    Supprimée si sa facture est archivée.
  end note
```

`anomalie.statut` vaut `ouverte`, `traitee` ou `ignoree` (contrainte
`CHECK`). Le masquage n'est pas un statut : `condition_regles_actives`
exclut des lectures toute règle désactivée par `CONTROLE_PRIX_ACTIF`
(R07, R08, R09) ou `CONTROLE_LIVRE_NON_FACTURE_ACTIF` (R06). Cela vaut aussi
pour les anomalies traitées ou ignorées de ces règles. Une règle désactivée
n'est ni évaluée ni balayée ; ses anomalies restent donc en base, telles
quelles, jusqu'à sa réactivation (modifier `.env` puis recréer le conteneur
API). Seule exception : l'archivage d'une facture lève toutes ses anomalies
ouvertes de règles de facture, y compris celles des règles désactivées. Son
balayage à vide porte sur tout `REGLES_FACTURE`, donc sur R07, R08 et R09
même désactivées : ces anomalies masquées sont supprimées, avec un journal
`anomalie_levee` (`corrections.py:1063-1068`). Le journal, lui, ne filtre
pas.

Sources : `app/modules/ingest/models.py:450-541`,
`app/modules/ingest/anomalies.py:17-132`,
`app/modules/ingest/anomalies.py:184-190`,
`app/modules/ingest/anomalies.py:432-452`,
`app/modules/ingest/anomalies.py:516-526`,
`app/modules/ingest/corrections.py:1063-1068`,
`app/modules/ingest/commun.py:60-109`, `app/core/config.py:37-56`.

---

## 7. Front

### 7.1 Navigation, routes et gardes

```mermaid
flowchart TB
  connexion["/connexion - seule route publique"]
  protegee["RouteProtegee - GET /api/moi, cache 5 min"]
  gabarit["Gabarit - barre latérale sur ordinateur, barre basse sur téléphone"]

  connexion -->|"POST /api/auth/login"| protegee
  protegee --> gabarit

  subgraph garde_admin["GardeAdmin - rôle admin, sinon renvoi vers /documents"]
    vue["/ - Vue d'ensemble"]
    aregler["/a-regler et /a-regler/:id - liste et détail d'un problème"]
    chantiers["/chantiers et /chantiers/:chantierId"]
    fournisseurs["/fournisseurs et /fournisseurs/:fournisseurId"]
    livraisons["/livraisons - bons conformes et autres états"]
    prix["/prix - prix à vérifier, et /fournisseurs/:id/prix - grille d'un fournisseur"]
    comptes["/comptes - gestion des comptes"]
    reglages["/reglages - seuils administrables"]
    journal["/journal - lecture du journal"]
    labo["/ia - Laboratoire IA"]
  end

  subgraph ouvert["Admin et agent"]
    documents["/documents - vue restreinte pour l'agent, dépôt de facture pour l'admin"]
    page_bl["/documents/:id et /bl/:id - PageBl, ou FactureDetail sur 404"]
  end

  gabarit --> vue
  gabarit --> aregler
  gabarit --> chantiers
  gabarit --> fournisseurs
  gabarit --> prix
  gabarit -.-> livraisons
  gabarit -->|"seule entrée de l'agent"| documents
  gabarit -.->|"liens discrets admin"| reglages
  gabarit -.-> journal
  gabarit -.-> comptes
  reglages -.-> labo
  documents --> page_bl
  anciennes["Anciennes URL : anomalies, a-traiter, bilan, factures, bl, chantiers/referentiel, chantiers/:c/:f"] -.->|"RedirectionAncienneUrl"| gabarit
```

L'admin a cinq entrées d'origine : Vue d'ensemble, À régler (avec la pastille
du nombre de problèmes), Chantiers, Fournisseurs et Documents, auxquelles
s'ajoute Prix depuis le 28/09 (la barre basse du téléphone compte alors six
entrées). Comptes, Journal et Réglages sont des liens discrets ; le
Laboratoire IA (`/ia`) s'ouvre depuis Réglages (« Essayer l'IA »), et
`/livraisons` depuis les montants « Conforme ». La page BL porte les
commentaires par ligne (phase 3). L'agent ne voit que Documents. Les gardes
ne décident que de la navigation : le rôle vient de `GET /api/moi`, et c'est
l'API qui contrôle les droits (`admin_requis`). Sur un grand écran,
`/a-regler/:id` affiche le détail dans un panneau à droite ; en dessous,
en page pleine. Toute URL inconnue renvoie vers `/`.

Sources : `web/src/App.tsx:21-219`, `web/src/routes/GardeAdmin.tsx:7-32`,
`web/src/routes/RouteProtegee.tsx:6-35`,
`web/src/routes/RedirectionAncienneUrl.tsx:4-22`,
`web/src/components/Gabarit.tsx:60-427`, `web/src/pages/PageBl.tsx:431-521`.

### 7.2 Flux de données

```mermaid
flowchart TB
  page["Pages - VueEnsemble, ARegler, FicheChantier, Documents..."]
  rq["TanStack Query - un seul QueryClient"]
  modules["web/src/api - un module par domaine"]
  client["appelerApi - client.ts, fetch typé par schema.d.ts"]
  fastapi["FastAPI /api - même origine, cookie bl_session httpOnly"]
  ingest_svc["ingest - services et agrégats"]
  ecoute["EcouteAuthentification - vers /connexion, cache vidé"]
  inval["invaliderApresChangementAnomalies"]
  schema["web/openapi.json puis src/api/schema.d.ts"]

  page -->|"useQuery et useMutation"| rq
  rq --> modules
  modules --> client
  client -->|"credentials same-origin"| fastapi
  fastapi --> ingest_svc
  client -->|"401"| ecoute
  page -->|"après une écriture"| inval
  inval --> rq
  fastapi -.->|"npm run api:schema puis api:types"| schema
  schema -.-> client
```

Le front ne contient aucune règle métier : les montants, états de chantier
et catégories arrivent calculés par l'API. Il est servi par la même origine
que l'API : pas de CORS, pas de JWT, rien dans localStorage. Les types TS
sont générés depuis le schéma OpenAPI par openapi-typescript, et les deux
fichiers générés sont versionnés. En production, `core/front.py` sert
`/assets` et renvoie `index.html` pour toute route GET du front, avec
`Cache-Control: no-cache`.
Les préfixes réservés (`/api`, `/tg`, `/health`...) restent en 404 JSON.
Pile : React 18, react-router 7, TanStack Query 5, Vite, TypeScript strict,
Tailwind (charte « Registre » dans `theme.extend`) et polices
auto-hébergées, compatibles avec la CSP.

Sources : `web/src/main.tsx:1-52`, `web/src/api/client.ts:1-132`,
`web/src/components/EcouteAuthentification.tsx:7-32`,
`web/src/api/invalidations.ts:9-38`, `web/package.json:9-32`,
`app/core/front.py:1-87`, `app/core/auth.py:95-100`,
`web/tailwind.config.cjs:1-39`.

---

## 8. Règles de contrôle

### 8.1 Ordre d'évaluation d'une facture

```mermaid
flowchart TB
  debut["evaluer_facture - facture au statut recu"] --> r10{"R10 : total de la facture incohérent ?"}
  r10 -->|"oui, jamais emprunté aujourd'hui"| seule["R10 est la seule anomalie renvoyée"]
  r10 -->|"non"| bloc["Pour chaque bloc"]
  bloc --> r11["R11 sur le BL rapproché, s'il y en a un"]
  r11 --> regles_bloc["R01 ou R02, puis R12 - toujours"]
  regles_bloc --> garde{"R11 muette et BL du bloc au statut recu ?"}
  garde -->|"oui"| quantite["Par ligne : R03 ou R04, puis R05, puis R17"]
  garde -->|"non"| prix
  quantite --> prix["Par ligne : R07 ou R08, puis R09 - si actives"]
  prix -->|"bloc suivant"| bloc
  prix -->|"après le dernier bloc"| r13["R13 une fois par facture"]
  r13 --> filtre["_filtrees retire toute règle inactive"]
  seule --> filtre
```

Chaque règle est une fonction pure, dans son propre fichier
(`rules/rules/Rxx.py`). Elle reçoit des dataclasses et renvoie
`Anomalie | None`, avec un `detail` chiffré jamais vide. `rules` ne lit
jamais la configuration : `ingest.commun.regles_desactivees()` décide
seule, et le moteur reçoit l'ensemble des règles actives. Exclusivités :
R01 ou R02, R03 ou R04, et R07 jusqu'au seuil fort inclus, R08 au-delà.

La branche « oui » de R10 n'est jamais empruntée aujourd'hui. R10 lit
l'écart dans le seul motif `somme_incoherente` de `document.motifs`. Or ce
motif, posé au dépôt, met la facture en `a_verifier`, et `rapprocher_facture`
n'évalue rien tant qu'elle n'est pas `recu`. Aucun chemin ne repasse une
facture en `recu` : `valider_document` ne traite que les BL et enlèvements.
Une facture `recu` n'a donc aucun motif, et R10 renvoie toujours `None`
(voir `docs/dette.md`, « une facture à vérifier ne se corrige pas depuis
l'application »). **Audit du 29/09/2026** (constat B-09) : décision d'Ilane, R10
doit être réellement produite et apparaître dans « À régler », la facture
restant comptée dans « Facturé » avec la mention « dont X euros sur des
factures à vérifier » ; correction à faire (`README.md` §20).

**Autres points d'entrée (octobre 2026).** `REGLES_CHANTIER` (`evaluer_chantier` :
R18, au rattachement d'un chantier) et `REGLES_PRIX_BL` (R19 à R25, évaluées
après la lecture d'un bon et après la correction de ses lignes par
`ingest/prix_bl.py`, chacune derrière son interrupteur de réglage et
l'interrupteur général `prix_controle_bl_actif`).

### 8.2 Catalogue

| Règle | Intitulé | Famille à l'écran | Gravité | État au 29/09/2026 |
| --- | --- | --- | --- | --- |
| R01 | BL facturé non reçu | bl | haute | active, à chaque rapprochement |
| R02 | BL facturé « pas de bon » | bl | haute | active |
| R03 | Quantité facturée > quantité BL | quantites | haute | active |
| R04 | Quantité facturée < quantité BL | quantites | moyenne | active |
| R05 | Ligne facturée absente du BL | quantites | haute | active |
| R06 | Ligne BL non facturée après 45 j | quantites | basse | désactivée par `CONTROLE_LIVRE_NON_FACTURE_ACTIF` ; dépend de `controles-differes` |
| R07 | Prix hors historique, écart de plus de 5 % et jusqu'à 15 % | prix | moyenne | désactivée par `CONTROLE_PRIX_ACTIF` |
| R08 | Prix hors historique fort, plus de 15 % | prix | haute | désactivée par `CONTROLE_PRIX_ACTIF` |
| R09 | Remise absente | prix | moyenne | désactivée par `CONTROLE_PRIX_ACTIF` |
| R10 | Incohérence arithmétique de la facture | autre | haute | active dans le code, inatteignable en pratique : une facture incohérente reste à vérifier et n'est jamais rapprochée ; correction décidée le 29/09, à faire |
| R11 | Incohérence arithmétique du BL | autre | moyenne | active |
| R12 | Doublon de facturation | autre | haute | active |
| R13 | Avoir sans origine | autre | moyenne | active |
| R14 | Chantier non résolu après 48 h | rattacher | moyenne | dépend de `controles-differes` (minuterie `controles` posée le 27/09) |
| R15 | BL sans confirmation après 24 h | autre | basse | dépend de `controles-differes` |
| R16 | Chantier silencieux depuis 7 j | autre | basse | dépend de `controles-differes` |
| R17 | Conditionnement inhabituel | autre | moyenne | active |
| R18 | Chantier à confirmer (nom lu et légende en désaccord) | rattacher | moyenne | active, `evaluer_chantier` |
| R19 | Plus cher que la grille | prix | haute | active si le contrôle des prix des bons est allumé (éteint en production) |
| R20 | Plus cher que la dernière fois (dernier prix facturé) | prix | haute | idem |
| R21 | Moins cher que la grille | prix | basse | idem |
| R22 | Produit absent de la grille (porte `dernier_prix`) | prix | basse | idem ; déclenche la recherche de prix internet si l'IA est allumée |
| R23 | Produit reconnu seulement par son nom | prix | basse | idem |
| R24 | Unités différentes, prix non comparable | prix | moyenne | idem |
| R25 | Grille ancienne | prix | basse | idem |

Quatre points d'entrée : `REGLES_FACTURE` (`evaluer_facture`, lancé à chaque
rapprochement), `REGLES_SUIVI` (`evaluer_suivi` : R06, R14, R15, R16, lancé
seulement par `python -m app.cli controles-differes`, appelé chaque nuit par la
minuterie `controles` depuis le 27/09), `REGLES_CHANTIER` (R18) et
`REGLES_PRIX_BL` (R19 à R25) (§8.1). La famille vient de `CATEGORIES_REGLE`, seule table
règle vers catégorie. Elle fonde l'état d'un chantier au tableau de bord et
le montant « en écart » du bilan. Les seuils et interrupteurs sont les réglages de
`ingest/parametres.py` (9 au 24/09, 22 au 29/09 avec le seuil de
ressemblance des chantiers, la durée d'ignorance et les réglages du contrôle des
prix) ; ceux d'une règle désactivée sont masqués. Les
délais de suivi sont comparés en « strictement supérieur ».

Sources : `app/modules/rules/engine.py:1-38`,
`app/modules/rules/engine.py:139-370`, `app/modules/rules/modeles.py:24-237`,
`app/modules/rules/rules/R01.py` à `R17.py` (docstrings),
`app/modules/ingest/anomalies.py:134-181`,
`app/modules/ingest/commun.py:19-109`,
`app/modules/ingest/parametres.py:58-171`,
`app/modules/ingest/rapprochement.py:280-297` et `:591`,
`app/modules/ingest/factures.py:368`,
`app/modules/ingest/corrections.py:560-570` et `:977-989`.

---

## 9. Renvois

- `infra/README.md` : documentation technique d'ensemble (projet, CDC
  résumé, architecture, infrastructure, services externes, sécurité,
  exploitation). Quatre passages sont périmés. Deux disent encore que
  `refonte-front` diverge de `main`, alors que les deux pointent sur
  `ee28162` : la ligne 315 (« Mécanisme fusionné dans `refonte-front`, pas
  dans `main` ») et l'avertissement des lignes 1122-1125. Deux parlent de
  deux dumps manuels (lignes 828 et 1224), alors qu'il y en a six.
- `docs/cahier-des-charges.md` : ce qui fait foi.
- `docs/passation-lot-5.md`, puis les passations précédentes : état,
  décisions, questions ouvertes.
- `docs/lot-1-recette.md` à `docs/lot-5-recette.md` et
  `docs/refonte-front-recette.md` : recettes.
- `docs/dette.md` (dette assumée, désactivations R06 à R09, audit du
  29/09/2026) et `docs/evolutions-proposees.md`.
- `README.md` : documentation globale à jour au 29/09/2026 (périmètre livré,
  état des demandes du client, IA, audit, limites) ;
  `docs/roadmap-octobre-2026.md` (demandes du 26/09, phases 1 à 4, suivi) ;
  `docs/phase-4-ia.md` et `docs/superpowers/specs/2026-09-27-phase-4-ia-design.md`
  (IA), `docs/superpowers/specs/2026-09-27-prix-design.md` (lot Prix),
  `docs/superpowers/specs/2026-09-29-prix-internet-plusieurs-sources-design.md`
  (prix internet à plusieurs sources), `docs/deploiement-octobre-2026.md`.
- `docs/deploiement-et-tests.md`, `docs/exploitation-lot-4.md` et
  `docs/exploitation-lot-5.md` : instances, commandes, crontab prévue.
- `docs/protocole-mesure-ocr.md` : mesure OCR à la réception des photos.
- `deploy/` : `docker-compose.yml` et ses surcouches `vps` et `dev`,
  `nginx/habitat.conf`, `backup.sh`, `restore.sh`, `test-restauration.sh`
  et `RESTAURATION.md`.
- `tests/test_frontieres.py` : la garde des frontières du §3.
