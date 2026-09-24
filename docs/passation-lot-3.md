# Passation — lot 3 (Extraction), 17 septembre 2026

Document de reprise pour la session suivante. **À lire en entier avant de
toucher au code**, avec `CLAUDE.md`, `docs/cahier-des-charges.md` (qui fait
foi), `docs/passation-lots-1-2.md` (lots précédents), `docs/lot-3-recette.md`
(recette détaillée, commandes exécutées, mesure OCR) et `docs/dette.md`.

---

## 1. État au 17/09/2026, fin de journée

- **Branche `lot-3-extraction`** (dépôt `/home/debian/habitat_reno`), créée
  depuis `main` @ `379d5bc` (« docs: passation des lots 1 et 2 »), tête
  `07d3a73` après la vague finale de clôture. **Non fusionnée dans `main`**
  au moment de la rédaction de cette mise à jour. Aucun remote, rien de
  déployé.
- **Revue de branche refermée.** La tâche L3-T10 (`web: détail et
  correction d'un document`, commit `0edaf2c`) avait reçu un verdict
  « Needs fixes » (1 Important : l'état d'édition du détail document ne se
  réinitialisait pas après une écriture réussie — risque de réinsertion de
  lignes à un second enregistrement, trace de la valeur OCR d'un champ
  corrigé invisible jusqu'au rechargement). Deux tours de correction l'ont
  refermée :
  - **Fix round 1** (`81b0d85`, « web: état d'édition réinitialisé après
    enregistrement ») referme tout le mode édition et reconstruit
    `FormulaireEntete`/`TableauLignesEdition` depuis le détail renvoyé par
    l'API après un PATCH/PUT réussi — corrige le risque de réinsertion et
    la trace OCR invisible. La re-revue de ce tour a relevé une régression
    qu'il introduisait : enregistrer une section referme aussi le mode
    édition (et efface le brouillon non enregistré) de l'autre section.
  - **Fix round 2** (`4a50e02`, « web: édition indépendante de l'en-tête et
    des lignes », Ruling R16) : deux drapeaux d'édition indépendants
    (en-tête / lignes), chacun avec son propre bouton « Modifier »/
    « Annuler », refermé seulement par sa propre écriture réussie —
    conserve le bénéfice du tour 1 sans toucher au brouillon voisin.
  Les deux tours sont re-revus **clean** (`.superpowers/sdd/plan-lot-3/
  progress.md`, entrées « L3-T10: fix round 1/5 » et « fix round 2/5 »).
  La revue finale de branche (`379d5bc..07d3a73`, 28 commits) n'a plus
  relevé qu'un point de documentation — `CLAUDE.md`, cette passation et
  `docs/lot-3-recette.md` affirmaient à tort que L3-T10 restait ouvert
  alors qu'il était déjà corrigé — refermé par la présente mise à jour.
  **Le lot 3 est clos côté code**, prêt à être fusionné dans `main`.
- **Répertoire de cette tâche (L3-T12)** : `/home/debian/habitat_reno-wt-l3`,
  branche `lot-3-pur`, recréée au dernier commit de `lot-3-extraction`
  (`6ec0ab4`) — ce document, `docs/lot-3-recette.md` et les mises à jour de
  `docs/dette.md`/`CLAUDE.md` ont d'abord été commités là (`24c860c`), puis
  intégrés (cherry-pick) dans `lot-3-extraction` en `07d3a73`, une fois
  L3-T10 refermé. Cette mise à jour de clôture (vague finale : docstring
  `get_ocr_facture`, `--seuil nan`, noms accessibles des boutons « Modifier »/
  « Annuler », et la présente correction documentaire) est commitée
  directement sur `lot-3-extraction`.
- **Environnement de dev** (VPS partagé) : Postgres de dev
  `habitat_reno-postgres-1` (`127.0.0.1:5450`), base `bl` migrée à `head`
  (`0005`). `.env` par arbre (mode 600, `MISTRAL_API_KEY` réelle — toujours
  en attente de rotation depuis le lot 1, `docs/passation-lots-1-2.md`).
  Fixtures réelles ignorées par git :
  - `tests/fixtures/unikalo/` (facture d'août, héritée du lot 1) ;
  - `tests/fixtures/bl/` (**nouveau ce lot-ci**) : 4 photos réelles fournies
    par Ilane le 17/09 (3 Unikalo de deux agences, 1 bon d'enlèvement
    Point.P), leurs réponses OCR Mistral réelles en cache
    (`*.mistral-ocr.json`, régénérées une fois après L3-T6b pour le nouveau
    schéma d'annotation — les anciennes gardées à côté en
    `*.ancien-schema.json`) et leurs valeurs attendues écrites à la main
    (`*.attendu.json`, jamais confirmées mot à mot par Ilane).
  - **Absentes de l'arbre `/home/debian/habitat_reno-wt-l3`** (seul
    `tests/fixtures/README.md` y existe) : les tests qui en dépendent y
    `pytest.skip` (13 skips, cf. `docs/lot-3-recette.md` §6).
- **Journal détaillé** : `.superpowers/sdd/plan-lot-3/` — `progress.md`
  (dispatches, verdicts, rulings), fiches `L3-T*-brief.md`/`-controleur.md`,
  rapports `L3-T*-report.md`, `donnees/` (script + réponse Mistral inventés
  de L3-T1), `contraintes-revue.md`, `verification-front.md`.

---

## 2. Ce qui a été fait

Détail commit par commit et revue par revue dans `docs/lot-3-recette.md`
§1. Résumé :

| Tâche | Contenu |
| --- | --- |
| L3-T0 | Proxy Vite de dev réécrit `Origin` (corrige L2-R10) ; test derrière un vrai proxy ; base de migrations dérivée du nom de la base de test (second arbre de travail) |
| L3-T1 | `extract/confiance.py` : confiance d'une valeur à partir des scores OCR par mot (page + tableaux), confiances non finies ignorées |
| L3-T2 | `extract/bl.py` : schéma d'annotation Mistral, `BLExtrait`, `analyser_bl` |
| L3-T3 | `extract/verification.py` : `Motif`, `verifier_bl`, `verifier_facture` |
| L3-T4 | `normalize/` (nouveau paquet, pur) : fournisseur, chantier, unités, article |
| L3-T5 | Migration 0005 ; `ingest/referentiels.py` (résolution + `definir_fournisseur`) ; CLI `fournisseur-definir` |
| L3-T6 | `ingest/extraction_bl.py` : extraction complète d'un BL déposé, branchée sur le webhook ; reprise sur doublon concurrent |
| L3-T6b | Ajustements sur les 4 premiers BL réels : deux quantités par ligne, dates en toutes lettres, total/lignes absents toujours signalés, lignes éco typées, montants avec symbole devise |
| L3-T7 | `ingest/factures.py` : confiance réduite, motifs, alias, articles sur une facture déposée |
| L3-T8a | `ingest/corrections.py` + routes `api/documents.py` : détail, correction, validation, archivage, relance d'un document |
| L3-T8b | `ingest/a_traiter.py` + `ingest/referentiels.py` (complété) + routes `api/a_traiter.py`/`api/referentiels.py` : écran « À traiter », chantiers/fournisseurs/alias/articles |
| L3-T9 | Front : écran « À traiter », navigation, badges factures |
| L3-T10 | Front : détail et correction d'un document, revue refermée après deux tours de correction (`81b0d85`, `4a50e02` — voir §1) |
| L3-T11 | `ingest/rapport_ocr.py` + CLI `rapport-ocr` : outil de mesure du taux d'erreur OCR, `docs/protocole-mesure-ocr.md` |
| L3-T12 | Cette passation, `docs/lot-3-recette.md`, `docs/dette.md`, `CLAUDE.md` |

**Mesure réelle sur les 4 photos disponibles** (contrôleur, `rapport-ocr`,
aucune valeur client) : numéro 100 %, fournisseur 50 %, date 75 %, chantier
brut 75 %, documents aux 4 champs justes 50 %, lignes justes 66,7 %, **0
erreur silencieuse**, confiances justes ≥ 0,92, plus haute confiance fausse
0,83. Échantillon 6 à 7 fois trop petit pour conclure sur les seuils du CDC
§10 (30 photos dont 10 dégradées requises). Détail en
`docs/lot-3-recette.md` §4.

---

## 3. Décisions

### 3.1 Validées par Ilane (17/09/2026)

- Fourniture et autorisation d'envoi à l'OCR Mistral des 4 photos réelles de
  BL (3 Unikalo, 1 Point.P) — conservées dans `tests/fixtures/bl/`.
- Reprise du travail après une interruption de session API (« Reprend »),
  deux fois ce lot-ci (~10:40-11:00 et ~15:10-16:00).
- Mode de travail inchangé depuis les lots 1-2 : autonomie, sous-agents
  **Sonnet uniquement**, enchaîner les lots.

### 3.2 Prises en autonomie — décisions de conception (L3-D1 à L3-D26)

Liste complète, avec pourquoi/coût si faux et question associée quand il y
en a une, dans `docs/plan-lot-3.md` §4 et reproduite dans
`docs/lot-3-recette.md` §2. **À valider par Ilane** (questions Q1, Q3, Q4,
Q5, Q6, Q7 — non bloquantes, décisions provisoires déjà en place) :

- **Q1 / L3-D1** — un BL est lu par l'annotation structurée Mistral (schéma
  JSON commun aux deux fournisseurs) plutôt qu'un parseur déterministe par
  fournisseur, faute d'exemple de BL au moment de la décision.
