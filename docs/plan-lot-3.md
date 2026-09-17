# Plan — Lot 3 (Extraction)

> **Pour les agents :** exécuté par `superpowers:subagent-driven-development` (une fiche par tâche, implémenteur Sonnet, relecteur Sonnet). Chaque tâche = un commit (plus d'éventuels commits de correction).

**Objectif (CDC §11) :** OCR des BL, contrôle de cohérence, écran « À traiter » avec correction, normalisation fournisseur / chantier / article avec validation des alias, parseur Point.P. Le client voit à la fin du lot le **rapport du taux d'erreur OCR sur 30 BL réels**.

**Critères de réception (CDC §10, lot Extraction) :**
- Sur au moins 30 photos de BL réelles, dont au moins 10 dégradées : numéro de BL, fournisseur, date et chantier brut corrects pour ≥ 95 % des documents.
- Lignes (code, quantité) correctes pour ≥ 90 % des lignes ; toute ligne fausse dont la confiance était haute est analysée et documentée.
- Aucune erreur silencieuse : tout document dont la somme des lignes ne correspond pas au total est « à vérifier » (100 %).

**Architecture :** on s'appuie sur les lots 1 et 2 (`ingest` seul orchestrateur ; `extract` pur ; `api` couche d'entrée qui n'importe que `ingest` et `app.core` ; front React servi par l'API). Ce lot ajoute :
- `extract/confiance.py` (score de confiance par valeur à partir des scores par mot de Mistral), `extract/bl.py` (lecture d'un BL depuis l'annotation Mistral), `extract/verification.py` (cohérence, champs obligatoires, seuil de confiance) ;
- le module pur `normalize/` (texte, fournisseur, chantier, unités, article) ;
- côté `ingest` : référentiels (résolution fournisseur/chantier/article), extraction des BL, corrections, écran « À traiter », outil de mesure OCR ;
- deux écrans front : « À traiter » et le détail/correction d'un document.

**Spec :** `docs/cahier-des-charges.md` (§2, §3, §4.3, §4.4, §4.6, §5 R11/R14, §6, §10, §11, §13). À lire aussi : `docs/passation-lots-1-2.md`, `docs/dette.md`.

**Statut :** plan écrit en autonomie (mandat d'Ilane : enchaîner les lots, 17/09/2026), exécuté sans validation préalable. Chaque décision prise sans Ilane est listée en §4 avec son coût si elle est mauvaise.

---

## 1. Contraintes globales

Celles des lots 1 et 2 (`docs/plan-lot-1.md` §1, `docs/plan-lot-2.md` §1, `CLAUDE.md`) s'appliquent toutes. Rappel des plus exposées dans ce lot :
- `extract`, `normalize`, `rules` : ni FastAPI, ni Starlette, ni SQLAlchemy, ni httpx, ni asyncpg ; entrées et sorties en dataclasses ; aucun import d'un autre module de `app.modules` (y compris : `normalize` n'importe pas `extract`, et inversement). Tests sans base ni réseau.
- `api` n'importe que `app.core` et `app.modules.ingest` (L2-D3). Aucune règle métier dans les routers ni dans le front : le router valide, appelle un service `ingest`, sérialise.
- Montants, quantités, confiances : `Decimal`, jamais `float` (sauf lecture brute du JSON Mistral, convertie immédiatement via `Decimal(str(x))`).
- Toute action d'un utilisateur qui modifie une donnée métier est journalisée (`journal` : auteur, action, cible, avant, après, horodatage). Les résolutions automatiques sont journalisées avec `utilisateur_id = NULL`.
- **Données client** : aucune valeur réelle (nom, chantier, numéro, montant) dans le code commité, les messages de commit, les journaux applicatifs ou les messages d'assertion. Les tests commités n'utilisent que des données inventées. Les fixtures réelles restent dans `tests/fixtures/` (ignoré par git) ; un test qui les lit fait `pytest.skip` si elles sont absentes et n'affiche que des comptes.
- Aucun envoi de document client à un service extérieur pendant le développement. Les appels réels à Mistral ne se font qu'avec des documents **inventés**.
- Interface en français. Pas de tests unitaires front (L2-D17) : `typecheck` + `build` + parcours manuel.

## 2. Constats (état au début du lot 3, `main` @ `59a2880`)

