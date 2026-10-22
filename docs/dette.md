# Dette technique

Ce fichier liste les simplifications assumées (solution plus simple que
l'idéal, avec ce qu'elle ne couvre pas) au fil des tâches ; il ne contient
aucune entrée tant qu'aucune simplification n'a été prise.

## Résolu au lot 3

Trois points de dette/blocage antérieurs, fermés par le lot 3 (Extraction) :

- **« Confiance réduite » (CDC §4.2) jamais renseignée sur une facture**
  (dette L2-T4, Ruling L2-R5) — **résolu par L3-D16** :
  `ingest/factures.py::deposer_facture` appelle désormais l'OCR Mistral avec
  `confidence_scores_granularity: "page"` et calcule
  `document.confiance_min` (plus petit score de page) ; `confiance_reduite`
  est exposée par l'API comme `ocr_brut IS NOT NULL`. Voir l'entrée
  d'origine ci-dessous (conservée pour l'historique).
- **Pas de nouvelle tentative après un échec d'OCR** (dette T6b) —
  **résolu par L3-D15** : `POST /api/documents/{id}/extraction`
  (« Relancer l'extraction », admin, document `a_verifier`) relit le
  fichier et rappelle l'OCR. Reste vrai : la relance est **manuelle**,
  déclenchée par l'admin depuis l'écran — aucune nouvelle tentative
  **automatique** planifiée. Voir l'entrée d'origine ci-dessous.
- **L2-R10 — contrôle d'origine bloquant les POST via `npm run dev`**
  (point ouvert du lot 2, jamais formalisé dans ce fichier) — **résolu par
  L3-D21** : `web/vite.config.mts` réécrit l'en-tête `Origin` de la requête
  proxyée vers l'origine de l'API cible ; le contrôle serveur
  (`app/core/origine.py`) reste strict et inchangé, un test « derrière un
  vrai proxy » (`ProxyHeadersMiddleware`) a été ajouté (L3-T0).

## T5 — extract (parseur de facture Unikalo sur réponse OCR)

- **R16 — lecture native pdfplumber reportée.** La seule facture Unikalo
  disponible (`facture_2026-08.pdf`) est un scan sans couche texte ;
  `pdfplumber` ne peut rien en extraire. Au lot 1, toutes les factures
  Unikalo passent donc par l'OCR Mistral (`table_format: markdown`), avec
  le coût par appel et la confiance réduite que cela implique au sens du
  CDC §4.2. `app/modules/extract/unikalo.py` (parseur Unikalo, CDC §13 : un
  parseur par fournisseur) n'analyse que la réponse OCR déjà obtenue,
  via les utilitaires génériques de `ocr.py` (aucun appel réseau, R17). Ne
  couvre pas : une facture Unikalo transmise en PDF natif (export direct de
  leur logiciel de facturation) — à écrire dès réception d'un tel PDF,
  probablement comme un module `extract/pdf.py` séparé.
- **R5 — désignations tronquées sur deux lignes.** Une ligne de texte sans
  code article ni valeur numérique est toujours classée `COMMENTAIRE`,
  jamais fusionnée dans la désignation de la ligne précédente. Ne couvre
  pas le cas où une désignation d'article est réellement coupée sur deux
  lignes source par l'imprimante Unikalo (avant l'OCR) : la suite apparaît
  alors comme un commentaire distinct plutôt que comme la fin de la
  désignation. Cas supplémentaire propre à l'OCR : quand une mention
  CHANTIER, un commentaire (RETRAIT/PAS DE BON/CDE/PRIS PAR...) et une
  ligne article chiffrée sont fusionnés par l'OCR sur une seule ligne de
  tableau, le texte de commentaire reste inclus dans la désignation de la
  ligne article plutôt que d'être isolé en `COMMENTAIRE` distinct (5
  occurrences sur la fixture d'août) — la somme des montants n'est pas
  affectée, seule la désignation de cette ligne est bruitée.
- **R5 (fusion OCR) — lignes empilées, attribution imprécise.** Quand deux
  lignes source sont fusionnées par l'OCR dans une même ligne de tableau
  (au moins une colonne numérique portant deux valeurs séparées par un
  espace, 3 occurrences sur la fixture d'août), le parseur les sépare en
  deux `LigneFacture`. Une colonne qui porte effectivement deux valeurs
  numériques distinctes (ex. les colonnes prix) est répartie une valeur par
  ligne ; en revanche, une colonne qui n'en porte qu'**une seule** dans la
  cellule fusionnée (ex. les quantités, quand seule la colonne prix est
  doublée) a cette valeur unique **dupliquée à l'identique** sur les deux
  lignes — ce n'est donc pas une répartition exacte colonne par colonne
  dans tous les cas. Le parseur attribue aussi le même
  `code_article`/`designation` aux deux lignes (celui de la ligne de
  tableau d'origine, faute de pouvoir les répartir entre les deux lignes
  source). Ne couvre pas l'attribution exacte par ligne dans ce cas rare ;
  la somme globale (exigence testée) reste exacte.
- **R7 — pas de colonne REMISE dédiée dans la sortie OCR.** L'en-tête
  « PRIX CDT » et « REMISE » sont fusionnés par l'OCR ; `remise_pct` n'est
  donc jamais lu depuis une colonne isolée. Il est déduit à 100 % quand
  toutes les valeurs numériques d'une ligne sont vides, ou lu quand un
  signe « % » apparaît explicitement dans une cellule de prix (rare). Ne
  couvre pas une remise partielle (ex. 20 %) imprimée sans qu'aucune
  cellule numérique ne porte de « % » : elle resterait `remise_pct=None`.
- **R6 — taux de TVA.** `LigneFacture.tva` est résolu via le récapitulatif
  code → taux de la facture (lisible sur la fixture réelle). Si ce
  récapitulatif est absent ou illisible dans une future facture,
  `tva=None` pour toutes les lignes plutôt qu'une `FactureIllisible` :
  aucune valeur ne sera alors devinée.
- **`chantier_brut` — extraction non garantie à 100 %.** La mention
  `CHANTIER : libellé (code)` n'est reconnue que sous cette forme exacte
  (deux-points puis code entre parenthèses). Une mention mal séparée par
  l'OCR (fusionnée avec un autre segment de texte, sans deux-points ou sans
  parenthèses — 2 cas sur 30 mentions relevés lors de l'exploration) laisse
  `chantier_brut=None` pour le bloc concerné plutôt que de faire échouer
  toute l'analyse ; le texte reste visible dans les commentaires du bloc.
  Mesuré (tour de correction 1/5, test de non-régression R19 contre
  `facture_2026-08.attendu.json`) : **28/28 blocs** conformes à la
  référence après normalisation des espaces multiples (comme les autres
  champs de bloc : `numero_bl`, `date_bl`, `montant_ht`).
- **En-tête de facture (`fournisseur_brut`, `client`) — heuristique de
  position.** `fournisseur_brut` est la première ligne du bandeau
  entièrement en majuscules, d'au moins deux mots et sans aucun chiffre
  (exclut les lignes logo d'un seul mot et la phrase administrative
  SIRET/TVA qui reprend pourtant le nom de la société). `client` est la
  première ligne du bloc adresse qui suit la mention « Page : x / y »,
  débarrassée d'un éventuel titre markdown (« # ») que l'OCR ajoute
  parfois. Les deux sont vérifiés exacts sur `facture_2026-08` (test R19),
  mais restent une heuristique de position, non une lecture d'un champ
  structuré de l'OCR : à confirmer si une deuxième facture Unikalo révèle
  une mise en page différente (bandeau sur une seule ligne, absence de
  titre markdown pour le client, etc.).

## T6 — messaging/ingest (webhook Telegram, dédoublonnage, stockage des documents)

- **Tâche de fond perdue si le process meurt après le 200.** Le webhook
  répond 200 à Telegram dès que `enregistrer_update` marque l'`update_id`
  comme vu, puis lance `traiter_fichier` en tâche de fond
  (`BackgroundTasks`). Si le process de l'API s'arrête (crash, redéploiement)
  après ce 200 mais avant la fin de `traiter_fichier`, Telegram considère
  l'update livré et ne le renverra jamais : le fichier n'est ni téléchargé
  ni enregistré, sans que rien ne le signale automatiquement (seul le log,
  s'il a eu le temps d'être écrit, en garde une trace). Ne couvre pas de
  mécanisme de reprise ; à traiter par une file de tâches durable si ce cas
  s'avère fréquent en usage réel. Résolu depuis le lot 2 (L2-T2) pour tout
  échec **transitoire** en cours de traitement (téléchargement, écriture
  disque, insertion du `document`) : `traiter_fichier` signale désormais un
  message de supervision et répond à l'agent dans le groupe BL (« Échec de
  l'enregistrement, renvoyez la photo. », Ruling R22) — seul le cas du
  process tué entre le 200 et la fin du traitement, ci-dessus, reste sans
  notification (aucun code n'a la main pour la déclencher).
- **Fichiers de plus de 20 Mo non téléchargeables.** La Bot API Telegram
  refuse de fournir le chemin de téléchargement (`getFile`) pour un fichier
  de plus de 20 Mo : `TelegramClient.telecharger` lèverait alors
  `ErreurTelegram` (comportement normal, pas un bug), mais rien
  n'avertit l'expéditeur qu'une photo/PDF trop volumineux n'a pas pu être
  récupéré autrement que par l'absence de réponse « reçu ». Ne couvre pas
  un message d'erreur explicite à l'utilisateur ni une compression côté
  bot ; à revoir si ce cas se présente en usage réel.

## T6b — extract/ingest (détection du numéro de BL sur photo, OCR Mistral minimal)

- **Pas de nouvelle tentative automatique après un échec d'OCR — résolu au
  lot 3, voir « Résolu au lot 3 » ci-dessus (L3-D15).** Entrée d'origine,
  conservée pour l'historique : si l'appel
  à l'API Mistral OCR échoue (réseau, timeout, statut HTTP), le document
  reste `recu` sans `numero` ni `ocr_brut`, et rien ne relance
  automatiquement l'OCR plus tard. Ne couvre pas un mécanisme de reprise :
  à ajouter (job planifié ou action manuelle) dès le lot où la relecture des
  documents `a_verifier`/sans numéro est traitée.
- **Longueur du numéro non contrainte dans `detecter_numero_bl`.** Les
  motifs acceptent `L\d+` (Unikalo) et `\d+` (Point.P) sans imposer une
  longueur exacte (12 et 10 chiffres respectivement, décision du
  contrôleur), pour rester robuste à une variation mineure d'un fournisseur
  à l'autre ou d'une page à l'autre. Ne couvre pas le rejet d'un numéro
  anormalement court qui matcherait accidentellement le motif (aucun cas de
  ce type observé sur les fixtures disponibles).
- **`_mime_pour_extension` sur une extension inconnue.** Le mapping
  extension -> type MIME (`ingest/service.py`) ne couvre que les extensions
  réellement produites par `Messagerie.telecharger` (images Telegram
  usuelles + PDF). Une extension hors de cette liste retombe sur
  `application/octet-stream`, envoyée à Mistral comme un `document_url` (pas
  un `image_url`) : ne couvre pas un format de fichier inattendu, qui
  échouerait alors côté Mistral (capté comme un échec d'OCR ordinaire,
  document conservé `recu` sans numéro).

## T7 — ingest (commande `bl-non-recus`)

- **Non-normalisation des numéros de BL au-delà de `strip()`/majuscules.**
  `blocs_avec_reception` compare `numero_bl` (lu dans la facture) et
  `document.numero` (détecté par l'OCR sur la photo, T6b) après
  suppression des espaces de bord et mise en majuscules des deux côtés
  (le préfixe `L` Unikalo est parfois lu en minuscule par l'OCR). Ne
  couvre pas d'autres écarts possibles entre les deux lectures : zéros de
  tête différents, espace interne, tiret ou caractère mal reconnu par l'un
  des deux OCR (facture vs photo). Un même BL pourrait donc apparaître à
  tort comme « non reçu » si les deux OCR ne rendent pas exactement la
  même chaîne. Non observé sur les fixtures disponibles (aucun numéro en
  commun entre la facture d'août et les 4 photos de test). Décision
  reportée à la vérification sur des fixtures réelles communes (numéro de
  BL identique lu à la fois sur la facture et sur une photo) ; la
  normalisation plus poussée, si nécessaire, relève du lot 3.

## L2-T1 — auth (connexion par cookie, sessions en base)

- **Pas de purge des jetons expirés de `jeton_session`.** `utilisateur_courant`
  (`app/core/auth.py`) refuse déjà toute requête portant un jeton dont
  l'activité remonte à plus de 12 h (`DUREE_SESSION_S`, lu par
  `DatabaseStrategy.read_token` via un filtre SQL sur `created_at`), mais la
  ligne correspondante de `jeton_session` n'est jamais supprimée pour
  autant : seul `POST /api/auth/logout` (`strategy.destroy_token`) retire un
  jeton de la table. Un jeton expiré (jamais revenu se reconnecter) reste
  donc en base indéfiniment. Ne couvre pas de purge périodique ; à ajouter
  (ex. tâche planifiée sous `app/modules/jobs/`, ou un cron exécutant
  `DELETE FROM jeton_session WHERE created_at < now() - interval '12 hours'`)
  si la table grossit de façon gênante en usage réel — décision reportée
  (vague finale du lot 2, point 6).

## L2-T1b — auth (commandes de gestion des utilisateurs)

- **Unicité de l'e-mail toujours sensible à la casse en base.**
  `creer_utilisateur` (`app/core/auth.py`) normalise l'e-mail (`strip()` +
  minuscules) avant d'écrire et vérifie son unicité par
  `func.lower(Utilisateur.email) == email_normalise` (tour de correction
  1/5, constat Important : sans cette normalisation, créer un compte avec
  une casse différente d'un compte existant passait la vérification
  d'unicité mais faisait ensuite échouer le login des deux comptes en 500,
  `MultipleResultsFound` — `SQLAlchemyUserDatabase.get_by_email`, utilisée
  par le login, compare elle aussi via `func.lower` des deux côtés). La
  contrainte `UNIQUE` de la colonne `email` reste cependant sensible à la
  casse **en base** (pas de migration au lot 2, décision du contrôleur) :
  elle ne protège donc pas contre une insertion qui contournerait
  `creer_utilisateur` — seule la CLI (`utilisateur-creer`) écrit des comptes
  aujourd'hui, et elle normalise systématiquement. Ne couvre pas un index
  fonctionnel `lower(email)` en base ; à ajouter par migration si un autre
  point d'écriture sur `utilisateur` apparaît (ex. une route d'inscription).
- **Import différé de `app.core.auth` dans `app/cli.py`.** `app/core/auth.py`
  appelle `get_settings()` au niveau module (comme `app.main`) : un import
  en tête de `app/cli.py` ferait donc échouer tout `python -m app.cli ...`
  (y compris `bl-non-recus`) dès qu'une variable d'environnement manque,
  avant même l'analyse des arguments — régression détectée pendant L2-T1b
  (`test_bl_non_recus_fichier_inexistant_code_2_sans_configuration` passait
  au rouge). Contourné par un import dans le corps de
  `_utilisateur_creer`/`_utilisateur_desactiver`, plutôt qu'en tête de
  fichier. Ne couvre pas la cause racine (`get_settings()` appelée à
  l'import de `app.core.auth`) ; à rendre paresseuse (ex. propriété calculée
  à la demande plutôt qu'une variable de module) si une autre commande CLI
  doit un jour importer ce module sans dépendre de la configuration
  complète.

## L2-T3 — messaging/ingest (numéro interne et boutons de confirmation)

- **Clic non autorisé signalé sans nom Telegram.** `ClicBouton`
  (`messaging/base.py`) ne porte que `expediteur_id` (pas de champ
  `expediteur_nom`, contrairement à `FichierEntrant`) : la ligne de
  supervision d'un clic refusé (`traiter_clic`, L2-D10) ne montre donc que
  l'identifiant Telegram numérique, jamais le nom d'affichage, contrairement
  au message « expéditeur non rattaché » d'un dépôt (L2-D7). Ne couvre pas
  l'identification humaine rapide d'un clic non autorisé en supervision ;
  à ajouter si besoin en étendant `ClicBouton` avec le nom Telegram déjà
  lu par `messaging.telegram._expediteur_nom` sur `callback_query.from`.
- **Accusé d'erreur générique possible malgré une écriture réussie.**
  `traiter_clic` (`ingest/service.py::_decider_clic`) enregistre la
  confirmation et le journal, puis `await session.commit()`, avant de
  construire les textes d'accusé et d'édition du message. Si une exception
  survient après ce `commit()` (formatage final, fermeture de session,
  envoi Telegram) mais avant que le routeur ne réponde, l'agent verrait un
  accusé générique d'erreur alors que `confirme_le`/`confirme_par` et le
  journal sont déjà écrits en base — situation théorique, jamais observée
  ni testée. Ne couvre pas la distinction entre un échec avant et après
  l'écriture pour le message renvoyé à l'agent ; à traiter si un agent
  rapporte un accusé d'erreur alors que la confirmation apparaît bien à
  l'écran.

## L2-T4 — ingest/api (dépôt de facture PDF Unikalo)

- **`confiance_min` jamais renseignée (Ruling L2-R5, constat important) —
  résolu au lot 3, voir « Résolu au lot 3 » ci-dessus (L3-D16).** Entrée
  d'origine, conservée pour l'historique : le CDC §4.2 prévoit qu'une
  facture lue par OCR porte une « confiance réduite » par champ. La colonne
  `document.confiance_min` existe (lot 2, L2-D5) mais `deposer_facture` ne
  la renseignait jamais : toutes les factures déposées passent par l'OCR
  (aucune lecture native disponible, cf. dette T5) et aucune n'était donc
  marquée « confiance réduite » — `confiance_min` restait `NULL` pour
  toutes. Ne couvrait pas le calcul d'un score de confiance par champ ni
  son report sur le document ; décision explicite du contrôleur au lot 2 :
  ce calcul serait défini et implémenté au lot 3 (Extraction), pas au lot
  2 — fait (L3-D16, `confidence_scores_granularity: "page"`).
- **Avoirs non distingués des factures (Ruling L2-R5, constat important).**
  Le CDC §4.2 parle d'un dépôt « de facture ou d'avoir », mais
  `deposer_facture` écrit toujours `document.type = "facture"`, quel que
  soit le contenu réel du PDF déposé : aucun exemple d'avoir Unikalo n'est
  disponible pour identifier ce qui distingue sa structure OCR de celle
  d'une facture (même gabarit avec des lignes négatives ? document
  différent ? mention explicite « AVOIR » en en-tête ?). Un avoir déposé
  aujourd'hui serait donc soit typé `facture` à tort (si son format est
  assez proche pour passer `analyser_facture_unikalo`), soit refusé en 422
  `FormatNonPrisEnCharge` (si son format diffère trop). Ne couvre pas la
  détection ni le typage d'un avoir ; à traiter dès réception d'un exemple
  réel — question posée à Ilane (`docs/plan-lot-2.md` §3, Q5).

## L2-T5 — api (factures et documents en lecture)

- **`FileResponse` sans `filename` explicite.** `GET /api/factures/{id}
  /fichier` et `GET /api/documents/{id}/fichier` renvoient le fichier sans
  fixer son nom de téléchargement : le navigateur propose un nom générique
  (dérivé de l'URL, pas du numéro de facture/BL). Cosmétique, ne couvre pas
  le classement des fichiers téléchargés par l'utilisateur ; à ajouter
  (paramètre `filename` de `FileResponse`) si signalé comme gênant en
  usage réel.

## L3-T11 — ingest (outil de mesure du taux d'erreur OCR)

Fix round 1 (isolation par document, finding 1) : `mesurer_dossier` isole
maintenant un `<nom>.attendu.json` invalide et un échec OCR (cache
invalide ou appel `ocr` en échec) par document, sans jamais interrompre la
mesure des autres photos. Restent volontairement non isolés (rares,
purement liés au système de fichiers, jamais déclenchés par le contenu
d'une photo ou d'un attendu) :

- **Erreur de listage du dossier** (`_lister_entrees` : `Path.iterdir`,
  `.is_file()`). Un dossier supprimé pendant le scan, ou des permissions
  insuffisantes sur `tests/fixtures/bl/`, ferait toujours planter toute la
  commande avec un `traceback` Python plutôt qu'un message clair. Ne
  couvre pas ce cas ; à traiter si rencontré en pratique (message clair +
  code de sortie dédié).
- **Échec de lecture d'une photo** (`entree.chemin_photo.read_bytes()`,
  juste avant l'appel `ocr`) : une photo illisible (permissions, disque
  corrompu) ferait échouer la commande entière au lieu de classer
  seulement ce document en `echecs_ocr`. Rare en pratique (les photos sont
  déposées une fois puis relues, jamais modifiées entre deux passages).
- **Échec d'écriture du cache après un appel OCR réussi**
  (`_ecrire_cache`, disque plein ou permissions insuffisantes sur
  `tests/fixtures/bl/`) : l'appel Mistral aurait déjà eu lieu (coût réel)
  mais son résultat serait perdu et la commande planterait quand même,
  perdant aussi les résultats déjà accumulés pour les autres photos du
  lot. Cas jugé assez rare (même répertoire que les photos déjà présentes,
  donc déjà accessible en écriture) pour ne pas complexifier
  `mesurer_dossier` davantage dans ce tour ; à isoler (comme `echecs_ocr`)
  si rencontré en pratique, avec une note explicite que l'appel a
  malgré tout été facturé/consommé côté Mistral.

Aucun de ces trois cas n'a de test dédié (comportement inchangé, pas une
régression de ce tour) : les isoler proprement demanderait de distinguer
« l'appel réseau a réussi mais l'écriture locale échoue » de tous les
autres échecs, ce qui n'apporte rien tant qu'il n'a jamais été rencontré.