- **Q3 / L3-D4** — champs obligatoires (fournisseur, numéro, date, chantier
  brut) et seuil de confiance provisoire à 0,80, à recaler sur les 30
  photos une fois disponibles (piste actuelle, sur seulement 4 photos :
  plutôt vers 0,90).
- **Q4 / L3-D14** — pas de validation forcée d'un document dont le BL
  imprimé lui-même est incohérent : l'admin doit corriger une valeur.
- **Q5 / L3-D17** — pas de correction d'une facture scannée à l'écran ce
  lot-ci (le CDC suppose des PDF natifs).
- **Q6 / L3-D11** — pas de fusion de BL sur deux pages ce lot-ci ; un
  doublon de numéro met le second document « à vérifier », archivable.
- **Q7 / L3-D8** — une agence fournisseur n'est jamais créée depuis le
  texte OCR, seulement rattachée si elle existe déjà (créée par la CLI).

### 3.3 Prises en cours d'exécution — rulings (R1 à R16)

Liste complète dans `docs/lot-3-recette.md` §2. En résumé (aucune n'a de
conséquence irréversible, rien n'est déployé) :

- **R1** donnée synthétique régénérée aux clés définitives du schéma L3-T2.
- **R2** ordre T9/T10 : lien vers `/documents/:id` posé avant que la route
  n'existe (redirection accueil entretemps).
- **R3** parallélisme flux pur / arbre principal, intégration cherry-pick.
- **R4** préfixe « chantier » sans borne de mot requalifié Important
  (corruption silencieuse de la clé d'alias).
- **R5** filet générique sur toute exception d'extraction inattendue
  (`enregistrer_echec_ocr`), jamais un document `recu` invisible.
- **R6** corrections de L3-T3 faites dans l'arbre séparé, cherry-pickées
  après L3-T6.
- **R7** confidentialité prime sur la formulation littérale d'une fiche :
  jamais d'égalité brute affichable sur une fixture réelle.
- **R8** tâche L3-T6b ajoutée (ajustements sur les 4 premiers BL réels,
  avant que L3-T8a/T9/T10 ne figent le format).
- **R9** L3-T7 dans l'arbre séparé pendant L3-T6b dans l'arbre principal.
- **R10** défaut TDD de L3-T6 traité par preuve (mutations délibérées,
  RED observé), pas par un nouveau code.
- **R11** doublon de numéro sur annotation illisible : contrôle avec
  `document.fournisseur_id`, pas `None` figé (corrigé par L3-T8a).
- **R12** même traitement que R10 pour L3-T7 (preuve déjà dans le rapport,
  finding parqué).
- **R13** §6 du protocole de mesure requalifié Important : option CLI
  `--seuil` ajoutée, protocole réécrit.
- **R14** journal de relance écrit après la réextraction (seconde
  transaction), pour survivre à une reprise sur doublon concurrent.
- **R15** L3-T9 : implémenteur épuisé en cours de correction, repris par un
  implémenteur neuf qui vérifie puis termine.
- **R16** L3-T10 fix round 2 : un drapeau d'édition par section (en-tête /
  lignes), chacun refermé par sa propre écriture, plutôt qu'un drapeau
  partagé — conserve le bénéfice du fix round 1 (état reconstruit depuis la
  réponse de l'API) sans perdre le brouillon de la section voisine.

---

## 4. Questions ouvertes (non bloquantes, décisions provisoires en place)

Q1, Q3, Q4, Q5, Q6, Q7 ci-dessus (§3.2). Plus, **bloquante** celle-ci :

- **Q2 — fichiers manquants.** Il faut, pour lever le blocage principal du
  lot (§5 de `docs/lot-3-recette.md`) :
  - au moins 30 photos de BL réelles dont 10 dégradées, avec leurs valeurs
    attendues écrites à la main (`docs/protocole-mesure-ocr.md`) ;
  - des factures et bons d'enlèvement Point.P ;
  - la liste des chantiers actifs avec leur agence ;
  - les SIRET/TVA des deux fournisseurs et les noms de leurs agences.

Héritées des lots précédents, toujours ouvertes : Q4 du lot 2 (identifiants
des deux groupes Telegram et vrai bot, bloquant pour tout test Telegram
réel), Q5 du lot 2 (format d'un avoir Unikalo).

---

## 5. Méthode qui a fonctionné (reconduite depuis les lots 1-2)

Inchangée par rapport à `docs/passation-lots-1-2.md` §5 : un plan par lot
(`docs/plan-lot-3.md`), skill `superpowers:subagent-driven-development`
(fiche → implémenteur Sonnet → relecteur Sonnet → tour de correction sur
Critical/Important → re-revue → mineurs consignés), journal
`progress.md`, fichier de règles d'exécution commun
(`.superpowers/sdd/plan-lot-3/execution.md`). Particularités de ce lot-ci :

- **Deux arbres de travail simultanés** presque en permanence :
  `/home/debian/habitat_reno` (arbre principal, branche
  `lot-3-extraction`) et `/home/debian/habitat_reno-wt-l3` (branche
  `lot-3-pur`, recréée plusieurs fois au commit courant de
  `lot-3-extraction` pour repartir d'une base à jour). Le flux « pur »
  (`extract`/`normalize`/`verification`, plus L3-T7 et L3-T12) tournait
  dans l'arbre séparé pendant que l'arbre principal avançait sur `ingest`/
  `api`/`web`, intégré ensuite par cherry-pick — cf. R3, R6, R9.
- **Essai réel en cours de lot** (constat 11 du plan) : après L3-T6, Ilane a
  fourni 4 photos réelles ; l'OCR a été appelé réellement dessus deux fois
  (avant et après le nouveau schéma d'annotation de L3-T6b), et une tâche
  supplémentaire (L3-T6b) a été insérée au milieu du plan pour corriger le
  cœur du format d'extraction avant qu'il ne soit figé par les tâches
  suivantes (Ruling R8).

---

## 6. Pièges rencontrés (à éviter)

En plus de ceux déjà listés dans `docs/passation-lots-1-2.md` §6 (toujours
valables : filtre de sécurité du mode auto sur les documents client,
mémoire du VPS, base de test partagée, worktrees/hooks partagés) :

- **Confiances non finies dans un score JSON.** `json.loads` accepte par
  défaut `NaN`/`Infinity`/`-Infinity` (extension Python non standard) : une
  réponse OCR corrompue portant l'une de ces valeurs dans un score de
  confiance faisait lever `decimal.InvalidOperation` au lieu d'être
  ignorée. Filtrer explicitement avec `math.isfinite` avant toute
  conversion en `Decimal`.
- **Preuve TDD rétroactive interdite par le mode auto.** `git checkout` sur
  un commit passé pour rejouer un vrai RED, même sur un arbre propre et
  entièrement récupérable, est refusé comme « destruction locale
  irréversible ». Solution qui a fonctionné : mutations délibérées
  appliquées une à la fois via l'outil d'édition (jamais `git stash`/
  `checkout` pour ce cas précis), `git diff` vérifié vide après chaque
  restauration individuelle (L3-T6, Ruling R10) ; `git stash push --
  <fichier>` / `stash pop` reste accepté pour retirer **temporairement**
  une implémentation déjà écrite et confirmer un RED (utilisé par L3-T7,
  L3-T8b).
- **JSON `null` ≠ SQL `NULL` en colonne JSONB.** Un test qui passe
  explicitement `champ=None` au constructeur ORM d'une colonne JSONB
  l'enregistre comme littéral JSON `null`, pas comme `NULL` SQL : une
  requête `colonne IS NOT NULL` répond alors « vrai » à tort. Ne jamais
  affecter explicitement `None` à une colonne JSONB dans un test — omettre
  l'argument pour laisser la colonne réellement `NULL` (trouvé et corrigé
  en L3-T7, uniquement dans un helper de test, jamais atteignable par le
  code de production).
- **Rattraper une `IntegrityError` en `try`/`except` implique de resupprimer
  les lignes déjà supprimées par le rollback avant de rejouer** (le
  `DELETE` initial est lui aussi annulé) — sinon la seconde tentative
  échoue sur des lignes fantômes (L3-T6, doublon de numéro concurrent).
- **Un journal ajouté à la session *avant* un appel qui peut déclencher un
  rollback interne (reprise sur `IntegrityError`) disparaît avec lui.**
  Écrire un journal d'audit obligatoire dans une transaction/commit séparé
  **après** l'opération qu'il documente, jamais avant dans la même session
  non commitée (L3-T8a, Ruling R14).
- **Objets ORM expirés après plusieurs `commit()`/`rollback()` dans un même
  test** (`expire_on_commit`, par défaut) : un accès synchrone à un
  attribut hors `await` lève `sqlalchemy.exc.MissingGreenlet`. Rafraîchir
  explicitement l'objet avant de comparer ses attributs après une séquence
  de reprise.
- **Épuisement de contexte d'un sous-agent en plein tour de correction**
  (L3-T9, ~393k jetons) : le travail était commité mais le rapport non
  écrit. Un nouvel implémenteur peut reprendre en relisant le diff déjà
  commité plutôt que de tout refaire — vérifier d'abord `git status`/
  `git log` avant de relancer un travail qui pourrait déjà exister.
- **Deux exécutions indépendantes de la même tâche de correction ont pu se
  chevaucher** (L3-T9 fix round 1) : la seconde a constaté que la première
  avait déjà terminé (diff et message de commit identiques à l'octet près)
  et n'a rien recommité — vérifier `git status`/le dernier commit avant
  d'écrire quoi que ce soit en reprenant une tâche.

---

## 7. Point de départ du lot 4 — Rapprochement (CDC §11)

Prérequis rempli : le point de revue L3-T10 (§1) est refermé et la branche
`lot-3-extraction` a passé sa revue finale — le lot 3 peut être fusionné
dans `main` avant, ou en même temps que le démarrage du lot 4.

**Contenu du lot 4** (CDC §11) :
- Rapprochement BL ↔ blocs de facture (correspondance déjà esquissée au
  lot 2 pour l'onglet « BL déposés », `documents_bl_par_numeros`) ;
- conversion d'unités et de quantités via le ratio d'article proposé
  (`normalize/article.py::proposer_ratio`, déjà en place, jamais encore
  appliqué à une comparaison réelle — `ligne.qte_fact` toujours vide) ;
- gestion des avoirs (toujours aucun exemple disponible, Q5 du lot 2) ;
- moteur de règles déterministes R01 à R17 (`app/modules/rules/`, dossier
  prévu par l'architecture, pas encore créé) ;
- écran « Anomalies ».

**Point de départ dans le code** :
- `extract/verification.py` : motifs déjà posés côté BL/facture, à
  distinguer des anomalies de rapprochement (probablement un autre
  vocabulaire/une autre table, à trancher) ;
- `ligne.qte_totale`/`qte_livree`/`qte_fact` : les deux premières sont
  renseignées depuis L3-T6b (même sens que la facture, L3-D24) ;
  `qte_fact` (conversion effective) reste à calculer, explicitement reporté
  au lot 4 par L3-D9 ;
- `normalize/article.py::proposer_ratio`/`PropositionArticle` : le ratio
  conditionnement ↔ facturation est déjà proposé et stocké sur `article`
  (colonnes `ratio`, `valide`), mais jamais appliqué à une comparaison
  BL/facture ;
- `chantier_alias`/`Article.valide` : le flux de validation humaine
  (écran « À traiter ») existe déjà pour les deux, réutilisable tel quel ;
- `docs/dette.md` à reprendre : parseur Point.P non construit (bloque tout
  rapprochement avec ce fournisseur), pas de fusion de documents
  multi-pages (un doublon de numéro reste juste « à vérifier »), pas de
  correction de facture à l'écran.

**Avant de commencer le lot 4** :
1. vérifier la disponibilité des 30 photos réelles et des documents
   Point.P (Q2) — sans eux, ni le rapport CDC §10 ni le parseur Point.P
   ne peuvent être complétés, et le rapprochement avec ce fournisseur reste
   bloqué ;
2. relire `docs/dette.md` (sections lot 3 en particulier).