1. **Aucune photo de BL ni aucun document Point.P n'est sur le disque** (`tests/fixtures/` ne contient que la facture Unikalo d'août, sa réponse OCR et sa référence). Les 4 photos du lot 1 n'ont jamais été déposées. Le livrable du lot (taux d'erreur sur 30 BL réels) et le parseur Point.P ne peuvent donc pas être faits ni mesurés dans ce lot : on construit tout ce qui n'en dépend pas, dont l'outil de mesure, et on consigne le blocage.
2. Sur une photo, seul le numéro de BL est lu aujourd'hui (`extract/ocr.py::detecter_numero_bl`, motifs « LIVRAISON N°L… » Unikalo et « Bon d'enlèvement N° … » Point.P). On ne connaît rien d'autre de la mise en page des BL des deux fournisseurs.
3. **L'API Mistral OCR fournit ce qu'il faut pour les deux besoins du lot** (vérifié le 17/09/2026 par un appel réel sur une image de BL **inventée**, générée localement) :
   - `confidence_scores_granularity: "word"` renvoie, par page, `confidence_scores = {average_page_confidence_score, minimum_page_confidence_score, word_confidence_scores: [{text, confidence, start_index}]}` où `start_index` indexe `page["markdown"]` ; chaque tableau (`page["tables"][i]`) porte ses propres `word_confidence_scores`, indexés dans `table["content"]`. `text` peut commencer par une espace (l'espace appartient au mot suivant). Les tableaux ne sont que référencés dans `page["markdown"]` (`[tbl-0.md](tbl-0.md)`).
   - `document_annotation_format: {"type": "json_schema", "json_schema": {"name", "schema", "strict": true}}` + `document_annotation_prompt` renvoie `document_annotation` : **une chaîne JSON** conforme au schéma, dans la même réponse que l'OCR et les scores.
   - La réponse obtenue est commitée (données inventées) comme donnée de test : `app/modules/extract/tests/donnees/bl_synthetique.mistral-ocr.json` (tâche L3-T1 ; copie de `.superpowers/sdd/plan-lot-3/donnees/bl_synthetique.mistral-ocr.json`, produite par `bl_synthetique.py` du même dossier avec le schéma définitif de L3-T2). Valeurs inventées qu'elle contient : fournisseur « PEINTURES EXEMPLE SAS », BL « L209900000123 » du 03/09/2026, chantier « MAISON TEST (9900000001) », 3 lignes (AB1234 ×4 SEAU 126,00 ; CD5678 ×2 U 24,50 ; EF9012 ×10 M 11,00), total HT 161,50.
4. Le document est commité en base (`recu`) **avant** l'OCR (`ingest/depot_telegram.py::traiter_fichier`), puis `_executer_ocr` met à jour `numero`, `type`, `statut`. Un échec d'OCR laisse le document `recu` sans numéro : il est invisible pour l'admin (dette T6b).
5. Le modèle de données n'a pas de chantier sur `document` (seulement sur `bloc_facture`), ni référence commande, ni « enlevé par », ni totaux TVA/TTC, ni emplacement pour les valeurs OCR d'origine ou les motifs de mise « à vérifier ». Les colonnes `document.confiance_min`, `chantier_alias`, `article`, `ligne.qte_fact` existent.
6. `chantier_alias` a une contrainte d'unicité `(fournisseur_id, libelle_brut, code_brut)` alors que le CDC §4.4 interdit d'utiliser le code chantier fournisseur comme clé (il change d'une commande à l'autre).
7. Les lignes de facture Unikalo n'ont pas de colonne unité (`LigneFacture.unite` toujours `None`) mais portent `qte_livree` (conditionnements) et `qte_totale` (unité de facturation) : c'est la base de la proposition de ratio (4 seaux ↔ 100 kg).
8. Point ouvert L2-R10 : `app/core/origine.py` refuse les POST passant par le proxy de `npm run dev` (Origin du serveur Vite ≠ hôte réécrit). Aucun test « derrière proxy » (X-Forwarded-Proto) n'existe. Le Dockerfile lance bien uvicorn avec `--proxy-headers --forwarded-allow-ips=*`.
9. `tests/conftest.py::url_base_migrations` force le nom `bl_test_migrations` : deux arbres de travail qui testent sur le même Postgres se marchent dessus, même avec des `TEST_DATABASE_URL` différentes.
10. Pre-commit lance la suite pytest complète à chaque commit : un seul commit à la fois par base de test.

## 3. Questions à Ilane (non bloquantes, décisions provisoires en §4)

- **Q1 — Extraction des BL par annotation Mistral.** Faute d'exemple de BL, les champs d'une photo sont extraits par l'annotation structurée de l'API Mistral OCR (un schéma JSON commun aux deux fournisseurs), puis contrôlés de façon déterministe (chaque valeur doit se retrouver dans le texte OCR, sinon confiance 0 ; somme des lignes ; numéro recoupé par le motif existant). D'accord, ou faut-il un parseur déterministe par fournisseur écrit sur les 30 photos ? (provisoire : annotation, L3-D1)
- **Q2 — Fichiers manquants (bloquants pour le livrable).** Les 30 photos de BL réelles (dont 10 dégradées) avec, pour chacune, les valeurs attendues ; des factures et BL Point.P ; la liste des chantiers actifs avec leur agence ; SIRET/TVA des deux fournisseurs et noms de leurs agences. Sans eux : pas de rapport de taux d'erreur, pas de parseur de facture Point.P.
- **Q3 — Champs obligatoires et seuil.** Obligatoires provisoires : fournisseur, numéro, date, chantier brut (les 4 champs du critère §10). Un bon d'enlèvement Point.P sans chantier imprimé partirait toujours « à vérifier ». Seuil de confiance provisoire 0,80, à recaler sur les 30 photos (le rapport de mesure donne la distribution des confiances des champs justes et faux).
- **Q4 — Validation d'un document fournisseur faux.** Si le BL imprimé lui-même est incohérent (somme ≠ total), l'admin ne peut pas le valider sans corriger une valeur. Faut-il une validation forcée avec commentaire ? (provisoire : non, L3-D14)
- **Q5 — Correction des factures scannées.** Le lot 3 marque une facture incohérente « à vérifier » mais ne permet pas de la corriger à l'écran (le CDC suppose des PDF natifs). À confirmer. (provisoire : pas de correction de facture, L3-D17)
- **Q6 — Fusion de deux documents (BL sur deux pages, CDC §4.1).** Aucun lot ne la cite explicitement. Lot 3 ou lot 5 ? (provisoire : non construite au lot 3 ; un doublon de numéro met le second document « à vérifier » et l'admin peut l'archiver, L3-D11)
- **Q7 — Agences fournisseur.** Rattachées à un document seulement si elles existent déjà (créées par la CLI `fournisseur-definir`), jamais créées automatiquement à partir du texte OCR. D'accord ? (provisoire : oui, L3-D8)

## 4. Décisions prises en autonomie

| # | Décision | Pourquoi | Coût si faux |
| --- | --- | --- | --- |
| L3-D1 | **Lecture d'une photo de BL = un seul appel Mistral OCR** avec `table_format: markdown`, `confidence_scores_granularity: "word"`, `document_annotation_format` (schéma JSON `SCHEMA_ANNOTATION_BL`, toutes les valeurs en chaînes « telles qu'imprimées » ou `null`) et `document_annotation_prompt`. `extract/bl.py` lit `document_annotation` et convertit (nombres, dates) de façon déterministe | Aucun exemple de BL (constat 1) : un parseur par fournisseur écrit à l'aveugle serait faux ; l'annotation couvre Unikalo et Point.P sans les connaître, dans la stack (API Mistral OCR) ; l'IA extrait, elle ne décide pas | Écrire des parseurs déterministes par fournisseur sur les 30 photos ; `BLExtrait` et tout l'aval restent inchangés |
| L3-D2 | **Confiance d'une valeur** = on cherche la valeur brute dans le texte OCR (markdown de page et contenu des tableaux), bornée par des caractères non alphanumériques, insensible à la casse, espaces souples ; pour chaque occurrence, minimum des confiances des mots qui la recouvrent ; on garde la meilleure occurrence. Valeur introuvable → confiance **0** (l'annotation a inventé ou reformulé). Scores absents → `None`. Pour une ligne d'articles, les valeurs sont cherchées dans **une même ligne source** (celle qui en contient le plus) | Détecte les valeurs inventées ou reformulées sans rien deviner ; un « 4 » isolé ailleurs dans le document ne doit pas confirmer la quantité d'une ligne | Recalage de l'algorithme sur les 30 photos |
| L3-D3 | Motifs de mise « à vérifier » d'un BL, calculés par `extract/verification.py::verifier_bl` : champ obligatoire absent, valeur illisible (brut présent mais non convertible), confiance sous le seuil (champs obligatoires, `total_ht`, et chaque ligne), somme des montants des lignes ≠ `total_ht` au-delà de la tolérance, total absent alors qu'au moins une ligne a un montant, numéro lu ≠ numéro détecté par le motif. `ingest` ajoute : échec OCR, annotation illisible, fournisseur inconnu, numéro en double. Un document avec au moins un motif est `a_verifier` | CDC §4.3 et §10 « aucune erreur silencieuse » | Motifs à ajuster |
| L3-D4 | Champs obligatoires d'un BL : `fournisseur`, `numero`, `date_doc`, `chantier_brut`. Seuil de confiance par défaut `0.80`, tolérance `0.05` €. Les fonctions pures reçoivent seuil et tolérance en paramètres ; `ingest` lit `parametre` (clés `seuil_confiance_ocr`, `tolerance_total_ht`) avec ces défauts. L'écran de paramétrage est au lot 5 | Q3 ; CDC §5 « seuils modifiables » | Valeurs à changer en base |
| L3-D5 | Migration 0005 : `document` + `chantier_brut text`, `chantier_id uuid → chantier`, `numero_commande text`, `enleve_par text`, `total_tva numeric`, `total_ttc numeric`, `extraction jsonb` (instantané immuable de l'extraction OCR : valeurs brutes, valeurs converties, confiances, motifs d'origine), `motifs jsonb` (motifs courants) ; `ligne` + `confiance numeric` | Constat 5 ; « valeur OCR d'origine conservée » (CDC §4.3) ; le Bilan et R16 ont besoin du chantier d'un BL | Colonnes à retirer |
| L3-D6 | **Clé d'alias chantier** = `(fournisseur_id, libellé normalisé)` : `libelle_brut` stocke le libellé normalisé (sans accents, minuscules, ponctuation réduite, code entre parenthèses retiré), `code_brut` reste toujours `NULL`. Le libellé brut complet reste sur `document.chantier_brut` / `bloc_facture.chantier_brut` | Constat 6 : le code change d'une commande à l'autre, il ne peut pas être une clé ; la contrainte existante est conservée sans migration | Une migration de contrainte |
| L3-D7 | Alias inconnu → ligne `chantier_alias` avec `chantier_id NULL` (« demande de validation », `INSERT … ON CONFLICT DO NOTHING`). Pas d'alias créé tant que le fournisseur n'est pas résolu. La validation (rattacher à un chantier existant ou créé) renseigne `chantier_id`, `valide_par`, `valide_le` et propage `chantier_id` aux documents et blocs de facture de ce fournisseur au même libellé normalisé encore non résolus. Un alias inconnu ne met **pas** le document « à vérifier » (CDC §10 : pas un motif de refus) | CDC §4.4 | — |
| L3-D8 | Fournisseur d'un BL résolu par `normalize/fournisseur.py` : SIREN (9 premiers chiffres du SIRET lu) puis numéro de TVA, puis nom (tous les mots d'un nom ou alias du référentiel présents dans le nom lu), résultat unique exigé sinon non résolu. Jamais créé automatiquement. Agence : rattachée si une agence existante du fournisseur a tous ses mots dans l'agence lue, jamais créée. Référentiel alimenté par la CLI `fournisseur-definir` | CDC §4.4 ; Q7 ; évite de polluer le référentiel avec du bruit OCR | Écran référentiel au lot 5 |
| L3-D9 | Article : clé `(fournisseur_id, code)`, créé automatiquement (`valide = false`) à la première ligne portant un code. Depuis une facture : `libelle`, ratio proposé = `qte_totale / qte_livree` quand les deux existent et diffèrent. Depuis un BL : `libelle`, unité lue classée conditionnement (`unite_cdt`) ou mesure (`unite_fact`). Un article existant non validé est complété (champs vides seulement), jamais écrasé. « À valider » = non validé avec un ratio proposé ≠ 1. La conversion `qte_fact` est faite au lot 4 | CDC §4.4 ; §11 place la conversion au lot 4 | Liste « à valider » plus large |
| L3-D10 | Un échec d'OCR ou une annotation illisible met le document `a_verifier` avec le motif correspondant (au lieu de le laisser `recu` sans numéro). Si le motif existant détecte quand même un numéro, il est enregistré | Constat 4 : plus aucun document invisible | — |
| L3-D11 | Numéro déjà porté par un autre document du même fournisseur : le numéro n'est **pas** écrit sur le document (contrainte d'unicité), il reste dans `extraction`, motif `numero_en_double` avec le numéro interne de l'autre document. L'admin peut archiver le doublon (`statut = archive`, commentaire obligatoire, journal) | Unicité `(fournisseur_id, numero)` ; deux photos du même BL arriveront (renvoi, deux pages) ; Q6 | Fusion à construire |
| L3-D12 | Type du document : motif `detecter_numero_bl` d'abord (livraison → `bl`, enlèvement → `enlevement`), sinon champ `type_bon` de l'annotation, sinon `bl` | Le motif est déterministe et déjà en place | — |
| L3-D13 | Corrections par l'admin sur un BL non archivé : `PATCH /api/documents/{id}` (champs d'en-tête), `PUT /api/documents/{id}/lignes` (liste complète : mise à jour par `id`, ajout sans `id`, suppression des absentes). Chaque écriture : journal `document_corrige` / `lignes_corrigees` avec avant/après (seulement ce qui change), nouvelle résolution chantier/articles si fournisseur ou chantier change, recalcul des motifs **structurels** (sans confiance : l'humain a vu le document), une ligne modifiée ou ajoutée a `confiance = NULL`. La valeur OCR d'origine reste dans `extraction` | CDC §4.3 « valeur corrigée tracée, valeur OCR conservée » | — |
| L3-D14 | « Valider » (`POST /api/documents/{id}/validation`, admin, document `a_verifier`) : recalcule les motifs structurels ; aucun → `statut = recu`, `motifs = []`, journal `document_valide` ; sinon 409 avec les motifs. Pas de validation forcée | Q4 ; CDC §5 : les règles ne tournent pas tant que l'admin n'a pas corrigé | Ajouter une validation forcée commentée |
| L3-D15 | « Relancer l'extraction » (`POST /api/documents/{id}/extraction`, admin, document `a_verifier`) : relit le fichier, rappelle l'OCR, remplace valeurs et lignes par la nouvelle extraction, le document reste `a_verifier` (seul « Valider » le fait passer `recu`), journal `extraction_relancee` avec les anciennes valeurs | Dette T6b (aucune reprise après échec d'OCR) | — |
| L3-D16 | Facture déposée : OCR avec `confidence_scores_granularity: "page"` ; `confiance_min` = plus petit `minimum_page_confidence_score` ; « confiance réduite » exposée par l'API (`confiance_reduite = ocr_brut IS NOT NULL`) ; somme des montants des blocs ≠ total HT au-delà de la tolérance → `a_verifier` + motif ; chantier de chaque bloc et article de chaque ligne résolus comme pour un BL. Fournisseur toujours « Unikalo » (parseur Unikalo) | Dette L2-R5 ; CDC §4.2, §4.3 | — |
| L3-D17 | Pas de correction de facture à l'écran au lot 3 : une facture « à vérifier » apparaît dans « À traiter » et renvoie vers son détail en lecture. Dette notée | Q5 ; le CDC suppose des factures PDF natives | Écran de correction de facture |
| L3-D18 | Écran « À traiter » réservé à l'admin (mobile d'abord) : documents « à vérifier » (BL, enlèvements et factures) avec motifs et état de confirmation, alias chantier en attente, articles à valider. La section « anomalies de gravité haute » arrive au lot 4. Accueil de l'admin : « À traiter » ; de l'agent : « BL déposés » | CDC §3, §4.6 | Ouvrir une vue agent |
| L3-D19 | Détail d'un BL (`GET /api/documents/{id}`) ouvert à l'admin (tous) et à l'agent (ses dépôts, en lecture seule) ; une facture y renvoie 404 (elle a sa route). Photo affichée depuis `/api/documents/{id}/fichier` | CDC §3 : l'agent voit les BL qu'il a déposés | — |
| L3-D20 | **Outil de mesure** : `python -m app.cli rapport-ocr <dossier> --sortie <rapport.md> [--appeler-ocr]`. Le dossier contient chaque photo et un `<nom>.attendu.json` écrit à la main ; la réponse OCR est mise en cache dans `<nom>.mistral-ocr.json` (appel réel seulement avec `--appeler-ocr`). Le rapport donne les taux par champ, le taux de lignes justes, les erreurs silencieuses, les lignes fausses à confiance haute et la distribution des confiances. Stdout : comptes seulement. Protocole de collecte dans `docs/protocole-mesure-ocr.md` | Le livrable du lot devient une commande dès que les photos arrivent | — |
| L3-D21 | L2-R10 corrigé côté **dev** : le proxy Vite réécrit l'en-tête `Origin` vers sa cible. Le contrôle serveur reste strict. Test « derrière proxy » ajouté avec `ProxyHeadersMiddleware` d'uvicorn | Aucun affaiblissement en production | — |
| L3-D22 | `url_base_migrations` dérive le nom de la base de migrations de celui de la base de test (`<base>_migrations`) : `bl_test` → `bl_test_migrations` (inchangé), `bl_test_wt` → `bl_test_wt_migrations`. Permet à un second arbre de travail de tester en parallèle sur le même Postgres | Constat 9 ; mémoire du VPS (pas de second conteneur) | — |
| L3-D23 | Parseur Point.P (facture) **non construit** : aucun document Point.P disponible. Les bons d'enlèvement Point.P passent par la même extraction que les BL (L3-D1) | CLAUDE.md : « si quelque chose n'y est pas, on ne le construit pas » ; constat 1 | Tâche à ouvrir dès réception |

## 5. Structure des fichiers

```
web/vite.config.mts                              L3-T0  proxy : réécriture d'Origin
app/core/tests/test_origine.py                   L3-T0  test derrière proxy
tests/conftest.py                                L3-T0  base de migrations dérivée
app/modules/extract/confiance.py                 L3-T1  index des scores par mot, confiance d'une valeur
app/modules/extract/tests/test_confiance.py      L3-T1
app/modules/extract/tests/donnees/bl_synthetique.mistral-ocr.json   L3-T1 (données inventées)
app/modules/extract/bl.py                        L3-T2  schéma d'annotation, BLExtrait, analyser_bl, JSON
app/modules/extract/tests/test_bl.py             L3-T2
app/modules/extract/verification.py              L3-T3  Motif, verifier_bl, verifier_facture
app/modules/extract/tests/test_verification.py   L3-T3
app/modules/normalize/__init__.py                L3-T4
app/modules/normalize/texte.py                   L3-T4  normaliser_libelle
app/modules/normalize/fournisseur.py             L3-T4  SIRET/TVA, resoudre_fournisseur, resoudre_agence
app/modules/normalize/chantier.py                L3-T4  decomposer_chantier
app/modules/normalize/unites.py                  L3-T4  normaliser_unite
app/modules/normalize/article.py                 L3-T4  proposer_ratio, propositions d'article
app/modules/normalize/tests/                     L3-T4
migrations/versions/0005_extraction.py           L3-T5
app/modules/ingest/models.py                     L3-T5  colonnes de la migration 0005
app/modules/ingest/referentiels.py               L3-T5  chargement/résolution, paramètres ; L3-T8b opérations admin
app/modules/ingest/tests/test_referentiels.py    L3-T5, L3-T8b
app/cli.py                                       L3-T5 (fournisseur-definir), L3-T11 (rapport-ocr)
app/modules/ingest/mistral.py                    L3-T6  options de requête
app/modules/ingest/extraction_bl.py              L3-T6  extraction et enregistrement d'un BL
app/modules/ingest/depot_telegram.py             L3-T6  branchement, supervision
app/modules/ingest/router.py                     L3-T6 (get_ocr BL), L3-T7 (get_ocr_facture)
app/modules/ingest/tests/test_extraction_bl.py   L3-T6
app/modules/ingest/factures.py                   L3-T7
app/modules/ingest/lecture.py                    L3-T7 (factures), L3-T8a (documents)
app/modules/ingest/corrections.py                L3-T8a détail, corrections, validation, archivage, relance
app/modules/ingest/tests/test_corrections.py     L3-T8a
app/modules/ingest/a_traiter.py                  L3-T8b
app/modules/api/documents.py                     L3-T8a
app/modules/api/a_traiter.py                     L3-T8b
app/modules/api/referentiels.py                  L3-T8b chantiers, fournisseurs, alias, articles
app/modules/api/schemas.py                       L3-T7, L3-T8a, L3-T8b
app/modules/api/__init__.py                      L3-T8b
app/modules/api/tests/                           L3-T7, L3-T8a, L3-T8b
web/src/...                                      L3-T9 (À traiter, navigation, badges factures), L3-T10 (détail document)
app/modules/ingest/rapport_ocr.py                L3-T11
app/modules/ingest/tests/test_rapport_ocr.py     L3-T11
docs/protocole-mesure-ocr.md                     L3-T11
docs/lot-3-recette.md, docs/dette.md             L3-T12
```

## 6. Tâches

Ordre et parallélisme : L3-T0 d'abord. Puis deux flux : **flux pur** dans un arbre de travail séparé (L3-T1 → L3-T2 → L3-T3, base de test `bl_test_wt`) et **flux principal** (L3-T4 → L3-T5). Intégration du flux pur par cherry-pick (fichiers disjoints), puis L3-T6 → L3-T7 → L3-T8a → L3-T8b → L3-T9 → L3-T10, avec L3-T11 en parallèle du front dans l'arbre séparé, et L3-T12 en dernier.

### L3-T0 — `core: contrôle d'origine derrière proxy et en dev Vite`
- `web/vite.config.mts` : le proxy `/api` réécrit l'en-tête `Origin` de la requête sortante vers l'origine de sa cible (`http://127.0.0.1:8450`), via `configure: (proxy) => proxy.on("proxyReq", ...)` ou l'option `headers`, selon ce qui fonctionne réellement avec la version de Vite installée. `changeOrigin: true` conservé.
- `app/core/tests/test_origine.py` : application de test enveloppée par `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware(app, trusted_hosts="*")` :
  - `POST /api/...` avec `X-Forwarded-Proto: https`, `Host: bl.example.invalid`, `Origin: https://bl.example.invalid` → pas 403 ;
  - même requête avec `Origin: http://bl.example.invalid` → 403 ;
  - même requête avec `Origin: https://autre.example.invalid` → 403.
- `tests/conftest.py::url_base_migrations` : nom dérivé `f"{nom_de_la_base_de_test}_migrations"` (L3-D22) ; docstrings de `tests/conftest.py` et `tests/test_migrations.py` mises à jour.
- Vérification manuelle (rapport) : uvicorn local sur 8450 branché sur la base de dev, `npm --prefix web run dev` sur un port libre, `curl -X POST http://127.0.0.1:<port vite>/api/auth/login -H 'Origin: http://127.0.0.1:<port vite>' -d 'username=inconnu@example.invalid&password=x'` → **400** (identifiants refusés), pas 403. Arrêter les deux processus ensuite.

### L3-T1 — `extract: confiance d'une valeur à partir des scores OCR par mot`
Fichier `app/modules/extract/confiance.py` (pur). Données de test : copier la réponse inventée (constat 3) dans `app/modules/extract/tests/donnees/bl_synthetique.mistral-ocr.json`, avec un `README.md` d'une ligne dans le même dossier (« réponse réelle de l'API Mistral OCR sur une image de BL inventée, aucune donnée client »).