## L3-T11 — livrable du lot (CDC §10 non mesuré)

- **Rapport de taux d'erreur OCR non mesuré sur 30 photos réelles (L3-D20,
  constat 1 du plan lot 3).** Seules 4 photos réelles sont disponibles au
  17/09/2026 (3 Unikalo, 1 bon d'enlèvement Point.P), contre 30 dont 10
  dégradées exigées par le CDC §10. L'outil de mesure (`rapport-ocr`,
  `docs/protocole-mesure-ocr.md`) est prêt et a été exécuté sur les 4
  photos disponibles (résultat en comptes/taux uniquement dans
  `docs/lot-3-recette.md` §4), mais l'échantillon est 6 à 7 fois trop petit
  pour conclure sur les seuils du CDC ni pour recaler le seuil de
  confiance provisoire (0,80, L3-D4). Ne couvre pas le livrable exigé par
  le CDC ; à faire dès réception des 30 photos (`docs/protocole-mesure-ocr.md`,
  une seule commande une fois les fichiers réunis).

## L3-D23 — extract/ingest (parseur de facture Point.P)

- **Parseur de facture Point.P non construit.** Aucun document de facture
  Point.P n'est disponible (constat 1 du plan lot 3) : seul un bon
  d'enlèvement Point.P a pu être testé, et il passe par la même extraction
  qu'un BL (annotation Mistral, L3-D1), jamais par un parseur dédié comme
  `extract/unikalo.py` pour les factures Unikalo. Ne couvre pas le dépôt
  d'une facture Point.P (aucune route ne le reconnaît, comportement non
  vérifié) ; à construire dès réception d'un exemple réel — bloque aussi
  tout rapprochement lot 4 avec ce fournisseur.

## L3-D17 — ingest/web (correction d'une facture scannée)

- **Pas d'écran de correction pour une facture « à vérifier ».** Le lot 3
  calcule les motifs d'incohérence d'une facture (somme des blocs ≠ total
  HT, L3-D16) et l'affiche dans l'écran « À traiter », mais ne permet pas
  de corriger une valeur à l'écran (contrairement à un BL, `PATCH`/`PUT`
  sur `/api/documents/{id}`) : une facture « à vérifier » renvoie
  uniquement vers son détail en lecture. Le CDC suppose des factures en
  PDF natif, jamais rencontré ce lot-ci (toutes scannées, cf. dette T5).
  Ne couvre pas la correction d'une facture scannée à l'écran ; question
  posée à Ilane (Q5 du plan lot 3) — à construire si la réponse le
  confirme nécessaire.

## L3-D11 — ingest (fusion de documents BL multi-pages)

- **Fusion de deux documents pour un même BL non construite.** Le CDC §4.1
  évoque un BL sur deux pages sans préciser à quel lot le traiter (aucune
  tâche du plan ne le cite explicitement). Provisoirement : un numéro déjà
  porté par un autre document du même fournisseur met le second document
  « à vérifier » (motif `numero_en_double`, numéro non écrit) et l'admin
  peut l'archiver manuellement, mais rien ne fusionne automatiquement les
  deux pages en un seul document logique (lignes, total). Ne couvre pas la
  fusion ; question posée à Ilane (Q6 du plan lot 3) — à construire au lot
  qu'elle désignera (candidat : lot 4, avec le rapprochement).

## L3-T8b — api (sélection des alias chantier en attente)

- **Une requête SQL par alias en attente, pas un lot unique.**
  `a_traiter.py::_lister_alias_en_attente` appelle
  `referentiels.candidats_alias` une fois par alias en attente pour compter
  ses documents/blocs correspondants, plutôt qu'une passe batchée par
  fournisseur — choix délibéré pour garder une seule définition de la
  sélection alias-matching, partagée avec `valider_alias` (jamais deux
  implémentations divergentes de la même règle). Acceptable au volume du
  CDC §9 (500 documents/mois, donc très peu d'alias en attente
  simultanément) ; ne couvre pas un très grand nombre d'alias en attente
  sans dégradation de performance — à revoir (passe batchée dédiée) si ce
  volume change.

## L3-T10 — web (état du détail document non réinitialisé entre deux documents)

- **`DocumentDetail` ne réinitialise pas son état local en changeant de
  document sans repasser par une liste.** La page étant montée une seule
  fois par le routeur pour toute la route `/documents/:id`, l'état local
  (mode édition ouvert, formulaire d'archivage déplié) reste celui du
  document précédent si l'admin navigue directement d'un document à un
  autre sans repasser par un lien de liste (« À traiter », « BL déposés »).
  Le contenu affiché reste correct (sous-formulaires remontés via une `key`
  incluant l'id), seul le mode reste celui d'avant. Ne couvre pas ce cas ;
  non corrigé faute de lien de ce type dans l'app aujourd'hui — à traiter
  si un tel lien apparaît (ex. suivant/précédent dans une liste).

## L4-T7 fix2 — normalize/rules (Ruling R16, comparaison de quantité perdue en paire mixte)

- **Comparaison de quantité perdue quand une seule des deux lignes
  appariées a une unité connue.** Le Ruling R14 (fix round 1) fait
  comparer deux quantités rendues inchangées faute d'unité connue des deux
  côtés (cas 2 de `convertir_en_unite_fact`) ; le Ruling R16 (fix round 2)
  restreint cette comparaison aux paires où les **deux** lignes sont dans
  ce cas (`LigneControlee.unite_implicite` identique des deux côtés) — une
  paire mixte (une ligne convertie « normalement », l'autre en unité
  implicite) ne produit plus ni R03 ni R04, alors qu'une des deux
  quantités pourrait être correcte. Volontairement conservateur (CDC §10 :
  « 0 anomalie R03/R04 due à une unité » prime sur la détection) ; à
  revoir quand le référentiel article (unité de facturation, ratio validé)
  sera renseigné des deux côtés pour ce fournisseur — la comparaison
  redeviendrait alors possible sans ambiguïté.

## L4-T7 tour 2 — ingest (document d'origine ajouté à l'identité d'une anomalie)

- **Anomalies enregistrées avant cette correction, sans identifiant de
  facture.** Depuis la correction qui fait porter à toute anomalie produite
  par le rapprochement l'identifiant de sa facture (`document_id`), cet
  identifiant fait partie de la clé qui identifie une anomalie de façon
  unique. Si une base contenait déjà des anomalies enregistrées sans cet
  identifiant (écrites avant cette correction), le premier rejeu du
  rapprochement après une mise à jour en créerait de nouvelles au lieu de
  mettre à jour les anciennes — un doublon temporaire, refermé tout seul au
  rejeu suivant par la suppression normale des anomalies devenues obsolètes,
  jamais une perte de donnée. Sans objet aujourd'hui : rien n'est en
  production, aucune anomalie n'a été accumulée en base avant cette
  correction. Ne couvre pas de migration de données pour ce cas ; à traiter,
  avant la première mise en service, par un rejeu complet du rapprochement
  sur toutes les factures reçues (commande `rapprocher --tout`) si des
  anomalies s'étaient entre-temps accumulées en base de production.

## Revue finale du lot 4 — une facture « à vérifier » ne se corrige pas depuis l'application

- **Constat.** Le rapprochement se déclenche au dépôt d'une facture
  (décision L4-D3). Si ce rapprochement place la facture en « à vérifier »
  — typiquement parce que sa somme est incohérente (règle R10) — personne ne
  peut la corriger ni la valider depuis l'application : les routes de
  correction, de validation, d'archivage et de relance d'extraction ne
  reconnaissent que les bons de livraison et les enlèvements (décision
  L3-T8a, dette L3-D17 déjà notée). La facture reste donc en l'état jusqu'à
  ce qu'un rejeu en ligne de commande (`rapprocher --facture <id>` ou
  `rapprocher --tout`) soit lancé après correction en base.
- **Ce qui a été écarté.** La revue finale du lot 4 a d'abord lu cette
  situation comme un défaut du rapprochement : « une facture validée n'est
  jamais rapprochée ». Vérification faite, le scénario n'existe pas — une
  facture ne peut pas atteindre la validation, et même en levant ce verrou
  elle serait refusée par le recalcul des motifs, qui exige des champs
  propres au bon de livraison. Aucun branchement n'a donc été ajouté :
  brancher un rapprochement sur un chemin inatteignable aurait produit du
  code mort, impossible à couvrir par un test honnête.
- **À traiter.** La correction d'une facture depuis l'application est un
  sujet à part entière (quels champs sont corrigeables, quelles règles se
  rejouent, quelle trace au journal). Elle se construira avec les écrans de
  restitution, pas en marge du rapprochement. L'archivage, lui, est déjà
  ouvert aux factures depuis cette même revue finale : il purge leurs
  anomalies.

## Lot 5 — Restitution

### Accès et exploitation externes

- **Synchronisation Google Drive non validée sur un Drive réel — bloquée par
  le type de compte, constat du déploiement du 23/09/2026.** Le client
  Google, les deux modes d'envoi et l'orchestration sont couverts par des
  doubles de test sans réseau, mais aucun compte de service ni dossier cible
  autorisé n'a été fourni (Q1). La CLI refuse correctement de démarrer sans
  configuration (code 2 et message clair). Ne couvre pas une recette réelle
  des permissions, de l'arborescence, des `appProperties` d'identité, des
  quotas, des sessions résumables ni de la reprise après une panne Google.
  Le 23/09/2026, la tentative de configuration réelle a montré qu'un compte
  de service ne peut pas écrire sur un Drive **personnel** (aucun quota qui
  lui soit propre côté Google) : il faut soit un dossier sur un Drive
  **partagé** Google Workspace, soit remplacer l'authentification du compte
  de service par une authentification **OAuth** utilisateur dans
  `app/modules/jobs/drive.py`. Aucune des deux options n'est en place ; ne
  pas poser le cron `drive-sync` avant d'avoir tranché avec Ilane. À faire
  dès réception des accès selon `docs/exploitation-lot-5.md`, sans jamais
  versionner le JSON du compte.
- **Notification Drive au plus une fois, donc potentiellement perdue.** Après
  24 h d'échec, la réservation de l'alerte est commitée avant l'appel Telegram
  afin d'éviter les doublons. Si l'appel Telegram échoue après cette
  réservation, l'alerte n'est pas retentée. Ce compromis at-most-once est
  explicite dans `docs/exploitation-lot-5.md`; à remplacer par une boîte
  d'envoi persistante seulement si des pertes sont observées ou si la garantie
  devient contractuelle.
- **Crons des lots 4 et 5, et sauvegardes restic, non posés sur les deux
  instances déployées le 23/09/2026.** Les lignes pour `controles-differes`
  (lot 4) et `drive-sync` (lot 5, de toute façon bloqué, voir ci-dessus) sont
  documentées, mais aucune n'est installée sur `habitat_demo` ni
  `habitat_prod` (`docs/deploiement-et-tests.md` §1.1). Aucun dépôt restic
  n'est initialisé pour ces deux instances non plus : seules des sauvegardes
  manuelles ponctuelles (`pg_dump -Fc`) ont été prises avant la migration
  `0010`, dans `~/sauvegardes-habitat/`, hors dépôt Git. À poser avec
  `flock`, rotation des logs et supervision des codes de sortie
  (`docs/deploiement-et-tests.md` §9 et §11) avant de considérer le
  déploiement complet.
- **`backup.sh` ne pouvait plus lire `DOCS_HOST_DIR` en cron non-root, depuis
  le durcissement des permissions des documents (0640/0750, tâche T3,
  `a59daa3`).** Les documents sont écrits par le conteneur `api` avec l'uid
  10001 (`Dockerfile`, `USER 10001`), sans droit de lecture pour « other » ;
  `backup.sh` monte `DOCS_HOST_DIR` en lecture seule pour restic avec
  `-u "$(id -u):$(id -g)"`, c'est-à-dire l'uid/gid de l'utilisateur **hôte**
  qui invoque le script, jamais l'uid 10001. Un cron exécuté par un compte
  hôte ordinaire (ex. `debian`) obtenait donc `permission denied` sur
  `restic backup` dès qu'il tournait. **Résolu (constat R1 de la revue
  finale du 25/09/2026, « Optimisations du 25/09/2026 » ci-dessous)** :
  `backup.sh` ajoute désormais le gid 10001 comme groupe supplémentaire du
  conteneur restic (`--group-add`), lisible quel que soit le compte hôte
  qui invoque le script — plus besoin de root ni de `setfacl`.

