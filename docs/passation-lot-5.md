# Passation — lot 5 (Restitution), 20 septembre 2026

Document de reprise pour la session suivante. **À lire en entier avant de
toucher au code**, avec `CLAUDE.md`, `docs/cahier-des-charges.md` (qui fait
foi), `docs/plan-lot-5.md`, `docs/lot-5-recette.md`,
`docs/passation-lot-4.md`, `docs/dette.md` et
`docs/exploitation-lot-5.md`.

---

## 1. État au 20/09/2026

- Dépôt `/home/debian/habitat_reno`, branche `lot-5-restitution`, créée depuis
  `main` à `c9f51a5`. Dernier commit technique : `d770654` (L5-T11). Avant
  L5-T12, la branche contient 26 commits au-dessus de `main`.
- **L5-T1 à L5-T11 sont faites, commitées et relues.** Les corrections issues
  des revues sont incluses dans la branche; l'ultime revue de L5-T11 a rendu
  `passed=true`. Correspondance exacte dans `docs/lot-5-recette.md` §1.
- **L5-T12 est achevée par le présent commit documentaire** : recette,
  passation, dette et état du projet dans `CLAUDE.md` sont mis à jour. Aucun
  code applicatif n'est modifié et rien ne doit être poussé par cette tâche.
- **La revue finale complète de `main..HEAD` a eu lieu.** Elle a
  relevé cinq constats moyens, tous corrigés dans `e599fda` : jointures
  null-safe du Bilan, colonne anomalies du tableau BL, identité Drive non
  visible, cache front limité à `moi` et filtre agence fermé. Leur relecture
  indépendante a rendu `passed=true`, sans constat bloquant. La branche a été
  fusionnée localement par avance rapide; `main` pointe sur `e599fda` avant la
  présente mise à jour documentaire.
- Aucun remote n'a été utilisé, aucun push et aucun déploiement n'ont été faits.
  Les lignes cron des lots 4 et 5 ne sont pas posées.
- Derniers contrôles réels connus après les corrections finales : `1362 passed
  in 370.36s`; Ruff vert et 215 fichiers conformes; mypy vert sur 182 fichiers;
  typecheck/build front verts (98 modules); `docker compose ... config -q`
  vert. L5-T12 ne rejoue aucun test.
- La CLI Drive sans configuration retourne bien le code 2 avec un message
  clair. Aucun test Google réel n'est possible sans le compte de service et le
  dossier cible.
- Les captures du lot 5 sont sous `var/captures/`, hors dépôt, avec uniquement
  des données inventées. Elles ne valent pas validation client.

---

## 2. Ce qui a été fait

| Tâche | Contenu principal |
| --- | --- |
| L5-T1 | `ingest/bilan.py` : agrégats chantier, quatre montants L5-D3, anomalies ouvertes; migration de données 0008 pour rattacher les anomalies de ligne à leur bloc |
| L5-T2 | Niveaux fournisseur et BL, vue inverse fournisseur → chantiers, agrégats factorisés |
| L5-T3 | Routes JSON du bilan, admin, mois/agence, décimaux en chaînes |
| L5-T4 | Exports CSV serveur par niveau, Excel français (BOM, `;`, virgule décimale) |
| L5-T5 | Écran Bilan chantier, téléphone/ordinateur, filtres dans l'URL |
| L5-T6 | Navigation chantier → fournisseur → BL → document/anomalies et vue inverse |
| L5-T7 | Vue des dépôts par personne, chantiers silencieux, agences connues |
| L5-T8 | Écran Chantiers & fournisseurs, création, agences, alias, activité |
| L5-T9 | Journal filtré/paginé, route et écran admin |
| L5-T10 | Lecture/modification des neuf seuils, validation service, journalisation, écran Réglages |
| L5-T11 | Migration 0009, client et synchronisation Drive, CLI, reprise/idempotence, notification, note d'exploitation |
| L5-T12 | Documentation de recette/passation/dette et état du projet, commit `f879114` |

Le bilan réel d'août n'est repris qu'en comptes sans donnée client : 28 blocs
(3 reçus, 4 « pas de bon », 21 non reçus), 25 anomalies (R01 ×21, R02 ×4,
R13 ×3), 136 lignes dont 113 avec `qte_fact` et 3 appariées. Ce classement
reste **non confirmé par Ilane**. Voir `docs/lot-5-recette.md` §4 pour les
réserves.

