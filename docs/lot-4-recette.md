# Recette du lot 4 (Rapprochement) — Contrôle BL & factures

Branche `lot-4-rapprochement` (dépôt `/home/debian/habitat_reno`), créée
depuis `main` (plan écrit en `bf910d2`). Comme au lot 3, le flux **pur**
(`rules/`, plus une partie de `normalize/`) a été mené dans un arbre séparé
(`/home/debian/habitat_reno-wt-l4`, branche `lot-4-pur`, supprimée après
intégration) pendant que l'arbre principal avançait sur `ingest`/`api`/
`web`, avec intégration par report de commits. Aucune donnée réelle
(numéro, chantier, montant, nom, SIRET/TVA, contenu de fichier client) dans
ce document : comptes et taux uniquement, comme les recettes des lots
précédents. **Rien n'est fusionné dans `main`** : le lot reste sur sa
branche. Les 11 tâches techniques (L4-T1 à L4-T11) sont faites et relues,
chaque revue de tâche s'est refermée sans point ouvert ; il reste la revue
finale de l'ensemble de la branche avant fusion (mandat de fusion déjà donné
par Ilane le 17/09/2026, cf. `docs/passation-lot-4.md` §3.1).

## À lire d'abord (Ilane)

- **Ce qui est fait** : un moteur de règles pur (`app/modules/rules/`, 17
  règles R01 à R17, chacune testée par au moins un cas positif et un cas
  négatif), la conversion des quantités et l'appariement des lignes de BL
  aux lignes de facture, le rapprochement complet d'une facture (statut par
  bloc — reçu / non reçu / pas de bon —, lignes rapprochées, anomalies),
  persisté et rejouable sans jamais créer de doublon, le cycle de vie complet
  d'une anomalie (apparition, mise à jour, disparition automatique, prise en
  charge « traitée » ou « ignorée » avec commentaire obligatoire), l'écran
  Anomalies (admin, filtres règle/gravité/statut/chantier/fournisseur/
  période) et sa section dans l'écran « À traiter », et deux commandes (rejeu
  du rapprochement, contrôles différés quotidiens) avec leur note
  d'exploitation (`docs/exploitation-lot-4.md`). Détail tâche par tâche en
  §1, décisions en §2.