### Bilan — définitions et validation provisoires

- **Les quatre montants du Bilan reposent sur L5-D3, non validée par Ilane.**
  Facturé HT, rapproché, en écart et non justifié sont implémentés selon la
  définition du plan et ne forment pas une partition. Le classement d'août
  affiché par le Bilan est lui aussi hérité du lot 4 et non confirmé. Ne couvre
  pas une acceptation métier ; toute correction touche les expressions
  d'agrégat et leurs tests, sans perte de données.
- **Pas d'index, de cache ni de table d'agrégat dédiés au Bilan.** Les vues sont
  calculées à la demande, choix adapté au volume prévu pour un seul client.
  Ne pas ajouter un index Drive ou Bilan par anticipation : mesurer d'abord en
  production. Pour Drive, un index partiel sur les documents à synchroniser
  n'est à envisager que si le volume rend la sélection mesurablement lente ;
  pour le Bilan, index ou vue matérialisée seulement si une requête réelle
  dépasse l'objectif d'usage.

### L5-T7 fix1 — ingest (vue des dépôts : factures hors périmètre)

- **Les factures ne comptent pas comme des « dépôts ».** `depots_par_agent`
  et `chantiers_sans_depot` ne lisent que `document.chantier_id`, jamais
  `bloc_facture.chantier_id` : ce sont les agents de terrain qui déposent
  des bons de livraison, et le chantier d'une facture vit à la maille du
  bloc, pas du document qui la porte. Ne couvre pas un futur cas où
  `document.chantier_id` serait renseigné pour une facture ; à revoir si le
  modèle évolue en ce sens.
- **Un chantier n'est jugé silencieux que sur ses bons de livraison.**
  `chantiers_sans_depot` ignore entièrement la facturation reçue pour un
  chantier : un chantier qui continue de recevoir des factures sans
  qu'aucun agent n'y dépose de BL est signalé silencieux quand même. Ne
  couvre pas le cas où la seule facturation attesterait d'une activité
  persistante ; à revoir si un signal combiné (BL + facture) devenait
  nécessaire.

### L5-T8 fix1 — web (chantier inactif non désactivable)

- **Le statut d'un chantier s'affiche mais ne se change pas.** L'écran
  « Chantiers & fournisseurs » affiche `chantier.actif` (badge Actif/
  Inactif), mais aucune route ne permet de désactiver ou de fermer un
  chantier depuis l'application (`POST /api/chantiers` ne crée qu'avec
  `actif=true`) ; à traiter quand la gestion du cycle de vie d'un chantier
  (fermeture, réouverture) sera abordée.

### L5-T8 fix2 — web (deux points d'ergonomie, non corrigés)

- **Cibles tactiles sous 44 px.** Motif hérité de tous les écrans du
  projet (boutons, liens et cases de formulaire souvent plus petits que la
  cible tactile minimale recommandée), pas une régression de cette tâche ;
  à reprendre globalement, pas écran par écran.
- **Bandeau d'erreur global.** Les erreurs réseau/API sont aujourd'hui
  gérées section par section (chaque requête affiche ou non son propre
  message) plutôt que par un bandeau d'erreur global cohérent ; corriger
  proprement demande de repenser la gestion d'erreur par section, hors
  périmètre de cette tâche.

### Export détaillé du bilan (décision d'Ilane du 23/09/2026, Q3) — ingest/export

- **R06 n'apparaît jamais dans `codes_regles`/`nb_anomalies_ouvertes` de ce
  fichier.** Cette règle (« ligne du BL non facturée ») porte `ligne_id` sur
  la ligne de *BL* absente de la facture, jamais sur une ligne de facture ni
  `None` — `bilan_detail` (`ingest/bilan.py`) n'attribue une anomalie sans
  ligne de facture propre qu'à son bloc (`bloc_id`, cas de R01/R02) ; une
  anomalie dont `ligne_id` est renseigné mais étranger au périmètre exporté
  ne peut donc être rattachée à aucune ligne de ce fichier, testé
  explicitement
  (`test_bilan_detail_anomalie_r06_jamais_attribuee_a_une_ligne_de_facture`).
  R06 reste visible depuis l'écran Anomalies et le compte
  `nb_anomalies_ouvertes` des cinq autres niveaux du bilan (au niveau bloc/
  chantier) ; seule sa décomposition par ligne de facture manque ici, faute
  d'une ligne de facture à laquelle la rattacher sans l'inventer.
- **Les quantités (`Quantité facturée`, `Quantité BL appariée`) sont
  arrondies à deux décimales, virgule française, comme les montants**
  (`_formater_montant`, décision explicite pour réutiliser au maximum le
  format des exports existants) — alors que le front (`lib/formats.ts
  ::formaterQuantite`) en affiche jusqu'à trois pour une quantité. Aucune
  quantité observée aujourd'hui n'en porte une troisième significative,
  mais rien dans le modèle (`Ligne.qte_totale`, `Numeric` sans échelle
  fixe) ne le garantit ; à corriger (formateur de quantité dédié dans
  `ingest/export.py`, sans toucher `_formater_montant`) si une facture
  réelle porte une quantité à trois décimales.

### Client du chantier (ajout hors CDC du 23/09/2026) — ingest/api

- **Client du chantier = ajout hors CDC du 23/09/2026, texte libre sans
  référentiel.** `Chantier.client` (migration 0010) est une simple colonne
  texte optionnelle, remplie à la main sur chaque chantier (`POST`/`PUT
  /api/chantiers`) — aucune table dédiée, aucun rapprochement avec une
  quelconque source externe (pas de SIRET, pas de recherche, pas de
  déduplication). Même normalisation que `agence` (espaces de bord
  retirés, chaîne vide -> `None`). Si le nombre de clients grandit ou
  qu'un besoin de recherche/à normaliser apparaît, un référentiel dédié
  serait alors justifié — hors périmètre de cette tâche.

### Liste « Documents » (Task 8, refonte front) — web/src/pages/DocumentsListe.tsx

- **Filtres `?mois=`/`?chantier=`/`?fournisseur=` côté client, pas côté
  serveur.** `GET /api/documents` et `GET /api/factures` n'exposent aucun
  paramètre de requête pour ces filtres (contrairement à
  `/api/bilan/chantiers`, par exemple) : `DocumentsListe` filtre donc après
  coup, sur les pages déjà chargées (jusqu'à `LIMITE_DOCUMENTS_DEFAUT`/100
  documents pour `GET /api/documents`, aucune pagination ajoutée). Depuis
  le tour de correction 1, un texte s'affiche quand un filtre est actif et
  que la liste atteint cette borne (« Seuls les 100 bons de livraison les
  plus récents sont chargés ici… ») — signalement, pas une résolution : un
  document plus ancien que les 100 derniers déposés reste invisible à tout
  filtre. Négligeable au volume actuel (un seul client, quelques dizaines
  de documents par mois) ; à revoir si le volume grandit (ajouter les
  paramètres côté serveur, sur le modèle de `bilan.py`).
- **Filtre `?chantier=` corrigé au tour de correction 1** (était par
  préfixe de `chantier_brut`, texte OCR non normalisé, cf. `git log` de ce
  fichier pour l'ancienne version de cette entrée) : `chantier_id` a été
  ajouté à `DocumentReponse`/`ingest.lecture.DocumentResume` (petit ajout
  serveur, un champ déjà présent sur `Document` et déjà sélectionné par la
  requête, aucune jointure supplémentaire) — le filtre compare désormais
  cet identifiant par égalité, comme `chantiers/:id` le fait déjà côté
  fiche chantier. Limite résiduelle, assumée : `FactureResumeReponse` ne
  porte toujours aucun chantier (une facture regroupe plusieurs chantiers
  via ses livraisons) — le filtre chantier continue d'exclure toutes les
  factures, quel que soit le chantier ciblé.
- **Filtre `?fournisseur=` (spec §4, absent avant ce tour) comparé au nom
  du fournisseur, pas à son identifiant.** Ni `DocumentReponse` ni
  `FactureResumeReponse` ne porte `fournisseur_id` (seul le nom résolu,
  `fournisseur: str | None`) — `DocumentsListe` compare donc ce nom par
  égalité stricte au `nom` du fournisseur choisi dans le sélecteur (les
  deux valeurs proviennent de la même colonne `fournisseur.nom`, jamais
  d'un texte OCR non normalisé comme `chantier_brut` — aucun des travers du
  filtre chantier d'avant ce tour ne s'applique ici). À revoir si deux
  fournisseurs finissaient par porter un jour le même nom (le référentiel
  ne l'interdit pas explicitement) — hors périmètre de ce tour, aucune
  fixture démo ne présente ce cas.
- **Filtre `?mois=` corrigé au tour de correction 2** (constat de revue :
  un BL/enlèvement était toujours classé sur `cree_le`, sa date de dépôt,
  jamais sa date de livraison, contrairement à une facture déjà classée sur
  `date_doc`) : `date_doc` a été ajouté à `DocumentReponse`/
  `ingest.lecture.DocumentResume`, même colonne `Document.date_doc` qu'une
  facture (déjà sélectionnée par la requête, aucune jointure
  supplémentaire) — `extract/bl.py` la lit déjà comme « date du bon telle
  qu'imprimée ». Limite résiduelle, assumée : un BL dont l'extraction n'a
  jamais pu lire cette date (`date_doc` nul) retombe toujours sur
  `cree_le` — rare en pratique (`date_doc` est un champ obligatoire du BL,
  `CHAMPS_OBLIGATOIRES_BL`, et l'un des deux seuls champs que `verifier_bl`
  peut classer illisible plutôt qu'absent, `extract/verification.py`), pas
  observé sur les fixtures démo.
- **Tri de la liste toujours sur `creeLe` (date de dépôt), pas sur
  `date_doc` (constat de revue, tour de correction 3).** Le constat notait
  que `date_doc` classe le filtre `?mois=` mais n'apparaissait jamais à
  l'écran ; corrigé en affichant « Livré le … » dans le contexte de chaque
  bon (`contexteDocument`, carte et tableau). Le constat suggérait aussi,
  en piste secondaire (« envisager »), de trier sur `date_doc` avant
  `creeLe` : non fait — un document qui vient d'être déposé mais dont
  l'extraction n'a pas encore lu `date_doc` (donc `null`) serait alors
  systématiquement relégué en fin de liste malgré son dépôt récent,
  masquant justement les dépôts qui ont le plus besoin d'attention
  immédiate (écran « À corriger »). Le tri par date de dépôt (le plus
  récent en premier, comportement inchangé depuis avant Task 8) reste donc
  la clé principale ; à revoir si un besoin explicite de tri par date de
  livraison est exprimé (ex. un tri choisi par l'utilisateur, hors
  périmètre de ce tour).

### Task 10, fix round 1 (23/09/2026) — web (filtre auteur du Journal)

- **Le filtre auteur du Journal demande un identifiant, sans liste de
  comptes où le trouver.** Le libellé et le texte d'aide ne parlent plus
  d'« UUID » (reformulé en « Auteur » / « identifiant de la personne »,
  fix round 1 de la revue de la Task 10), mais le champ reste un texte
  libre à coller — aucune route `GET /api/utilisateurs` (ni équivalent)
  n'existe pour peupler un sélecteur de comptes. Corriger proprement
  demande cette route et un composant de sélection, hors périmètre de
  cette tâche (habillage uniquement, contenu inchangé).
  **Résolu le 28/09/2026** (recette de la démo) : le filtre « Auteur » est
  une liste des comptes par nom (`GET /api/comptes`, écran Comptes de la
  phase 1), et la colonne « Cible » d'une action sur un compte affiche son
  nom (`ingest/journal.py` résout `cible_id` quand `cible_table` vaut
  `utilisateur`) : plus aucun identifiant de compte à l'écran.

### Task 10, tour 2 (23/09/2026) — web (libellés des réglages dans le Journal)

- **`lib/journal.ts::LIBELLES_PARAMETRE` duplique les neuf libellés de
  `ingest/parametres.py::DEFINITIONS_PARAMETRES`** pour afficher le nom du
  réglage plutôt que sa clé technique dans la colonne Cible d'un « Réglage
  modifié » (constat de la revue, tour 2 de la Task 10) — la page Journal
  n'appelle pas l'API des réglages, seule source du libellé à jour. Un
  dixième réglage ajouté côté serveur sans mise à jour de cette liste
  s'affichera par sa clé technique brute (repli défensif déjà en place pour
  le reste de ce fichier, jamais une erreur). À corriger proprement en
  exposant le libellé depuis l'entrée du journal elle-même côté serveur
  (`ingest/parametres.py`) plutôt que dupliqué côté front, hors périmètre de
  cette tâche.
- **Le filtre auteur du Journal renvoyait à « la dette technique »
  (`docs/dette.md`, un document interne inaccessible au dirigeant) dans son
  texte d'aide** — jargon de développeur laissé par le fix round 1, corrigé
  au tour 2 : le texte pointe maintenant vers la colonne Cible d'une entrée
  « Compte utilisateur créé », où l'identifiant est réellement visible. La
  limite elle-même (pas de sélecteur de comptes, cf. entrée ci-dessus) est
  inchangée et reste documentée ici, ce qui suffit.

### Chantiers et fiche chantier (Task 7, refonte du front) — web

- **Pas de « Conforme » par chantier sur la fiche — corrigé à la revue
  finale de la refonte (constats ECRAN-4/COUVERTURE-12) :**
  `MontantsBilan.conforme` est désormais calculé par `ingest.bilan`, livraison
  par livraison, et la fiche affiche ses quatre chiffres. Entrée d'origine,
  gardée pour l'historique : La consigne de la
  Task 7 demandait quatre `Chiffre` sur `FicheChantier.tsx` (Facturé,
  Conforme, Écart, Sans bon), avec un repli explicite « sinon n'afficher
  que Facturé / Écart / Sans bon » si le serveur ne fournit pas
  « conforme ». Vérification faite : aucun endpoint ne fournit ce montant
  par chantier — `LigneBilanChantierReponse.montants` et
  `ChantierTableauReponse.montants` (`MontantsBilanReponse`) n'ont que
  `facture_ht`/`rapproche`/`en_ecart`/`non_justifie`/
  `nb_anomalies_ouvertes` ; seul `TableauDeBordReponse.totaux.conforme`
  existe, agrégé sur tous les chantiers du mois, inutilisable pour un seul
  chantier sans le recalculer côté front (interdit). Le repli s'applique
  donc toujours : la fiche affiche trois chiffres, jamais quatre. Pour
  aller plus loin, il faudrait exposer un `conforme` par chantier dans
  `ChantierTableau`/`MontantsBilan` côté serveur (`ingest/tableau_de_bord
  .py`/`ingest/bilan.py`).
- **Pastille d'état de la fiche chantier limitée au mois courant —
  corrigé (fix round 1, constat 3).** La fiche interrogeait silencieusement
  `/api/tableau-de-bord` pour le mois courant implicite, jamais indiqué à
  côté de `Chiffre` pouvant porter sur toute la durée du chantier (deux
  périodes différentes affichées sans libellé sur le même écran). La fiche
  lit désormais `?mois` (même représentation `AAAA-MM-01` que
  `ChantiersListe.tsx`, transmise par ses liens et par l'ancienne
  redirection `/bilan/:c?mois=…`) : la pastille ne s'affiche plus que si un
  mois est choisi, et chaque `Chiffre` précise sa période (« — tous les
  mois » ou « en septembre 2026 »).
- **Livraisons d'un fournisseur non résolu absentes de la fiche.** La
  carte « Livraisons » assemble les BL de tous les fournisseurs du
  chantier via `GET /api/bilan/chantiers/{id}/fournisseurs` puis, pour
  chacun, `GET /api/bilan/chantiers/{id}/fournisseurs/{fournisseur_id}/bl`
  — cette seconde route exige un `fournisseur_id` réel (chemin), donc les
  blocs dont le fournisseur n'a pas pu être résolu (`fournisseur_id`
  `None` dans `GET .../fournisseurs`) n'ont aucune route pour récupérer
  leurs lignes de BL et n'apparaissent pas dans la liste. Ils restent
  visibles depuis « À régler » (règle R14, chantier/fournisseur à
  rattacher) et depuis « Documents ». Un endpoint qui accepterait
  `fournisseur_id=null` (ou une route unique « toutes les livraisons du
  chantier ») lèverait cette limite.