Interfaces :
```python
@dataclass(frozen=True)
class Mot:
    debut: int            # index du premier caractère dans le texte de la source
    fin: int              # index exclusif
    confiance: Decimal    # Decimal(str(float)) arrondi à 4 décimales (ROUND_HALF_UP)

@dataclass(frozen=True)
class Source:
    texte: str                  # page["markdown"] ou table["content"]
    mots: tuple[Mot, ...]

@dataclass(frozen=True)
class IndexConfiance:
    sources: tuple[Source, ...]

    @property
    def disponible(self) -> bool: ...   # au moins une source a au moins un mot

def indexer_confiance(reponse: dict[str, Any]) -> IndexConfiance
def confiance_valeur(index: IndexConfiance, valeur: str | None) -> Decimal | None
def confiances_ligne(index: IndexConfiance, valeurs: Sequence[str | None]) -> tuple[Decimal | None, ...]
def confiance_min_pages(reponse: dict[str, Any]) -> Decimal | None
```
Règles :
- `indexer_confiance` : pour chaque page, une source `page["markdown"]` avec `page["confidence_scores"]["word_confidence_scores"]`, puis une source par tableau `page["tables"][i]["content"]` avec `table["word_confidence_scores"]`. Un mot = `[start_index, start_index + len(text))`. Entrées mal formées (types inattendus, index hors texte) ignorées sans lever. Réponse sans `pages` → index vide.
- `confiance_valeur` : `None` si `valeur` est `None` ou blanche, ou si `index.disponible` est faux. Motif : jetons de `valeur.split()` échappés, joints par `\s+`, encadrés par `(?<!\w)` et `(?!\w)`, `re.IGNORECASE`. Si la valeur ressemble à un nombre (`^-?[\d\s]+(?:[.,]\d+)?$`), on cherche aussi la variante avec l'autre séparateur décimal. Pour chaque occurrence dans chaque source : minimum des confiances des mots qui recouvrent `[debut, fin)` (recouvrement : `mot.debut < fin and mot.fin > debut`) ; occurrence sans mot recouvrant ignorée. Résultat : maximum sur les occurrences ; aucune occurrence retenue → `Decimal("0")`.
- `confiances_ligne` : découpe chaque source en lignes (`\n`) avec leurs décalages ; retient la ligne source qui contient le plus de valeurs non nulles (égalité : meilleur minimum de confiance, puis première rencontrée) ; chaque valeur non nulle reçoit sa confiance calculée **dans cette ligne seulement** (absente de la ligne → `0`) ; valeur nulle → `None`. Si aucune ligne ne contient aucune valeur : `0` pour chaque valeur non nulle. `None` partout si l'index n'est pas disponible.
- `confiance_min_pages` : plus petit `minimum_page_confidence_score` des pages qui en ont un, `None` sinon.

