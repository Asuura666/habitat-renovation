# L'IA (synthèse des commentaires, avis sur les alertes prix)

Guide opérationnel pour Ilane (phase 4, T8, 28/09/2026). Il couvre
l'installation du conteneur OpenCode, son rattachement à une instance, la
connexion de l'abonnement ChatGPT, l'essai avant de se fier au prix
internet, la surveillance et l'arrêt d'urgence. La conception complète (ce
que fait le code, comment, pourquoi) reste dans
`docs/superpowers/specs/2026-09-27-phase-4-ia-design.md` — ce guide n'en est
que le mode d'emploi.

Le socle applicatif (client OpenCode, schémas, tâches, écrans) est déjà
construit et testé **sans abonnement** : l'IA reste éteinte
(`IA_ACTIVE=false`) tant que ce guide n'a pas été suivi jusqu'au bout sur une
instance. Rien de ce qui suit n'est urgent ni automatique : chaque étape est
un geste volontaire d'Ilane.

## 1. Ce que fait l'IA — et ce qu'elle ne fait jamais

L'IA n'est jamais le moteur métier : elle explique, résume et cherche une
information à titre indicatif. **Python décide seul** qu'une anomalie
existe ; l'IA ne crée, ne ferme ni ne modifie jamais une anomalie, un prix
de grille ou un document.

Trois usages :

| Usage | Ce qu'elle fait | Ce qu'elle ne fait pas |
| --- | --- | --- |
| **Synthèse hebdomadaire des commentaires** | Résume en français les commentaires de la semaine laissés sur les lignes de bons, propose des actions à cocher | Ne décide jamais si une anomalie est justifiée ni si un fournisseur doit être relancé |
| **Explication d'une alerte prix** | Explique en une à trois phrases l'écart déjà calculé par les règles | Ne dit jamais si le prix est bon, mauvais, normal ou anormal ; n'invente aucun chiffre absent des données |
| **Prix trouvé sur internet** | Cherche le prix public d'un produit absent de la grille, avec sa source et sa date | Jamais utilisé par une règle ni comparé automatiquement à un prix interne ; toujours affiché comme indicatif ; jamais de prix inventé (`prix_non_verifiable` sinon) |

L'IA utilisée est **OpenCode**, connecté à l'abonnement ChatGPT Plus/Pro
personnel d'Ilane (décision du 27/09/2026, contre la recommandation d'une
API payante à l'usage). La recherche web passe par le service public
gratuit d'Exa. Aucun des deux ne reçoit jamais : un mot de passe, une donnée
de connexion, le nom d'un chantier ou d'un client, le contenu d'un document,
ni un prix de grille.

## 2. Prérequis

- Un abonnement **ChatGPT Plus ou Pro** actif au nom d'Ilane (usage
  personnel, décision D2 — voir les risques au §9).
- **Avant** de connecter l'abonnement (§3.1) : dans ChatGPT, `Paramètres` →
  `Contrôle des données` → désactiver **« Améliorer le modèle pour tout le
  monde »**. Sans ce réglage, le contenu envoyé par l'application (textes de
  commentaires, désignations de produits) pourrait servir à l'entraînement
  d'OpenAI.
