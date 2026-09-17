# Protocole de mesure du taux d'erreur OCR (lot 3, L3-T11)

Ce document décrit comment produire le livrable du lot 3 exigé par le
cahier des charges (§10) : un rapport de taux d'erreur OCR sur au moins 30
photos réelles de bons de livraison, dont au moins 10 dégradées. L'outil de
mesure (`app.modules.ingest.rapport_ocr`, commande `rapport-ocr`) est prêt
dès L3-T11 ; ce protocole reste bloqué (constat 1/Q2 du plan du lot 3) tant
que les photos et leurs valeurs attendues ne sont pas réunies. Une fois
réunies, produire le rapport est **une seule commande** (§5).

Objectifs du CDC §10, rappelés dans le rapport lui-même :

| Critère | Objectif |
| --- | --- |
| Documents avec les 4 champs (numéro, fournisseur, date, chantier brut) justes | ≥ 95 % |
| Lignes (code, quantité) justes | ≥ 90 % |
| Erreurs silencieuses (erreur non signalée par un motif « à vérifier ») | 0 |

## 1. Choix des 30 photos

- Au moins **30 photos** de bons de livraison réels, des deux fournisseurs
  (Unikalo et Point.P) si possible, de plusieurs chantiers et de plusieurs
  agences — pas 30 photos du même bon.
- Au moins **10 dégradées** parmi les 30 : froissées, mal cadrées (bord du
  document hors du cadre, tableau ou total coupé), annotées à la main
  (ratures, mentions manuscrites), mal éclairées ou floues. Une photo
  dégradée n'est pas mise de côté : elle mesure le comportement de l'outil
  dans le pire cas réel (CDC §10, « aucune erreur silencieuse » y compris
  sur un document illisible).
- Éviter les doublons volontaires du même bon (sauf si le lot en contient
  réellement, auquel cas les deux photos sont mesurées : le doublon de
  numéro est un motif à part, `NUMERO_EN_DOUBLE`, non couvert par cet outil
  qui compare seulement l'OCR à l'attendu — voir §6).

## 2. Nommage et emplacement

- Chaque photo et son fichier attendu partagent le même nom de base :
  `<nom>.<extension>` (`.jpg`, `.jpeg`, `.png`, `.webp`, `.heic` ou `.pdf`)
  et `<nom>.attendu.json`. Exemple : `bl-042.jpg` + `bl-042.attendu.json`.
- `<nom>` est un identifiant neutre (ex. `bl-001`, `bl-002`, …) — **jamais**
  un numéro de BL réel, un nom de chantier ou un nom de fournisseur : ce nom
  apparaît tel quel dans le rapport Markdown (§4), lui-même destiné au
  client mais qui peut circuler plus largement.
- Tous les fichiers (photos, `.attendu.json`, caches `.mistral-ocr.json`)
  vivent dans `tests/fixtures/bl/` — **jamais commités** (`.gitignore` du
  dépôt couvre déjà `tests/fixtures/`). Ce sont des documents d'un client
  réel : ils ne sortent jamais du disque du VPS, ne sont jamais copiés dans
  un message, un commit ou un journal applicatif (CLAUDE.md).

## 3. Format de `<nom>.attendu.json`

Valeurs lues à la main sur la photo, exactement telles qu'elles doivent
être comparées (pas de mise en forme spéciale : dates en ISO, quantités et
`total_ht` en chaînes décimales à point). Exemple **entièrement inventé**
(à ne jamais recopier tel quel, seul le format fait foi) :

```json
{
  "numero": "L209900000123",
  "fournisseur": "Peintures Exemple",
  "date_doc": "2026-09-03",
  "chantier_brut": "MAISON TEST (9900000001)",
  "total_ht": "161.50",
  "degradee": true,
  "lignes": [
    {"code": "AB1234", "quantite": "100"},
    {"code": null, "quantite": "10"}
  ]
}
```

Règles :

- Clés obligatoires : `numero`, `fournisseur`, `date_doc`, `chantier_brut`,
  `lignes`, `degradee`. Une clé manquante ou mal typée fait échouer la
  lecture de ce fichier (`ValueError`, remonté par la commande avec le nom
  du fichier en cause).
- `date_doc` : format ISO (`AAAA-MM-JJ`), quel que soit le format imprimé
  sur la photo (y compris une date en toutes lettres).
- `total_ht` : **facultatif**, ignoré par la comparaison actuelle (clé
  inconnue jamais une erreur) — à renseigner quand même si disponible, pour
  une éventuelle mesure future du total.
- `degradee` : `true` si la photo correspond à l'un des cas du §1
  (froissée, mal cadrée, annotée, floue…), `false` sinon.
- `lignes` : une entrée par ligne d'article ou d'éco-participation
  effectivement imprimée sur le bon, dans l'ordre d'impression. `code` peut
  être `null` (ligne d'éco-participation sans code article) ; `quantite`
  est la quantité facturée (celle qui multiplie le prix unitaire), jamais
  le nombre de conditionnements quand les deux sont imprimés séparément
  (colonnes UNITE/QUANTITE chez Unikalo, voir `docs/dette.md`/plan lot 3,
  décision L3-D24).
- Une ligne attendue à `code: null` s'apparie, à la mesure, à la première
  ligne lue par l'OCR dont le code est lui aussi absent — remplir dans le
  même ordre que l'impression si plusieurs lignes sans code existent sur le
  même bon.

## 4. Déroulé de la collecte

1. Rassembler les photos dans `tests/fixtures/bl/` avec leur nommage (§2).
2. Pour chaque photo, écrire son `<nom>.attendu.json` (§3) en lisant la
   photo à l'œil — jamais en recopiant une sortie de l'outil (cela
   invaliderait la mesure).
3. Ne **jamais** lancer la commande sur une partie seulement des photos
   pour « corriger » l'attendu après coup : le rapport doit refléter la
   première lecture humaine du lot complet.

## 5. Lancer la mesure

Premier passage, avec appel réel à l'API Mistral OCR (une seule fois par
photo : la réponse est mise en cache dans `<nom>.mistral-ocr.json`, à côté
de la photo) :

