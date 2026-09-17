# Recette du lot 3 (Extraction) — Contrôle BL & factures

Branche `lot-3-extraction` (dépôt `/home/debian/habitat_reno`), avec un flux
pur (`extract`/`normalize`/`verification`, plus `L3-T7` et cette recette)
mené dans l'arbre séparé `/home/debian/habitat_reno-wt-l3` (branche
`lot-3-pur`) et intégré par cherry-pick. Tâches L3-T0 à L3-T12. Aucune
donnée réelle (numéro, chantier, montant, nom, SIRET/TVA, contenu de
fichier client) dans ce document : comptes et taux uniquement, comme
`docs/lot-1-recette.md` et `docs/lot-2-recette.md`. **Rien n'est fusionné
dans `main`** : le lot reste sur sa branche, comme le lot 2 avant sa fusion
du 17/09.

## À lire d'abord (Ilane)

- **Ce qui est fait** : extraction d'un BL/enlèvement depuis l'annotation
  structurée Mistral OCR (fournisseur, numéro, date, chantier brut,
  lignes), calcul de confiance par champ à partir des scores OCR par mot,
  contrôle de cohérence déterministe (motifs « à vérifier »), résolution du
  fournisseur/agence/chantier/article, migration de schéma, écran
  « À traiter » (admin), détail/correction/validation/archivage/relance
  d'un document, contrôle et normalisation des factures déposées (motifs,
  confiance réduite, alias, articles), outil de mesure du taux d'erreur OCR
  (`rapport-ocr`). Détail tâche par tâche en §1, décisions en §2.