- **« Exporter pour Excel » de la fiche chantier — complété (fix round 1,
  constat 4), dette résiduelle inchangée.** La fiche n'offrait que l'export
  fournisseurs du chantier (`GET /api/bilan/chantiers/{id}
  /fournisseurs.csv`) sous ce libellé, alors que la carte affichée est
  « Livraisons » (niveau BL) — mismatch de niveau. La carte « Livraisons »
  propose désormais, en plus de cet export fournisseurs (gardé), un export
  CSV par fournisseur résolu au niveau BL (`urlExportBilanBl`, une entrée
  « Exporter les livraisons <fournisseur> (CSV) » par fournisseur). Il n'y a
  toujours pas de CSV serveur unique « toutes les livraisons, tous
  fournisseurs confondus » correspondant exactement à l'assemblage front
  affiché — un export par fournisseur reste donc nécessaire côté client
  pour couvrir tout le chantier ; un endpoint dédié lèverait cette limite.
- **Dépôts par agent (CDC §4, 30 jours) repris dans `ChantiersListe.tsx`,
  pas dans un écran dédié.** L'ancien écran « Chantiers & fournisseurs »
  regroupait référentiels, alias, activité (dépôts par agent + chantiers
  silencieux) ; la refonte disperse ce contenu (alias → « À régler », Task
  6 ; agences d'un fournisseur → fiche fournisseur, Task 9) sans lui
  laisser de nouvel écran dédié. Faute d'un tel écran, la Task 7 a ajouté
  une carte « Dépôts récents (30 jours) » en bas de `ChantiersListe.tsx`
  pour que cette exigence du CDC reste accessible quelque part — décision
  du contrôleur/de l'implémenteur à confirmer, un autre emplacement
  (Réglages ? un écran « Activité » séparé ?) étant tout aussi défendable.
- **« Dernier bon retrouvé sur une facture » (ex-« Dernière livraison
  reçue ») recalculée sans filtre de mois — corrigé (fix round 2, constat
  1), coût réseau résiduel.** Elle portait sur `livraisons`, déjà filtrée
  par `?mois` : un chantier livré en août et en septembre, la fiche
  filtrée sur octobre, affichait un « aucun bon retrouvé » erroné.
  `FicheChantier.tsx` interroge désormais `GET .../fournisseurs` et
  `GET .../fournisseurs/{f}/bl` une seconde fois, sans `?mois`
  (`fournisseursTous`/`blTousParFournisseur`) — mêmes clés que les requêtes
  filtrées quand aucun mois n'est choisi (`@tanstack/react-query` partage
  alors le cache, pas de requête réseau en double), mais deux requêtes
  HTTP de plus par fournisseur résolu quand un mois est choisi. Sans
  incidence perceptible avec le volume de données de démo (un seul
  fournisseur résolu par chantier) ; à surveiller si un chantier accumule
  beaucoup de fournisseurs.