---

## 3. Architecture livrée et invariants

### 3.1 Bilan et export

- `app/modules/ingest/bilan.py` est l'unique couche qui calcule les agrégats.
  L'API sérialise et le front présente; aucune somme métier n'est recalculée
  dans les routers ou React.
- Les montants restent des `Decimal` et traversent l'API comme chaînes.
- Le mois est celui de la facture, avec repli sur `created_at` converti en
  Europe/Paris. Le chantier résolu combine bloc et document selon les règles
  existantes; les objets non résolus ne sont pas éliminés silencieusement.
- `app/modules/ingest/export.py` produit les CSV à partir des mêmes lignes que
  le JSON : pas de deuxième requête métier divergente.
- Routes front : `/bilan`, `/bilan/:chantierId`,
  `/bilan/:chantierId/:fournisseurId`; filtres mois/agence dans l'URL.

### 3.2 Référentiels, journal et paramètres

- `referentiels_vue.py` fournit les dépôts sur une fenêtre calendaire parisienne,
  les chantiers silencieux et les agences connues. Un administrateur ayant
  réellement déposé reste visible avec son rôle; tous les agents apparaissent,
  y compris à zéro.
- L'écran Chantiers réutilise `AliasCarte`; les mutations qui peuvent changer
  `document.chantier_id` invalident aussi les vues de chantiers silencieux.
- `ingest/journal.py` lit le journal append-only avec pagination et filtres. Les
  décisions automatiques ont un auteur nul, présenté comme tel.
- `ingest/parametres.py` est l'autorité sur les neuf clés, libellés, unités et
  bornes. Une clé inconnue n'est pas créable depuis l'interface. Toute
  modification est journalisée avec avant/après.

### 3.3 Google Drive

- `app/modules/jobs/drive.py` porte le protocole `ClientDrive` et
  l'implémentation Google; `drive_sync.py` orchestre la sélection, l'envoi et
  la persistance. `jobs` reste une couche d'entrée et respecte les frontières
  du monolithe.
- Migration 0009 : URL et état de synchronisation/échec sur `document`.
- Chemin distant documenté :
  `Fournisseurs/<fournisseur>/<AAAA-MM>/`; nom
  `<type>_<numero>_<chantier>.<ext>`. Les identifiants stables restent non
  visibles dans les `appProperties` Drive. Voir `docs/exploitation-lot-5.md`
  plutôt que de recopier les commandes.
- Jusqu'à 5 Mio : multipart; au-delà : upload résumable, dans la limite
  applicative de 20 Mio. Le client vérifie l'identité distante avant envoi, et la
  sélection utilise verrouillage/`SKIP LOCKED` pour une reprise idempotente.
- Après 24 h d'échec, l'alerte de supervision est réservée avant l'appel et
  envoyée **au plus une fois**. Si Telegram échoue après réservation, l'alerte
  peut être perdue : dette explicitement documentée.
- La configuration Google est optionnelle pour démarrer l'API, mais obligatoire
  et validée au lancement de `drive-sync`.

---

## 4. Décisions à conserver jusqu'à validation

Les décisions L5-D1 à L5-D12 sont reproduites avec leur coût dans
`docs/lot-5-recette.md` §2 et définies intégralement dans
`docs/plan-lot-5.md` §4. Les plus structurantes :

- agrégats dans `ingest`, sans cache ni table d'agrégat (D1-D2);
- définitions provisoires des quatre montants, qui ne forment pas une partition
  (D3), et mois porté par la facture (D4);
- CSV au niveau affiché (D5), agences issues du texte existant (D6);
- Drive comme commande cron derrière un protocole testable (D7-D8);
- neuf seuils fermés, validation côté service (D9);
- journal paginé sans recherche plein texte JSONB (D10);
- navigation par URL et présentation mobile en cartes (D11-D12).

Aucune de ces décisions n'est irréversible; plusieurs restent à valider avec
Ilane avant de considérer la restitution acceptée.

---

## 5. Questions ouvertes

### 5.1 Lot 5 — Q1 à Q6

1. **Google Drive** : fournir un compte de service autorisé et l'identifiant du
   dossier cible; effectuer alors une recette réelle sans exposer le secret.
