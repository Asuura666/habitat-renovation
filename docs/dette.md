# Dette technique

Ce fichier liste les simplifications assumées (solution plus simple que
l'idéal, avec ce qu'elle ne couvre pas) au fil des tâches ; il ne contient
aucune entrée tant qu'aucune simplification n'a été prise.

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
  s'avère fréquent en usage réel (hors lot 1).
- **Fichiers de plus de 20 Mo non téléchargeables.** La Bot API Telegram
  refuse de fournir le chemin de téléchargement (`getFile`) pour un fichier
  de plus de 20 Mo : `TelegramClient.telecharger` lèverait alors
  `ErreurTelegram` (comportement normal, pas un bug), mais rien
  n'avertit l'expéditeur qu'une photo/PDF trop volumineux n'a pas pu être
  récupéré autrement que par l'absence de réponse « reçu ». Ne couvre pas
  un message d'erreur explicite à l'utilisateur ni une compression côté
  bot ; à revoir si ce cas se présente en usage réel.
- **Bot ouvert à tout expéditeur jusqu'au lot 2.** Décision D15 du brief T6 :
  aucune whitelist au lot 1, tout expéditeur Telegram peut déposer un
  document (`deposant_id` rempli seulement si `telegram_user_id` correspond
  à un `utilisateur` existant, sinon `NULL`). Ne couvre pas le rejet des
  expéditeurs non autorisés ; la whitelist arrive au lot 2.
- **Photo compressée non marquée en base.** `FichierEntrant.compresse`
  distingue une photo Telegram compressée (`photo[]`) d'un envoi « en
  fichier » (document non compressé), mais aucune colonne de la section 6
  du CDC ne permet de conserver cette information : `traiter_fichier`
  l'utilise seulement pour le comportement de téléchargement, elle est
  perdue dès l'insertion du `document`. Ne couvre pas la traçabilité a
  posteriori de « cette photo était compressée » (utile pour juger de la
  qualité d'une image avant OCR) ; à ajouter par migration si ce besoin
  apparaît (lot 2/3).

## T6b — extract/ingest (détection du numéro de BL sur photo, OCR Mistral minimal)

- **Pas de nouvelle tentative automatique après un échec d'OCR.** Si l'appel
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