Tests (données inventées, construites dans le test ou lues depuis `donnees/`) :
- mots avec espace initiale : la valeur « EXEMPLE SAS » prend le minimum des deux mots, pas du mot précédent ;
- deux occurrences (confiances 0,6 et 0,95) → 0,95 ;
- valeur absente du texte → 0 ; valeur `None`/blanche → `None` ; réponse sans scores → `None` ;
- bornes : « 4 » n'est trouvé ni dans « 24,50 » ni dans « 4X5 » ; « L209900000123 » est trouvé dans « N°L209900000123 » ;
- casse différente trouvée ; espaces multiples dans le texte trouvés ; « 126.00 » trouvé dans « 126,00 » ;
- ligne : code et quantité dans la même ligne de tableau → confiances de cette ligne, et un « 4 » à forte confiance ailleurs ne change rien ; montant absent de la ligne retenue → 0 ;
- `confiance_min_pages` : minimum des pages, `None` sans scores ;
- sur `bl_synthetique.mistral-ocr.json` : toutes les valeurs de l'annotation ont une confiance > 0,5 (header via `confiance_valeur`, lignes via `confiances_ligne`).

### L3-T2 — `extract: lecture d'un BL depuis l'annotation Mistral`
Fichier `app/modules/extract/bl.py` (pur). Dépend de L3-T1 (`indexer_confiance`, `confiance_valeur`, `confiances_ligne`) et de `ocr.py` (`texte_ocr`, `detecter_numero_bl`, `NumeroBL`, `TypeBL`, `decimal_fr`).

Interfaces :
```python
CHAMPS_ENTETE_BL: tuple[str, ...] = (
    "type_bon", "fournisseur", "agence_fournisseur", "siret", "tva_intracommunautaire",
    "numero", "date_doc", "chantier_brut", "numero_commande", "enleve_par",
    "total_ht", "total_tva", "total_ttc",
)
CHAMPS_LIGNE_BL: tuple[str, ...] = ("code", "designation", "quantite", "unite", "pu_ht", "montant_ht")
SCHEMA_ANNOTATION_BL: dict[str, Any]
CONSIGNE_ANNOTATION_BL: str
OPTIONS_OCR_BL: dict[str, Any]   # options à fusionner dans la requête /v1/ocr

@dataclass(frozen=True)
class TexteLu:
    brut: str | None
    confiance: Decimal | None

@dataclass(frozen=True)
class NombreLu:
    brut: str | None
    valeur: Decimal | None     # None si brut None ou non convertible
    confiance: Decimal | None

@dataclass(frozen=True)
class DateLue:
    brut: str | None
    valeur: date | None
    confiance: Decimal | None

@dataclass(frozen=True)
class LigneBL:
    ordre: int
    code: TexteLu
    designation: TexteLu
    quantite: NombreLu
    unite: TexteLu
    pu_ht: NombreLu
    montant_ht: NombreLu

@dataclass(frozen=True)
class BLExtrait:
    type_bon: TexteLu
    fournisseur: TexteLu
    agence_fournisseur: TexteLu
    siret: TexteLu
    tva_intracommunautaire: TexteLu
    numero: TexteLu
    date_doc: DateLue
    chantier_brut: TexteLu
    numero_commande: TexteLu
    enleve_par: TexteLu
    total_ht: NombreLu
    total_tva: NombreLu
    total_ttc: NombreLu
    lignes: tuple[LigneBL, ...]
    numero_detecte: NumeroBL | None

class AnnotationIllisible(Exception): ...

def nombre_bl(brut: str | None) -> Decimal | None
def date_bl(brut: str | None) -> date | None
def normaliser_numero_bl(brut: str | None) -> str | None
def analyser_bl(reponse: dict[str, Any]) -> BLExtrait
def extraction_en_json(extrait: BLExtrait) -> dict[str, Any]
```
Règles :
- `SCHEMA_ANNOTATION_BL` : objet `strict`, `additionalProperties: false`, toutes les clés de `CHAMPS_ENTETE_BL` et `lignes` requises ; chaque valeur `{"type": ["string", "null"], "description": "<consigne française courte>"}` ; `lignes` = tableau d'objets aux clés `CHAMPS_LIGNE_BL`, mêmes types. Descriptions : `type_bon` « "livraison" pour un bon de livraison, "enlevement" pour un bon d'enlèvement, null si indéterminé » ; `numero` « numéro du bon tel qu'imprimé, sans le libellé "N°" » ; `date_doc` « date du bon telle qu'imprimée » ; `chantier_brut` « libellé du chantier ou de l'adresse de livraison tel qu'imprimé, code entre parenthèses compris » ; etc.
- `CONSIGNE_ANNOTATION_BL` : « Recopie chaque valeur exactement telle qu'elle est imprimée sur le document (mêmes caractères, virgule décimale conservée). Mets null si la valeur est absente ou illisible. N'invente, ne calcule et ne corrige aucune valeur. Ignore les mentions manuscrites. »
- `OPTIONS_OCR_BL = {"confidence_scores_granularity": "word", "document_annotation_format": {"type": "json_schema", "json_schema": {"name": "bon_de_livraison", "schema": SCHEMA_ANNOTATION_BL, "strict": True}}, "document_annotation_prompt": CONSIGNE_ANNOTATION_BL}`.
- `nombre_bl` : retire espaces (normales, insécables, fines), accepte `,` ou `.` comme séparateur décimal (un seul séparateur), signe `-` initial ; « 1 234,56 », « 31.50 », « 4 », « -2,5 » ; tout autre texte → `None`.
- `date_bl` : `JJ/MM/AAAA`, `JJ/MM/AA` (→ 20AA), séparateurs `/`, `.` ou `-` ; date impossible → `None`.
- `normaliser_numero_bl` : retire tous les espaces, majuscules ; vide → `None`.
- `analyser_bl` : `document_annotation` doit être une chaîne JSON d'objet (ou un `dict`) sinon `AnnotationIllisible` (message fixe, sans contenu). Clé absente → `None`. Valeur non chaîne et non nulle (nombre, booléen) → `str(valeur)`. Chaîne blanche → `None`. `lignes` absent ou non liste → `()` ; une ligne dont tous les champs sont nuls est ignorée ; `ordre` = position parmi les lignes gardées. Confiances : en-tête par `confiance_valeur`, lignes par `confiances_ligne` sur les 6 bruts. `numero_detecte = detecter_numero_bl(texte_ocr(reponse))`.
- `extraction_en_json` : `{"version": 1, "champs": {nom: {"brut": str|None, "valeur": str|None, "confiance": str|None}}, "lignes": [{"ordre": int, <champ>: {"brut", "valeur", "confiance"}}], "numero_detecte": str|None}`. `valeur` : `Decimal` en chaîne (`str`), `date` en ISO, texte = brut débarrassé des espaces multiples ; `numero` = `normaliser_numero_bl`. Tout est sérialisable par `json.dumps`.

Tests :
- `bl_synthetique.mistral-ocr.json` → tous les champs inventés attendus (valeurs converties comprises), 3 lignes, `numero_detecte.numero == "L209900000123"`, confiances non nulles ;
- annotation absente, `null`, JSON invalide, JSON non objet → `AnnotationIllisible` ;
- annotation en `dict` acceptée ; nombre JSON converti en chaîne ; clés manquantes → `None` ;
- ligne entièrement nulle ignorée, `ordre` recalculé ;
- valeur modifiée dans l'annotation pour qu'elle n'existe pas dans le texte → confiance 0 ;
- `nombre_bl` et `date_bl` : cas valides et invalides listés ci-dessus ; `normaliser_numero_bl(" l 2099 ") == "L2099"` ;
- `extraction_en_json` : `json.dumps` réussit ; date en ISO ; confiance en chaîne ;
- `OPTIONS_OCR_BL` : `json.dumps` réussit, `strict` vrai, toutes les clés de `CHAMPS_ENTETE_BL` sont requises.

### L3-T3 — `extract: vérification d'un BL et d'une facture`
Fichier `app/modules/extract/verification.py` (pur). Dépend de L3-T2 (`BLExtrait`, `normaliser_numero_bl`) et de `facture.py` (`Facture`).

Interfaces :
```python
class CodeMotif(StrEnum):
    CHAMP_ABSENT = "champ_absent"
    VALEUR_ILLISIBLE = "valeur_illisible"
    CONFIANCE_FAIBLE = "confiance_faible"
    SOMME_INCOHERENTE = "somme_incoherente"
    TOTAL_ABSENT = "total_absent"
    NUMERO_INCOHERENT = "numero_incoherent"
    OCR_ECHEC = "ocr_echec"                      # posé par ingest
    ANNOTATION_ILLISIBLE = "annotation_illisible" # posé par ingest
    FOURNISSEUR_INCONNU = "fournisseur_inconnu"   # posé par ingest
    NUMERO_EN_DOUBLE = "numero_en_double"         # posé par ingest

@dataclass(frozen=True)
class Motif:
    code: CodeMotif
    champ: str | None             # "fournisseur", "numero", "date_doc", "chantier_brut", "total_ht", "lignes", "ligne:<ordre>", ou None
    detail: dict[str, str]        # valeurs chiffrées en chaînes ; jamais vide pour les motifs chiffrés

CHAMPS_OBLIGATOIRES_BL: tuple[str, ...] = ("fournisseur", "numero", "date_doc", "chantier_brut")
SEUIL_CONFIANCE_DEFAUT = Decimal("0.80")
TOLERANCE_TOTAL_DEFAUT = Decimal("0.05")

@dataclass(frozen=True)
class LigneAVerifier:
    ordre: int
    montant_ht: Decimal | None
    confiance: Decimal | None     # minimum des confiances non nulles de code, quantité, montant

@dataclass(frozen=True)
class BLAVerifier:
    fournisseur: str | None
    numero: str | None
    date_doc: date | None
    chantier_brut: str | None
    total_ht: Decimal | None
    lignes: tuple[LigneAVerifier, ...]
    confiances: Mapping[str, Decimal | None] | None   # None : vérification structurelle seule
    illisibles: frozenset[str] = frozenset()          # champs au brut présent mais non convertible
    numero_detecte: str | None = None

def bl_a_verifier(extrait: BLExtrait) -> BLAVerifier
def verifier_bl(bl: BLAVerifier, *, seuil_confiance: Decimal, tolerance: Decimal) -> tuple[Motif, ...]
def verifier_facture(facture: Facture, *, tolerance: Decimal) -> tuple[Motif, ...]
def motif_en_json(motif: Motif) -> dict[str, Any]
def motif_depuis_json(donnees: Mapping[str, Any]) -> Motif     # ValueError si mal formé
```
Règles de `verifier_bl`, dans cet ordre (ordre des motifs = ordre de sortie) :
1. Pour chaque champ de `CHAMPS_OBLIGATOIRES_BL` : valeur `None` → `VALEUR_ILLISIBLE` (champ = nom, detail `{"champ": nom}`) si le champ est dans `illisibles`, sinon `CHAMP_ABSENT` (champ = nom, detail `{"champ": nom}`). `total_ht` dans `illisibles` → `VALEUR_ILLISIBLE` aussi.
2. Si `confiances` n'est pas `None` : pour chaque champ obligatoire présent et `total_ht` présent, confiance `None` ou `< seuil` → `CONFIANCE_FAIBLE` detail `{"confiance": str(c) ou "inconnue", "seuil": str(seuil)}` ; puis pour chaque ligne dont la confiance est `None` ou `< seuil` → `CONFIANCE_FAIBLE` champ `ligne:<ordre>`.
3. Somme = somme des `montant_ht` non nuls. `total_ht` `None` et au moins un montant → `TOTAL_ABSENT` champ `total_ht` detail `{"somme": ...}`. `total_ht` présent et `abs(somme - total) > tolerance` → `SOMME_INCOHERENTE` champ `total_ht` detail `{"somme", "total", "ecart", "tolerance"}` (`ecart = somme - total`). Égalité à la tolérance près acceptée (`<=`).
4. `numero` et `numero_detecte` présents et différents après `normaliser_numero_bl` → `NUMERO_INCOHERENT` champ `numero` detail `{"lu", "detecte"}`.

