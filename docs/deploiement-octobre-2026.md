# Déploiement d'octobre 2026 — phases 1 à 4

Préparé le 28/09/2026 (session A) pour être relu par Ilane **avant** toute
action. Rien de ce document n'a été exécuté. Il complète
`docs/deploiement-et-tests.md` (procédure générale, §10 mise à jour, §11
retour arrière) avec ce qui est propre à ce déploiement. La livraison des corrections
d'audit a sa propre page courte : `docs/deploiement-corrections-audit.md`.

---

## 1. Ce qu'on déploie

| | Aujourd'hui en ligne (démo et production) | Après ce déploiement |
| --- | --- | --- |
| Code | `e95f7c4` (optimisations du 25/09 + tuile « Montant des bons reçus ») | `main` = `dev` au moment du feu vert |
| Schéma | migration `0010` | `0014` (ou la dernière de `dev`) |
| Contenu nouveau | — | Phase 1 (mise en production du 1er octobre), phase 2 (tâches planifiées, alerte), phase 3 (commentaires, lot Prix), phase 4 (IA, **éteinte**), T10 |

Migrations appliquées d'un coup par `alembic upgrade head` :

| Révision | Objet | Effet sur les données existantes |
| --- | --- | --- |
| `0011` | légende du bon, chantier « à compléter », fusion de chantiers | ajout de colonnes, rien de réécrit |
| `0012` | commentaires sur les lignes | nouvelle table |
| `0013` | grilles de prix, historique inaltérable (déclencheur PostgreSQL), `anomalie.ligne_id` en `ON DELETE CASCADE` | nouvelles tables, contrainte modifiée |
| `0014` | tables de l'IA | nouvelles tables |

Nouvelles dépendances Python dans l'image : `openpyxl`, `defusedxml` (lot
Prix). Aucune modification de nginx. Aucune nouvelle variable
d'environnement **obligatoire** : les variables de l'IA sont facultatives
(IA éteinte par défaut).

**Principe** : une seule mise à jour, **démo d'abord**, recette sur la démo
(§6), puis production. L'IA est mise en service **plus tard, à part** (§5),
quand l'abonnement est branché.

---

## 2. Conditions à réunir avant de commencer (feu vert)

- [ ] Lot Prix (session B) fusionné dans `dev`, avec la chaîne de migrations
  en ligne `0012 → 0013 → 0014` (`tests/test_migrations.py` vert) et le
  dernier prix facturé dans le détail de R22.
- [ ] T10 fusionné dans `dev` (colonne « Internet » de la page Prix).
- [ ] Suite complète **rejouée sur la pointe de `dev`** après la dernière
  fusion (les fusions faites sur GitHub ne passent pas par le hook) :
  `flock /tmp/habitat_reno-tests.lock uv run pytest`, `uv run ruff check`,
  `uv run mypy`, `npm --prefix web run typecheck`, `npm --prefix web run
  build` ; aucune PR ouverte vers `dev`.
- [ ] **Accord d'Ilane** pour `dev` → `main` (§3.1).
- [ ] Décision sur les scripts non commités de `feature/exploitation-2`
  (surveillance, vérification des sauvegardes) : les garder (PR) ou les
  retirer. Tant qu'ils existent, l'arbre `/home/debian/habitat_reno` n'est
  pas propre : on déploie depuis un arbre dédié (§3.2).
- [ ] Place disque : au moins 5 Go libres (`df -h /` : 17 Go libres le
  28/09, 76 % occupés). Sinon `docker builder prune -f` avant le build.
- [ ] Mémoire : au moins 1,5 Go disponible pendant le build (`free -h`).
  Arrêter ce qui ne sert pas au projet, **jamais** `habitat_prod-*` ni
  `habitat_demo-*`.
- [ ] Dernière sauvegarde restic de chaque instance de moins de 24 h
  (`systemctl --user list-timers 'habitat-*'`, `journalctl --user -u
  habitat-prod-sauvegarde.service -n 20`).
- [ ] Fenêtre annoncée aux employés (≈ 15 min par instance). Un dépôt
  Telegram envoyé pendant l'arrêt de l'API n'est pas perdu : Telegram
  renvoie la mise à jour tant que le webhook ne répond pas 200.

---

## 3. Préparer le code

### 3.1 `dev` → `main` (avec l'accord d'Ilane)

PR sur GitHub `dev` → `main` (commit de fusion), puis étiquette :