- **Verdicts réels sur la facture d'août** (rejeu complet du rapprochement
  par le contrôleur sur les documents réels — la facture d'août et les
  trois BL dont le numéro y figure —, dans une base dédiée jetable, jamais
  commitée) : **28 blocs, 3 reçus, 4 « pas de bon », 21 non reçus** ; **25
  anomalies : R01 ×21, R02 ×4, R13 ×3** ; sur les 136 lignes de facture,
  `qte_fact` est renseignée sur **113** après la dernière correction du
  rapprochement, et **3 lignes** sont appariées à une ligne de BL (les
  seules dont le bloc a un BL) ; **aucun écart de quantité signalé à tort**,
  **aucune anomalie de prix** (un seul mois d'historique disponible).
  **Ce classement n'a pas été confirmé par vous** (Q6, §2) : nous savons
  seulement que 3 BL sur 4 disponibles portent un numéro présent dans cette
  facture. Détail en §4.
- **Ce qui n'est pas vérifiable en l'état** (détail en §5) : la
  semi-remorque (aucun déclencheur défini avec vous), l'historique de prix
  (un seul mois de documents), un avoir complet (aucun exemple fourni), une
  deuxième facture ou un deuxième fournisseur (Point.P, aucun document), et
  le critère de volume du CDC §10 (30 documents, revue de 30 anomalies au
  hasard).
- **Décisions à valider** (détail en §2) : **Q1** — semi-remorque non
  construite faute de déclencheur ; **Q2** — pas d'anomalie de prix sous 3
  occurrences d'historique ; **Q3** — écran Anomalies réservé à l'admin ;
  **Q4** — une anomalie dont la cause disparaît est supprimée (pas
  archivée) ; **Q5** — les 3 lignes négatives de la facture d'août traitées
  comme des avoirs de ligne, faute d'exemple d'avoir complet ; **Q6** — les
  verdicts reçu/non reçu/pas de bon des 28 blocs à confirmer.
- **Deux points ajoutés à `docs/dette.md`** par ce lot : une comparaison de
  quantité perdue quand une seule des deux lignes appariées a une unité
  connue (choix volontairement prudent, CDC §10 : « 0 anomalie R03/R04 due à
  une unité ») ; une remarque de déploiement sur l'identité d'une anomalie
  (sans effet tant que rien n'est en production).

## 1. Ce qui est fait

| Tâche | Commit(s) sur la branche | Résultat |
| --- | --- | --- |
| L4-T1 | `1929842` | `rules: socle du moteur de règles`. Moteur (`evaluer_facture`), dataclasses d'entrée, R10/R11. Revue → spec ✅, **Approved** (pureté vérifiée, bornes de tolérance, ordre d'arrêt après R10 respecté). 3 points mineurs reportés. Terminé. |
| L4-T2 | `b0e3d1b` | `rules: règles de bloc R01, R02, R12`. Revue → spec ✅, **Approved**. Décision prise en cours de route : le chantier cité dans le détail de R01/R02 est le nom canonique s'il existe, sinon le libellé brut, sinon un tiret. 3 points mineurs reportés. Terminé. |
| L4-T3 | `71363ff` | `rules: règles de ligne R03, R04, R05, R17`. Revue → spec ✅, **Approved** ; portée de R17 confirmée (évaluée sur la ligne de facture, pas sur la ligne de BL appariée). 2 points mineurs reportés. Terminé. |
| L4-T4 | `21f4e3b` + correction `49781b0` | `rules: prix et remises R07, R08, R09` + `rules: prix évalués sur toutes les lignes d'article`. Revue → spec ✅, **Approved** (arithmétique, bornes 5 %/15 %, minimums d'occurrences, sémantique de R09) ; une décision restait à appliquer (les règles de prix ignorent l'état du BL — absent, à vérifier, incohérent — et s'évaluent sur toute ligne article). Re-revue → 1 point corrigé, aucun ouvert. 1 point mineur reporté. Terminé. |
| L4-T5 | `ce6f6c8` + correction `7207768` | `rules: avoirs et suivi R13, R06, R14, R15, R16` + `rules: portée des anomalies de suivi (chantier et alias)`. Revue → spec ✅, **Approved** ; un point mineur relevé (R14 souffrait de la même collision d'identité que R16 — toutes les anomalies d'alias en attente partageraient la même clé). Re-revue → 2 points corrigés, aucun ouvert. 1 point mineur reporté. Terminé. |
| L4-T6 | `17528e6` + correction `320d763` | `normalize: conversion d'unités et appariement des lignes` + `normalize: unité absente acceptée seulement sur les factures`. Revue → spec ✅, **Approved** ; un point Important signalé comme conséquence d'une décision du contrôleur (unité absente acceptée), à trancher avant L4-T7. Re-revue → 1 point corrigé, aucun ouvert. 2 points mineurs reportés. Terminé. |
| L4-T7 | `59c7a18` + correction 1 `0cb8c97` + correction 2 (`10ce175`, `a4740ee`, `c9cbde8`) | `ingest: rapprochement des factures` + `ingest: quantités comparables sans unité imprimée et doublons hors archives` + `normalize/rules: quantités comparables seulement entre mêmes modes` + `ingest: document d'origine sur les anomalies de facture` + `ingest: chantier propre des anomalies de suivi en lecture`. Revue → Needs fixes (1 point Important : un doublon de facturation entre factures ne filtrait pas les factures déjà archivées) ; en rejouant le rapprochement sur la facture réelle d'août, le contrôleur a aussi mesuré que la quantité convertie restait vide sur toutes les lignes (Unikalo n'imprime aucune unité), corrigé par la première correction. La deuxième correction a fermé un point relevé en re-revue (une quantité rendue telle quelle faute d'unité connue ne doit être comparée qu'à une autre quantité dans le même cas), ajouté l'identifiant de la facture sur chaque anomalie qu'elle produit, et corrigé la résolution du chantier d'une anomalie en lecture. Repris une fois par un agent neuf après épuisement du premier en cours de correction (état du dépôt vérifié avant reprise). Toutes les revues refermées sans point ouvert. 3 points mineurs reportés. Terminé. |
| L4-T8 | `336cb36` + correction `68f14ab` | `ingest: anomalies (génération idempotente, cycle de vie, lecture)` + `ingest: portée des anomalies limitée aux règles recalculées`. Revue → Needs fixes (1 point Important : un rejeu portant sur une seule facture pouvait aussi supprimer par erreur des anomalies de suivi rattachées aux blocs de cette facture). Re-revue → 1 point corrigé, aucun ouvert. 6 points mineurs reportés. Terminé. |
| L4-T9 | `6d80bfe` + correction `b8b7952` | `api: anomalies` + `api: filtre de statut « toutes » sur les anomalies`. Revue → spec ✅, **Approved** ; points mineurs relevés (pas de moyen de lister toutes les anomalies en un appel ; bornes de période, commentaire trop long et accès anonyme non testés). Re-revue → 4 points corrigés, aucun ouvert. Terminé. |
| L4-T10 | `e070805` + correction `3a0a01b` | `web: écran Anomalies` + `web: quantités formatées à la française`. Revue → spec ✅, qualité bonne ; 3 points Important : quantités affichées avec un point décimal à côté de montants en français (corrigé par ce tour) ; 9 règles sur 12 sans lien vers leur facture (déjà pris en charge par la deuxième correction de L4-T7, rien à refaire ici) ; le correctif d'un plantage sur une valeur absente n'a aucun test automatisé (dette front déjà connue, aucun outillage de test côté front). Re-revue → 1 point corrigé, aucun ouvert. 2 points mineurs reportés. Terminé. |
| L4-T11 | `c342580` | `ingest/cli: contrôles différés et rejeu du rapprochement`. Revue → spec ✅, qualité solide, aucun point Critical ; un point Important préexistant relevé (la résolution du chantier d'une anomalie en lecture ne regardait jamais le chantier propre à l'anomalie elle-même), pris en charge par la deuxième correction de L4-T7 ci-dessus. 2 points mineurs reportés. Terminé. |
| L4-T12 | (ce commit) | `docs: recette et passation du lot 4` — ce document, `docs/passation-lot-4.md`, `docs/dette.md` et `CLAUDE.md` mis à jour. |

## 2. Décisions

### 2.1 Décisions du plan (`docs/plan-lot-4.md` §4)

| # | Décision (résumé) | Coût si faux | À valider |
| --- | --- | --- | --- |
| L4-D1 | Module `rules` pur, sans import d'`extract` ni de `normalize` : dataclasses d'entrée propres, construites par `ingest` | Duplication de quelques dataclasses (assumée) | — |
| L4-D2 | Une fonction par règle (`Rxx.py`), plus `engine.py` qui les enchaîne dans l'ordre du CDC §5 | — | — |
| L4-D3 | Rapprochement d'une facture idempotent, rejouable, déclenché au dépôt d'une facture, après validation d'un BL, et par une commande | — | — |
| L4-D4 | Statut de rapprochement et BL rattaché persistés par bloc ; la lecture existante continue de fonctionner tant qu'aucun rapprochement n'a tourné | Recalcul à la lecture | — |
| L4-D5 | Correspondance bloc ↔ BL : même fournisseur et même numéro normalisé, document non archivé ; plusieurs BL du même numéro → le plus ancien fait foi, les autres signalés en doublon | Appariement à affiner | — |
| L4-D6 | Appariement des lignes : d'abord par code article, puis par désignation, jamais une ligne de BL utilisée deux fois, jamais entre deux blocs différents | Appariement à affiner (ex. distance de chaînes) | — |
| L4-D7 | Quantité facturée convertie dans l'unité de facturation de l'article ; une conversion impossible ne produit jamais d'anomalie de quantité fausse | Comparaisons manquées, jamais fausses | — |
| L4-D8 | Les anomalies de somme incohérente reprennent le motif déjà calculé à l'extraction, pas un nouveau calcul | — | — |
| L4-D9 | Historique de prix : médiane sur les 6 mois précédents, aucune anomalie sous 3 occurrences | Seuil d'occurrences à changer | **Q2** |
| L4-D10 | Seuils créés avec leur valeur par défaut au premier rapprochement ; pas d'écran pour les modifier ce lot-ci (lot 5) | Valeurs à changer en base | — |
| L4-D11 | Identité d'une anomalie garantie par un index unique ; un rejeu met à jour une anomalie ouverte existante plutôt que d'en créer une seconde | Migration d'index | — |
| L4-D12 | Une anomalie ouverte dont la cause a disparu est supprimée, la levée journalisée ; une anomalie traitée ou ignorée n'est jamais touchée | Statut « levée » à ajouter si vous préférez les conserver | **Q4** |
| L4-D13 | Une anomalie ignorée depuis moins de 90 jours bloque la régénération d'une anomalie de même règle pour le même couple fournisseur/article | Colonne à retirer | — |
| L4-D14 | Les règles qui dépendent du temps écoulé (R06, R14, R15, R16) sont calculées par une commande quotidienne, pas à chaque dépôt | Planification à ajouter | — |
| L4-D15 | Traiter une anomalie exige un commentaire, seulement depuis le statut ouverte | — | — |
| L4-D16 | Semi-remorque **non construite** : aucun déclencheur défini avec vous | Une règle à écrire dès réception du déclencheur | **Q1** |
| L4-D17 | Écran Anomalies réservé à l'admin, avec les six filtres du CDC §4.6 et une phrase de justification construite côté front à partir des chiffres renvoyés par l'API | Ouvrir aux agents | **Q3** |
| L4-D18 | Section « anomalies ouvertes de gravité haute » ajoutée à l'écran « À traiter » | — | — |

### 2.2 Décisions prises en cours de route

Contrairement aux décisions ci-dessus (prises en préparant le lot), celles-ci
ont été prises pendant l'exécution, face à un choix non couvert par le plan.
Aucune n'a de conséquence irréversible (rien n'est en production).