`bl_a_verifier` : `fournisseur` = brut du fournisseur ; `numero` = `normaliser_numero_bl` ; `date_doc`, `total_ht` = valeurs converties ; `chantier_brut` = brut ; `illisibles` = champs `date_doc`/`total_ht` dont le brut existe et la valeur est `None` ; `confiances` = `{"fournisseur", "numero", "date_doc", "chantier_brut", "total_ht"}` ; `numero_detecte` = `extrait.numero_detecte.numero` ou `None` ; confiance d'une ligne = minimum des confiances non nulles de code, quantité, montant (`None` si toutes nulles).

`verifier_facture` : somme des `BlocBL.montant_ht` ≠ `facture.total_ht` au-delà de la tolérance → un `SOMME_INCOHERENTE` champ `total_ht` (mêmes clés de detail), sinon `()`.

Tests : un test positif et un négatif par motif ; tolérance exactement 0,05 → aucun motif, 0,06 → motif ; seuil exactement 0,80 → aucun motif, 0,7999 → motif ; `confiances=None` → aucun `CONFIANCE_FAIBLE` ; confiance `None` → motif « inconnue » ; ligne sans montant ignorée dans la somme ; aucune ligne et total présent → `SOMME_INCOHERENTE` ; `bl_a_verifier` sur la donnée synthétique → `verifier_bl` sans motif ; aller-retour `motif_depuis_json(motif_en_json(m)) == m` ; `motif_depuis_json` sur un code inconnu → `ValueError` ; `verifier_facture` sur une `Facture` inventée cohérente et incohérente ; si la fixture réelle de facture existe (`tests/fixtures/unikalo/facture_2026-08.mistral-ocr.json`, sinon `skip`) : `verifier_facture(analyser_facture_unikalo(...)) == ()` (assertion sans afficher de valeur).

### L3-T4 — `normalize: fournisseur, chantier, unités et article`
Paquet `app/modules/normalize/` (pur, aucun import de `app.modules.*` hors `normalize`).

Interfaces :
```python
# texte.py
def normaliser_libelle(texte: str | None) -> str   # NFKD sans diacritiques, casefold, tout non-alphanumérique → espace, espaces réduits, strip ; None → ""

# fournisseur.py
def normaliser_siret(brut: str | None) -> str | None   # chiffres seuls ; 14 (SIRET) ou 9 (SIREN) chiffres, sinon None
def normaliser_tva(brut: str | None) -> str | None     # majuscules sans espaces ni points ; ^[A-Z]{2}[0-9A-Z]{2,13}$ sinon None

class MethodeFournisseur(StrEnum):
    SIRET = "siret"
    TVA = "tva"
    NOM = "nom"

@dataclass(frozen=True)
class FournisseurRef:
    id: uuid.UUID
    nom: str
    siret: str | None
    tva: str | None
    aliases: tuple[str, ...]

@dataclass(frozen=True)
class ResolutionFournisseur:
    fournisseur_id: uuid.UUID | None
    methode: MethodeFournisseur | None

@dataclass(frozen=True)
class AgenceRef:
    id: uuid.UUID
    nom: str

def resoudre_fournisseur(*, siret: str | None, tva: str | None, nom: str | None,
                         referentiel: Sequence[FournisseurRef]) -> ResolutionFournisseur
def resoudre_agence(brut: str | None, agences: Sequence[AgenceRef]) -> uuid.UUID | None

# chantier.py
@dataclass(frozen=True)
class LibelleChantier:
    libelle: str          # clé d'alias (L3-D6)
    code: str | None      # code fournisseur, jamais une clé

def decomposer_chantier(brut: str | None) -> LibelleChantier | None

# unites.py
class NatureUnite(StrEnum):
    MESURE = "mesure"
    CONDITIONNEMENT = "conditionnement"

@dataclass(frozen=True)
class Unite:
    code: str
    nature: NatureUnite

def normaliser_unite(brut: str | None) -> Unite | None

# article.py
@dataclass(frozen=True)
class PropositionArticle:
    code: str
    libelle: str | None
    unite_cdt: str | None
    unite_fact: str | None
    ratio: Decimal | None

def proposer_ratio(qte_conditionnement: Decimal | None, qte_facturation: Decimal | None) -> Decimal | None
def proposer_article_facture(code: str | None, designation: str | None,
                             qte_livree: Decimal | None, qte_totale: Decimal | None) -> PropositionArticle | None
def proposer_article_bl(code: str | None, designation: str | None, unite_brut: str | None) -> PropositionArticle | None
def completer_article(existant: PropositionArticle, nouvelle: PropositionArticle) -> PropositionArticle
```
Règles :
- `resoudre_fournisseur` : (1) SIREN = 9 premiers chiffres de `normaliser_siret(siret)` ; références dont le SIRET normalisé commence par ce SIREN ; exactement une → `SIRET`. (2) `normaliser_tva(tva)` égal à la TVA normalisée d'exactement une référence → `TVA`. (3) mots de `normaliser_libelle(nom)` ; une référence correspond si, pour son nom ou l'un de ses alias, l'ensemble non vide de ses mots normalisés est inclus dans les mots lus ; exactement une référence → `NOM`. Sinon `ResolutionFournisseur(None, None)`. Une étape ambiguë (plusieurs) passe à la suivante.
- `resoudre_agence` : agences dont les mots normalisés (non vides) sont tous inclus dans les mots du brut ; exactement une → son id, sinon `None`.
- `decomposer_chantier` : retire un préfixe `chantier` suivi d'un éventuel `:` (insensible à la casse) ; un groupe final `( <alphanumériques et tirets> )` devient `code` et est retiré du libellé ; `libelle = normaliser_libelle(reste)` ; libellé vide → `None`. « ORMEAUX (9944126862) » → `("ormeaux", "9944126862")` est l'exemple du CDC (§4.4, donnée publique du CDC) ; les tests utilisent des libellés inventés.
- `normaliser_unite` : comparaison sur `normaliser_libelle` sans espaces ; table explicite. Mesures : `kg` (KG, KGS, KILO, KILOS, KILOGRAMME, KILOGRAMMES), `g` (G, GR, GRAMME, GRAMMES), `t` (T, TONNE, TONNES), `l` (L, LT, LITRE, LITRES), `m` (M, ML, METRE, METRES, MTR), `m2` (M2, M², MQ, METRECARRE), `m3` (M3, M³), `u` (U, UN, UNITE, UNITES, PCE, PC, PIECE, PIECES). Conditionnements : `seau` (SEAU, SEAUX, SE), `sac` (SAC, SACS), `rouleau` (ROULEAU, ROULEAUX, RLX, RL), `bidon` (BIDON, BIDONS, BID), `pot` (POT, POTS), `carton` (CARTON, CARTONS, CTN), `boite` (BOITE, BOITES, BTE), `palette` (PALETTE, PALETTES, PAL), `lot` (LOT, LOTS), `paquet` (PAQUET, PAQUETS, PAQ, PQT), `cartouche` (CARTOUCHE, CARTOUCHES, CART). Inconnue → `None`.
- `proposer_ratio` : `None` si l'une manque ou ≤ 0 ; sinon `qte_facturation / qte_conditionnement` quantifié à 4 décimales (`ROUND_HALF_UP`) puis `.normalize()` sans notation exponentielle (ex. `Decimal("25")`).
- `proposer_article_facture` : `None` si code absent/blanc ; `libelle = designation` ; unités `None` ; `ratio = proposer_ratio(qte_livree, qte_totale)` seulement si `qte_livree != qte_totale`, sinon `None`.
- `proposer_article_bl` : `None` si code absent ; unité normalisée de nature conditionnement → `unite_cdt`, mesure → `unite_fact` ; ratio `None`.
- `completer_article` : garde chaque champ de `existant`, ne prend de `nouvelle` que les champs `None` de `existant` ; `code` de `existant`.

Tests : un positif et un négatif par règle ci-dessus, dont : SIREN commun à deux agences d'un même fournisseur → résolu ; deux références au même SIREN → passe à la TVA ; nom lu « NUANCES EXEMPLE TOULOUSE » résolu par l'alias « Nuances Exemple » ; nom ambigu → non résolu ; accents et casse dans les libellés ; « Chantier : Maison Test (99-001) » → `("maison test", "99-001")` ; parenthèses au milieu non retirées ; unités connues des deux natures, unité inconnue ; ratio 100/4 = 25, ratio 10/3 arrondi, quantité nulle → `None` ; `completer_article` ne remplace pas une valeur existante.