- Le dépôt à jour sur le serveur, migration `0014` disponible
  (`alembic upgrade head` l'applique).

## 3. Installer le conteneur OpenCode

Un seul conteneur OpenCode sert la production **et** la démo (mémoire du
VPS) ; il vit dans son propre projet Compose (`habitat_ia`), indépendant des
instances applicatives.

```bash
cd /home/debian/habitat_reno   # ou l'arbre de travail à jour
cp deploy/opencode/exemple.env deploy/opencode/.env
chmod 600 deploy/opencode/.env
```

Remplir `deploy/opencode/.env` :

- `OPENCODE_SERVER_PASSWORD` : générer une valeur avec
  `openssl rand -hex 32` — **noter ce mot de passe**, il sera recopié à
  l'identique dans `OPENCODE_MOT_DE_PASSE` de chaque `.env.<instance>` (§4.1).
- `EXA_API_KEY` : laisser vide (la recherche web fonctionne déjà via le
  service public d'Exa, `OPENCODE_ENABLE_EXA=1`, câblé dans le compose).

Construire et démarrer :

```bash
docker compose -f deploy/opencode/docker-compose.yml up -d --build
docker compose -f deploy/opencode/docker-compose.yml ps
docker compose -f deploy/opencode/docker-compose.yml logs --tail=50 opencode
```

Aucun port n'est publié : ce conteneur n'est joignable que depuis le réseau
Docker interne `habitat_ia`, jamais depuis l'extérieur ni depuis un
navigateur.

### 3.1 Connecter l'abonnement (une seule fois)

Connexion « headless » (sans interface graphique sur le serveur) :

```bash
docker compose -f deploy/opencode/docker-compose.yml run --rm opencode \
  opencode auth login
```

Choisir `OpenAI`, puis `ChatGPT Pro/Plus (headless)`. La commande affiche un
code à saisir sur `https://auth.openai.com/codex/device`, ouvert sur
**n'importe quel appareil** (téléphone, ordinateur personnel) déjà connecté
au compte ChatGPT d'Ilane. Le jeton obtenu est écrit dans le volume nommé
`opencode-donnees` (fichier `auth.json`), jamais dans l'image ni dans le
dépôt.

Vérifier la connexion sans jamais afficher le jeton lui-même :

```bash
docker compose -f deploy/opencode/docker-compose.yml exec opencode \
  opencode auth list
```

La sortie doit montrer un fournisseur `openai` connecté. Ne jamais lire,
copier ou coller le contenu du fichier `auth.json` (secret, même règle que
tout autre jeton du projet) : `auth login`/`auth list` suffisent pour tout
l'usage courant.

**Puis redémarrer OpenCode** (constaté le 29/09/2026) : la connexion est
écrite par un conteneur à part (`run --rm`), et le serveur déjà lancé ne la
relit pas — tant qu'il n'est pas redémarré, il ne connaît que ses modèles
gratuits et chaque essai échoue (« Model not found: openai/… », réponse
500) :

```bash
docker compose -f deploy/opencode/docker-compose.yml restart opencode
```

La page « Essayer l'IA » (Réglages) montre ensuite le voyant « Abonnement
ChatGPT connecté » au vert. Les trois agents utilisent `openai/gpt-5.6-sol`
(`deploy/opencode/opencode.json`, choix d'Ilane du 29/09/2026) ; changer de
modèle = modifier ce fichier, puis reconstruire le conteneur (`up -d
--build`).

## 4. Allumer l'IA sur une instance

À faire séparément pour `prod` et pour `demo` (le choix d'allumer l'une sans
l'autre reste possible : la démo peut rester `IA_ACTIVE=false`).

### 4.1 Variables de l'instance

Dans `.env.<instance>` (`.env.prod` ou `.env.demo`, **Ilane les écrit
lui-même** — jamais lus ni modifiés par Claude, voir les contraintes
globales de cette phase) :

```bash
IA_ACTIVE=true
OPENCODE_URL=http://opencode:4096
OPENCODE_MOT_DE_PASSE=<le même mot de passe que deploy/opencode/.env>
IA_APPELS_MAX_JOUR=40
```

`IA_APPELS_MAX_JOUR` (défaut 40 si absent) plafonne, toutes tâches
confondues, le nombre de requêtes envoyées à l'IA par jour (heure de Paris)
— à ajuster seulement si l'abonnement le permet et si le besoin réel le
justifie.

### 4.2 Appliquer la migration et redémarrer l'API

```bash
P="-p habitat_prod --env-file .env.prod"      # puis -p habitat_demo --env-file .env.demo
C="-f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml -f deploy/docker-compose.ia.yml"

docker compose $P $C run --rm -T api alembic upgrade head
docker compose $P $C up -d api
docker compose $P $C exec -T api alembic current   # doit afficher 0014 (ou plus récent)
```

`deploy/docker-compose.ia.yml` est la surcouche qui rattache `api` au
réseau `habitat_ia` et lui passe les quatre variables du §4.1 (sans elle,
`IA_ACTIVE` resterait absente donc fausse — rien ne changerait). Elle
s'ajoute aux commandes habituelles de l'instance (`docs/deploiement-et-tests
.md` §1.1), elle ne les remplace pas.

Vérifier que l'API démarre sans refuser (`docker compose $P $C logs --tail=50
api`) : `app/core/config.py` refuse de démarrer si `IA_ACTIVE=true` sans
`OPENCODE_URL`/`OPENCODE_MOT_DE_PASSE` — un message clair nomme alors la
variable manquante.

### 4.3 Installer les deux tâches planifiées

```bash
deploy/installer-taches.sh prod --taches synthese,ia-prix    # puis demo
```

Additif : cette commande n'installe (et ne réactive) que `synthese` et
`ia-prix` — elle ne touche pas aux tâches déjà en place
(`sauvegarde`/`controles`/`photos`). Horaires (heure de Paris) :

| Tâche | Commande | Production | Démo |
| --- | --- | --- | --- |
| `synthese` | `python -m app.cli synthese-commentaires` | chaque jour à 07:00 | chaque jour à 07:20 |
| `ia-prix` | `python -m app.cli ia-prix` | chaque heure de 07:10 à 20:10 | chaque heure de 07:40 à 20:40 |

Comme les autres tâches de la phase 2, une alerte part sur le canal
Telegram de supervision de l'instance en cas d'échec
(`OnFailure=…-alerte@%n`). Tant que `IA_ACTIVE` est faux, ces deux commandes
se terminent tout de suite en affichant « IA éteinte : rien à faire »
(code 0) : les installer par avance sur une instance encore éteinte ne
déclenche jamais d'alerte inutile.

`--desinstaller` retire les cinq tâches (y compris `synthese`/`ia-prix`
si elles étaient posées) :

```bash
deploy/installer-taches.sh prod --desinstaller
```

## 5. Essai avant de se fier au prix internet (document d'Ilane §16)

Avant de considérer les prix trouvés sur internet comme fiables au
quotidien, essayer la recherche sur une vingtaine de produits **réels** :

1. Préparer un fichier CSV `;` en UTF-8, une ligne par produit :

   ```csv
   fournisseur;designation;code;unite
   Unikalo;Peinture façade blanche;PF-15L;seau de 15 L
   ```

   Colonnes : `fournisseur;designation;code;unite` (`designation` seule est
   obligatoire) ; ligne d'en-tête facultative ; un fichier Excel avec BOM
   est accepté tel quel. **Ce fichier ne va jamais dans le dépôt** (données
   réelles d'un fournisseur) : le garder dans un dossier personnel, comme
   les fixtures de test.

2. Le copier dans le conteneur `api` de l'instance concernée (le conteneur
   OpenCode n'étant joignable que depuis le réseau `habitat_ia`, l'essai
   doit tourner depuis un conteneur qui y est rattaché) :

   ```bash
   P="-p habitat_prod --env-file .env.prod"
   C="-f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml -f deploy/docker-compose.ia.yml"

   docker compose $P $C cp ./produits.csv api:/tmp/produits-essai.csv
   docker compose $P $C exec -T api \
     python -m app.cli essai-prix-internet --fichier /tmp/produits-essai.csv \
     > essai-prix-resultat.csv
   docker compose $P $C exec -T api rm -f /tmp/produits-essai.csv
   ```

3. `essai-prix-resultat.csv` contient une ligne par produit : désignation,
   statut (`trouve`/`prix_non_verifiable`/`echec`), prix, taxes (HT/TTC),
   unité, conditionnement, produit trouvé, source, confiance, raison,
   durée, puis le nombre d'offres (`nb_sources`) et le prix HT le plus bas
   et le plus haut (`prix_ht_min`, `prix_ht_max`). L'agent cherche jusqu'à
   cinq offres de sites différents pour le même produit ; les prix TTC sont
   ramenés en HT (÷ 1,20), une offre dont les taxes sont inconnues est
   listée mais ne compte ni dans le plus bas ni dans le plus haut. Rien n'est enregistré en base (ni cache ni historique) : seul
   `appel_ia` garde une trace technique (usage, durée, succès/échec), comme
   pour tout appel à l'IA.

Critères d'Ilane pour juger l'essai concluant (document §16) : aucun faux
prix présenté comme sûr, les échecs sont explicites (jamais un prix
approximatif présenté comme fiable), la majorité des produits réellement en
vente publique sont retrouvés, et chaque prix trouvé est vérifiable en
ouvrant sa source. Si l'essai n'est pas concluant, revoir la consigne de
l'agent `habitat-prix` (`deploy/opencode/opencode.json`) plutôt que de
mettre en production la recherche automatique.

`IA_ACTIVE` doit être vrai pour lancer l'essai (sinon : « IA éteinte : rien
à faire », **code 1** — ici un humain attend un résultat, contrairement à la
tâche planifiée `ia-prix` où « rien à faire » n'est pas un échec).

## 6. Surveiller

- **Journal technique** : table `appel_ia` (une ligne par requête tentée,
  succès ou échec, avec sa durée et le code d'erreur éventuel) — aucune
  route ne l'expose encore ; un coup d'œil en base suffit en cas de doute
  (`SELECT usage, statut, erreur, duree_ms, created_at FROM appel_ia ORDER
  BY created_at DESC LIMIT 20;`).
- **Plafond quotidien** (`IA_APPELS_MAX_JOUR`, défaut 40, heure de Paris,
  toutes tâches confondues) : une fois atteint, tout nouvel appel renvoie
  aussitôt « IA éteinte » côté technique (`IAIndisponible("plafond")`),
  sans requête envoyée à l'IA ; `ia-prix` l'affiche alors comme
  « — plafond du jour atteint ».
- **Messages « IA éteinte »** : les trois commandes (`synthese-commentaires`,
  `ia-prix`, `essai-prix-internet`) et les deux écrans (carte des
  commentaires, encart « Avis de l'IA ») le disent clairement dès que
  `IA_ACTIVE` est faux ou que l'abonnement est déconnecté — jamais une
  erreur technique brute affichée à un agent.
- **Alertes Telegram des timers** : comme les trois autres tâches
  planifiées, `synthese` et `ia-prix` alertent le canal de supervision de
  l'instance en cas d'échec du service systemd lui-même. `ia-prix` ne
  renvoie un code d'échec (et donc une alerte) que si **toutes** les
  tentatives de la passe ont échoué faute d'IA joignable (réseau, délai,
  abonnement déconnecté) — un plafond atteint sans tentative, ou un mélange
  de succès et d'échecs, reste silencieux (rien d'urgent).
- **Logs du conteneur OpenCode** (`docker compose -f
  deploy/opencode/docker-compose.yml logs -f opencode`) : à consulter si les
  deux tâches échouent systématiquement (abonnement déconnecté, conteneur
  arrêté) — jamais de mot de passe ni de texte envoyé/reçu dans ces logs
  côté application (`app/modules/ingest/opencode.py`), mais ne pas partager
  les logs d'OpenCode lui-même sans les avoir relus.

## 7. Éteindre en urgence

Deux niveaux, du plus léger au plus complet. `$P`/`$C` (mêmes variables
qu'au §4.2, à redéfinir ici si cette section est suivie seule) :

```bash
P="-p habitat_prod --env-file .env.prod"      # puis -p habitat_demo --env-file .env.demo
C="-f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml -f deploy/docker-compose.ia.yml"
```

1. **Couper une instance sans toucher au conteneur** (le plus rapide, ne
   coupe pas l'autre instance) :
   ```bash
   # Dans .env.<instance> : IA_ACTIVE=false
   docker compose $P $C up -d api
   ```
   Aucune nouvelle requête ne part ; les tâches planifiées, si elles sont
   installées, continuent de tourner mais se terminent tout de suite
   (« IA éteinte : rien à faire », pas d'alerte).

2. **Arrêter le conteneur OpenCode** (coupe l'IA pour les deux instances à
   la fois) :
   ```bash
   docker compose -f deploy/opencode/docker-compose.yml stop
   ```
   Les appels en cours échouent proprement (délai ou réseau, journalisés
   dans `appel_ia`, jamais bloquants pour le reste de l'application) ; les
   écrans affichent alors une IA indisponible plutôt qu'une erreur.

Retirer les tâches planifiées si l'arrêt est définitif :
`deploy/installer-taches.sh <instance> --desinstaller` (retire les cinq,
pas seulement les deux liées à l'IA — réinstaller ensuite les trois
premières si l'arrêt ne visait que l'IA).

## 8. Ce qui part chez qui (RGPD, avenant au CDC — à confirmer par Ilane)

| Sous-traitant | Reçoit | Localisation |
| --- | --- | --- |
| OpenAI (abonnement ChatGPT d'Ilane) | Texte des commentaires **sans nom d'auteur ni chantier** ; fournisseur, désignations, codes et unités des produits ; chiffres des alertes prix | États-Unis |
| Exa (recherche web publique d'OpenCode) | Requêtes de recherche (désignations de produits) | États-Unis |

Jamais envoyés : mot de passe, jeton, nom de chantier ou de client, contenu
d'un document, prix de grille interne. Détail complet et registre à tenir à
jour : `docs/superpowers/specs/2026-09-27-phase-4-ia-design.md` §9.

## 9. Limites connues

- **Trois pièges d'OpenCode 1.18.32, constatés le 29/09/2026 sur le vrai
  serveur** (les deux premiers expliquent les premiers essais ratés du
  Laboratoire IA : synthèse en `StructuredOutputError`, recherche de prix
  qui tournait jusqu'au délai) :
  1. la réponse au format JSON passe par un outil interne,
     `StructuredOutput` ; la permission `"*": "deny"` des agents le retirait
     aussi. Chaque agent l'autorise désormais explicitement
     (`deploy/opencode/opencode.json`, vérifié par
     `tests/test_opencode_config.py`) ;
  2. chaque étape de l'agent prix (une recherche, une page ouverte, la
     réponse) est un message à part, et `POST /session/{id}/message` ne
     renvoie que le dernier. Les pages lues aux étapes précédentes étaient
     donc invisibles, et le contrôle « la page source a vraiment été
     ouverte » aurait rejeté tout prix trouvé. Elles se relisent maintenant
     une étape à la fois (`ingest/opencode.py`,
     `_parties_de_toutes_les_etapes`) ;
  3. OpenCode ne sait pas renvoyer la demande de départ (400 « Expected
     OutputFormatJsonSchema ») dès qu'elle porte un format JSON : la liste
     complète des messages échoue, d'où cette relecture une étape à la fois,
     qui s'arrête sur ce refus. **À revoir à chaque mise à jour d'OpenCode**
     (image épinglée sur 1.18.32).

  Une fois ces pièges levés, l'agent prix répondait sans rien chercher. Sa
  consigne exige maintenant au moins une recherche, au plus trois
  recherches et trois pages. Essai réel du 29/09/2026 : une plaque BA13 est
  trouvée à 13,79 € TTC chez un revendeur identifié, les quatre contrôles
  sont verts. Un mastic Unikalo sans prix public ressort en « non
  vérifiable », avec sa raison.
- **Conteneur `read_only` non activé, par choix délibéré**
  (`deploy/opencode/docker-compose.yml`) : confirmé en direct (fix round 1,
  essai sur l'image construite) — OpenCode écrit un `.gitignore` dans
  `~/.config/opencode` à chaque création de session (`POST /session`).
  Racine en lecture seule (même avec un `tmpfs` sur `/tmp`, `~/.cache`,
  `~/.local/share/opencode` et `~/.local/state`) → cette écriture échoue en
  `EROFS` et la création de session échoue avec elle. Dans ce conteneur
  (sans `read_only`), le même répertoire est déjà fermé à `opencode`
  (`root:root`, 0555 — immuabilité voulue de la configuration des agents) :
  l'écriture échoue aussi, mais sans conséquence, OpenCode l'ignore et
  la session se crée quand même. Rendre la racine en lecture seule
  transformerait donc cet échec aujourd'hui sans gravité en échec bloquant :
  le conteneur reste durci par ailleurs (`no-new-privileges`, `cap_drop:
  ALL`, `pids_limit`, `mem_limit`, aucun port publié, utilisateur non root,
  réseau dédié).
- **Abonnement personnel d'Ilane** (D2, risque consigné au §9 de la spec) :
  l'usage de l'application consomme son quota ; un compte suspendu rend
  l'IA indisponible sans casser le reste de l'application
  (`IA_ACTIVE=false` reste le repli). Sur le futur serveur dédié au client,
  prévoir un abonnement ou une clé au nom du client.
- **Historique de prix jamais exercé sur des données réelles** : un seul
  mois de factures est disponible à ce jour (même limite que les contrôles
  de prix R07-R09, `docs/dette.md`).
- **Pas de route qui expose `appel_ia`** : la surveillance du plafond et des
  échecs se fait en base ou par les logs (§6), pas encore par un écran.
- **La 3ᵉ colonne « Internet » de la page Prix** n'existe pas encore à
  l'écran (T10b) ; le service serveur qui l'alimentera est fait (T10a,
  `ingest.ia_prix.prix_internet_des_anomalies`, route `GET
  /api/ia/prix-internet`). Le lot Prix est fusionné dans `dev` depuis le
  28/09/2026 (PR #5) et le détail de R22 porte bien une clé `dernier_prix`
  (avec `date_dernier_prix`, « — » sinon) : **le déclencheur de la recherche
  de prix internet est définitif** -- elle ne se déclenche que pour un
  produit absent à la fois de la grille et de toute facture, jamais pour un
  produit déjà facturé mais simplement absent de la grille -- vérifié par un
  essai de bout en bout sur une vraie anomalie R22
  (`ingest/tests/test_ia_prix_bout_en_bout.py`, T10a).