2. **Quatre montants** : confirmer ou corriger L5-D3 en priorité. Leur définition
   conditionne tout l'écran Bilan.
3. **CSV** : confirmer qu'un export du niveau affiché et des mêmes colonnes
   suffit.
4. **Journal** : confirmer qu'il reste réservé aux administrateurs.
5. **Août** : confirmer les verdicts reçu/non reçu/pas de bon déjà calculés au
   lot 4 avant présentation comme vérité métier.
6. **Agences** : confirmer le filtre sur le texte libre existant ou demander un
   référentiel dédié.

### 5.2 Héritées des lots précédents

- 30 photos réelles, dont 10 dégradées, avec attendus; seules quatre sont
  disponibles.
- Factures Point.P et documents associés; le parseur de facture Point.P n'existe
  pas.
- Exemple et format d'un avoir complet.
- Identifiants des groupes Telegram et bot réels pour une recette Telegram.
- Déclencheur de la variante semi-remorque et validation des décisions du lot 4.
- Historique de prix réel supérieur à un mois.

---

## 6. Méthode qui a fonctionné

- Une tâche technique par commit principal, puis des commits correctifs
  explicites après revue; ne pas écraser l'historique qui permet de relier un
  constat à sa correction.
- Vérifier les invariants transverses, pas seulement le fichier de la tâche :
  le rattachement `bloc_id` découvert en L5-T1 affectait aussi le filtre
  Anomalies et l'identité persistée; une migration de données était nécessaire.
- Pour les vues agrégées, séparer lignes et anomalies avant agrégation. Un JOIN
  direct multiplie les deux cardinalités et double les montants/comptes.
- Vérifier les frontières Europe/Paris à une minute près autour de minuit; un
  test loin de la borne ne protège pas le contrat calendaire.
- Après toute mutation front qui change ou peut recalculer `chantier_id`,
  invalider à la fois les listes de documents/chantiers et la vue des chantiers
  silencieux. Tester le retour par navigation SPA sans `page.goto`, qui
  masquerait un cache périmé.
- Pour un effet externe avant commit local, combiner identité technique distante,
  recherche avant upload, verrou en base et réessai. Tester les frontières de
  taille exactes et les pannes entre étapes.
- Continuer à n'utiliser qu'un processus pytest par base et à ne jamais modifier
  l'arbre pendant un hook de commit, pièges documentés au lot 4.

---

## 7. Pièges et limites à garder visibles

- Une revue de tâche verte n'est pas une revue finale de branche. La lecture
  complète de `main..HEAD` a réellement trouvé cinq constats moyens; ils ont
  été corrigés et leur relecture indépendante a rendu `passed=true`.
- Les captures sont fictives et hors dépôt. Ne jamais les présenter comme une
  validation des données d'août ou du client.
- Le nombre total d'anomalies ne se déduit pas en additionnant les comptes par
  règle, et les quatre montants ne s'additionnent pas non plus.
- Un chantier silencieux signifie « sans dépôt de BL » : les factures ne sont
  volontairement pas comptées comme dépôts.
- Le filtre agence peut rester vide : `chantier.agence` est un texte libre non
  renseigné aujourd'hui.
- Une alerte Drive est at-most-once : le choix évite les doublons mais autorise
  une perte si l'envoi Telegram échoue après réservation.
- Ne pas poser les crons tant que l'application n'est pas déployée et les
  commandes/migrations ne sont pas présentes dans le conteneur cible.
- Ne jamais mettre le JSON du compte de service, un identifiant Drive, une
  donnée client ou une capture réelle dans Git, un log ou un ticket.

---

## 8. Point de départ du lot 6

Le périmètre du lot 6 n'est pas défini dans les documents lus pour cette
passation; **ne pas l'inventer**. Avant toute planification :

1. ne pas pousser ni déployer implicitement le lot 5;
2. obtenir ou relire la source autoritative qui définit le prochain lot, puis
   écrire son plan à partir du CDC, des questions ouvertes et de
   `docs/dette.md`.

Si les accès externes arrivent avant le prochain lot, la première action utile
est la recette Drive réelle selon `docs/exploitation-lot-5.md`, puis la
validation métier des définitions et du bilan d'août avec Ilane. Cela clôt le
lot 5; ce n'est pas un périmètre supposé du lot 6.