### L3-T5 — `ingest: migration 0005 et résolution des référentiels`
- Migration `0005_extraction.py` (L3-D5) et colonnes correspondantes dans `ingest/models.py` : `Document.chantier_brut`, `chantier_id` (FK `chantier.id`), `numero_commande`, `enleve_par`, `total_tva`, `total_ttc`, `extraction` (JSONB), `motifs` (JSONB) ; `Ligne.confiance` (Numeric). Tous nullables. `alembic check` sans dérive. Supprimer `bl_test` et `bl_test_migrations` si le test de migration voit un schéma périmé (piège connu).
- `app/modules/ingest/referentiels.py` :
```python
async def charger_fournisseurs(session: AsyncSession) -> list[FournisseurRef]
async def charger_agences(session: AsyncSession, fournisseur_id: uuid.UUID) -> list[AgenceRef]
async def resoudre_chantier(session: AsyncSession, fournisseur_id: uuid.UUID,
                            chantier_brut: str | None) -> ResolutionChantier
async def rattacher_article(session: AsyncSession, fournisseur_id: uuid.UUID,
                            proposition: PropositionArticle | None) -> uuid.UUID | None
async def lire_parametre_decimal(session: AsyncSession, cle: str, defaut: Decimal) -> Decimal

@dataclass(frozen=True)
class ResolutionChantier:
    chantier_id: uuid.UUID | None
    libelle: str | None          # clé d'alias ; None si brut vide
    alias_id: uuid.UUID | None   # None si brut vide
    demande_creee: bool          # True si l'alias vient d'être créé en attente
```
  - `resoudre_chantier` : `decomposer_chantier` ; `None` → `ResolutionChantier(None, None, None, False)`. Sinon `INSERT INTO chantier_alias (fournisseur_id, libelle_brut, code_brut) VALUES (:f, :libelle, NULL) ON CONFLICT DO NOTHING RETURNING id` ; si rien n'est renvoyé, relecture de l'alias existant. `chantier_id` = celui de l'alias (peut être `NULL`). Ne commite pas (l'appelant commite).
  - `rattacher_article` : `None` → `None`. Sinon article `(fournisseur_id, code)` : absent → insertion (`valide = false`, champs de la proposition) avec `ON CONFLICT DO NOTHING` puis relecture ; présent non validé → `completer_article` appliqué (UPDATE des seuls champs vides) ; présent validé → inchangé. Renvoie l'id. Ne commite pas.
  - `lire_parametre_decimal` : `parametre.valeur` convertie en `Decimal` ; absente ou non convertible → `defaut`.
- CLI `python -m app.cli fournisseur-definir --nom NOM [--siret S] [--tva T] [--alias A]... [--agence NOM_AGENCE]...` : crée le fournisseur (nom comparé sans casse) ou le met à jour (SIRET et TVA remplacés s'ils sont fournis ; alias et agences ajoutés sans doublon, comparaison `normaliser_libelle`). Code de sortie 0 ; sortie : « Fournisseur créé » / « Fournisseur mis à jour » + nombre d'alias et d'agences. Import de la base dans le corps de la fonction (même contournement que `utilisateur-creer`, dette L2-T1b).
- Tests (base `bl_test`) : migration aller-retour ; `resoudre_chantier` crée une demande puis la retrouve (pas de doublon, deux appels) ; deux bruts « Maison Test » et « MAISON TEST (99-002) » → même alias ; alias validé → `chantier_id` ; brut vide → rien créé ; `rattacher_article` crée, complète sans écraser, ne touche pas un article validé ; `lire_parametre_decimal` défaut et valeur ; CLI création, mise à jour, alias en double ignoré, agence ajoutée.

### L3-T6 — `ingest: extraction complète des BL déposés`
- `ingest/mistral.py::ocr_document` gagne un paramètre nommé `options: Mapping[str, Any] | None = None`, fusionné dans le corps de la requête (les clés existantes `model`, `document`, `table_format`, `include_image_base64` ne peuvent pas être écrasées). Test : le corps envoyé contient les options.
- `ingest/router.py::get_ocr` construit l'OCR des photos avec `OPTIONS_OCR_BL` et un délai de 90 s.
- Nouveau `app/modules/ingest/extraction_bl.py` :
```python
@dataclass(frozen=True)
class ResultatExtraction:
    numero: str | None
    statut: str
    fournisseur_nom: str | None
    chantier_brut: str | None
    nb_motifs: int

async def enregistrer_echec_ocr(session: AsyncSession, document_id: uuid.UUID) -> ResultatExtraction
async def enregistrer_extraction_bl(session: AsyncSession, document_id: uuid.UUID,
                                    reponse: dict[str, Any], *, relance: bool = False) -> ResultatExtraction
```
  `enregistrer_extraction_bl`, dans une transaction (commit à la fin) :
  1. seuil et tolérance via `lire_parametre_decimal` (L3-D4) ;
  2. `analyser_bl(reponse)` ; `AnnotationIllisible` → pas d'extraction : `numero`/`type` depuis `detecter_numero_bl(texte_ocr(reponse))` si trouvé (doublon traité comme au point 6), motif `ANNOTATION_ILLISIBLE`, `extraction = {"version": 1, "champs": {}, "lignes": [], "numero_detecte": ..., "motifs": [...]}`, `statut = a_verifier`, lignes existantes supprimées ;
  3. fournisseur : `resoudre_fournisseur(siret, tva, nom)` sur `charger_fournisseurs` ; agence par `resoudre_agence` ; brut présent et non résolu → motif `FOURNISSEUR_INCONNU` (champ `fournisseur`, detail `{"brut_present": "oui"}`) ;
  4. type (L3-D12) ; numéro = `normaliser_numero_bl(extrait.numero.brut)` sinon numéro détecté ;
  5. motifs = `verifier_bl(bl_a_verifier(extrait), ...)` + motifs d'`ingest` ;
  6. doublon (L3-D11) : fournisseur résolu et un autre document de ce fournisseur porte ce numéro → numéro non écrit, motif `NUMERO_EN_DOUBLE` detail `{"numero_interne_existant": "<n>"}` ;
  7. chantier : `resoudre_chantier` si fournisseur résolu ;
  8. document : `type`, `numero`, `fournisseur_id`, `agence_fournisseur_id`, `date_doc`, `chantier_brut`, `chantier_id`, `numero_commande`, `enleve_par`, `total_ht`, `total_tva`, `total_ttc`, `ocr_brut = reponse`, `extraction = extraction_en_json(extrait) | {"motifs": [...]}`, `motifs = [...]`, `confiance_min` = minimum des confiances non nulles des champs obligatoires, de `total_ht` et des lignes, `statut` = `a_verifier` si `relance` ou motifs, sinon `recu` ;
  9. lignes : suppression des lignes existantes du document, puis une `Ligne` par `LigneBL` (`type_ligne = "article"`, `code_brut`, `article_brut` = désignation, `qte_livree`, `unite_brut`, `pu_ht`, `montant_ht`, `ordre`, `confiance` = celle de `bl_a_verifier`, `article_id = rattacher_article(proposer_article_bl(...))` si fournisseur résolu) ;
  10. journal `extraction_bl` (`utilisateur_id` NULL, `cible_table = document`) : `apres = {"statut", "nb_lignes", "motifs": [codes], "fournisseur_id", "methode_fournisseur", "chantier_libelle", "chantier_id", "methode_chantier": "alias" | null}`.
  `enregistrer_echec_ocr` : `statut = a_verifier`, `motifs = [OCR_ECHEC]`, journal `extraction_bl` avec `motifs: ["ocr_echec"]`, commit.
- `depot_telegram._executer_ocr` : échec d'appel OCR ou réponse mal formée → `enregistrer_echec_ocr` (dans une nouvelle session ; son propre échec est journalisé et avalé comme aujourd'hui) ; sinon `enregistrer_extraction_bl`. `_ResultatOcr` porte aussi `fournisseur_nom` et `chantier_brut`.
- Ligne de supervision (remplace L2-D8) : `Document n° <interne> · BL <numéro ou « non détecté »> · fournisseur <nom du référentiel ou « — »> · chantier <chantier brut ou « — »> · <déposant> · <HH:MM> · <statut>`.
- Tests (base de test, OCR factice renvoyant la donnée synthétique ou une variante modifiée en mémoire, aucun réseau) :
  - BL complet, fournisseur « PEINTURES EXEMPLE » défini avec alias → `recu`, colonnes renseignées, 3 lignes avec `confiance`, articles créés, demande d'alias créée, journal `extraction_bl`, `extraction` contient les bruts et `motifs` vide ;
  - fournisseur absent du référentiel → `a_verifier`, `fournisseur_inconnu`, aucun article ni alias ;
  - total modifié → `somme_incoherente` ; confiance d'un mot abaissée → `confiance_faible` sur le bon champ ; date absente → `champ_absent` ;
  - annotation absente → `annotation_illisible`, numéro repris du motif ;
  - OCR en échec → `a_verifier` + `ocr_echec` + réponse « Reçu » quand même ;
  - même BL déposé deux fois → second document `a_verifier`, `numero_en_double`, numéro NULL, premier intact ;
  - alias déjà validé → `chantier_id` renseigné ;
  - ligne de supervision au nouveau format ;
  - les tests existants de `traiter_fichier` et de `_executer_ocr` sont mis à jour au nouveau comportement (L3-D10), sans en supprimer la couverture.