| # | Décision | Coût si faux |
| --- | --- | --- |
| R1 | L4-T8 (anomalies) fait avant L4-T7 (rapprochement), qui l'appelle | Aucun, simple ordre |
| R2 | Précisions d'ordre du moteur : si R10 est produite, aucune autre règle ne tourne pour la facture ; si R11 est produite pour le BL d'un bloc, les règles de ligne de ce bloc ne tournent pas, les autres blocs restent évalués | Quelques anomalies de ligne en moins sur un BL incohérent |
| R3 | Un bloc est « reçu » dès qu'un BL du même fournisseur porte son numéro, quel que soit son propre statut (sauf archivé) ; les règles de ligne ne comparent des quantités que si ce BL est validé | Des blocs marqués reçus sans comparaison de ligne, visible dans la recette |
| R4 | Organisation du travail : flux pur dans un arbre séparé, flux base dans l'arbre principal, intégration par report de commits | Dérive d'intégration, vue par la revue finale |
| R5 | Le chantier cité dans le détail de R01/R02 est le nom canonique s'il existe, sinon le libellé brut, sinon un tiret | Une clé de détail à changer |
| R6 | Organisation du travail : la tâche de conversion d'unités avancée dans l'arbre principal | Aucun |
| R8 | La suppression des anomalies devenues obsolètes exige désormais toujours l'ensemble complet des règles recalculées, pas une liste reconstituée par chaque appelant | Un paramètre obligatoire de plus |
| R9 | R17 (quantité de conditionnement non entière) reste évaluée sur la ligne de facture, pas sur la ligne de BL appariée | Une ligne de plus dans le moteur si l'interprétation change |
| R10 | La conversion d'une quantité accepte une unité non imprimée du côté facture (Unikalo n'en imprime jamais), mais pas du côté BL | Comparaisons manquées, jamais fausses |
| R11 | Les règles de prix (R07, R08, R09) s'évaluent sur toutes les lignes article de tous les blocs, quel que soit l'état du BL — absent, à vérifier ou incohérent | Quelques anomalies de prix en trop sur des documents douteux |
| R12 | Les ensembles de règles (règles de facture, règles de suivi) deviennent une seule constante partagée plutôt qu'une liste recopiée par chaque appelant | Une constante à déplacer |
| R13 | Une anomalie porte aussi, quand c'est pertinent, l'identifiant du chantier (R16) et de l'alias (R14) concernés, pour ne pas confondre deux chantiers ou deux alias distincts sous la même anomalie | Deux colonnes et un index à défaire |
| R14 | Quand ni l'unité lue ni l'unité de facturation de l'article ne sont connues des deux côtés, la quantité est comparée telle quelle (cas réel chez Unikalo, qui n'imprime aucune unité) | Des comparaisons entre unités implicites différentes, que d'autres règles signaleraient |
| R15 | L'API accepte une valeur de statut qui retire le filtre par défaut, pour pouvoir afficher l'historique complet des anomalies | Une valeur à retirer |
| R16 | Une quantité comparée telle quelle faute d'unité connue (R14) n'est comparée qu'à une autre quantité dans le même cas, jamais à une quantité réellement convertie | Une comparaison de quantité perdue dans les cas mixtes, notée en dette |
| R17 | Toute anomalie produite par le rapprochement porte désormais l'identifiant de sa facture | Une remarque de déploiement, notée en dette |
| R18 | Une quantité s'affiche toujours avec une virgule française, jamais un point, aux trois endroits de l'écran qui en montrent une | Une fonction de présentation à retirer |
| R19 | La résolution du chantier d'une anomalie, en lecture, regarde d'abord le chantier propre à l'anomalie, puis celui du bloc, puis celui du document | Un terme de recherche à retirer |