- **Ce qui est bloqué, et pourquoi (constat 1 du plan)** : au 17/09/2026,
  **4 photos réelles** de BL sont disponibles (3 Unikalo de deux agences, 1
  bon d'enlèvement Point.P), contre **30 dont 10 dégradées** exigées par le
  CDC §10 pour mesurer le livrable du lot. Conséquence directe :
  - le **rapport de taux d'erreur OCR exigé par le CDC §10 n'est pas
    mesuré** — seule une mesure sur les 4 photos disponibles existe (§4),
    un échantillon bien trop petit pour conclure ;
  - le **parseur de facture Point.P n'est pas construit** (L3-D23) : aucun
    document Point.P (facture) n'est disponible, seul un bon d'enlèvement
    a pu être testé (il passe par la même extraction qu'un BL).
  - La marche à suivre exacte dès réception des fichiers est dans
    `docs/protocole-mesure-ocr.md` (§4 ci-dessous).
- **Décisions à valider par Ilane** (détail en §2) :
  - **Q1** — extraction d'un BL par l'annotation structurée Mistral plutôt
    qu'un parseur déterministe par fournisseur (L3-D1), faute d'exemple de
    BL au moment de la décision ;
  - **Q3** — champs obligatoires (fournisseur, numéro, date, chantier brut)
    et seuil de confiance provisoire à 0,80 (L3-D4), à recaler sur les 30
    photos une fois disponibles ;
  - **Q4** — pas de validation forcée d'un document dont le BL imprimé
    lui-même est incohérent : l'admin doit corriger une valeur (L3-D14) ;
  - **Q5** — pas de correction d'une facture scannée à l'écran ce lot-ci
    (L3-D17), le CDC supposant des PDF natifs ;
  - **Q6** — pas de fusion de BL sur deux pages ce lot-ci (L3-D11) : un
    doublon de numéro met le second document « à vérifier », archivable
    manuellement ;
  - **Q7** — une agence fournisseur n'est jamais créée depuis le texte OCR,
    seulement rattachée si elle existe déjà (L3-D8), créée par la CLI.
- **Tests réels non faits** : Telegram de bout en bout (aucun bot ni
  groupe réel, hérité du lot 2 — jamais un BL n'a été déposé par le vrai
  webhook avec un vrai appel Mistral, voir §3) ; sauvegarde/restauration
  (non rejouée depuis le lot 1, aucune colonne de la migration 0005 n'a été
  vérifiée dans un cycle backup/restore réel) ; navigateur sur un appareil
  mobile réel (seule une émulation Chromium/Playwright à 375 px a été
  utilisée, jamais un téléphone).
- **Point à vérifier en premier par la prochaine session** : la revue de
  **L3-T10** a relevé un point Important (état d'édition du détail document
  non réinitialisé après une écriture réussie — risque de réinsertion de
  lignes à un second enregistrement, trace de la valeur OCR d'un champ
  corrigé invisible jusqu'au rechargement) et un tour de correction a été
  dispatché sur la branche `lot-3-extraction` (base `9fe112e`, implémenteur
  repris) **au moment de la rédaction de cette recette, sans qu'aucun
  résultat n'ait encore été consigné dans `progress.md` ni commité**. Cette
  recette décrit donc L3-T10 comme *Needs fixes, correction en cours* —
  relire `progress.md` (fin de fichier) et `git log lot-3-extraction` pour
  voir si un commit a été ajouté après `9fe112e`, et mettre à jour cette
  recette et `docs/passation-lot-3.md` en conséquence avant de considérer le
  lot clos.

## 1. Ce qui est fait

| Tâche | Commit(s) | Résultat de revue (`progress.md`) |
| --- | --- | --- |
| L3-T0 | `dee4ace` | `core: contrôle d'origine derrière proxy et en dev Vite`. Revue → spec ✅, **Approved** (trailer vérifié, vérification manuelle acceptée). 2 minor (deferred). Complete. |
| L3-T1 | `e7df9d8` (flux pur `496444c`) + correction `38c7dd7` (`a11456d`) | `extract: confiance d'une valeur à partir des scores OCR par mot` + `extract: confiances non finies ignorées`. Revue → 1 Important (confiances `NaN`/`Infinity` faisaient lever une exception au lieu d'être ignorées, contrat rompu), corrigé. Re-revue → 1 addressed, 0 open. 2 minor (deferred). Complete. |
| L3-T2 | `90fbdbd` (`269d4bb`) | `extract: lecture d'un BL depuis l'annotation Mistral`. Revue → spec ✅, **Approved** (trailer vérifié). 2 minor (deferred). Complete. |
| L3-T3 | `bd4183f` (`5d7f94d`) + correction `cbec517` (`1fc0640`) | `extract: vérification d'un BL et d'une facture` + `extract: motif JSON non objet refusé et test de facture réelle sans valeur`. Revue → 2 Important (`motif_depuis_json` levait `TypeError` au lieu de `ValueError` sur une entrée non objet ; un test sur fixture réelle aurait pu afficher une valeur client à l'échec — Ruling R7, la confidentialité prime sur la formulation littérale de la fiche). Re-revue → 2 addressed, 0 open. 2 minor (deferred). Complete. |
| L3-T4 | `709d4c6` + correction `c884293` | `normalize: fournisseur, chantier, unités et article` + `normalize: test de résolution par alias et préfixe chantier borné`. Revue → 2 Important (le test « résolution par alias » passait en fait par le nom, l'alias n'était jamais exercé ; le préfixe « chantier » retiré sans borne de mot corrompait la clé d'alias — Ruling R4, ex. « Chantiers Réunis » → « s reunis »). Re-revue → 2 addressed, 0 open. 2 minor (deferred). Complete. |
| L3-T5 | `234e3c1` + correction `79da97d` | `ingest: migration 0005 et résolution des référentiels` + `ingest: journal de la définition d'un fournisseur`. Implémenteur DONE_WITH_CONCERNS (ajout non demandé de `definir_fournisseur`, accepté comme conforme à l'architecture). Revue → 1 Important plan-mandated (`fournisseur-definir` sans entrée de journal, contrairement à `utilisateur-creer`), corrigé. Re-revue → 1 addressed, 0 open. 2 minor (deferred). Complete. |
| L3-T6 | `57caa70` + correction `35d1cd2` | `ingest: extraction complète des BL déposés` + `ingest: doublon de numéro concurrent et ligne de supervision testée`. Implémenteur DONE_WITH_CONCERNS (TDD non strictement RED d'abord, déclaré honnêtement). Revue → 3 Important (TDD — Ruling R10, preuve par mutations délibérées ; aucun test de la ligne de supervision avec fournisseur/chantier résolus ; doublon de numéro concurrent non sûr en course → `IntegrityError` brute au lieu du motif `numero_en_double`). Re-revue → 3 addressed, 0 open. 2 minor (deferred). Complete. |
| L3-T6b | `0703557` + correction `7065a56` | `extract: extraction ajustée aux premiers BL réels` + `extract: montants suivis du symbole euro`. Revue → spec ✅, **Approved**. 2 minor (deferred : couverture des mois inégale ; quantité de conditionnements Point.P sans effet observable). Fix round 1 : gap confirmé par le contrôleur en ré-exécutant l'OCR réel sur les photos client (un total imprimé avec « € » était refusé par `nombre_bl`). Re-revue → 1 addressed, 0 open. Complete. |
| L3-T7 | `8066b36` (`d640d1c`, flux pur) | `ingest: contrôle et normalisation des factures déposées`. Implémenteur DONE_WITH_CONCERNS (TDD vérifié après coup par `git stash`/`stash pop`, RED→GREEN réel mais tardif). Revue → spec ✅, **Approved** ; 1 Important de procédure (même défaut TDD) **parké** (Ruling R12 : la preuve RED→GREEN par retrait du code est déjà dans le rapport, rien à corriger dans le code livré). 2 minor (deferred). Complete, 1 parked. |
| L3-T8a | `1036586` (`ed3ac7d`) + correction `db0a513` (`92ebd9c`) | `api: détail, correction et validation d'un BL` + `ingest: journal de relance préservé en cas de reprise`. Revue → 1 Important (le journal `extraction_relancee` était écrit avant l'appel à l'extraction, dans la même transaction ; une reprise sur doublon concurrent le faisait disparaître au rollback — Ruling R14). Re-revue → 1 addressed, 0 open. 2 minor (deferred). Complete. |
| L3-T8b | `45c6a2c` | `api: écran À traiter et référentiels`. Revue → spec ✅, **Approved**. 3 minor (deferred). Complete. |
| L3-T9 | `651d4a6` (`4d446c4`) + correction `9fe112e` (`9dc5690`) | `web: écran À traiter et navigation` + `web: lisibilité des motifs et échec partiel de rattachement`. Revue → 3 Important (confiance/seuil affichés en fraction brute type « 0.80 » ; numérotation de ligne 0-based « Ligne 0 » ; un échec de rattachement après création réussie d'un chantier laissait l'écran sans issue). L'implémenteur d'origine s'est épuisé en cours de correction (Ruling R15) ; repris par un implémenteur neuf qui a vérifié le travail déjà commité puis terminé. Re-revue → 3 addressed, 0 open. Complete (reprise indépendante confirmée sans second commit). |
| L3-T10 | `b572623` | `web: détail et correction d'un document`. Implémenteur DONE (typecheck/build, 828 passed dans l'arbre principal, 13 captures). **Revue → Needs fixes** : 1 Important (état d'édition non réinitialisé après une écriture réussie — réinsertion possible de lignes à un second enregistrement, trace OCR d'un champ corrigé invisible jusqu'au rechargement). **Fix round 1 dispatché (base `9fe112e`), résultat non connu au moment de la rédaction de cette recette — voir « À lire d'abord ».** |
| L3-T11 | `fd6eb5f` + correction `389512b` | `ingest: outil de mesure du taux d'erreur OCR` + `ingest: mesure OCR robuste aux fichiers invalides et seuil paramétrable`. Revue → 1 Important (aucune isolation par document : un seul fichier corrompu ou un échec réseau pendant `--appeler-ocr` faisait planter toute la commande, perte de toute la mesure) ; Ruling R13 (le §6 du protocole, sans chemin actionnable pour recaler le seuil, requalifié Important). Re-revue → 2 addressed, 0 open. 3 minor (deferred). Complete. |
| L3-T12 | (ce commit) | Cette recette, `docs/passation-lot-3.md`, `docs/dette.md` et `CLAUDE.md` mis à jour. |

## 2. Décisions prises en autonomie

### Décisions du plan (`docs/plan-lot-3.md` §4) — « À valider » = question posée à Ilane (§3 du plan, non bloquante)

| # | Décision (résumé) | Coût si faux | À valider |
| --- | --- | --- | --- |
| L3-D1 | Lecture d'un BL = un appel Mistral OCR (`table_format: markdown`, scores par mot, annotation structurée `SCHEMA_ANNOTATION_BL`) ; `extract/bl.py` convertit de façon déterministe | Écrire des parseurs déterministes par fournisseur sur les 30 photos | **Q1** |
| L3-D2 | Confiance d'une valeur = recherche du brut dans le texte OCR, bornée par des caractères non alphanumériques, minimum des mots couvrants, meilleure occurrence ; introuvable → confiance 0 ; ligne = valeurs cherchées dans une même ligne source | Recalage de l'algorithme sur les 30 photos | — |
| L3-D3 | Motifs « à vérifier » calculés par `extract/verification.py::verifier_bl` (champ absent, valeur illisible, confiance faible, somme incohérente, total absent, numéro incohérent) ; `ingest` ajoute échec OCR, annotation illisible, fournisseur inconnu, numéro en double | Motifs à ajuster | — |
| L3-D4 | Champs obligatoires d'un BL : fournisseur, numéro, date, chantier brut. Seuil de confiance par défaut 0,80, tolérance 0,05 € | Valeurs à changer en base | **Q3** |
| L3-D5 | Migration 0005 : `document` gagne `chantier_brut`, `chantier_id`, `numero_commande`, `enleve_par`, `total_tva`, `total_ttc`, `extraction` (jsonb), `motifs` (jsonb) ; `ligne` gagne `confiance` | Colonnes à retirer | — |
| L3-D6 | Clé d'alias chantier = `(fournisseur_id, libellé normalisé)`, `code_brut` toujours `NULL` (le code change d'une commande à l'autre, CDC §4.4) | Une migration de contrainte | — |
| L3-D7 | Alias inconnu → ligne `chantier_alias` avec `chantier_id NULL`, jamais créé tant que le fournisseur n'est pas résolu ; ne met pas le document « à vérifier » | — | — |
| L3-D8 | Fournisseur résolu par SIREN puis TVA puis nom (référentiel via CLI `fournisseur-definir`) ; agence rattachée seulement si elle existe déjà, jamais créée depuis l'OCR | Écran référentiel au lot 5 | **Q7** |
| L3-D9 | Article : clé `(fournisseur_id, code)`, créé automatiquement non validé ; ratio proposé si les deux quantités diffèrent ; jamais écrasé une fois validé | Liste « à valider » plus large | — |
| L3-D10 | Échec d'OCR ou annotation illisible → document `a_verifier` avec motif (plus jamais `recu` invisible sans numéro) | — | — |
| L3-D11 | Numéro déjà porté par un autre document du même fournisseur : numéro non écrit, motif `numero_en_double`, archivage manuel possible (pas de fusion construite ce lot-ci) | Fusion à construire | **Q6** |
| L3-D12 | Type du document : motif déterministe d'abord, sinon `type_bon` de l'annotation, sinon `bl` | — | — |
| L3-D13 | Corrections admin : `PATCH .../{{id}}` (en-tête), `PUT .../{{id}}/lignes` (liste complète) ; journal avant/après, valeur OCR d'origine conservée, ligne modifiée/ajoutée → confiance `NULL` | — | — |
| L3-D14 | « Valider » recalcule les motifs structurels ; aucun → `recu` ; sinon 409 avec les motifs. Pas de validation forcée | Ajouter une validation forcée commentée | **Q4** |
| L3-D15 | « Relancer l'extraction » : relit le fichier, rappelle l'OCR, remplace valeurs/lignes, reste `a_verifier` (seul « Valider » passe `recu`) | — | — |
| L3-D16 | Facture : OCR granularité page, `confiance_min` = plus petit score de page, « confiance réduite » = `ocr_brut IS NOT NULL`, somme des blocs vs total HT, chantier/article résolus comme un BL | — | — |
| L3-D17 | Pas de correction de facture à l'écran ce lot-ci ; une facture « à vérifier » apparaît dans « À traiter », renvoie vers son détail en lecture | Écran de correction de facture | **Q5** |
| L3-D18 | Écran « À traiter » réservé à l'admin : documents à vérifier (BL, enlèvements, factures), alias en attente, articles à valider | Ouvrir une vue agent | — |
| L3-D19 | Détail d'un BL ouvert à l'admin (tous) et à l'agent (ses dépôts, lecture seule) ; une facture y renvoie 404 | — | — |
| L3-D20 | Outil de mesure `rapport-ocr <dossier> --sortie <rapport.md> [--appeler-ocr]` ; taux par champ, taux de lignes, erreurs silencieuses, distribution des confiances | Le livrable du lot devient une commande dès que les photos arrivent | — |
| L3-D21 | L2-R10 corrigé côté dev : le proxy Vite réécrit `Origin` vers sa cible ; contrôle serveur inchangé (strict) ; test derrière un vrai proxy ajouté | Aucun affaiblissement en production | — |
| L3-D22 | `url_base_migrations` dérive le nom de la base de migrations de celui de la base de test (`<base>_migrations`) — permet à un second arbre de travail de tester en parallèle | — | — |
| L3-D23 | Parseur de facture Point.P **non construit** (aucun document disponible) ; les bons d'enlèvement Point.P passent par la même extraction qu'un BL | Tâche à ouvrir dès réception | — |
| L3-D24 | Lignes de BL à deux quantités : `ligne.qte_totale` = quantité facturée, `ligne.qte_livree` = nombre de conditionnements (même sens que la facture, pour la comparaison du lot 4) | Migration de données si le sens s'avère inverse | — |
| L3-D25 | Un BL sans `total_ht` lu → toujours `total_absent` ; sans aucune ligne → toujours `lignes_absentes` | Un bon réellement sans prix partirait « à vérifier » | — |
| L3-D26 | Consignes du schéma d'annotation précisées sur les cas réels (fournisseur = émetteur jamais le client, chantier jamais l'adresse de livraison, total HT = celui qui inclut les éco-contributions, lignes éco typées `eco`) | Consignes à réajuster sur les 30 photos | — |

### Rulings du journal (`progress.md`)

| # | Décision | Coût si faux |
| --- | --- | --- |
| R1 | Réponse Mistral inventée régénérée (appel réel, image inventée) avec les clés définitives du schéma L3-T2 | Aucun (donnée inventée) |
| R2 | L3-T9 pose les liens vers `/documents/:id` avant que L3-T10 crée la route (redirection vers l'accueil entre les deux commits) | Un lien inactif le temps d'une tâche |
| R3 | Parallélisme : flux pur (L3-T1→T2→T3) dans l'arbre séparé pendant L3-T4→T5 dans l'arbre principal, intégration par cherry-pick | Dérive d'intégration, vue par la revue finale |
| R4 | Le préfixe « chantier » retiré sans borne de mot requalifié Important (corrompait silencieusement la clé d'alias) | Une ligne de regex et un test en plus |
| R5 | Filet pour toute exception inattendue d'extraction porté par L3-T6 : `enregistrer_echec_ocr` dans une session neuve, jamais un document `recu` invisible | Cas rare traité comme un échec d'OCR |
| R6 | Toute correction de L3-T3 faite dans l'arbre séparé puis cherry-pickée après la fin de L3-T6 (pas deux écritures git simultanées dans l'arbre principal) | Correction intégrée un peu plus tard |
| R7 | La règle de confidentialité prime sur la consigne « assertion `== ()` » de la fiche L3-T3 : tout test sur fixture réelle affirme un booléen calculé à part, jamais l'égalité brute | Diagnostic un peu moins riche à l'échec |
| R8 | Tâche L3-T6b ajoutée au plan (constat 11, ajustements sur les premiers BL réels) : ces écarts touchent le cœur du critère CDC §10, moins cher à corriger avant que L3-T8a/T9/T10 ne figent le format | Une tâche de plus |
| R9 | L3-T7 (factures) part dans l'arbre séparé pendant que L3-T6b occupe l'arbre principal, intégration par cherry-pick | Conflit mineur possible sur `ingest/router.py` |
| R10 | Le constat TDD de L3-T6 ne peut pas être « annulé » rétroactivement : traité en prouvant que les tests mordent (mutations délibérées non commitées, RED observé, trou de test comblé si une mutation passe) | Aucun code en plus, seulement de la preuve |
| R11 | La branche « annotation illisible » contrôlait le doublon avec `fournisseur_id=None` alors qu'une relance garde le `fournisseur_id` du document → `IntegrityError` possible sans concurrence ; corrigé par L3-T8a | Relance d'un doublon illisible marquée `ocr_echec` |
| R12 | Même traitement que R10 pour L3-T7 (TDD non respecté dans l'ordre) : preuve RED→GREEN par `git stash`/`stash pop` déjà dans le rapport, rien à corriger dans le code livré | Aucun effet sur le comportement |
| R13 | Le §6 du protocole de mesure (sans chemin actionnable pour recaler le seuil) requalifié Important : option CLI `--seuil`, §6 réécrit, libellés de synthèse corrigés | Une option CLI de plus |
| R14 | Journal de relance écrit **après** la réextraction, dans une seconde transaction (perte possible seulement sur panne de base entre les deux commits, alors signalée en erreur) | Une relance sans ligne de journal en cas de panne |
| R15 | L3-T9 : l'implémenteur d'origine épuisé (contexte saturé) avec les corrections préparées mais non commitées ; tour repris par un implémenteur neuf qui juge et termine le travail indexé | Un tour de correction en plus |

## 3. Vérification commande par commande

Cette section reprend les commandes **réellement exécutées** dans les
rapports de tâche (`.superpowers/sdd/plan-lot-3/L3-T*-report.md`). Quand une
commande de la fiche de contrôle n'a jamais été jouée telle quelle, c'est dit
explicitement plutôt qu'inventé.

### Migration

Vérifié par L3-T5, dans l'arbre principal, base de dev `bl` :

```bash
uv run alembic upgrade head    # 0004 -> 0005
uv run alembic check           # -> "No new upgrade operations detected."
```

`tests/test_migrations.py` (aller-retour complet + `alembic check` sur la
base de migrations dédiée) passe sans modification.

### `fournisseur-definir` (CLI)

**Vérifié uniquement via les tests automatisés**, jamais lancé à la main en
dehors de pytest dans les rapports disponibles :

```bash
uv run pytest tests/test_cli.py -q -k fournisseur
# -> 2 passed, 13 deselected
```

Couvre une création (SIRET/TVA/2 alias/1 agence → sortie
`Fournisseur créé (2 alias, 1 agences)`, code 0, état DB vérifié) et une
mise à jour (nom en casse différente, TVA remplacé, alias dédupliqué,
nouvelle agence → `Fournisseur mis à jour (1 alias, 2 agences)`). La forme
documentée de la commande est :

```bash
python -m app.cli fournisseur-definir --nom NOM [--siret S] [--tva T] [--alias A]... [--agence NOM]...
```

### Création d'un chantier

Vérifié par les tests automatisés (`test_referentiels.py`, `test_a_traiter.py`
côté `api`) et, visuellement, via le bouton « Créer un chantier » de l'écran
« À traiter » (Playwright/Chromium, données inventées — L3-T9, captures
`a-traiter-erreur-409-chantier-*`, `a-traiter-chantiers-vide-*`). Jamais
appelé directement en `curl` dans les rapports disponibles.

### Dépôt d'un BL — **écart avec la fiche de contrôle**

La fiche de contrôle de cette tâche demande de vérifier « un dépôt d'un BL
inventé via le webhook avec OCR réel sur une image inventée ». **Cela n'a
jamais été fait tel quel** :

- Le flux `POST /tg/webhook` → `traiter_fichier` → `enregistrer_extraction_bl`
  est testé de bout en bout par `test_router.py`/`test_service.py`, mais
  toujours avec un OCR **simulé** (`httpx.MockTransport`), jamais un vrai
  appel réseau à Mistral.
- Les **seuls** appels réels à l'API Mistral OCR faits pendant le lot 3
  portent : (a) sur une image de BL **inventée**, générée localement, pour
  produire une fois pour toutes la donnée de test
  `app/modules/extract/tests/donnees/bl_synthetique.mistral-ocr.json`
  (L3-T1, Ruling R1) — mais ce script (`donnees/bl_synthetique.py`) appelle
  l'API Mistral directement, jamais via le webhook Telegram réel ; (b) sur
  les **4 photos réelles** du client (Unikalo/Point.P), fournies et
  autorisées par Ilane le 17/09, également hors du webhook (script
  ponctuel, réponses mises en cache dans `tests/fixtures/bl/*.mistral-ocr.json`,
  jamais recommitées).
- Aucun bot ni groupe Telegram réel n'existe pour ce lot (hérité du lot 2,
  Q4 du plan lot 2, toujours non résolu) : un dépôt réel de bout en bout via
  Telegram (photo envoyée → webhook → OCR réel → document en base → réponse
  dans le groupe) **n'a jamais eu lieu**, ni au lot 2 ni au lot 3.

Ce qui a été fait à la place, et qui reste une vérification solide du code
livré : suite pytest complète (motifs, fournisseur/chantier/article résolus,
doublon concurrent testé par simulation déterministe, journal), plus
vérification visuelle de l'écran « À traiter »/détail document sur des
documents insérés directement en base à partir de la donnée synthétique
(scripts non commités `var/seed_a_traiter.py` etc., L3-T9/T10).

### Écran « À traiter »

- API : `uv run pytest app/modules/ingest/tests/test_a_traiter.py app/modules/api/tests/test_a_traiter.py -q` → 62 tests (avec `test_referentiels.py`) au vert (L3-T8b).
- Visuel (Playwright/Chromium, données inventées, jamais un vrai dépôt) :
  captures `a-traiter-rempli-{375,1280}.png`,
  `a-traiter-apres-validation-alias-*`, `a-traiter-badge-ecart-*` (L3-T9) —
  5 documents à vérifier (motifs variés), 2 alias en attente, 1 article à
  valider affichés correctement aux deux largeurs.

### Correction, validation, archivage, relance

- Service : `uv run pytest app/modules/ingest/tests/test_corrections.py -q` → 33 passed (+1 après le fix round 1 sur la relance, 34).
- Visuel (L3-T10, Playwright, données inventées) : `document-edition-*`
  (formulaire d'en-tête + lignes en une vue), `document-validation-refusee-*`
  (409 avec motifs), `document-validation-reussie-*` (correction du total
  puis validation réussie), `document-archivage-formulaire-375.png` et
  `document-archivage-reussi-*`.
- « Relancer l'extraction » est testé (service + capture indirecte via les
  motifs), mais **toujours avec la donnée synthétique déjà connue rejouée
  par un faux client OCR**, jamais un nouvel appel réseau réel déclenché
  depuis l'écran.
- **Ce point précis reste ouvert** : la revue de L3-T10 a signalé un défaut
  (état d'édition non réinitialisé après écriture) dont la correction n'est
  pas confirmée au moment de la rédaction de cette recette (voir « À lire
  d'abord »).

### Dépôt de facture « à vérifier »

- Service : `uv run pytest app/modules/ingest/tests/test_deposer_facture.py -q` → 15 passed, 1 skipped (fixture réelle absente de cet arbre) — cohérent/incohérent, confiance réduite, alias, ratio d'article, tous couverts.
- Visuel (L3-T9) : deux factures **insérées directement en base** (jamais
  déposées via `POST /api/factures`), captures `factures-liste-badges-*`
  (badges « À vérifier »/« Confiance réduite (OCR) ») et
  `facture-detail-badges-motifs-*` (encart motifs, ex. « Somme des lignes
  différente du total »).
- **Aucun dépôt réel d'une facture via l'écran n'a eu lieu ce lot-ci** (ni
  avec un vrai PDF ni avec un vrai appel OCR) : contrairement au lot 2, où
  la facture d'août avait été déposée avec un OCR simulé, le lot 3 n'a
  vérifié ce chemin que par les tests automatisés et par insertion directe
  en base pour les captures.

### `rapport-ocr`

- Sur données inventées : `uv run pytest app/modules/ingest/tests/test_rapport_ocr.py tests/test_cli.py -q` → 67 passed (L3-T11, après le fix round 1). Vérification manuelle de bout en bout sur un dossier `/tmp` inventé (mélange document valide / attendu invalide / cache non-objet, `--seuil 0.5`) → code 0, rapport écrit, section « Documents non mesurés » correcte.
- **Sur les 4 photos réelles (mesure du contrôleur, jamais rejouée par un
  agent)** :
  ```bash
  python -m app.cli rapport-ocr tests/fixtures/bl --sortie var/rapport-ocr-4-bl.md
  ```
  (sans `--appeler-ocr` : les réponses des 4 photos étaient déjà en cache
  depuis les essais réels de L3-T6/T6b). Résultat détaillé en §4.

## 4. Mesure du taux d'erreur OCR (CDC §10)

**Le critère du CDC §10 n'est pas mesuré** : il faut au moins 30 photos
réelles dont 10 dégradées ; 4 seulement sont disponibles au 17/09/2026.
`docs/protocole-mesure-ocr.md` donne la marche à suivre complète dès
réception des fichiers manquants : nommage (`tests/fixtures/bl/`, jamais
commité), format de `<nom>.attendu.json`, commande de première mesure
(`--appeler-ocr`, un seul appel réseau par photo, mis en cache) et de
relance (sans réseau), lecture du rapport, et une section dédiée au calage
du seuil de confiance (Ruling R13, option `--seuil`) — ainsi qu'une section
« ce que cet outil ne mesure pas » (doublon de numéro, fournisseur inconnu,
facture Point.P, dépôt Telegram réel).

**Mesure réelle sur les 4 photos disponibles** (contrôleur, 17/09/2026,
`tests/fixtures/bl/`, autorisation d'Ilane) — **aucune valeur du document
n'est recopiée ici, uniquement des comptes et des taux** :

| Champ/critère | Résultat sur 4 photos |
| --- | --- |
| Numéro juste | 100 % |
| Fournisseur juste | 50 % |
| Date juste | 75 % |
| Chantier brut juste | 75 % |
| Documents avec les 4 champs justes (objectif CDC ≥ 95 %) | 50 % |
| Lignes justes (objectif CDC ≥ 90 %) | 66,7 % |
| Erreurs silencieuses (objectif CDC = 0) | **0** |
| Confiance des valeurs justes | ≥ 0,92 |
| Confiance la plus haute parmi les valeurs fausses | 0,83 |

Détail (sans valeur réelle) : les deux photos nettes sont justes sur les 4
champs et toutes leurs lignes ; la photo prise en biais fait boucler l'OCR
(aucun tableau, aucune ligne, aucun total détecté) et part « à vérifier »
sans produire d'erreur silencieuse ; la quatrième a un nom de fournisseur
mal lu et un code article mal lu, tous deux signalés par une confiance
basse (pas d'erreur silencieuse non plus).

**Ce que ces 4 chiffres ne permettent pas de conclure** : l'échantillon est
6 à 7 fois plus petit que le minimum requis par le CDC (30, dont 10
dégradées), et ne contient qu'une seule photo dégradée (celle qui boucle).
Rien n'indique si le seuil provisoire de 0,80 (L3-D4/Q3) est le bon — les
deux bornes de confiance observées (justes ≥ 0,92, la plus haute fausse à
0,83) suggèrent un seuil plutôt autour de 0,90, mais 4 photos ne suffisent
pas à trancher. Le taux d'erreur silencieuse à 0 % est encourageant mais ne
peut pas non plus être extrapolé à 30 photos.

## 5. Ce qui manque / reste à faire avec Ilane

- **Fichiers manquants** (constat 1, bloquants pour le livrable du lot et
  pour le parseur Point.P) :
  - au moins 30 photos de BL réelles dont 10 dégradées, avec leurs valeurs
    attendues (`docs/protocole-mesure-ocr.md`) ;
  - des factures et bons d'enlèvement Point.P ;
  - la liste des chantiers actifs avec leur agence, les SIRET/TVA des deux
    fournisseurs et les noms de leurs agences (pour alimenter
    `fournisseur-definir`/la CLI de rattachement chantier avant tout usage
    réel).
- **Point de revue non refermé** : L3-T10 (voir « À lire d'abord ») — à
  vérifier et clore avant de considérer le lot 3 terminé.
- **Décisions à valider** : Q1, Q3, Q4, Q5, Q6, Q7 (§2) — aucune n'a de
  conséquence irréversible en base de production (rien n'est déployé).
- **Q2** (fichiers manquants) reste la question bloquante : sans elle, ni
  le rapport de taux d'erreur ni le parseur Point.P ne peuvent avancer.
- **Tests réels jamais faits** :
  - Telegram de bout en bout (aucun bot/groupe réel, cf. lot 2 Q4) — un BL
    n'a jamais été déposé par un vrai message Telegram avec un vrai appel
    Mistral OCR ;
  - sauvegarde/restauration avec le schéma du lot 3 (migration 0005) ;
  - navigateur sur un appareil mobile réel (seule une émulation à 375 px a
    été utilisée) ;
  - dépôt réel d'une facture via l'écran (PDF réel + vrai OCR).
- **Dette ajoutée par ce lot** (`docs/dette.md`, détail complet) :
  parseur Point.P non construit ; pas de correction de facture à l'écran ;
  pas de fusion de documents multi-pages ; sélection des alias en attente
  par deux requêtes par alias (volumes CDC §9 très faibles) ; état
  d'édition du détail document non réinitialisé entre deux documents
  consécutifs sans passer par une liste.

## 6. Tests (relancés réellement, arbre `/home/debian/habitat_reno-wt-l3`, 17/09/2026)

```bash
uv run pytest -q
```
```
815 passed, 13 skipped in 150.41s (0:02:30)
```
(les 13 skips sont dus à l'absence de `tests/fixtures/{unikalo,bl}/` dans
cet arbre de travail — attendu, ces fixtures réelles ne sont jamais
committées. Dans l'arbre principal, où ces fixtures existent, le dernier
compte rapporté était **828 passed** avec les mêmes tests non skippés — cf.
rapport L3-T10 — la différence de 13 correspond exactement aux tests sur
fixtures réelles.)

```bash
uv run ruff check
```
```
All checks passed!
```

```bash
uv run ruff format --check
```
```
119 files already formatted
```

```bash
uv run mypy
```
```
Success: no issues found in 100 source files
```

Front (typecheck/build) : vérifié par L3-T9 et L3-T10 dans leurs rapports
respectifs (`npm --prefix web run typecheck`/`build`, propres) — non rejoué
par cette tâche (aucun fichier front modifié par L3-T12).