### L3-T7 — `ingest: contrôle et normalisation des factures déposées`
- `ingest/router.py::get_ocr_facture` : options `{"confidence_scores_granularity": "page"}`.
- `ingest/factures.py::deposer_facture` (L3-D16) : `confiance_min = confiance_min_pages(reponse_ocr)` ; motifs `verifier_facture(facture, tolerance=...)` (tolérance via `lire_parametre_decimal`) → `document.motifs`, `statut = a_verifier` si motifs ; pour chaque bloc `chantier_id = resoudre_chantier(...).chantier_id` ; pour chaque ligne `ARTICLE` avec code `article_id = rattacher_article(proposer_article_facture(...))` ; journal `facture_deposee` : `apres` gagne `statut` et `motifs` (codes).
- `ingest/lecture.py` et `api/schemas.py` : `FactureResume`/`FactureResumeReponse` et `FactureDetail`/`FactureDetailReponse` gagnent `statut: str`, `confiance_reduite: bool` (`ocr_brut` non nul), `confiance_min: Decimal | None`, `motifs: list[MotifReponse]` ; `BlocFactureLu`/`BlocFactureReponse` gagnent `chantier_id: uuid.UUID | None`.
- `MotifReponse` (dans `api/schemas.py`) : `code: str`, `champ: str | None`, `detail: dict[str, str]`. `ingest/lecture.py` fournit `MotifLu` (dataclass de mêmes champs) construit depuis le JSON stocké (motif mal formé ignoré, jamais d'erreur 500).
- Tests : dépôt synthétique cohérent → `recu`, `motifs == []` ; total incohérent → `a_verifier` + `somme_incoherente` ; blocs avec chantier → demandes d'alias créées, `chantier_id` d'un alias validé propagé ; lignes avec code → articles, ratio proposé quand `qte_livree ≠ qte_totale` ; `GET /api/factures` et `/{id}` exposent les nouveaux champs ; fixture réelle (skip si absente) → `recu`.

### L3-T8a — `api: détail, correction et validation d'un BL`
- `app/modules/ingest/corrections.py` :
```python
CHAMPS_CORRIGEABLES: tuple[str, ...] = ("type", "fournisseur_id", "numero", "date_doc", "chantier_brut",
                                         "numero_commande", "enleve_par", "total_ht", "total_tva", "total_ttc")

@dataclass(frozen=True)
class ChampLu:
    valeur: str | None          # valeur courante (date ISO, décimal en chaîne, nom du fournisseur pour « fournisseur »)
    valeur_ocr: str | None      # brut lu par l'OCR (extraction), None sans extraction
    confiance: Decimal | None
    corrige: bool               # une entrée de journal document_corrige touche ce champ
    corrige_par: str | None     # nom affiché (ou e-mail) du dernier correcteur
    corrige_le: datetime | None

@dataclass(frozen=True)
class LigneLue:
    id: uuid.UUID
    ordre: int
    code_brut: str | None
    article_brut: str | None
    qte_livree: Decimal | None
    unite_brut: str | None
    pu_ht: Decimal | None
    montant_ht: Decimal | None
    confiance: Decimal | None
    article_id: uuid.UUID | None

@dataclass(frozen=True)
class DocumentDetail:
    id: uuid.UUID
    numero_interne: int
    type: str
    statut: str
    deposant: str | None
    cree_le: datetime
    confirme_le: datetime | None
    confirme_par: str | None
    confirmation: str | None        # "verifiee" | "ecart" | None (même calcul que lister_documents)
    photo_compressee: bool | None
    fournisseur_id: uuid.UUID | None
    agence_fournisseur: str | None
    chantier_id: uuid.UUID | None
    chantier: str | None            # nom canonique
    champs: dict[str, ChampLu]      # clés : fournisseur, numero, date_doc, chantier_brut, numero_commande, enleve_par, total_ht, total_tva, total_ttc
    lignes: list[LigneLue]
    motifs: list[MotifLu]
    seuil_confiance: Decimal
    modifiable: bool                # admin et statut != archive

@dataclass(frozen=True)
class CorrectionEntete:
    valeurs: dict[str, object]     # seulement les champs envoyés (None autorisé), clés ⊂ CHAMPS_CORRIGEABLES

@dataclass(frozen=True)
class LigneSaisie:
    id: uuid.UUID | None
    code_brut: str | None
    article_brut: str | None
    qte_livree: Decimal | None
    unite_brut: str | None
    pu_ht: Decimal | None
    montant_ht: Decimal | None

class DocumentIntrouvable(Exception)            # réutiliser celle de lecture.py
class DocumentNonModifiable(Exception)          # archivé, ou facture
class NumeroDejaUtilise(Exception):  original_id: uuid.UUID
class ValidationRefusee(Exception):  motifs: list[MotifLu]
class LigneInconnue(Exception)                  # id de ligne étranger au document
class FournisseurIntrouvable(Exception)

async def detail_document(session, document_id, *, utilisateur_id, role) -> DocumentDetail
async def corriger_entete(session, document_id, correction: CorrectionEntete, *, auteur_id) -> DocumentDetail
async def corriger_lignes(session, document_id, lignes: list[LigneSaisie], *, auteur_id) -> DocumentDetail
async def valider_document(session, document_id, *, auteur_id) -> DocumentDetail
async def archiver_document(session, document_id, *, commentaire: str, auteur_id) -> DocumentDetail
async def relancer_extraction(session, document_id, docs_dir: Path, ocr, *, auteur_id) -> DocumentDetail
```
  Règles : L3-D13 à L3-D15, L3-D19. Détail : agent → seulement ses documents (sinon `DocumentIntrouvable`), `modifiable = False`. Motifs structurels = `verifier_bl(BLAVerifier(fournisseur=<nom du fournisseur rattaché ou None>, numero, date_doc, chantier_brut, total_ht, lignes=<montants des lignes en base>, confiances=None, illisibles=frozenset(), numero_detecte=None), ...)` : l'humain a revu le document, ni la confiance ni le recoupement du numéro ne comptent plus ; un fournisseur non rattaché donne `CHAMP_ABSENT` sur `fournisseur`. Correction d'en-tête : `fournisseur_id` inexistant → `FournisseurIntrouvable` ; numéro pris par un autre document du même fournisseur → `NumeroDejaUtilise` ; fournisseur ou `chantier_brut` modifié → nouvelle résolution du chantier ; fournisseur modifié → articles des lignes rattachés ; un document `recu` qui gagne un motif passe `a_verifier`. Relance : statut `a_verifier` exigé (sinon `DocumentNonModifiable`), `ErreurOCR` → remonte en `LectureImpossible` (celle de `factures.py`), journal `extraction_relancee` avec `avant` = anciennes valeurs d'en-tête et nombre de lignes, puis `enregistrer_extraction_bl(..., relance=True)`.
- `app/modules/api/documents.py` :
  - `GET /api/documents/{id}` (utilisateur courant) → `DocumentDetailReponse` ; 404.
  - `PATCH /api/documents/{id}` (admin) corps `CorrectionEnteteRequete` (tous champs optionnels ; seuls ceux présents dans `model_fields_set` sont transmis ; `type` ∈ {`bl`, `enlevement`}) → 200 détail ; 404 ; 409 `{detail, original_id}` numéro pris ; 409 `{detail}` non modifiable ; 422 fournisseur introuvable.
  - `PUT /api/documents/{id}/lignes` (admin) `{lignes: [...]}` → 200 ; 422 ligne inconnue ; 409 non modifiable.
  - `POST /api/documents/{id}/validation` (admin) → 200 ; 409 `{detail, motifs}` ; 409 statut non `a_verifier`.
  - `POST /api/documents/{id}/archivage` (admin) `{commentaire}` (1 à 500 caractères, blanc refusé) → 200.
  - `POST /api/documents/{id}/extraction` (admin) → 200 ; 502 lecture impossible ; 409.
  - `DocumentReponse` (liste) gagne `fournisseur: str | None` et `chantier_brut: str | None`.
- Schémas Pydantic dans `api/schemas.py` : `ChampReponse`, `LigneDocumentReponse`, `DocumentDetailReponse` (`champs` modèle à attributs nommés `fournisseur`, `numero`, …), `CorrectionEnteteRequete`, `LigneSaisieRequete`, `LignesRequete`, `ArchivageRequete`.
- Tests (service et API) : droits (agent : lecture de son document, 404 sur celui d'un autre, 403 sur toute écriture) ; détail avec valeurs OCR et confiances ; correction d'un champ → journal avant/après, `corrige` vrai, valeur OCR conservée ; correction du fournisseur → alias et articles résolus ; numéro pris → 409 avec `original_id` ; lignes : modification (confiance NULL), ajout, suppression, id étranger 422, journal ; validation refusée avec motifs puis acceptée après correction du total ; archivage (commentaire obligatoire, journal) puis écriture refusée ; relance avec OCR factice → valeurs remplacées, reste `a_verifier`, journal ; relance OCR en échec → 502 ; facture → 404 sur le détail.

### L3-T8b — `api: écran À traiter et référentiels`
- `ingest/a_traiter.py` :
```python
@dataclass(frozen=True)
class DocumentATraiter:
    id: uuid.UUID
    numero_interne: int
    type: str
    numero: str | None
    fournisseur: str | None
    chantier_brut: str | None
    deposant: str | None
    cree_le: datetime
    confirmation: str | None
    motifs: list[MotifLu]

@dataclass(frozen=True)
class AliasEnAttente:
    id: uuid.UUID
    fournisseur: str
    libelle: str
    exemple_brut: str | None      # un chantier_brut récent (document ou bloc) de ce libellé
    nb_documents: int             # documents + blocs de facture concernés non résolus
    cree_le: datetime

@dataclass(frozen=True)
class ArticleAValider:
    id: uuid.UUID
    fournisseur: str
    code: str
    libelle: str | None
    unite_cdt: str | None
    unite_fact: str | None
    ratio: Decimal | None
    cree_le: datetime

@dataclass(frozen=True)
class ATraiter:
    documents: list[DocumentATraiter]   # statut a_verifier, tous types, du plus ancien au plus récent
    alias: list[AliasEnAttente]
    articles: list[ArticleAValider]

async def lister_a_traiter(session: AsyncSession) -> ATraiter
```
- Dans `ingest/referentiels.py` :
```python
@dataclass(frozen=True)
class ChantierResume: id: uuid.UUID; nom_canonique: str; agence: str | None; actif: bool
@dataclass(frozen=True)
class FournisseurResume: id: uuid.UUID; nom: str

class ChantierEnDouble(Exception): original_id: uuid.UUID
class AliasIntrouvable(Exception)
class AliasDejaValide(Exception)
class ChantierIntrouvable(Exception)
class ArticleIntrouvable(Exception)

async def lister_chantiers(session) -> list[ChantierResume]            # actifs d'abord, puis nom
async def creer_chantier(session, *, nom_canonique: str, agence: str | None, auteur_id) -> ChantierResume
async def lister_fournisseurs(session) -> list[FournisseurResume]
async def valider_alias(session, alias_id, *, chantier_id, auteur_id) -> int      # nombre de documents + blocs mis à jour
async def valider_article(session, article_id, *, unite_cdt, unite_fact, ratio, auteur_id) -> None
```
  Règles : `creer_chantier` refuse un nom égal à un existant après `normaliser_libelle` (`ChantierEnDouble`), journal `chantier_cree`. `valider_alias` : alias déjà rattaché → `AliasDejaValide` ; renseigne `chantier_id`, `valide_par`, `valide_le` ; propage aux documents du fournisseur et aux blocs des factures du fournisseur dont `decomposer_chantier(chantier_brut).libelle` est ce libellé et `chantier_id` est NULL ; journal `alias_valide` `apres = {"libelle", "chantier_id", "methode": "validation_humaine", "nb_mis_a_jour"}`. `valider_article` : `ratio > 0` exigé si fourni, `unite_*` passées par `normaliser_unite` (code) quand reconnues, sinon gardées telles quelles ; `valide = true` ; journal `article_valide` avant/après.
- `api/a_traiter.py` : `GET /api/a-traiter` (admin) → `ATraiterReponse`.
- `api/referentiels.py` (admin) : `GET /api/chantiers`, `POST /api/chantiers` (201 ; 409 `{detail, original_id}` ; nom 1 à 200 caractères non blanc), `GET /api/fournisseurs`, `POST /api/alias-chantier/{id}/validation` `{chantier_id}` (200 `{nb_mis_a_jour}` ; 404 alias ou chantier ; 409 déjà validé), `POST /api/articles/{id}/validation` `{unite_cdt, unite_fact, ratio}` (204 ; 404 ; 422 ratio ≤ 0).
- `api/__init__.py` inclut les deux routeurs.
- Tests : contenu d'`À traiter` (document `a_verifier` avec motifs, écart constaté sans motif, document `recu` absent, facture `a_verifier` présente ; alias en attente avec compte et exemple ; article à ratio ≠ 1 présent, ratio 1 ou validé absent) ; agent → 403 partout ; création de chantier et doublon ; validation d'alias et propagation aux documents et blocs, journal ; alias déjà validé 409 ; validation d'article et journal.

### L3-T9 — `web: écran À traiter et navigation`
- `npm run api:schema && npm run api:types` (schéma régénéré, commité).
- `web/src/api/aTraiter.ts`, `web/src/api/referentiels.ts` : fonctions typées et clés TanStack Query.
- Page `web/src/pages/ATraiter.tsx` (admin, mobile d'abord, cartes empilées sur téléphone) :
  - section « Documents à vérifier » : carte par document (n° interne, type, numéro ou « sans numéro », fournisseur, chantier brut, déposant, date) ; motifs listés en français (table de libellés `code → texte` dans `web/src/lib/motifs.ts`, avec les valeurs du `detail`), badge « Écart constaté » si `confirmation === "ecart"` ; lien vers `/documents/:id` (BL/enlèvement) ou `/factures/:id` (facture) ;
  - section « Chantiers à rattacher » : libellé, fournisseur, exemple brut, nombre de documents ; formulaire : choisir un chantier existant (liste `GET /api/chantiers`) **ou** créer un chantier (nom, agence) puis valider ; invalidation des requêtes après succès ; erreurs 409 affichées ;
  - section « Articles à valider » : code, libellé, unités, ratio proposé ; champs éditables (unité de conditionnement, unité de facturation, ratio) et bouton « Valider » ;
  - chaque section vide affiche « Rien à traiter » ; rafraîchissement toutes les 30 s.
- Navigation (`Gabarit.tsx`) : admin → « À traiter », « Factures », « BL déposés » ; agent → « BL déposés ». `RedirectionAccueil` : admin → `/a-traiter`, agent → `/bl`. Route `/a-traiter` sous `GardeAdmin`.
- Factures : liste et détail affichent un badge « À vérifier » (avec motifs sur le détail) et « Confiance réduite (OCR) ».
- `BlDeposes.tsx` : colonnes/cartes fournisseur et chantier brut ; chaque BL ouvre `/documents/:id`.
- Vérifications : `typecheck`, `build` ; parcours manuel sur uvicorn local + front construit, données inventées (un admin de test créé par CLI, documents semés par un petit script **non commité** ou par les services), écran à 375 px et à 1280 px ; rapport des vérifications (captures non commitées).

### L3-T10 — `web: détail et correction d'un document`
- `web/src/api/client.ts` : méthodes `PATCH` et `PUT`, corps JSON (`Content-Type: application/json`).
- `web/src/api/documents.ts` : `lireDocument`, `corrigerEntete`, `corrigerLignes`, `validerDocument`, `archiverDocument`, `relancerExtraction`.
- Page `web/src/pages/DocumentDetail.tsx`, route `/documents/:id` (admin et agent) :
  - photo (balise `img` sur `/api/documents/{id}/fichier`, lien « ouvrir » ; PDF : lien seulement) ;
  - en-tête : statut, n° interne, déposant, confirmation ; motifs courants en français ;
  - champs : valeur, badge de confiance (pourcentage ; orange si `< seuil_confiance`), champ surligné s'il est cité par un motif ; si `corrige` : « Valeur OCR : … — corrigée par … le … » ;
  - mode édition (admin, `modifiable`) : formulaire d'en-tête (fournisseur en liste déroulante `GET /api/fournisseurs`, type, numéro, date, chantier brut, commande, enlevé par, totaux) → `PATCH` ; tableau des lignes éditable (modifier, ajouter, supprimer) → `PUT` ; affichage de la somme des montants et de l'écart au total **renvoyés par les motifs de l'API** (aucun calcul métier dans le front) ;
  - boutons « Valider » (409 : motifs affichés), « Relancer l'extraction » (confirmation), « Archiver » (commentaire obligatoire) ;
  - agent : lecture seule ; mobile : champs empilés, lignes en cartes.
- Vérifications : comme L3-T9, dont le parcours complet « document à vérifier → correction du total → validation » et « archivage d'un doublon ».

### L3-T11 — `ingest: outil de mesure du taux d'erreur OCR`
- `app/modules/ingest/rapport_ocr.py` :
```python
@dataclass(frozen=True)
class LigneAttendue: code: str | None; quantite: Decimal | None
@dataclass(frozen=True)
class BLAttendu:
    nom: str
    numero: str
    fournisseur: str
    date_doc: date
    chantier_brut: str
    lignes: tuple[LigneAttendue, ...]
    degradee: bool

@dataclass(frozen=True)
class ChampCompare: champ: str; juste: bool; confiance: Decimal | None
@dataclass(frozen=True)
class LigneComparee: code_attendu: str | None; trouvee: bool; juste: bool; confiance: Decimal | None
@dataclass(frozen=True)
class ComparaisonBL:
    nom: str
    degradee: bool
    champs: tuple[ChampCompare, ...]        # numero, fournisseur, date_doc, chantier_brut
    lignes: tuple[LigneComparee, ...]
    lignes_en_trop: int
    motifs: tuple[str, ...]                 # codes des motifs de verifier_bl (+ fournisseur_inconnu non évalué ici)
    silencieuse: bool                       # au moins une erreur et aucun motif

@dataclass(frozen=True)
class RapportOCR:
    nb_documents: int
    nb_degrades: int
    taux_champs: dict[str, Decimal]         # par champ, en proportion 0..1
    taux_documents_4_champs: Decimal        # documents dont les 4 champs sont justes
    taux_lignes: Decimal
    nb_erreurs_silencieuses: int
    lignes_fausses_confiance_haute: tuple[tuple[str, str | None, Decimal], ...]   # (document, code, confiance)
    confiances_justes: tuple[Decimal, ...]
    confiances_fausses: tuple[Decimal, ...]
    documents_sans_ocr: tuple[str, ...]

def lire_attendu(donnees: Mapping[str, Any], nom: str) -> BLAttendu        # ValueError si mal formé
def comparer_bl(extrait: BLExtrait, attendu: BLAttendu, *, seuil: Decimal, tolerance: Decimal) -> ComparaisonBL
def agreger(comparaisons: Sequence[ComparaisonBL], documents_sans_ocr: Sequence[str], *, seuil: Decimal) -> RapportOCR
def rapport_markdown(rapport: RapportOCR, comparaisons: Sequence[ComparaisonBL]) -> str
async def mesurer_dossier(dossier: Path, *, ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]] | None,
                          seuil: Decimal, tolerance: Decimal) -> tuple[RapportOCR, list[ComparaisonBL]]
```
  Règles de comparaison : `numero` égal après `normaliser_numero_bl` ; `fournisseur` juste si les mots de `normaliser_libelle(attendu)` sont tous dans ceux du lu ; `date_doc` égale ; `chantier_brut` égal après `normaliser_libelle` ; ligne attendue appariée à la première ligne lue non appariée de même code (`normaliser_libelle` sans espaces), juste si quantité égale ; `lignes_en_trop` = lignes lues non appariées ; confiance d'un champ = celle de l'extraction ; confiance d'une ligne = minimum de code et quantité. `mesurer_dossier` : photos `*.jpg|*.jpeg|*.png|*.webp|*.heic|*.pdf` ayant un `<nom>.attendu.json` ; cache `<nom>.mistral-ocr.json` lu s'il existe, sinon appel `ocr` si fourni (réponse écrite dans le cache), sinon document listé dans `documents_sans_ocr`. `rapport_markdown` : synthèse (taux, objectifs CDC ≥ 95 % / ≥ 90 % / 0 erreur silencieuse, atteint ou non), tableau par document (nom, dégradée, champs faux, lignes justes/total, motifs, silencieuse), lignes fausses à confiance haute, distribution des confiances (min, médiane, max) justes/fausses.
- CLI `python -m app.cli rapport-ocr DOSSIER --sortie FICHIER [--appeler-ocr]` : écrit le rapport, affiche seulement les comptes et les taux ; code 0, 2 si le dossier n'existe pas ou ne contient aucun attendu.
- `docs/protocole-mesure-ocr.md` : choix des 30 photos (dont 10 dégradées : froissées, mal cadrées, annotées), nommage, format exact de `<nom>.attendu.json` (exemple inventé), emplacement (`tests/fixtures/bl/`, jamais commité), commande, lecture du rapport, calage du seuil à partir de la distribution des confiances, analyse des lignes fausses à confiance haute.
- Tests (sans base, données inventées dans `tmp_path`) : `lire_attendu` valide et invalide ; comparaison tout juste ; numéro faux avec motif → non silencieuse ; chantier faux sans motif → silencieuse ; ligne manquante, quantité fausse à confiance haute listée, ligne en trop ; agrégation des taux ; dossier avec cache sans appel OCR ; photo sans cache et sans OCR → `documents_sans_ocr` ; OCR factice appelé et cache écrit ; CLI : code 2 sur dossier vide, rapport écrit.

### L3-T12 — `docs: recette du lot 3`
- `docs/lot-3-recette.md` : encart « À lire d'abord » (ce qui est fait, ce qui est bloqué et pourquoi, décisions à valider Q1–Q7) ; vérification commande par commande (migration, `fournisseur-definir`, création d'un chantier, dépôt d'un BL inventé via le webhook avec OCR réel sur une image inventée, écran « À traiter », correction, validation, archivage, relance, facture « à vérifier », `rapport-ocr` sur un dossier inventé) ; procédure de mesure sur les 30 photos réelles ; liste complète des décisions L3-D* et des rulings L3-R* ; honnêteté sur ce qui n'a pas été vérifié réellement.
- `docs/dette.md` à jour (entrées nouvelles du lot 3 ; entrées résolues retirées ou marquées résolues : confiance réduite, reprise après échec d'OCR, L2-R10).
- `CLAUDE.md` : section « Où en est le projet » mise à jour.

## 7. Récapitulatif des tests

| Zone | Sans base | Avec base | Manuel |
| --- | --- | --- | --- |
| Confiance par mot | L3-T1 | | |
| Lecture d'un BL | L3-T2 | | appel réel sur image inventée (recette) |
| Vérification | L3-T3 | | |
| Normalisation | L3-T4 | | |
| Référentiels, migration, CLI | | L3-T5 | |
| Extraction des BL déposés | | L3-T6 | webhook local + OCR réel sur image inventée |
| Factures | | L3-T7 | |
| Corrections, validation | | L3-T8a | écran (L3-T10) |
| À traiter, référentiels | | L3-T8b | écran (L3-T9) |
| Front | typecheck, build | | parcours admin/agent, 375 px |
| Mesure OCR | L3-T11 | | 30 photos réelles (bloqué, Q2) |
| Origine derrière proxy | | L3-T0 | `npm run dev` + curl |