- **« Dernier bon retrouvé sur une facture » ne mesure toujours pas un vrai
  dépôt — corrections de revue tour 3, constat 2, limite non résolue.**
  Même après le correctif ci-dessus, cette date ne provient que des blocs
  d'une facture déjà arrivée (une fois par mois) dont la photo de BL a été
  retrouvée (`bl_document_id !== null`) — jamais des dépôts Telegram
  eux-mêmes (quotidiens). Un chantier qui a reçu des bons ce mois-ci mais
  dont la facture du mois n'est pas encore arrivée affiche donc « Aucun bon
  retrouvé sur une facture », alors que le bandeau « Chantiers sans bon
  déposé » (basé sur le vrai `dernier_depot_le`) le montrerait actif. Le
  libellé dit maintenant explicitement ce qu'il mesure (jamais « reçue »/
  « déposée » seules) et distingue « aucun bon retrouvé » de « bon
  retrouvé, date inconnue » (un bon sans `date_bl` affichait auparavant le
  même message que l'absence totale de bon) — mais l'écart entre les deux
  notions reste entier. Un vrai « dernier dépôt » par chantier individuel
  demanderait d'exposer côté serveur le même calcul que
  `ingest.referentiels_vue.chantiers_sans_depot` (qui l'a déjà, agrégé par
  chantier via `Document.created_at`), par exemple un champ
  `dernier_depot_le` sur `ChantierTableauReponse`/`LigneBilanChantierReponse`
  — hors périmètre Task 7.

### Revue finale de la refonte du front (23/09/2026) — ce qui reste volontairement de côté

Constats de `.superpowers/sdd/2026-09-23-refonte-front/constats-finaux.json`
non corrigés dans la vague de corrections finale (détail et justification
dans `correction-finale-rapport.md`, même dossier) :

- **Deux périmètres de « problèmes », chacun nommé (définition à valider par
  Ilane).** Le compte unique « à régler, en tout » (`GET /api/a-regler
  /compte`, `ingest.a_traiter.compter_problemes_a_regler`) compte chaque
  élément de la liste « À régler » : anomalies ouvertes de tous les mois,
  documents « à vérifier », chantiers à rattacher et articles à valider. La
  pastille de navigation, l'en-tête d'« À régler » et le « … en tout » de la
  vue d'ensemble l'affichent. La tuile « Problèmes à régler ce mois » garde
  la portée du bilan (anomalies des factures du mois, sans les documents,
  chantiers à rattacher ni articles, qui n'ont pas de mois de facture).
  L'écran « À régler » n'a pas de filtre par mois : ce mois-là ne s'y
  retrouve pas en un clic.
- **« Sans bon de livraison » reste un fait, pas une action.** Le montant
  (`non_justifie`, définition du lot 5 inchangée) ne baisse pas quand le
  dirigeant conteste ou ignore un « BL jamais reçu »/« Livré sans bon » :
  « À vérifier », l'état du chantier, « bons à réclamer » et le nombre de
  problèmes baissent, eux. Sur la démo d'août : 495,40 € sans bon, « aucun
  bon à réclamer », tous les chantiers conformes ou en quantités. À
  confirmer par Ilane avec les autres définitions monétaires.
- **Page d'un bon et fiche chantier ne comptent pas exactement la même
  chose.** Le « N problèmes » de la page du bon couvre tout ce qui concerne
  le bon (`condition_anomalies_du_bl` : aussi une quantité non confirmée ou
  une erreur de calcul portée par le bon lui-même, une ligne livrée jamais
  facturée) ; la colonne « Problèmes » d'une livraison sur la fiche chantier
  compte les anomalies portées par la livraison (bilan, `?blocId=`). Les
  deux ouvrent « À régler » sur exactement leurs propres problèmes, mais un
  problème porté par le bon seul n'apparaît que du premier côté.
- **Sixième état `a_voir` et titre R16 hors de la spec.** Le document de
  conception (§6.2) cite cinq états ; le serveur en a six (`a_voir`, Ruling
  de la Task 2). Le titre de R16 (§5, « … depuis 7 jours ») est devenu
  « Chantier sans bon déposé récemment », le délai étant réglable. La spec
  fait foi : les deux écarts sont à faire valider par Ilane, spec non
  modifiée.
- **« Montant en jeu » choisi par règle côté front** (`ARegler.tsx
  ::valeurEnJeu`, présentation d'une clé de `detail`) : l'écran « À régler »
  montre aussi un montant pour R10/R11/R12 et un écart de quantité pour
  R03/R04, que les priorités de l'accueil (`ingest.tableau_de_bord
  ._montant_en_jeu`, R01/R02/R05/R13) n'affichent pas. Aucun chiffre
  contradictoire, seulement des cases vides d'un côté.
- **Filtres de l'ancien écran « Anomalies » non repris** (constats
  COUVERTURE-16, LIENS-14) : règle précise, période depuis/jusqu'à,
  « traitées » séparées des « ignorées ». La spec §4 fixe la nouvelle liste
  de filtres ; l'historique d'un chantier ou d'un fournisseur reste
  consultable par « Voir l'historique » des deux fiches (`?filtre=regles`).
- **Retour depuis un problème ouvert par une fiche** (constat LIENS-11) :
  « ← Retour à la liste » et le passage au problème suivant mènent à la
  file « À régler », pas à la fiche chantier ou fournisseur d'origine.
- **Composants partagés incomplets** (constats LIENS-12, COUVERTURE-19) :
  pas de `Tableau` ni de `Barre latérale` dans `web/src/ui/` (tableaux
  propres à chaque écran, barre latérale dans `components/Gabarit.tsx`),
  `chiffresProbleme` et quelques libellés de type de document dupliqués
  entre écrans.
- **Exports CSV inchangés** (constat SERVEUR-9) : le client du chantier
  n'apparaît dans aucun export, et les en-têtes du lot 5 gardent leurs
  termes (« Rapproché », « Anomalies ouvertes », « Règles concernées » avec
  les codes de règle). Aucun chantier de la démo n'a de client renseigné.
- **« Document n° N » reste affiché** sur la page d'un bon (constat
  ECRAN-13) : c'est le numéro cité par chaque message Telegram, seul moyen
  de retrouver un dépôt depuis la conversation.
- **Contrôles de prix désactivés le 24/09/2026, décision d'Ilane** : un seul
  mois de factures ne fonde aucun « prix habituel », R07 (« Prix un peu plus
  cher »), R08 (« Prix plus cher que d'habitude ») et R09 (« Remise
  habituelle oubliée ») sont désactivées côté serveur (`CONTROLE_PRIX_ACTIF`,
  optionnelle, défaut `false` ; `ingest.commun.regles_desactivees`, seule
  source de vérité). Leurs anomalies existantes sont masquées de chaque
  écran (À régler, compte, tableau de bord, bilan, export, comparaison BL,
  fiches), **jamais fermées ni supprimées par un rapprochement rejoué**
  (`rapprocher_facture` ne les passe plus à `synchroniser_anomalies` comme
  « recalculées », elles restent donc ouvertes en base, prêtes à
  réapparaître) **ni par un passage des contrôles différés** (`R06`
  ci-dessous partage exactement ce mécanisme, aucune des deux catégories de
  règle désactivée n'est jamais considérée comme « recalculée » par le
  balayage de suppression, Ruling R8 d'`ingest/anomalies.py`) ; en revanche
  **l'archivage du document les retire, comme les autres anomalies** de sa
  portée (`corrections.archiver_document` sur une facture appelle
  `synchroniser_anomalies(anomalies=(), portee_regles=REGLES_FACTURE)`, qui
  couvre R07/R08/R09 sans condition — Ruling R25 du lot 4). Aucun
  interrupteur à l'écran ; le front adapte deux libellés (tuile « Écart prix
  ou quantité » -> « Écart de quantité », filtre « Prix » masqué dans « À
  régler »). Depuis la tâche « réglages des contrôles désactivés »
  (24/09/2026), les trois seuils concernés (`seuil_prix_pct`,
  `seuil_prix_fort_pct`, `occurrences_prix_min` — pas de seuil propre à la
  remise en plus de ce dernier) n'apparaissent plus du tout dans Réglages,
  masqués côté serveur (`ingest/parametres.py::_cle_masquee`, seul point de
  décision : `GET /api/parametres` ne les renvoie plus, `PUT
  /api/parametres/<clé>` les refuse comme une clé inconnue) — leur valeur
  n'est pas perdue pour autant, elle reste en base et réapparaît telle
  quelle dès la réactivation du drapeau ; le front ne filtre plus rien
  lui-même. Réactivation : geste d'administrateur serveur, pas un redémarrage —
  `CONTROLE_PRIX_ACTIF=true` dans le fichier d'environnement de l'instance
  (`.env.prod` ou `.env.demo`), puis recréation du conteneur API
  (`docker compose -p habitat_<instance> --env-file .env.<instance> -f
  deploy/docker-compose.yml -f deploy/docker-compose.vps.yml up -d api` ; un
  simple `restart` ne relit pas les variables d'environnement) quand
  l'historique couvre plusieurs mois. Pour recalculer aussi les anomalies
  sur les factures déjà reçues, rejeu facultatif de `rapprocher --tout`,
  sur le VPS : `docker compose -p habitat_<instance> --env-file
  .env.<instance> -f deploy/docker-compose.yml -f
  deploy/docker-compose.vps.yml exec -T api python -m app.cli rapprocher
  --tout`. Procédure détaillée : `docs/evolutions-proposees.md` §b.
- **R06 (« Livré mais pas facturé ») désactivée le 24/09/2026, seconde
  décision d'Ilane le même jour** : aucune preuve encore constatée que ce
  cas se produise. Même mécanisme que les contrôles de prix ci-dessus
  (`CONTROLE_LIVRE_NON_FACTURE_ACTIF`, optionnelle, défaut `false` ;
  `ingest.commun.regles_desactivees` combine les deux drapeaux). R06 est une
  règle de **suivi** (contrôle différé, `ingest.suivi.controles_differes`,
  déclenchée par `python -m app.cli controles-differes`, jamais par
  `rapprocher_facture`) : désactivée, elle n'est plus évaluée
  (`rules.engine.evaluer_suivi` saute son appel), ses anomalies existantes
  restent masquées de toutes les lectures (même point unique,
  `condition_regles_actives`) et ne sont pas touchées par un passage des
  contrôles différés tant que le drapeau reste désactivé
  (`controles_differes` passe `regles_actives`/`portee_regles = REGLES_SUIVI
  - regles_desactivees()`, R06 exclue des deux — un passage pendant que R06
  reste désactivée ne la considère donc ni pour la fermer ni pour la
  relever). **Contrairement aux contrôles de prix, l'archivage de la
  facture porteuse ne la retire pas sur-le-champ** : `corrections
  .archiver_document` ne balaie que `REGLES_FACTURE` pour une facture
  (Ruling R25 ci-dessus), R06 (`REGLES_SUIVI`) n'en fait pas partie — une R06
  déjà ouverte sur une facture ensuite archivée reste donc en base, masquée,
  tant que R06 reste désactivée. Elle n'y reste pas indéfiniment pour
  autant : `controles_differes` appelle `synchroniser_anomalies` sans
  `portee_document_id`, donc `_conditions_portee` (`ingest/anomalies.py`)
  balaie toutes les anomalies ouvertes des règles de la portée, pas un seul
  document (balayage global déjà observable sur R14 dans
  `test_suivi.py::test_controles_differes_leve_une_anomalie_disparue`) — au
  premier passage des contrôles différés où R06 est active, cette R06 est
  candidate comme les autres ; le filtre `facture_doc.statut != "archive"`
  d'`ingest.suivi._lignes_bl_non_facturees` l'empêche d'être reproduite,
  donc elle est levée (supprimée et journalisée `anomalie_levee`,
  `anomalies.py`) à ce passage-là. Constat de dette pré-existant, non
  introduit par cette désactivation (même lacune que si R06 était restée
  active) : le retrait n'est ni immédiat (contrairement aux prix) ni
  garanti tant que R06 reste désactivée — à corriger un jour si ce délai
  pose problème en pratique. Aucun interrupteur à l'écran ; depuis la tâche
  « réglages des contrôles désactivés » (24/09/2026), le seuil propre à R06
  (`delai_ligne_bl_non_facturee_j`) n'apparaît plus du tout dans Réglages
  tant que le drapeau reste désactivé — même mécanisme de masquage côté
  serveur que les seuils de prix ci-dessus (`ingest/parametres.py
  ::_cle_masquee`, un seul point de décision pour les deux contrôles),
  valeur conservée en base, réapparaît dès la réactivation. R02 (« Livré sans
  bon ») reste active (décision d'Ilane : la preuve est dans la facture).
  Réactivation : même geste d'administrateur serveur que les contrôles de
  prix ci-dessus — `CONTROLE_LIVRE_NON_FACTURE_ACTIF=true` dans le fichier
  d'environnement de l'instance, puis recréation du conteneur API (pas un
  `restart`, même commande que ci-dessus) si le cas est un jour constaté.
  Procédure détaillée : `docs/evolutions-proposees.md` §c.

## Sécurité : `/docs`, `/redoc` et `/openapi.json` publics (corrigé le 24/09/2026)

**Constat.** `FastAPI(...)` enregistre par défaut `/docs` (Swagger UI),
`/redoc` et `/openapi.json` sans aucune authentification (`app/main.py`) :
en production, `/openapi.json` renvoyait 200 avec le schéma complet de
l'API (toutes les routes, formes de requêtes et de réponses), lisible par
quiconque connaît le domaine sans avoir de compte. Les routes elles-mêmes
restaient protégées (`admin_requis`, cookie de session) ; seul le schéma
était exposé. `/docs` et `/redoc` répondaient aussi 200, mais leur
interface, chargée depuis `cdn.jsdelivr.net`, est bloquée par la CSP
`default-src 'self'` posée par nginx (`infra/README.md` §7.2) : elle ne
s'affichait donc pas dans un navigateur, seul `/openapi.json` était
réellement exploitable tel quel.

**Correction.** Nouvelle variable optionnelle `API_DOCS_ACTIVES` (défaut
`false`, même mécanisme que `CONTROLE_PRIX_ACTIF` et `CONTROLE_LIVRE_NON_
FACTURE_ACTIF` : `app.core.config.Settings`, transmise par Compose).
`app/main.py` passe `docs_url`/`redoc_url`/`openapi_url` à `None` quand
elle est fausse : les trois routes renvoient alors 404 (`app/core/front.py`
les bloque de toute façon via `_PREFIXES_RESERVES`, que le front soit monté
ou non). Testé (`app/core/tests/test_docs.py`, sous-processus isolé comme
`test_demarrage.py`, `app.main.app` étant un singleton construit à
l'import) : absente ou explicitement fausse → 404 sur les trois routes ;
`API_DOCS_ACTIVES=true` → 200 sur les trois.

**Sans effet sur la génération des types front** : `web/package.json`
(script `api:schema`) appelle `app.openapi()` directement en Python
(`from app.main import app; app.openapi()`), jamais cette route HTTP — la
méthode reste disponible que `openapi_url` soit `None` ou non.

**Reste à faire** : activer `API_DOCS_ACTIVES=true` sur une instance
seulement si un besoin ponctuel le justifie (revue d'API par un tiers,
par exemple), jamais en permanence sur la production.

## Optimisations du 25/09/2026 (rapidité et sécurité)

Audit « rapidité et sécurité » mené sur la branche `optimisations`
(extraite de `main`), tâches T1 à T13, non encore fusionnée. Contexte
d'hébergement à garder en tête pour toute cette section : le serveur
actuel (VPS partagé du prestataire) est **provisoire**, partagé avec
d'autres projets et d'autres comptes Unix ; le serveur cible, dédié au
client, n'aura que le compte d'Ilane (administrateur). Deux constats
ci-dessous (limite de connexion contournable, documents déjà présents
lisibles par d'autres comptes) ne valent que sur ce serveur provisoire et
tombent d'eux-mêmes sur le serveur dédié.

### Corrigé

- **T1 (`3b2c562`)** — base PostgreSQL de dev/test sans `fsync`
  (`docker-compose.dev.yml` uniquement, jamais `habitat_prod`/
  `habitat_demo`) : suite de tests plus rapide, base jetable sans valeur
  de durabilité à préserver.
- **T2 (`8918a55`)** — `conftest.py` réduit le coût Argon2 (`time_cost=1`,
  `memory_cost=8`) pendant la suite de tests seulement ; coût réel intact
  en production (`app/core/auth.py` non touché).
- **T3 (`a59daa3`)** — documents écrits en 0640 (dossier 0750) au lieu de
  0644/0755 : n'étaient plus protégés que par l'authentification
  applicative, lisibles par tout autre compte Unix du VPS partagé sans
  elle. Voir la limite résiduelle sur les fichiers déjà présents et
  `backup.sh`, ci-dessous (« Reporté »).
- **T3 fix (`80e06eb`)** — `fichier_document`
  (`GET /api/documents/{id}/fichier`) contrôle désormais `document.type`
  avant le rôle de l'appelant : une facture ne peut plus être servie par
  cette route (défense en profondeur, `TYPES_BL` comme le reste
  d'`ingest`).
- **T5 (`d1a59ef`)** — alias chantier en attente : une seule requête par
  `fournisseur_id` distinct au lieu d'une par alias (N+1 corrigé,
  `referentiels.candidats_bruts_fournisseur` + filtre Python, même règle
  qu'avant, non dupliquée).
- **T6 (`b0948fc`)** — `Cache-Control: public, max-age=31536000, immutable`
  sur les fichiers hachés de `/assets` (front Vite) ; `index.html` garde
  `no-cache`.
- **T7 (`3eab4c9`)** — `staleTime: 30_000` par défaut côté TanStack Query
  (au lieu de 0) ; revue des 14 `useMutation` pour compléter les
  invalidations qui en dépendaient désormais (réglages, agences,
  fournisseurs).
- **T3 fix (`64263f8`)** — avertissement documentaire : la sauvegarde
  nocturne doit tourner en root (ou avec un accès donné explicitement à
  l'uid 10001) depuis le durcissement des permissions T3 — entrée déjà
  détaillée dans « Lot 5 — Restitution » ci-dessus (§ `backup.sh` ne
  pourra plus lire `DOCS_HOST_DIR`…), non dupliquée ici.
- **R1 (revue finale du 25/09/2026)** — corrige réellement l'avertissement
  ci-dessus plutôt que de seulement le documenter : `deploy/backup.sh`
  ajoute le gid 10001 (propriétaire des documents écrits par l'API) comme
  groupe supplémentaire du conteneur restic (`--group-add`), lisible quel
  que soit le compte hôte qui invoque le script — plus besoin de root ni
  de `setfacl`. `deploy/test-restauration.sh` dépose désormais un second
  fichier de test avec les droits réels d'un document produit par l'API
  (0640, uid/gid 10001) et vérifie qu'il survit à l'aller-retour sauvegarde/
  restauration — reproduit et vérifié en échec avant ce correctif
  (`permission denied` de `restic backup`, snapshot partiel), en succès
  après.
- **T3 fix (`392b4d6`)** — le rapport `rapport-ocr --sortie` (peut
  contenir des valeurs lues sur un document client réel) était encore
  écrit en 0644, oublié par le grep de T3 (l'appel passait `write_text`
  en référence de méthode à `asyncio.to_thread`, invisible au grep) ;
  passe désormais par `rapport_ocr.ecrire_rapport` (0640).
- **T8 (`bd3340a`)** — taille d'un fichier Telegram plafonnée avant le
  téléchargement (déclaré par `getFile`) et pendant (flux tronqué si le
  serveur Telegram mentirait) : plus de téléchargement illimité déclenché
  par un simple envoi de fichier.
- **T9 (`72a0b74`)** — `signature_conforme` (`ingest/commun.py`, fonction
  pure) vérifie désormais la signature binaire réelle d'un fichier reçu
  par Telegram (jpg/png/webp/pdf/tiff/heic/heif), pas seulement le
  `mime_type` déclaré par le client — même principe que le contrôle déjà
  en place sur le dépôt de facture (« %PDF- »), devenu la seule source de
  vérité, reprise par `factures.py` et `depot_telegram.py`.
- **T10 (`f9fb2b6`)** — CSP complétée (`base-uri`, `form-action`,
  `object-src`), `Permissions-Policy`, `Cross-Origin-Opener-Policy` et
  `Cross-Origin-Resource-Policy: same-origin` ajoutés ; zone `limit_req`
  dédiée `login` (5 r/min) sur `/api/auth/login`, le reste garde
  `general`. Mêmes en-têtes reportés dans les labels Traefik du compose
  de production. Les deux zones (`general`, `login`) doivent exister dans
  le `nginx.conf` du serveur (hors dépôt) — voir « Reporté » ci-dessous
  pour la limite propre à `login` sur le serveur provisoire.
- **T11 conteneurs (`3c74a1e`)** — `security_opt: no-new-privileges:true`
  sur `api` et `postgres`, `cap_drop: ALL` sur `api` (déjà non-root, uid
  10001), `pids_limit: 200` sur les deux. Pas de `cap_drop` sur
  `postgres` (l'image officielle démarre en root avant d'abandonner ses
  privilèges, a besoin de capacités que `ALL` retirerait) — voir
  « Reporté » pour les limites mémoire et le rootfs en lecture seule,
  non traités par cette tâche.
- **T13 dépôt (`dae8bda`)** — hooks pre-commit `pip-audit` et
  `npm audit --omit=dev --audit-level=high`, déclenchés uniquement quand
  `uv.lock`/`pyproject.toml` ou `web/package-lock.json` changent (pas à
  chaque commit).

### Reporté

- **Limite de connexion (5 requêtes/minute sur `/login`) contournable par
  un processus local.** La zone nginx `login` (T10 ci-dessus) protège le
  trafic Internet, mais un `uvicorn` lancé avec
  `--forwarded-allow-ips=*` reste joignable sur son port TCP
  `127.0.0.1` par tout autre processus de l'hôte, qui contournerait ainsi
  nginx et sa limite. Parade : socket Unix entre nginx et uvicorn, ou
  secret partagé nginx → API vérifié par un middleware. **Sans objet sur
  le serveur dédié** s'il n'héberge rien d'autre que cette application ;
  concerne uniquement le VPS provisoire, partagé avec d'autres comptes.
- **Documents déjà présents sur le serveur provisoire, toujours en
  0644.** T3 (`a59daa3`) corrige les *nouveaux* fichiers (0640/0750) ;
  les documents déjà écrits avant ce commit restent en 0644 — choix
  explicite d'Ilane, pas de `chmod` rétroactif sur ce serveur provisoire.
  De toute façon, un compte membre du groupe `docker` de cet hôte a un
  accès équivalent à root (peut lire/écrire n'importe quel fichier via un
  conteneur) : le durcissement des permissions ne change donc rien face
  à ce niveau d'accès-là — seulement face à un compte Unix ordinaire,
  hors groupe `docker`. **Sans objet sur le serveur dédié**, sans autre
  compte que l'administrateur.
- **Session glissante de 12 h sans plafond absolu.** Conforme au CDC
  (déconnexion après 12 h d'inactivité, cf. « L2-T1 » ci-dessus) ; à
  confirmer avec Ilane si un plafond absolu (ex. 30 jours quelle que soit
  l'activité) est également voulu.
- **Limites mémoire des conteneurs, `cap_drop` sur `postgres`, rootfs en
  lecture seule.** Non traitées par T11 (`3c74a1e`) : à mesurer d'abord
  (`docker stats` sur une charge réelle) et à tester sur la démo avant la
  production, une limite mémoire trop basse pouvant faire tuer le
  conteneur (OOM) plutôt que de le protéger.
- **Images Docker épinglées par tag (`postgres:18`, etc.), pas par
  digest.** Choix assumé : un digest figé ne reçoit plus les correctifs
  de sécurité de l'image de base.
- **Pas de scanner de CVE de la couche système (paquets Debian, image de
  base).** Les hooks `pip-audit`/`npm audit` (T13, `dae8bda`) couvrent les
  dépendances applicatives, jamais la couche OS des images ; passer
  `trivy` à la main avant un déploiement sensible, pas automatisé.
- **Bundle JS unique de 108 Ko gzip.** Pas de découpage par page à ce
  volume (peu d'écrans, peu de dépendances lourdes) ; Brotli non activé
  (gain estimé ≈ 16 Ko, jugé non prioritaire au volume actuel).
- **Liste « Documents » plafonnée à 100 lignes, filtres chantier/
  fournisseur/mois côté navigateur.** Déjà noté ci-dessus (« Liste
  Documents », Task 8) : suffisant pour ≈ 6 jours de dépôts au volume du
  CDC ; filtrer côté SQL (sur le modèle de `bilan.py`) si le volume
  grandit.
- **Synchronisation des anomalies : une requête par anomalie candidate au
  dépôt d'une facture.** Négligeable devant le coût d'un appel OCR
  Mistral (même dépôt). Piège identifié à ne pas reproduire si ce code
  est retouché : `_conditions_portee` (`ingest/anomalies.py`) filtre sur
  `statut='ouverte'`, mais `_trouver_par_cle` doit, lui, retrouver aussi
  une anomalie déjà `traitée`/`ignorée` (la contrainte d'unicité
  couvrant toutes les anomalies, pas seulement les ouvertes) —
  restreindre ce second point à `ouverte` casserait cette unicité.
- **`preparer_base` rejouée 5 fois par run de tests.** Ne pas la
  mémoïser : les tests de migration comptent sur sa ré-exécution après un
  `alembic downgrade`. `pytest-xdist` non adopté pour autant (base de
  test partagée entre tous les tests, incompatible avec une exécution
  parallèle sans base par worker).

- **[Corrigé le 27/09/2026, phase 2 : `ps -a -q api`]** **`restore.sh` refuse de restaurer quand l'API est arrêtée (bogue
  antérieur aux optimisations, constaté le 25/09/2026).** Le garde-fou
  `docker compose … ps -q api` (`deploy/restore.sh`, vers la ligne 131)
  ne liste que les conteneurs **en marche** : après un `stop api` (fait
  par `deploy/test-restauration.sh` juste avant, et naturel avant une
  restauration), il conclut « conteneur api introuvable » et s'arrête sans
  rien modifier. Correctif probable : `ps -a -q api` (conteneur créé, en
  marche ou non), avec un test dans `tests/test_restore_script.py`. À
  traiter avec la mise en place des sauvegardes restic (priorité n° 1),
  en rejouant `deploy/test-restauration.sh` de bout en bout.

## Mise en production du 1er octobre (27/09/2026) — reporté

Relevé par les relectures (tâche par tâche et finale) et laissé de côté
volontairement ; aucun ne met en jeu les montants, les règles ni la sécurité.
Recette : `docs/mise-en-production-1er-octobre-recette.md`.

- **Compteur `nb_demandes_alias`** (journal `facture_deposee`, `ingest/factures.py`) : compte aussi un bloc dont le chantier brut se réduit à un code entre parenthèses. Chiffre de journal seulement.
- **Docstrings d'`ingest/anomalies.py`** : disent encore que `evaluer_chantier` n'est pas appelée par `ingest` (elle l'est depuis le rattachement automatique).
- **Tests manquants** : bon d'un fournisseur inconnu rattaché ou créé sans apprentissage ; repli de `_exemple_brut_alias` quand aucun brut n'existe ; course `retirer_acces` × `retirer_acces` ; `..` explicite dans `normaliser_segment`. Comportements vérifiés à la lecture.
- **Photos rangées** : si l'ancien lien est retiré et que le nouveau échoue, le bon n'a plus de lien jusqu'au prochain `ranger-photos` ; `corriger_entete` range la photo à chaque correction, même sans changement de chantier (idempotent). Les bons dont le chantier change par propagation d'un nom appris attendent `ranger-photos` (timer nocturne à poser en phase 2).
- **Écran** : colonne « Fournisseur » redondante dans les livraisons de la fiche fournisseur ; classe du champ mois dupliquée entre deux pages ; petite duplication du formulaire de création de chantier entre l'alerte et « Noms à rattacher » ; si une création puis un choix échouent, un second essai réutilise le chantier déjà créé même si le nom a été modifié.
- **Journal** : le libellé « Livraisons (total) » sert aussi au nombre de lignes de facture déplacées par une fusion ; le front traite `cible_id` comme un chantier sans connaître `cible_table` (sûr tant que seule la fusion l'écrit).
- **Comptes** : pas de longueur maximale du mot de passe (coût argon2, administrateur de confiance seul) ; identifiant Telegram sans contrainte `> 0` ; unicité de l'identifiant Telegram garantie par verrou applicatif, pas par un index en base (à ajouter dans une migration planifiée).
- **Reprise** : `rattacher-chantiers` garde le verrou des chantiers pendant toute sa durée (bloquerait les dépôts sur un gros arriéré).

## Phase 2 — exploitation (27/09/2026)

- **Sauvegardes dans un dépôt restic local** (`/home/debian/sauvegardes-habitat/restic-<instance>`, décision d'Ilane du 27/09) : protège d'une erreur ou d'une suppression, **pas de la perte du serveur** (même disque). Bascule vers OVH Object Storage (CDC §9) dès qu'Ilane a créé le conteneur et ses clés : changer `RESTIC_REPOSITORY` et ajouter `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` dans `.env.<instance>`, `restic init`, puis relancer une sauvegarde. Mots de passe restic dans `~/.secrets/restic-habitat.txt` : à recopier par Ilane dans son gestionnaire de mots de passe (sans eux, les sauvegardes sont illisibles).
- **Tâches planifiées lancées depuis l'arbre de travail** `/home/debian/habitat_reno` (scripts `deploy/*.sh`) : un changement de branche qui retirerait ces scripts casserait les tâches. Sur le serveur dédié, installer depuis une copie propre de `main`.
- **Contrôles différés et rangement des photos pas encore planifiés** : ils attendent le déploiement de la phase 1 (sinon ils tourneraient sur l'ancienne version et créeraient des rappels « chantier à rattacher » que la reprise résout).
- **Unicité de l'identifiant Telegram** (rappel de la phase 1) : verrou applicatif ; index partiel en base à ajouter dans une migration planifiée.
- **Alerte d'échec : angles morts** (relecture de la phase 2) : `controles-differes` et `ranger-photos` rendent toujours le code 0 (un échec sur un seul élément est journalisé mais ne fait pas échouer la tâche), donc seul un échec complet (base injoignable, conteneur arrêté) déclenche l'alerte Telegram ; la sauvegarde, elle, échoue au moindre problème. Si Telegram est injoignable, l'alerte elle-même échoue sans autre canal (journald seulement).

## Phase 3 — commentaires (session B, 27/09/2026)

Tâche C de la phase 3 (`docs/roadmap-octobre-2026.md` §6.2, §10) :
commentaires sur les lignes d'un bon (migration `0012`, `ingest/
commentaires.py`, `api/commentaires.py`, `web/src/components/
CommentairesLignes.tsx`). Limites connues, prévues dès la conception
(`docs/superpowers/specs/2026-09-27-commentaires-lignes-design.md` §3, §8) :

- **Pas de verrou en base empêchant la modification ou la suppression d'un
  commentaire.** La table `commentaire` n'a ni déclencheur ni règle qui
  refuserait un `UPDATE`/`DELETE` fait hors de l'application (aucune route
  n'en expose) : la mise à vide de `ligne_id` par `ON DELETE SET NULL`
  quand la ligne commentée est supprimée en est déjà une, faite par la
  base elle-même et voulue (garde le commentaire affichable via
  `ligne_libelle`). La roadmap ne demande un tel verrou que pour
  l'historique des prix (lot Prix, même session/branche) ; à réévaluer si
  un usage réel montre le besoin d'un commentaire réellement immuable au
  niveau base, pas seulement au niveau de l'API.
- **Pas de nombre de commentaires dans la liste des documents.** Seule la
  page d'un bon affiche « Commentaires (N) » (carte repliable) ; la liste
  des documents (`web/src/pages/DocumentsListe.tsx`) n'indique nulle part
  qu'un document en a. Hors périmètre de la demande client (§8 de la
  spec, « possible plus tard si utile ») ; ajouterait une colonne calculée
  (comptage par document) au routeur de la liste si demandé.

## Phase 4 — IA (27/09/2026)

Conception complète : `docs/superpowers/specs/2026-09-27-phase-4-ia-design.md`.
Guide d'exploitation, avec le détail de la décision `read_only` du
conteneur OpenCode : `docs/phase-4-ia.md` et la section « Phase 4 — IA,
exploitation (T8, 28/09/2026) » ci-dessous. Ce qui suit est propre à la
conception et au code métier (T1 à T7), pas à l'exploitation du conteneur.

- **Moteur choisi contre la recommandation.** Ilane a choisi OpenCode
  connecté à son abonnement personnel ChatGPT Plus/Pro (décision D2 de la
  spec, 27/09/2026) plutôt que l'API Mistral déjà dans la stack, payante à
  l'usage et hébergée en UE — recommandation écartée en connaissance de
  cause (risques consignés à l'avenant CDC §15 et dans `docs/phase-4-ia.md`
  §9). Un seul module, `ingest/opencode.py`, parle au moteur d'IA : changer
  de fournisseur (revenir à Mistral ou une autre API) revient à réécrire ce
  seul module, sans toucher `extract/reponses_ia.py` ni les services
  `ingest/ia_synthese.py`/`ingest/ia_prix.py`.
- **Version d'OpenCode figée (`opencode-ai@1.18.32`), aucune mise à jour
  automatique.** `deploy/opencode/Dockerfile` épingle cette version : une
  montée de version est un geste volontaire (reconstruction de l'image),
  jamais un effet de bord d'un autre changement. Une version plus récente
  pourrait changer le comportement des outils `websearch`/`webfetch` ou la
  prise en charge de Firecrawl (D3 de la spec), à revérifier avant toute
  montée de version.
- **Recherche web par le service public d'Exa, limites inconnues.**
  `OPENCODE_ENABLE_EXA=1` passe par le service public d'Exa, sans clé,
  plutôt que par Firecrawl (demandé par Ilane, non pris en charge par la
  version stable d'OpenCode, D3). Aucune limite de débit ni de volume n'est
  documentée par Exa pour ce service public ; une clé gratuite
  (`EXA_API_KEY`, 10 $ de crédit par mois) peut être ajoutée dans
  `deploy/opencode/.env` si le service public s'avère limitant en usage réel.
- **Aucun essai de bout en bout possible avant l'abonnement.** Les modèles
  gratuits pris en charge par OpenCode refusent le mode serveur (`opencode
  serve`) : aucun des trois usages (synthèse, explication, prix internet)
  n'a pu être exercé contre une vraie réponse de modèle, seulement contre
  des doubles (`httpx.MockTransport`) et des données inventées. L'essai réel
  (document d'Ilane §16, `python -m app.cli essai-prix-internet`) n'est
  possible qu'après la connexion de l'abonnement (`docs/phase-4-ia.md` §5).
- **Explication et prix internet sans objet tant que le lot Prix n'est pas
  fusionné.** Les alertes de catégorie « prix » que l'explication cible
  (R07-R09) restent masquées côté serveur (`CONTROLE_PRIX_ACTIF=false`,
  décision du 24/09/2026) et R22 (« Produit absent de la grille », seule
  règle qui déclenche une recherche de prix internet) n'est pas encore
  fusionnée dans `dev` (elle existe sur la branche du lot Prix) : le code
  de `ingest/ia_prix.py` est écrit et testé sur des anomalies inventées,
  mais n'a aujourd'hui aucune anomalie réelle à traiter.
  **Résolu (T10a, 28/09/2026) :** le lot Prix est fusionné dans `dev` (PR
  #5) — `expliquer_alertes` et `chercher_prix_internet` traitent désormais
  de vraies anomalies R19-R25/R22, prouvé par un essai de bout en bout sur
  une vraie anomalie R22 (`ingest/tests/test_ia_prix_bout_en_bout.py`,
  vrais services `controler_prix_bl`/`chercher_prix_internet`, faux
  transport OpenCode).
- **R22 (lot Prix) ne porte pas encore `dernier_prix`.** Vérifié contre le
  vrai code de la branche du lot Prix à la relecture finale du 28/09/2026
  (`git show origin/feature/phase-3-prix:app/modules/rules/rules/R22.py`) :
  le `detail` de R22 ne porte que `produit`, `code` (tiret cadratin si
  absent), `prix_bon`, `unite_bon` (tiret cadratin si absent), `date_bon`
  et `candidats` — jamais de clé `dernier_prix` (celle-ci n'existe que sur
  R20). Tant que le lot Prix n'ajoute pas cette clé, `chercher_prix_internet`
  (`ingest/ia_prix.py::_dernier_prix_utile`) ne peut jamais la trouver utile
  et lancera donc aussi la recherche de prix internet pour un produit déjà
  facturé mais simplement absent de la grille — contrairement à l'intention
  du §6.1 de la spec (« ni grille ni facture »). Action précise à la fusion :
  item dédié de T10, `docs/superpowers/plans/2026-09-27-phase-4-ia.md`.
  **Résolu (T10a, 28/09/2026) :** `rules/rules/R22.py`, tel que fusionné dans
  `dev`, porte bien `dernier_prix`/`date_dernier_prix` (« — » si aucun) —
  `ingest/ia_prix.py` lit exactement ces clés, sans modification nécessaire ;
  vérifié par l'essai de bout en bout (variante avec une facture antérieure :
  `dernier_prix` utile, aucune recherche internet lancée).
- **3ᵉ colonne « Internet » de la page `/prix` à construire (T10).** Elle
  lira le même service (`ingest/ia_prix.py`) une fois le lot Prix fusionné
  dans `dev` — hors périmètre de la phase 4 IA elle-même (spec §6.4, §11).
  **Précision (T10a, 28/09/2026) :** le lot Prix est fusionné ; le service
  serveur est fait (`ingest.ia_prix.prix_internet_des_anomalies`, route `GET
  /api/ia/prix-internet`, T10a). Reste seulement l'écran (T10b) : la colonne
  elle-même, consommant cette route.
  **Fait (T10b, 28/09/2026) :** colonne construite (`Prix.tsx`,
  `components/PrixInternetCellule.tsx`, `lib/prixInternet.ts` partagé avec
  `AvisIA.tsx`). Acceptée en l'état : comme la requête groupée ne pose pas
  de `placeholderData`, la colonne peut disparaître brièvement (retour à 6
  colonnes) le temps que la nouvelle liste d'alertes recharge après un
  changement de filtre (période/fournisseur), avant de réapparaître une fois
  la réponse revenue.
- **`appel_ia` jamais purgé.** Chaque appel à l'IA (réussi ou non) écrit une
  ligne dans cette table technique, jamais supprimée. Volume attendu faible
  (quelques lignes par jour, plafonné par `IA_APPELS_MAX_JOUR`) : à
  surveiller si l'usage grandit, purge par une tâche planifiée à ajouter si
  besoin.
- **Un seul conteneur OpenCode pour la production et la démonstration**
  (mémoire du VPS, `docs/phase-4-ia.md` §3) : un abonnement déconnecté ou un
  plafond atteint affecte les deux instances à la fois, sans isolation entre
  elles pour cet usage.
- **Incident : une ligne du `.env` de développement affichée par un
  sous-agent (T3, 27/09/2026).** En recherchant l'URL de la base de test
  avant d'écrire le code, l'implémenteur a lancé par erreur un `grep` sur le
  `.env` du worktree, ce qui a affiché la ligne `TEST_DATABASE_URL` (URL de
  la base de test locale, avec son mot de passe de développement — pas un
  secret de production). Transgression réelle de la consigne « ne jamais
  lire ni afficher `.env` », signalée dans le suivi de la tâche plutôt que
  passée sous silence ; aucune valeur n'est reproduite ici. Ilane peut faire
  tourner ce mot de passe de base de test locale s'il le juge utile ; aucune
  valeur de production n'est concernée.
- **Limites mineures relevées en relecture, sans conséquence sur le
  comportement observable :**
  - pas de test négatif dédié du `CHECK` sur `prix_internet.taxes` (valeur
    hors `HT`/`TTC`) ni de la borne de 300 caractères de
    `synthese_action.texte` (T1) — le `CHECK` est bien posé et vérifié
    structurellement (`alembic check`), seul un test positif dédié à son
    comportement à l'exécution manque ;
  - commentaire périmé dans `app/core/db.py` (« aucun index composite »)
    depuis que `PrixInternet` en ajoute un premier (T1) ;
  - la garde des chiffres de l'explication (T2) refuse « prudemment » un
    nombre valide quand un chiffre isolé le précède sans séparateur net dans
    le texte (ex. « Page 2 45,00 ») : faux négatif seulement (une
    explication légitime parfois refusée), jamais de faux positif (aucun
    chiffre inventé ne passe) ;
  - `ingest/opencode.py::_journaliser_appel` (T3) prend une deuxième
    connexion du pool de base pendant que l'appelant garde la sienne, pour
    écrire la ligne `appel_ia` dans sa propre transaction (§3.4 de la
    spec) — acceptable au volume attendu (quelques appels par jour), à
    revoir si le pool de connexions devenait un point de contention ;
  - un `SystemExit`/`KeyboardInterrupt` pendant un appel à l'IA (T3) saute
    quand même la ligne `appel_ia` (jamais avalé, propagé normalement) ;
    une annulation pendant la suppression de la session côté OpenCode
    remplace le code d'erreur d'origine par « interrompu » dans cette ligne
    technique ;
  - pas de test de la synthèse traversant un changement d'heure (été/hiver)
    (T4) — le chemin `IntegrityError`/`rollback` d'une course entre deux
    générations de synthèse simultanées est, lui, désormais couvert
    (`test_generer_synthese_vide_course_concurrente_deja_faite`, relecture
    finale du 28/09/2026) ;
  - l'essai (`essai-prix-internet`) reconnaît l'en-tête de son CSV par une
    heuristique sur la première colonne : un fournisseur réellement nommé
    « Fournisseur… » en première ligne serait pris à tort pour un en-tête
    (T6) ;
  - l'encart « Avis de l'IA » affiche le conditionnement du prix trouvé sur
    internet s'il existe, sinon l'unité, jamais les deux à la fois (T7) —
    affichage à confirmer par Ilane.

## Phase 4 — IA, exploitation (T8, 28/09/2026)

Conteneur OpenCode, rattachement de l'API et tâches planifiées
(`deploy/opencode/`, `deploy/docker-compose.ia.yml`), détail et procédures
dans `docs/phase-4-ia.md`.

- **`read_only: true` non activé sur le conteneur OpenCode, par choix
  délibéré** (`deploy/opencode/docker-compose.yml`) : confirmé en direct
  (fix round 1, essai sur l'image construite) — OpenCode écrit un
  `.gitignore` dans `~/.config/opencode` à chaque création de session
  (`POST /session`) ; avec une racine en lecture seule (même avec un
  `tmpfs` sur `/tmp`, `~/.cache`, `~/.local/share/opencode` et
  `~/.local/state`), cette écriture échoue en `EROFS` et la création de
  session échoue avec elle. Dans ce conteneur (sans `read_only`), le même
  répertoire est déjà fermé à `opencode` (`root:root`, 0555, immuabilité
  voulue de la configuration des agents) : l'écriture échoue aussi, mais
  sans conséquence (ignorée par OpenCode). Rendre la racine en lecture
  seule transformerait cet échec aujourd'hui sans gravité en échec bloquant
  — le conteneur reste durci par ailleurs (`no-new-privileges`, `cap_drop:
  ALL`, `pids_limit`, `mem_limit`, aucun port publié, utilisateur non root
  dédié, réseau interne dédié). Détail : `docs/phase-4-ia.md` §9.
- **Pas de route ni d'écran pour surveiller `appel_ia`** (plafond, échecs
  par usage) : la surveillance se fait pour l'instant en base ou par les
  logs (`docs/phase-4-ia.md` §6). Un écran dédié n'a pas été demandé par
  Ilane à ce stade.

## Phase 3 — prix (session B, 28/09/2026)

Lot Prix de la phase 3 (`docs/roadmap-octobre-2026.md` §6.2, §10) : grilles
fournisseur, contrôle des prix au bon (règles pures R19 à R25), page
« Prix à vérifier » (migration `0013`,
`docs/superpowers/specs/2026-09-27-prix-design.md`). Points hors
périmètre de la spec (§13) et laissés ouverts par la relecture de fin de
phase :

- **Contrôle des prix à la facture, prix trouvé sur internet, commentaire
  de l'IA sur l'écart** : renvoyés à la phase 4 par la spec (§13),
  remplaceraient à terme R07-R09 (déjà désactivées).
- **Suivi des réclamations fournisseur** après l'action « Contester » sur
  une alerte de prix : pas de statut ni d'historique au-delà du journal.
- **Prix des bons précédents comme « dernier prix payé »** (§6.3 de la
  spec) : seule la dernière facture sert de référence pour R20, pas le
  dernier bon.
- **Lecture de la remise imprimée sur un bon** : non gérée, le contrôle
  compare le prix unitaire brut.
- **R20 inopérante chez Point.P** : elle compare au dernier prix facturé,
  or le parseur de facture Point.P n'est toujours pas construit (blocage
  connu depuis le lot 3, aucun document disponible) ; tant qu'il n'existe
  pas, R20 ne se déclenche jamais pour ce fournisseur, même si son prix a
  augmenté.
- **Import d'une grille mise en page librement** (blocs de prix côte à
  côte sur une même feuille) non géré : il faut le modèle de colonnes
  attendu par `extract/grille_excel.py`.
- **Cascade des alertes réglées sur une ligne supprimée** (§3.3 de la
  spec) : la migration `0013` passe `anomalie.ligne_id` en
  `ON DELETE CASCADE` pour ne plus bloquer la suppression d'une ligne
  portant une alerte. Mais `corriger_lignes` supprime une ligne retirée
  par `session.delete(ligne)` sans appeler `synchroniser_anomalies` ni
  rien journaliser pour les anomalies qui pointaient dessus : la cascade
  les supprime silencieusement en base, y compris une anomalie déjà
  traitée ou ignorée (avec son commentaire de résolution et son auteur),
  sans aucune entrée « anomalie levée » au journal — contrairement à
  toute autre voie de suppression du code (`synchroniser_anomalies`, et
  le correctif équivalent déjà fait sur l'archivage d'un document,
  justement pour ce genre de perte silencieuse). Déjà noté au §3.3 de la
  spec comme limite connue ; à corriger si un usage réel montre que des
  alertes réglées disparaissent ainsi sans trace.
- **Déclencheurs de `grille_prix` désactivés dans les fixtures de test**
  (`conftest.py` de `app/core`, `app/modules/api`, `app/modules/ingest`,
  `app/modules/jobs` et `tests/`) : la table refuse tout `TRUNCATE`
  (historique inaltérable, déclencheur `grille_prix_sans_truncate`), donc
  la remise à zéro de la base de test désactive ces déclencheurs le temps
  du `TRUNCATE` puis les réactive. Sans base réelle exercée sur plusieurs
  mois, ce comportement n'a été vérifié qu'en test.
- **Tâche planifiée quotidienne jugée inutile** par la spec (§13) : le
  contrôle tourne à chaque dépôt et la page lit l'état courant. Aucun
  rattrapage périodique n'existe pour autant si le contrôle échoue
  silencieusement sur un dépôt (même angle mort que `controles-differes`
  et `ranger-photos`, phase 2).
- **Barre de navigation basse (téléphone)** : le passage à six entrées
  avec l'ajout de « Prix » resserre l'espace disponible par item ; les
  libellés ne sont pas protégés par une largeur minimale, un libellé long
  pourrait déborder à l'écran le plus étroit visé.
- **Libellé de R24** : la phrase affichée à l'écran enchaîne ses
  informations par des virgules sans les relier par un verbe, ce qui la
  rend un peu plus dense à lire que les autres règles de prix (R19-R23,
  R25).
- **Interrupteur général `prix_controle_bl_actif` éteint par défaut** :
  aucune alerte de prix n'est créée tant qu'il n'est pas activé (décision
  de déploiement, §14 de la spec) ; l'ordre conseillé au déploiement est
  d'importer les grilles, de vérifier la page Grille fournisseur, puis
  d'allumer le contrôle et de relancer un recontrôle des bons existants.

## « Conforme » strict et facture à somme incohérente (29/09/2026, audit B-02/B-03/B-09/D-01)

Décisions d'Ilane du 29/09/2026 (`.superpowers/sdd/corrections-audit/decisions-ilane.md`, points 1 et 2).

- **Une seule définition de « Conforme », calculée par le serveur**
  (`ingest.bilan._sous_requete_categories`). Une livraison (bloc de facture)
  est « conforme » seulement si son bon est **validé**, si le rapprochement l'a
  trouvé, si sa facture n'est pas « à vérifier » et si **aucune anomalie
  ouverte** (toute règle : R10, R11, R12, R13, R17, quantité, prix...) ne porte
  sur ce bloc ni sur le bon qu'il cite. Sinon « à vérifier » (ou « sans bon »
  quand le bon n'est jamais venu). Reprise par le montant « Conforme » (bilan à
  cinq niveaux, accueil, fiches chantier et fournisseur), la liste des
  livraisons (`categorie`), la page du bon (`categorie` de la comparaison) et
  l'état d'un chantier de l'accueil. Le front n'a plus de règle propre
  (`categorieLivraison` supprimée). Un doublon de facturation (R12) rend aussi
  le bloc d'origine « à vérifier » (les deux blocs citent le même bon).
- **Reste à savoir** : la colonne « Contrôle » de chaque ligne de la page du
  bon (`controle`) reste un verdict par ligne (appariée, comparée, sans
  anomalie), libellé « Identique » (et non « Conforme », réservé à la
  livraison) ; elle ne regarde pas le statut du bon. C'est la pastille du haut
  de page qui porte le verdict de la livraison.
- **R10 est produite pour une facture « à vérifier »** : `rapprocher_facture`
  n'apparie toujours pas une facture non validée, mais évalue R10 seule à
  partir du motif `somme_incoherente` posé à l'extraction (la tolérance de
  l'admin s'applique). L'alerte apparaît dans « À régler » (elle s'ajoute à la
  facture elle-même, listée dans « À traiter » : le compte unique compte donc
  les deux). Elle est levée au rejeu suivant si le motif disparaît (une
  correction ou une validation de facture rejoue la facture elle-même, dans
  la transaction de l'écriture : `corrections._rejouer_apres_ecriture` ;
  **mais** aucune route ne corrige ni ne valide une facture aujourd'hui,
  `corrections.py` est réservé aux bons : en pratique l'alerte tombe par
  archivage, par un changement de tolérance suivi de `rapprocher --tout`
  (les factures « à vérifier » y sont traitées), ou quand la correction de
  facture sera construite). Ce qui
  précède corrige la formule inexacte de la section précédente : R10 n'était
  jamais produite avant cette date.
- **« Facturé » garde ces factures**, avec la mention « dont X € sur des
  factures à vérifier » (champ `facture_a_verifier` de l'accueil, des fiches
  chantier et fournisseur). Les exports CSV du bilan (colonnes fixées par le
  CDC) n'ont pas cette mention.

## Rattachement des chantiers : nombres différents (29/09/2026, audit B-05)

- **Les lettres ne sont pas traitées** : « Bât A » / « Bât B » (ressemblance 94) se rattachent encore d'office ; seule la différence de nombres force « à confirmer » (décision d'Ilane, point 3).
- **Choix prudent** : « Les Pins » / « Les Pins 2 » (un nombre d'un seul côté) passe aussi « à confirmer » quand le score atteint le seuil, ce qui ajoute quelques R18.
- **Alias déjà appris** : jamais revus automatiquement ; diagnostic `chantiers-alias-suspects` (lecture seule), correction manuelle par Ilane. Les chiffres dans les mots (« m2 ») comptent comme des nombres.

## Sauvegardes et restauration (audit du 30/09/2026, groupe 5)

- **Corrigé (F-02, C-02, C-03)** : `restore.sh` fait tous ses contrôles avant
  la première destruction (dossier des copies de sécurité, parent de
  `DOCS_HOST_DIR`, snapshot, dump validé par `pg_restore --list`), écrit une
  copie de sécurité de la base courante (600, `~/sauvegardes-habitat/`) avant
  le `DROP`, et bascule les documents dans un conteneur root jetable
  (`deploy/basculer-documents.sh`) : uid/gid 10001, 0750/0640, sans exiger
  que l'opérateur soit root. **Ne couvre pas** : la copie de sécurité n'est
  jamais purgée (à supprimer à la main après validation) ; l'espace disque
  n'est pas vérifié ; l'ancien `.avant-restauration-*` reste à l'uid 10001
  (suppression par `sudo` ou conteneur). Les tests sans Docker
  (`tests/test_restore_script.py`, `tests/test_sauvegarde_scripts.py`) lisent
  l'ordre des appels avec un faux `docker` ; seul `deploy/test-restauration.sh`
  prouve les droits réels (à rejouer, y compris avec un parent possédé par
  root, ce qu'il ne reproduit pas).
- **Corrigé (F-01)** : le dump est monté sous `/dump` et `--host` vaut le nom
  du projet compose : la rétention 30 quotidiennes + 12 mensuelles s'applique
  enfin. **Reste** : les instantanés antérieurs (hôte aléatoire, un groupe
  chacun) ne sont pas purgés ; les supprimer à la main
  (`restic forget <id> --prune`) une fois quelques semaines de sauvegardes
  récentes en place.
- **Reste (F-04)** : aucune alerte quand une sauvegarde ne tourne pas du tout
  (timer désactivé, machine éteinte, dépôt restic plein) : `alerte-echec.sh`
  ne prévient que d'un échec du service, jamais d'un passage manquant. À
  prévoir : contrôle d'âge du dernier instantané (hors de ce passage, les
  scripts de supervision de `feature/exploitation-2` n'en font pas partie).

## Audit du 29/09/2026

Audit complet de `dev` (copie figée au commit `8ccd872`), six angles (A
sécurité, B métier, C données, D API et écrans, E intégrations, F
exploitation et tests), puis vérification contradictoire des 26 constats
classés « importants » (méthode et bilan : `README.md` §20). Résultat : **0
critique, 13 importants confirmés**. Ces 13 ne sont pas listés ici : ils ont
des corrections en cours (branche `feature/corrections-audit`, plan en cinq
groupes, `README.md` §20.4). Cette section ne liste que les constats
**mineurs ou latents**, sans répéter ce qui est déjà décrit plus haut. « V » =
vérifié par un vérificateur contradictoire (gravité révisée) ; « NV » = classé
mineur par l'auditeur, non revérifié un par un. Rien de ce qui suit ne bloque
la mise en production.

### Rétrogradés en mineurs ou latents après vérification (V)

- **A-01** — Mineur aujourd'hui (latent), **bloquant pour la bascule sur le
  serveur dédié** : le compose de base sous Traefik n'a ni limite de taille de
  corps ni limitation de débit (`deploy/docker-compose.yml:85-117`) ; seul nginx
  les pose (`deploy/nginx/habitat.conf:38`). À faire : `buffering` et `ratelimit`
  Traefik.
- **A-02** — Mineur : l'agent de prix de l'IA peut ouvrir n'importe quelle
  adresse par `webfetch`, sans filtrage des destinations
  (`deploy/opencode/opencode.json`, `deploy/opencode/docker-compose.yml`) ;
  portée réelle limitée (requêtes GET, aucune donnée sensible dans l'agent). À
  faire avant d'allumer l'IA en production : règle de pare-feu sur le réseau
  `habitat_ia` (passerelle de l'hôte, plages privées et link-local) ; arrêter
  aussi le petit serveur HTTP orphelin repéré sur l'hôte.
- **B-08** — Mineur aujourd'hui, important dès l'activation des prix : les
  références de prix (R20, historique R07-R09) incluent les factures archivées
  et « à vérifier » (`ingest/prix_bl.py:339-355`, `ingest/rapprochement.py:236-250`).
  À corriger avant d'allumer le contrôle des prix.
- **B-09 (mention)** — la phrase de « Revue finale du lot 4 » qui dit qu'une
  facture « à vérifier » l'est « typiquement parce que sa somme est incohérente
  (règle R10) » est inexacte : R10 n'est jamais produite pour une facture « à
  vérifier » (`ingest/rapprochement.py:585-595`). Correction du comportement
  décidée par Ilane le 29/09 (groupe 3).
- **C-03** — Mineur (important tant qu'aucune sauvegarde récente n'existe) :
  `restore.sh` supprime la base courante avant d'avoir validé la sauvegarde et
  sans copie de sécurité (`deploy/restore.sh:236-255`).
- **C-04** — Mineur : listes et contrôles qui chargent l'entité `Document` avec
  ses colonnes JSON lourdes (`ingest/lecture.py:574-593`, `ingest/suivi.py:256-262`),
  page Documents rafraîchie toutes les 15 s (`web/src/pages/DocumentsListe.tsx:506`).
- **D-02** — Mineur : erreurs de validation affichées « erreur 422 » sans texte
  utile ; champ de commentaire d'archivage sans limite de 500 caractères ;
  espaces insécables dans un nombre saisi refusés
  (`web/src/api/client.ts:88-101`, `web/src/pages/DocumentDetail.tsx:197-200,1278`).
- **D-03** — Mineur : sur téléphone, les montants supérieurs à environ cent
  mille euros dépassent de leur tuile d'accueil
  (`web/src/ui/Chiffre.tsx:57`, `web/src/pages/VueEnsemble.tsx:450`).
- **E-01** — Mineur (important le jour où l'IA sera allumée en production) : une
  panne de l'IA consomme les trois essais de chaque alerte et le plafond du
  jour (`ingest/ia_prix.py:376-424,690-712`). Correction soumise à l'accord
  d'Ilane (IA gelée).
- **E-02** (avec C-08) — Mineur : l'OCR Mistral n'a ni reprise ni limite de
  concurrence ; une rafale de photos peut donner des documents « à vérifier »
  (`ingest/mistral.py:108-117`, `ingest/router.py:186-215`). À surveiller en
  comptant les documents en échec d'OCR.
- **E-03** — Mineur : un bon resté « reçu » (traitement interrompu pendant
  l'OCR) ne peut pas être relancé depuis l'écran
  (`ingest/corrections.py:1167-1169`) ; le cas est rare (un déploiement pendant
  une lecture).
- **E-04** — Mineur, latent (Drive non planifié) : une seule transaction garde
  des verrous de lignes pendant tous les envois (`jobs/drive_sync.py:84-176`) ;
  à corriger, ou limiter à 10 documents par passage, avant de poser la tâche.
- **F-01** — Mineur : la rotation des sauvegardes ne supprime rien (le chemin du
  dump et le nom d'hôte changent à chaque passage, `deploy/backup.sh:57-145`) ;
  la rétention de 30 jours et 12 mois promise n'est pas tenue, impact disque
  faible.

### Autres mineurs (NV)

- **A-03** — Sessions : jetons stockés en clair (donc présents dans les
  sauvegardes), jamais purgés, expiration glissante sans plafond absolu
  (`ingest/models.py:712`, `core/auth.py:231-235`).
- **A-04** — Aucune trace des connexions ni des échecs de connexion
  (`core/auth.py:256-291`).
- **A-05** — Fichiers et réponses de l'API sans `Cache-Control` restrictif
  (`api/documents.py:143-149`, `api/factures.py:184`, `deploy/nginx/habitat.conf:40-51`).
- **A-06** — Webhook Telegram : un en-tête de secret non ASCII provoque une
  erreur 500 non authentifiée (`messaging/telegram.py:141-149`).
- **A-07** — Traefik : socket Docker monté en lecture seule
  (`deploy/docker-compose.yml:21`) ; sans objet tant que Traefik est désactivé.
- **B-10** — Export CSV détaillé : prix unitaire arrondi à 2 décimales et
  anomalies de bloc comptées sur chaque ligne (`ingest/export.py:270-297`,
  `ingest/bilan.py:1372-1385`).
- **B-11** — Correspondance de produit : une désignation de grille courte
  (sous-ensemble de mots) peut l'emporter sur la désignation exacte
  (`normalize/prix.py:84-135`).
- **B-12** — R09 : le critère « au moins 3 occurrences » ne tient pas compte de
  la proportion (règle désactivée) (`ingest/rapprochement.py:270-290`,
  `rules/rules/R09.py:45`).
- **C-05** — Une facture et un BL du même fournisseur partagent l'unicité du
  numéro ; un numéro identique donne une erreur 500 au dépôt de la facture
  (`ingest/models.py:273`, `ingest/factures.py:297-311,495-503`).
- **C-06** — Aucun index sur les clés étrangères ni sur `journal`
  (`migrations/versions/0001_schema_initial.py`) ; sans effet au volume actuel.
- **C-07** — Liste Documents limitée aux 100 derniers bons, sans pagination
  (`ingest/lecture.py:520-522,592-593`, `web/src/api/documents.ts:19`).
- **C-09** — Tables qui ne font que grossir, sans purge : `jeton_session`,
  `telegram_update`, `appel_ia`, `journal`, `prix_internet`
  (`ingest/models.py:610-841`).
- **D-04** — Page blanche si `GET /api/moi` échoue autrement que par un 401
  (`web/src/routes/RouteProtegee.tsx:27-33`).
- **D-05** — Invalidations TanStack incomplètes : alertes de prix après une
  saisie de grille ou un changement de réglage
  (`web/src/api/invalidations.ts:29-38`).
- **D-06** — « Article à valider » : jargon (unités, ratio) et validation à vide
  possible (`web/src/pages/ProblemeDetail.tsx:911-950`).
- **D-07** — Restes de règles métier dans le front : état d'une livraison
  (sera traité avec le groupe 3 de corrections), seuil de confiance faible
  (`web/src/components/TableauLivraisons.tsx:47-55`, `web/src/pages/DocumentDetail.tsx:100-104`).
- **D-08** — « Valider » un bon avec des lignes modifiées mais non enregistrées :
  le serveur valide les anciennes valeurs (`web/src/pages/DocumentDetail.tsx:1194-1211`).
- **D-09** — Champs d'édition des lignes à environ 34 px de haut sur téléphone,
  sous la cible de 44 px (`web/src/pages/DocumentDetail.tsx:617,672-715`).
- **D-10** — Prix unitaires affichés avec deux décimales seulement
  (`web/src/lib/formats.ts:83-91`).
- **E-05** — Drive bloqué : une notification Telegram par document, sans limite
  de débit, puis perdue (`jobs/drive_sync.py:151-186`).
- **E-06** — Synthèse IA : le texte libre des commentaires et le libellé d'une
  ligne partent tels quels chez le fournisseur d'IA ; la promesse « jamais de
  nom de chantier ni de client » ne tient que pour les champs structurés
  (`ingest/ia_synthese.py:147-177`). À faire connaître aux employés ou à
  filtrer ; à inscrire au registre des traitements.
- **E-07** — Facture et photo : l'OCR est appelé avant la détection d'un
  doublon (`ingest/factures.py:346-362`, `ingest/depot_telegram.py:508-521`).
- **E-08** — Telegram : ni reprise sur 429 ou erreur réseau, ni limite de 4096
  caractères, ni sonde de santé du webhook (`messaging/telegram.py:433-502`).
- **E-09** — Webhook : l'update est marqué « vu » avant les contrôles suivants ;
  une panne de base ensuite perd le message (`ingest/router.py:178-184`).
- **E-10** — Prix internet : la garde « prix présent dans la page » ne rattache
  pas le prix au produit demandé (`extract/reponses_ia.py:742-835`) ; le prix
  reste indicatif, avec sa source.
- **E-11** — Suppression de session OpenCode : délai jusqu'à 300 s ajouté après
  un délai déjà dépassé (`ingest/opencode.py:566-570`).
- **F-05** — Déployer avec la procédure du §4 sans la surcouche IA fait perdre
  l'IA à l'API sans message (`docs/deploiement-octobre-2026.md:108-158`).
- **F-06** — Aucune limite de mémoire sur `api` et `postgres`, journaux Docker
  non fixés dans le compose (`deploy/docker-compose.yml:30-36,124-140`).
- **F-07** — `/health` et le démarrage ne vérifient pas que le schéma est à la
  dernière révision (`app/main.py:68-75`).
- **F-08** — Après un arrêt, production et démo rattrapent leurs tâches en même
  temps (`deploy/installer-taches.sh:76-96,204-205`).
- **F-09** — Alerte d'échec fragile : lecture du fichier d'environnement sans
  guillemets, aucun secours si Telegram est injoignable ou si le bot de la démo
  est invalide (`deploy/alerte-echec.sh:23-38`).
- **F-10** — `tests/test_frontieres.py` ne couvre pas toutes les règles de
  frontière de `CLAUDE.md` (`tests/test_frontieres.py:46-54,171-199`).
- **F-11** — Aucune intégration continue : les fusions GitHub ne passent par
  aucun contrôle en ligne (`.github/` absent ; les hooks locaux en tiennent
  lieu).

### Constatés pendant l'exploitation du 28/09/2026

- **Supervision Telegram supprimée** : le canal de supervision a été supprimé
  par Ilane le 28/09 ; décision : aucune supervision pour l'instant. Les
  messages « expéditeur non rattaché », « échec du dépôt », « Document n° … »
  et les alertes d'échec des minuteries ne se retrouvent que dans les journaux
  (`docker compose … logs api`, `journalctl --user -u habitat-prod-*`). Pour la
  rétablir : Ilane démarre une conversation privée avec le bot et renseigne son
  identifiant dans `TELEGRAM_CHAT_SUPERVISION_ID` de `.env.prod`, puis recrée
  l'API.
- **Bot Telegram de la démo invalide** (jeton refusé par Telegram) : la démo ne
  reçoit aucun dépôt.

## Recherche à la demande et contestations de prix (01/10/2026)

Branche `feature/prix-contestations-recherche`, non fusionnée ; déployée sur la démo le 01/10/2026, pas en production.
Spécification : `docs/superpowers/specs/2026-10-01-prix-recherche-et-contestations-design.md`.

- **État des recherches en mémoire.** Les recherches de prix internet lancées
  par le bouton sont suivies dans un registre en mémoire du processus
  (`ingest/ia_prix.py`, `_RECHERCHES`). Un redémarrage de l'API l'efface : une
  recherche en cours est perdue (la cellule revient à son bouton) et un message
  d'échec disparaît. Un échec n'est gardé que 15 minutes, et un état « en
  cours » expire lui aussi après 15 minutes. Le registre suppose
  **une seule instance d'API** ; avec deux, le « déjà en cours » ne serait plus
  garanti. Même choix que le Laboratoire IA. Ce que cela ne couvre pas : la
  reprise après redémarrage, plusieurs instances.
- **Un seul identifiant par rangée de la page Prix.** Le bouton, la lecture
  groupée et l'affichage utilisent le premier identifiant d'alerte de la rangée
  (`anomalie_ids[0]`) : le serveur place en tête les alertes de la ligne la
  plus récente (celle dont viennent le nom et le prix affichés), triées par
  règle puis identifiant, donc le choix est stable et correspond à la ligne
  montrée. Si les alertes d'une même rangée portent des produits différents
  (clés de produit différentes), seule celle de la ligne la plus récente est
  cherchée et affichée.
- **Regroupement des contestations dans la synthèse par la clé du bon.** Les
  références `[pN]` regroupent par clé de produit telle que le bon la donne :
  un même produit de grille retrouvé une fois par référence (`ref:…`) et une
  fois par le nom (bon sans code, `nom:…`) peut donc former deux groupes. Sur
  l'écran de la grille, en revanche, la contestation est rattachée à la
  rangée du produit par sa désignation de grille.
- **Relancer la lecture d'un bon supprime ses contestations.** La relecture
  supprime les lignes du bon (`extraction_bl.py`) et les anomalies suivent
  (suppression en cascade) : la contestation disparaît de la grille et de la
  synthèse, et l'alerte revient « ouverte » au contrôle suivant. Le journal
  garde la trace. Comportement antérieur à cette branche, non corrigé.
- **Une contestation n'est ni modifiable ni annulable.** « Contester » ferme
  les alertes de façon définitive (une alerte fermée n'est jamais rouverte).
  L'écran de la grille et la synthèse ne font que les lire ; il n'y a aucun
  moyen de corriger un commentaire ou de retirer une contestation faite par
  erreur.
- **Les prix « ignorés » ne sont visibles nulle part hors du journal**
  (décision D4 d'Ilane : contestations seulement). Ni la grille du fournisseur
  ni la synthèse de la semaine ne les montrent.
- **Le prix de grille d'une contestation est la valeur au moment du
  contrôle.** Il vient du détail de l'alerte, pas de la grille actuelle : si la
  grille change ensuite, la contestation garde l'ancien prix. L'indication
  « absent de la grille » dit seulement si le produit est dans la grille
  maintenant.
- **Pas de tests automatiques du front.** Les écrans (bouton, « Recherche en
  cours… », dépliage des contestations, section, compteur de la carte) sont
  vérifiés par `tsc`, `vite build`, des gardes sur le texte du source
  (`tests/test_web_*.py`) et un contrôle visuel, pas par un test de
  comportement.
- **Au-delà de 500 contestations** pour un fournisseur, les plus anciennes ne
  sont pas listées ; la synthèse ne reçoit que 50 entrées (les plus récentes),
  avec une phrase de troncature.

## Comptes créés au premier envoi Telegram (02/10/2026)

Décision d'Ilane du 02/10/2026 (un employé sans compte avait envoyé un bon le
matin même : refusé sans que personne ne le sache, le groupe de supervision
ayant été supprimé le 28/09). Le premier envoi d'un employé inconnu dans le
groupe des bons crée son compte (`depot_telegram.rattacher_ou_creer_deposant`) ;
un compte désactivé reste refusé, avec une réponse dans le groupe.

- Toute personne ajoutée au groupe des bons peut déposer : le groupe tient lieu
  de liste blanche. Les autres groupes restent ignorés.
- Le compte créé n'a ni mot de passe ni agence, et une adresse technique
  `telegram-<id>@telegram.invalid` : à compléter dans « Comptes » si
  l'employé doit se connecter au site.
- Son nom est le nom Telegram (prénom et nom, sinon pseudo) : à corriger dans
  « Comptes » s'il est fantaisiste.
- `TELEGRAM_CHAT_SUPERVISION_ID` de la production désigne toujours un groupe
  supprimé : les messages de supervision échouent (journalisés), à remplacer
  par un groupe existant (`.env.prod`, puis redémarrage de l'API).


## Connexions gardées pendant les tâches de fond (07/10/2026)

Incident en production le 07/10/2026 : 16 photos envoyées d'un coup, 3 perdues
(`TimeoutError` à l'enregistrement, `/health` à 503 pendant 30 s). Cause :
FastAPI (0.141) ne ferme la session d'une dépendance `yield` (`get_session`)
qu'**après** les tâches de fond ; la transaction ouverte par la recherche de
l'expéditeur gardait donc sa connexion pendant toute la lecture du bon, et le
pool (15 connexions) était épuisé. Corrigé dans le webhook Telegram et dans la
recherche de prix à la demande (`await session.commit()` avant la tâche de
fond), avec un test qui reproduit l'incident sur un pool réduit.

**Règle** : toute nouvelle route qui lance une tâche de fond doit rendre la
connexion de sa session (commit ou rollback) avant de la planifier.

En plus, à la demande d'Ilane : pool agrandi (10 connexions + 10 de
débordement par instance, 60 s d'attente, `app.core.db.creer_engine`) et
nouvelle tentative à l'enregistrement d'un bon reçu par Telegram (3 essais,
pauses de 2 puis 5 s), seulement quand aucune connexion ne s'est libérée à
temps — rien n'a alors été écrit, donc pas de doublon possible. Non couvert :
une coupure de la base pendant l'écriture elle-même n'est pas retentée (risque
de doublon), le bon reste à renvoyer comme avant.