```bash
uv run python -m app.cli rapport-ocr tests/fixtures/bl --sortie tests/fixtures/bl/rapport.md --appeler-ocr
```

Relances suivantes (après correction d'un `<nom>.attendu.json`, ou pour
essayer un autre seuil de confiance) : le cache déjà écrit est réutilisé,
aucun nouvel appel réseau n'est fait, donc **sans** `--appeler-ocr` :

```bash
uv run python -m app.cli rapport-ocr tests/fixtures/bl --sortie tests/fixtures/bl/rapport.md
```

La sortie standard n'affiche que des comptes et des taux (jamais une valeur
lue ou attendue) :

```
30 documents mesurés (10 dégradés)
  champ numero juste : 0.9667
  champ fournisseur juste : 1.0000
  champ date_doc juste : 0.9333
  champ chantier_brut juste : 0.9667
  documents 4 champs justes : 0.9000
  lignes justes : 0.9200
  erreurs silencieuses : 0
rapport écrit : tests/fixtures/bl/rapport.md
```

Codes de sortie : `2` si le dossier n'existe pas ou ne contient aucune
photo appariée à un `<nom>.attendu.json` (rien n'est écrit dans
`--sortie`) ; `0` sinon, rapport écrit.

Pour ajouter une photo supplémentaire à un lot déjà mesuré : déposer la
photo et son `<nom>.attendu.json`, relancer avec `--appeler-ocr` (seule la
photo sans cache déclenche un appel) ; les photos déjà en cache ne sont pas
rappelées.

## 6. Lire le rapport

Le rapport Markdown (`--sortie`) contient, dans l'ordre :

1. **Synthèse** : les quatre critères du CDC (tableau en tête de ce
   document) avec la valeur mesurée et si l'objectif est atteint.
2. **Détail par document** : nom, dégradée ou non, champs faux, lignes
   justes/total, motifs `verifier_bl` posés (`champ_absent`,
   `confiance_faible`, `somme_incoherente`, `total_absent`,
   `lignes_absentes`, `numero_incoherent`, `annotation_illisible`) et si le
   document est une **erreur silencieuse** (une valeur fausse alors
   qu'aucun motif ne l'a signalée — le point que le CDC interdit à 100 %).
   S'il reste des erreurs silencieuses, regarder d'abord les lignes du
   tableau où `Silencieuse = oui` : elles indiquent un cas que
   `extract/verification.py` ne détecte pas encore (ex. un chantier faux
   lu avec une confiance élevée — aucune règle actuelle ne compare un
   chantier à un référentiel, seule sa présence/confiance compte).
3. **Lignes fausses à confiance haute** : une ligne dont la quantité ou le
   code sont faux mais dont la confiance OCR est **supérieure ou égale au
   seuil utilisé pour la mesure** (`SEUIL_CONFIANCE_DEFAUT`, 0,80 par
   défaut, L3-D4). Une entrée ici signale un cas où le seuil actuel
   n'aurait pas mis le document « à vérifier » alors que la valeur est
   fausse : chaque entrée doit être regardée à l'œil (rouvrir la photo) et
   documentée (nouveau motif nécessaire ? seuil à remonter ? erreur
   d'annotation ponctuelle sans mise en cause du seuil ?).
4. **Distribution des confiances** (min, médiane, max) des valeurs justes
   et des valeurs fausses, séparément. Sert à recaler le seuil (Q3 du plan
   du lot 3, provisoire à 0,80) : si les confiances des valeurs **fausses**
   chevauchent largement celles des valeurs **justes**, le seuil ne sépare
   pas bien les deux populations et doit être discuté avec Ilane avant
   d'être changé (`parametre.seuil_confiance_ocr`, écran de paramétrage au
   lot 5 ; en CLI en attendant : `fournisseur-definir` ne le touche pas,
   voir `ingest/referentiels.py::lire_parametre_decimal`).

Le rapport peut contenir des valeurs attendues et lues (numéros, noms de
chantier…) : c'est voulu, il est destiné au client. Ne jamais le coller
dans un message, un ticket ou une conversation qui sort du binôme
contrôleur/Ilane sans réflexion préalable (mêmes précautions que pour les
photos elles-mêmes).

## 7. Ce que cet outil ne mesure pas

- **Le doublon de numéro** (`NUMERO_EN_DOUBLE`) et **le fournisseur
  inconnu** (`FOURNISSEUR_INCONNU`) : ces deux motifs sont posés par
  `ingest.extraction_bl` après résolution du référentiel fournisseur (en
  base), hors de portée d'une comparaison purement OCR. Le commentaire du
  champ `motifs` de `ComparaisonBL` le rappelle dans le code.
- **Le parseur de facture Point.P** : aucun document Point.P n'était
  disponible à l'écriture de L3-T11 (L3-D23) ; cet outil ne mesure que les
  bons de livraison/enlèvement, jamais une facture.
- **Un vrai dépôt Telegram** : cet outil appelle l'OCR Mistral directement
  sur le fichier, il ne passe jamais par le bot ni par la base — il mesure
  la qualité de l'extraction, pas le chemin de dépôt.
