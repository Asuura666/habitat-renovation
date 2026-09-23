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

- **Synchronisation Google Drive non validée sur un Drive réel.** Le client
  Google, les deux modes d'envoi et l'orchestration sont couverts par des
  doubles de test sans réseau, mais aucun compte de service ni dossier cible
  autorisé n'a été fourni (Q1). La CLI refuse correctement de démarrer sans
  configuration (code 2 et message clair). Ne couvre pas une recette réelle
  des permissions, de l'arborescence, des `appProperties` d'identité, des
  quotas, des sessions résumables ni de la reprise après une panne Google ; à
  faire dès réception des accès selon
  `docs/exploitation-lot-5.md`, sans jamais versionner le JSON du compte.
- **Notification Drive au plus une fois, donc potentiellement perdue.** Après
  24 h d'échec, la réservation de l'alerte est commitée avant l'appel Telegram
  afin d'éviter les doublons. Si l'appel Telegram échoue après cette
  réservation, l'alerte n'est pas retentée. Ce compromis at-most-once est
  explicite dans `docs/exploitation-lot-5.md`; à remplacer par une boîte
  d'envoi persistante seulement si des pertes sont observées ou si la garantie
  devient contractuelle.
- **Crons des lots 4 et 5 non posés tant que rien n'est déployé.** Les lignes
  pour `controles-differes` (lot 4) et `drive-sync` (lot 5) sont documentées,
  mais ne doivent être installées qu'après déploiement des commandes et
  application des migrations sur le conteneur cible. À faire au déploiement,
  avec `flock`, rotation des logs et supervision des codes de sortie.

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