## 3. Vérification commande par commande

### Moteur de règles (sans base ni réseau)

Chaque règle a été vérifiée avec au moins un cas positif et un cas négatif
au moment de sa tâche (L4-T1 à L4-T5) ; la suite complète du module reste
incluse dans la vérification de branche (§6).

### Conversion d'unités et appariement des lignes

```bash
uv run pytest app/modules/normalize -q
```
Couvre les cinq cas de conversion (même unité, conditionnement avec ratio
validé, unité non imprimée côté facture, unité non imprimée des deux côtés,
tout le reste → non convertible) et l'appariement par code puis par
désignation.

### Rapprochement d'une facture

```bash
uv run pytest app/modules/ingest/tests/test_rapprochement.py -q
```
22 tests d'abord, puis 100 après la première correction (avec
`app/modules/normalize`). Couvre : BL déposé avant ou après la facture,
mention « pas de bon », idempotence d'un rejeu (aucun doublon de ligne ni
d'anomalie), garde sur une facture « à vérifier », doublon de facturation
(exclu si l'autre facture est archivée), avoir sans origine, prix hors
historique, et une vérification sur la fixture réelle par booléens calculés
et message fixe (jamais une valeur réelle affichée) — voir §4.

### Anomalies (cycle de vie)

```bash
uv run pytest app/modules/ingest/tests/test_anomalies.py -q
```
32 tests : mise à jour sans doublon sur rejeu, anomalie levée avec son
entrée de journal, anomalie traitée jamais retouchée par un rejeu, règle des
90 jours (une anomalie ignorée récemment bloque la régénération, une
ancienne ne la bloque plus), transitions de statut et refus, commentaire
obligatoire.

### API

```bash
uv run pytest app/modules/api/tests/test_anomalies.py app/modules/api/tests/test_a_traiter.py -q
```
30 tests : droits (agent refusé), chaque filtre (règle, gravité, statut —
dont la valeur qui retire le filtre —, chantier, fournisseur, période aux
bornes incluses, limite), cycle de vie complet (traitée, ignorée, 404, 409,
commentaire vide ou trop long, statut invalide), section des anomalies
hautes dans l'écran « À traiter », schémas OpenAPI présents.

### Contrôles différés et commandes CLI

```bash
uv run pytest app/modules/ingest/tests/test_suivi.py -q      # 15 passed
uv run pytest tests/test_cli.py -q                            # 38 passed
uv run pytest tests/test_migrations.py -q                     # 2 passed
```
Couvre les quatre règles de suivi (positif, négatif, garde spécifique à
chacune), le rejeu sans doublon, les deux commandes CLI (`rapprocher
--facture`, `rapprocher --tout` avec gestion d'un échec par facture,
`controles-differes`) avec leurs codes de sortie et une sortie qui n'affiche
jamais de valeur de document, et le cycle complet de la migration qui étend
l'identité d'une anomalie. Ces deux commandes n'ont **jamais été invoquées
manuellement sur les documents réels** : `rapprocher --facture`/`--tout`
n'a été vérifiée que par les tests ci-dessus ; le rejeu réel du
rapprochement rapporté en §4 a été fait par le contrôleur en appelant
directement la fonction de service, pas la commande. `controles-differes`
dépend du temps écoulé (jours, voire heures) : elle n'a donc jamais pu être
exercée sur un cas réel, faute d'un historique d'usage suffisant.

### Front

```bash
npm --prefix web run typecheck
npm --prefix web run build
```
Les deux commandes doivent s'exécuter sans erreur (silencieuse pour la
première, un résumé des modules transformés pour la seconde). Vérification
visuelle par navigateur automatisé, données entièrement inventées, jamais
les fixtures réelles : liste remplie, filtre actif, liste vide, formulaire
de commentaire, erreur de conflit, section de l'écran « À traiter ». Les
captures (375 px et 1280 px) sont dans `var/captures/` (42 fichiers, hors
dépôt, jamais commitées).