```bash
cd /home/debian/habitat_reno
git fetch origin
git tag -a mise-en-prod-octobre-2026 origin/main -m "Déploiement d'octobre 2026 : phases 1 à 4"
git push origin mise-en-prod-octobre-2026
```

### 3.2 Arbre de déploiement dédié

Le dépôt de travail `/home/debian/habitat_reno` sert au développement (une
branche de travail, parfois des modifications non commitées). Déployer
depuis un arbre propre, figé sur l'étiquette, comme le recommande
`docs/dette.md` (phase 2) :

```bash
cd /home/debian/habitat_reno
git worktree add --detach /home/debian/habitat_reno-prod mise-en-prod-octobre-2026
cd /home/debian/habitat_reno-prod
# Les fichiers d'environnement restent où ils sont (jamais copiés ni lus) :
ln -s /home/debian/habitat_reno/.env.prod .env.prod
ln -s /home/debian/habitat_reno/.env.demo .env.demo
git status --porcelain   # doit être vide (les liens .env.* sont ignorés par git)
```

Pour les déploiements suivants : `git -C /home/debian/habitat_reno-prod
switch --detach <nouvelle étiquette>`.

---

## 4. Procédure, instance par instance (démo, puis production)

Toutes les commandes depuis `/home/debian/habitat_reno-prod`.

```bash
cd /home/debian/habitat_reno-prod
# Démo :
I=demo; P="-p habitat_demo --env-file .env.demo -f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml"; PORT=8451
# Production (plus tard) :
# I=prod; P="-p habitat_prod --env-file .env.prod -f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml"; PORT=8450
```

### 4.1 Consigner l'état de départ

```bash
date -u +%Y-%m-%dT%H:%MZ
docker compose $P exec -T api alembic current        # attendu : 0010
docker image inspect habitat_${I}-api:latest --format '{{.Id}}'
```