### Suite complète et qualité (dernière vérification de branche)

Sur la branche complète, au commit `3a0a01b` :

```bash
uv run pytest -q
```
```
1139 passed
```
```bash
uv run ruff check
uv run ruff format --check
```
```
All checks passed!
175 files already formatted
```
```bash
uv run mypy
```
```
Success: no issues found in 150 source files
```
```bash
npm --prefix web run typecheck
npm --prefix web run build
```
Tous verts. Ces quatre commandes (`pytest`, `ruff check`, `ruff format
--check`, `mypy`) sont aussi rejouées automatiquement par le hook
pre-commit à chaque commit sur ce dépôt ; les deux commandes front ne le
sont que si un fichier sous `web/` est modifié, ce qui n'est pas le cas de
ce commit de documentation.

## 4. Verdicts réels sur la facture d'août

Rejoué par le contrôleur, après la dernière correction du rapprochement,
sur les documents réels disponibles — la facture d'août et les trois BL
dont le numéro y figure — dans une base dédiée et jetable, jamais commitée
ni gardée. Aucune valeur de document (numéro, chantier, montant) n'apparaît
ci-dessous, uniquement des comptes :

| Mesure | Résultat |
| --- | --- |
| Blocs de facture | 28 |
| … dont reçus (un BL du même fournisseur porte le numéro) | 3 |
| … dont « pas de bon » (mention explicite, aucun BL) | 4 |
| … dont non reçus | 21 |
| Anomalies produites | 25 |
| … R01 (bloc sans BL ni mention) | 21 |
| … R02 (bloc sans BL, mention « pas de bon ») | 4 |
| … R13 (avoir sans origine) | 3 |
| Lignes de facture | 136 |
| … avec `qte_fact` renseignée (quantité convertie) | 113 |
| … appariées à une ligne de BL | 3 |
| Écarts de quantité signalés à tort | 0 |
| Anomalies de prix produites | 0 (un seul mois d'historique disponible) |

**Ce classement n'est pas confirmé par Ilane** (Q6) : la seule chose que
nous savons de source sûre est que 3 des 4 photos de BL disponibles portent
un numéro présent dans cette facture. Les 25 verdicts et les 3 lignes
appariées restent donc à revoir avec elle avant d'être considérés fiables.

### Rappel des critères de réception du CDC §10 (lot Rapprochement)

| Critère | État |
| --- | --- |
| Chaque bloc classé reçu/non reçu/pas de bon, sans faux positif (vérifié à la main) | Mesuré (tableau ci-dessus), **non confirmé** par Ilane (Q6) |
| 0 anomalie R03/R04 due à une unité | Aucun écart signalé à tort observé, mais seules 3 lignes sur 136 sont effectivement comparées à une ligne de BL — échantillon trop petit pour conclure pleinement |
| Chaque anomalie cite sa règle, sa justification chiffrée et son document source, revue de 30 anomalies tirées au hasard | Chaque anomalie produite cite bien sa règle et ses chiffres (vérifié par les tests et l'écran) ; la revue de 30 anomalies au hasard **n'est pas mesurable** : seules 25 anomalies réelles existent au total |
| Chaque règle a au moins un test unitaire positif et un négatif | Mesuré et vérifié en revue, tâche par tâche (L4-T1 à L4-T5) |
| Semi-remorque | **Non construite**, déclencheur non défini (L4-D16) |

## 5. Ce qui n'est pas vérifiable

- **Semi-remorque** (variante de gravité haute du CDC §5) : non construite,
  aucun document de ce type n'a permis de définir son déclencheur avec vous
  (L4-D16, Q1).
- **Historique de prix** (R07, R08, R09) : un seul mois de documents est
  disponible, donc ces trois règles ne se déclenchent jamais sur les
  données réelles (aucune anomalie de prix mesurée, tableau §4) ; seuls les
  tests unitaires (données inventées) les couvrent.
- **Avoir complet** : aucun avoir n'a été fourni ; R13 (avoir sans origine)
  n'est vérifiée sur données réelles que par les 3 lignes négatives de la
  facture d'août, traitées comme des avoirs de ligne (Q5) — un document
  d'avoir à part entière reste non géré (dette héritée du lot 2).
- **Deuxième facture, deuxième fournisseur (Point.P)** : aucun document
  disponible, le parseur n'est pas construit (dette héritée du lot 3) —
  aucun rapprochement n'est possible avec ce fournisseur.
- **Volume du CDC §10** : le critère demande un volume de documents (30
  photos de BL dont 10 dégradées, revue de 30 anomalies) que le client n'a
  pas fourni ; il reste non mesuré, comme au lot 3.

## 6. Tests (état de la branche au moment de la rédaction)

Voir §3 « Suite complète et qualité » : `1139 passed`, `ruff check`/`ruff
format --check` propres sur 175 fichiers, `mypy` propre sur 150 fichiers,
`npm --prefix web run typecheck`/`build` propres. Ces chiffres datent du
commit `3a0a01b` (dernier commit de code du lot) et n'ont pas été rejoués
par cette tâche, qui ne touche que la documentation.