Noter les trois valeurs (journal d'exploitation) : elles servent au retour
arrière.

### 4.2 Sauvegarder

```bash
# 1) dump de la base (fichier protégé, hors dépôt)
(umask 077; docker compose $P exec -T postgres sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > /home/debian/sauvegardes-habitat/avant-octobre-${I}-$(date +%Y%m%d-%H%M).dump)
ls -la /home/debian/sauvegardes-habitat/avant-octobre-${I}-*.dump   # taille non nulle

# 2) instantané restic complet (base + documents)
systemctl --user start habitat-${I}-sauvegarde.service
journalctl --user -u habitat-${I}-sauvegarde.service -n 30 --no-pager   # relever l'identifiant du snapshot

# 3) garder l'image actuelle sous un nom stable (retour arrière rapide du code)
docker tag habitat_${I}-api:latest habitat_${I}-api:avant-octobre
```

Ne pas continuer si l'une des trois étapes échoue. Les photos et PDF
n'existent qu'en un exemplaire (`/home/debian/habitat-data/<instance>/docs`) :
seul l'instantané restic les protège.

### 4.3 Construire, arrêter, migrer, redémarrer

```bash
docker compose $P config -q
docker compose $P build api                               # hors fenêtre : l'ancienne API tourne encore

# Début de la fenêtre d'indisponibilité
docker compose $P stop api
docker compose $P run --rm -T api alembic upgrade head    # 0011, 0012, 0013, 0014
docker compose $P run --rm -T api alembic current         # attendu : 0014 (head)
docker compose $P up -d --wait
# Fin de la fenêtre
```

Si la migration échoue : **laisser l'API arrêtée** et passer au §7.

### 4.4 Reprises de la phase 1 (dans cet ordre)

```bash
docker compose $P exec -T api python -m app.cli rattacher-chantiers
docker compose $P exec -T api python -m app.cli ranger-photos
docker compose $P exec -T api python -m app.cli rapprocher --tout
```

`rattacher-chantiers` rattache les noms en attente et les bons sans chantier
(création « à compléter » si besoin, signalée dans « À régler ») ; il garde
le verrou des chantiers le temps de sa passe (quasi instantané aujourd'hui).
`ranger-photos` crée les liens `bl/<année>/<mois>/…` (aucune copie).
`rapprocher --tout` (ajouté le 29/09/2026, audit) rejoue le rapprochement de
toutes les factures reçues et évalue R10 (« total incohérent ») sur les
factures « à vérifier » déjà en base, qui n'en avaient jamais eu : sans cette
passe, elles restent sans alerte R10 (un total faux passait inaperçu) jusqu'à
leur prochain rejeu. Idempotent ; une ligne par facture, puis une synthèse
(« N factures traitées, 0 échec »). À lancer après le redémarrage de l'API du
§4.3 (le code corrigé doit tourner) et après `rattacher-chantiers`.

### 4.5 Vérifier

```bash
curl -fsS http://127.0.0.1:${PORT}/health             # {"statut":"ok","base":"ok"}
docker compose $P ps
docker compose $P logs --tail=100 api | grep -iE "error|exception|traceback" || echo "journaux propres"
```

Puis dans le navigateur : connexion, Vue d'ensemble, À régler, Chantiers,
Fournisseurs (fiche, filtre par mois), Documents (une page de bon), Comptes,
Journal, Réglages (section « Contrôle des prix des bons » présente,
interrupteur général **éteint**), page Prix (message « contrôle éteint »).

Production seulement, webhook Telegram (sans afficher le jeton) :

```bash
# Le jeton reste dans le conteneur : rien n'est lu ni affiché sur l'hôte.
docker compose $P exec -T api python -c "import httpx; from app.core.config import get_settings; t = get_settings().telegram_bot_token.get_secret_value(); r = httpx.get(f'https://api.telegram.org/bot{t}/getWebhookInfo', timeout=10).json()['result']; print({k: r.get(k) for k in ('url', 'pending_update_count', 'last_error_date', 'last_error_message')})"
```

Attendu : l'URL du webhook de production, `pending_update_count` à 0 (ou qui
redescend), pas d'erreur récente.

### 4.6 Tâches planifiées (depuis l'arbre de déploiement)

Réinstaller les tâches de l'instance depuis `/home/debian/habitat_reno-prod`
pour qu'elles ne dépendent plus de l'arbre de développement (le script écrit
les unités avec le chemin de l'arbre qui le lance) :

```bash
deploy/installer-taches.sh ${I}                      # sauvegarde, controles, photos
systemctl --user list-timers "habitat-${I}-*" --no-pager
systemctl --user start habitat-${I}-alerte@essai.service   # message d'essai dans le canal de supervision
```

Les tâches de l'IA (`synthese`, `ia-prix`) ne s'installent **pas** à ce
stade (§5).

### 4.7 Production seulement, juste après

1. **Changer le mot de passe admin** depuis l'écran Comptes.
2. Créer les comptes des employés (écran Comptes) avec leur identifiant
   Telegram ; les ajouter au groupe Telegram des bons.
3. Lot Prix — mise en service progressive :
   - vérifier que Cedeo et Point.P existent comme fournisseurs, sinon
     `docker compose $P exec -T api python -m app.cli fournisseur-definir --nom "Cedeo"` ;
   - importer les grilles depuis la fiche du fournisseur → « Grille de prix »
     → « Importer un fichier » (aperçu, puis confirmation). La grille Cedeo
     s'importe telle quelle ; la grille Point.P doit d'abord être recopiée
     dans le modèle (bouton « Télécharger le modèle ») ;
   - régler les seuils (Réglages → « Contrôle des prix des bons »), puis
     allumer l'interrupteur général ;
   - page Prix → « Recontrôler les bons » (ou `python -m app.cli
     controler-prix --depuis 2026-09-01`).

---

## 5. Mise en service de l'IA (à part, quand l'abonnement est prêt)

Procédure complète : `docs/phase-4-ia.md`. Résumé, **production seulement**
(la démo garde `IA_ACTIVE=false`) :

1. Dans ChatGPT : Paramètres → Contrôle des données → désactiver
   « Améliorer le modèle pour tout le monde ».
2. `cp deploy/opencode/exemple.env deploy/opencode/.env` puis Ilane y met
   `OPENCODE_SERVER_PASSWORD` (`openssl rand -hex 32`).
3. `docker compose -f deploy/opencode/docker-compose.yml up -d --build`.
4. Connexion : `docker compose -f deploy/opencode/docker-compose.yml run --rm
   opencode opencode auth login` → OpenAI → « ChatGPT Pro/Plus (headless) »
   → code à saisir sur `https://auth.openai.com/codex/device`.
5. Ilane ajoute à `.env.prod` : `IA_ACTIVE=true`, `OPENCODE_URL=http://opencode:4096`,
   `OPENCODE_MOT_DE_PASSE=<le même mot de passe>`.
6. `docker compose $P -f deploy/docker-compose.ia.yml up -d api` (la
   surcouche IA s'ajoute désormais à **toutes** les commandes `up` de la
   production).
7. Essai sur une vingtaine de produits réels :
   `docker compose $P -f deploy/docker-compose.ia.yml exec -T api python -m
   app.cli essai-prix-internet --fichier <csv>` (le fichier reste hors dépôt).
8. Si l'essai est concluant : `deploy/installer-taches.sh prod --taches
   synthese,ia-prix`.

Arrêt d'urgence : `IA_ACTIVE=false` dans `.env.prod` puis `up -d api`, ou
arrêt du conteneur OpenCode — l'application continue sans l'IA.

---

## 6. Recette (« tout check »)

À faire **sur la démo** après le §4, avant de lancer la production ; une
passe courte sur la production ensuite. Dépôts Telegram : seulement dans le
**groupe de test**, jamais dans le groupe de production (le bot de la démo a
un jeton invalide (constat du 25/09) : à remplacer d'abord, sinon tester les
dépôts sur la production avec un vrai bon, avec l'accord du client).

### 6.1 Phase 1 — mise en production du 1er octobre

- [ ] Fiche fournisseur : le filtre par mois change les chiffres et la liste.
- [ ] « Conforme » cliquable → écran Livraisons → ouverture du bon.
- [ ] Journal et fiches : noms des personnes et des fournisseurs, plus aucun identifiant.
- [ ] Dépôt d'une photo avec légende = nom d'un chantier existant → bon rattaché.
- [ ] Légende inconnue → chantier créé « à compléter », visible dans « À régler », complétable.
- [ ] Légende et nom lu sur le bon différents → alerte « Chantier à confirmer », choix du chantier.
- [ ] Fusion de deux chantiers (confirmation, bons déplacés, journal).
- [ ] Comptes : créer, modifier, changer un mot de passe, retirer puis rétablir l'accès ; impossible de se retirer soi-même ou de retirer le dernier admin.
- [ ] Photos rangées : `ls /home/debian/habitat-data/<instance>/docs/bl/2026/` (liens `<jour>_<déposant>_<chantier>_n<numéro>`).
- [ ] Seuil de ressemblance réglable dans Réglages (90 % par défaut à l'époque, 80 % depuis le 31/10/2026).
- [ ] Après `rapprocher --tout` : une facture « à vérifier » à total incohérent affiche son alerte R10 dans « À régler ».

### 6.2 Phase 3 — commentaires et prix

- [ ] Page d'un bon : ajouter un commentaire sur une ligne ; il s'affiche avec l'auteur et l'heure ; entrée « Commentaire ajouté » au journal.
- [ ] Grille d'un fournisseur : télécharger le modèle, importer un fichier (aperçu : nouveaux, modifiés, erreurs ligne par ligne), confirmer ; saisir un prix ; retirer un produit.
- [ ] Réglages : groupe « Contrôle des prix des bons », interrupteurs et seuils.
- [ ] Interrupteur allumé : un bon au prix différent de la grille → alerte sur la page Prix (prix du bon, grille et sa date, dernier prix facturé, écart, ressemblance).
- [ ] « Valider ce prix » → la grille prend le nouveau prix, l'alerte passe réglée ; « Contester » exige un commentaire ; « Ignorer ».
- [ ] Interrupteur éteint → plus aucune alerte de prix visible (rien n'est supprimé).

### 6.3 Phase 4 — IA (éteinte)

- [ ] Vue d'ensemble : pas de carte « Commentaires de la semaine ».
- [ ] Détail d'une alerte de prix : pas d'encart « Avis de l'IA ».
- [ ] `docker compose $P exec -T api python -m app.cli ia-prix` → « IA éteinte : rien à faire ».
- [ ] Après la mise en service (§5, production) : première synthèse le lundi suivant (ou `synthese-commentaires --semaine <lundi>`), avis de l'IA sur une alerte de prix, colonne « Internet » de la page Prix.

### 6.4 Exploitation

- [ ] `systemctl --user list-timers 'habitat-*'` : sauvegarde, controles, photos pour chaque instance.
- [ ] Message d'essai reçu dans le canal de supervision (§4.6).
- [ ] Le lendemain matin : sauvegarde de la nuit réussie (`journalctl`).

### 6.5 Non-régression

- [ ] Dépôt d'une facture PDF Unikalo (sur la démo) : lecture, blocs, rapprochement.
- [ ] « À régler » : traiter et ignorer un problème (commentaire obligatoire).
- [ ] Bilan : exports CSV (par chantier, détaillé).
- [ ] Téléphone : navigation basse, page d'un bon, cases à cocher.

---

## 7. Retour arrière

Le schéma `0014` n'est **pas** déclaré compatible avec l'ancien code
(`docs/deploiement-et-tests.md` §11.2) : en cas de problème, on restaure
**ensemble** code et base, jamais un `alembic downgrade`.

### 7.1 La migration échoue (API arrêtée)

```bash
docker compose $P stop api
# Restaurer le dump pris au §4.2 (base vide puis restauration) :
docker compose $P exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose $P exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' \
  < /home/debian/sauvegardes-habitat/avant-octobre-${I}-<date>.dump
docker tag habitat_${I}-api:avant-octobre habitat_${I}-api:latest
docker compose $P up -d --no-build api
docker compose $P exec -T api alembic current    # attendu : 0010
```

### 7.2 Un problème grave apparaît après coup

Tout dépôt reçu depuis le déploiement sera perdu par la restauration :
prévenir d'abord. Restauration complète base **et** documents depuis
l'instantané restic relevé au §4.2, selon `deploy/RESTAURATION.md` et
`docs/deploiement-et-tests.md` §11.3, avec l'ancien code
(`git -C /home/debian/habitat_reno-prod switch --detach e95f7c4`, puis image
`avant-octobre`). Commandes exactes de l'instance (`$I`, `$P` du §4), sans
`sudo` :

```bash
# I=demo (ou prod) et P comme au §4 ; depuis l'arbre de déploiement
docker compose $P stop api    # optionnel : restore.sh l'arrête lui-même
HABITAT_RENO_ENV_FILE=/home/debian/habitat_reno/.env.$I \
COMPOSE_PROJECT_NAME=habitat_$I \
COMPOSE_OVERRIDE_FILE=deploy/docker-compose.vps.yml \
  ./deploy/restore.sh <identifiant-snapshot> --confirmer
```

Le script contrôle tout avant de détruire, écrit une copie de sécurité de la
base courante dans `~/sauvegardes-habitat/` (à garder jusqu'à validation),
puis rend les documents à l'uid 10001. Il ne remplace pas l'image : la
remettre avant (`docker tag habitat_${I}-api:avant-octobre
habitat_${I}-api:latest`, `docker compose $P create --no-build api` si
besoin).

Un problème **mineur** (un écran, un libellé) se corrige plutôt par un
correctif sur `dev` puis un nouveau déploiement.

---

## 8. Après le déploiement

- Consigner : date, étiquette, révision, instantanés restic, dans le journal
  d'exploitation (`memory.md` §0).
- **Alias de chantier suspects** (audit B-05, 29/09/2026) : lancer, en lecture
  seule, `docker compose $P exec -T api python -m app.cli chantiers-alias-suspects`.
  Elle liste les noms appris par ressemblance dont les nombres diffèrent de
  ceux du chantier (« … 13 » appris sur « … 12 ») : libellé, chantier, date,
  nombre de documents concernés. Elle ne modifie rien : ces alias continuent
  de rattacher d'office tant qu'ils existent ; Ilane relit la liste et décide
  (fusion ou correction depuis l'application).
- Roadmap §10 : cocher les déploiements ; `docs/dette.md` : ce qui a été
  constaté.
- Supprimer les images `avant-octobre` et les dumps `avant-octobre-*` une
  semaine après, si tout va bien.
- Restent ensuite (phase 2) : sauvegardes hors serveur (OVH Object Storage),
  rotation des clés Mistral, Telegram et Google (`docs/phase-2-exploitation-recette.md` §2).

---

## 9. Déroulé et durées indicatives

| Étape | Qui | Durée |
| --- | --- | --- |
| Feu vert (§2), `dev` → `main`, étiquette, arbre de déploiement (§3) | Ilane + Claude | 20 min |
| Démo : sauvegarde, build, migration, reprises, vérifications, tâches (§4) | Claude | 20 min |
| Recette sur la démo (§6) | Ilane | 30 à 45 min |
| Production : même procédure (§4) + §4.7 | Claude, puis Ilane (mot de passe, comptes, grilles) | 30 min |
| IA (§5) | Ilane (abonnement, secrets) + Claude | 30 min, quand l'abonnement est prêt |
