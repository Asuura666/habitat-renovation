# Plan — Lot 4 (Rapprochement)

> **Pour les agents :** exécuté par `superpowers:subagent-driven-development` (une fiche par tâche, implémenteur Sonnet, relecteur Sonnet). Chaque tâche = un commit (plus d'éventuels commits de correction).

**Objectif (CDC §11) :** rapprocher chaque facture des BL déposés, bloc par bloc puis ligne par ligne, convertir les unités, traiter les avoirs, appliquer les règles R01 à R17 et offrir l'écran Anomalies. Ce que le client voit à la fin du lot : **des anomalies réelles sur les factures d'août (et de septembre dès qu'elle arrive), chacune justifiée par sa règle et ses chiffres**.

**Critères de réception (CDC §10, lot Rapprochement et lot Règles) :**
- Chaque bloc BL des factures de recette est classé reçu / non reçu / pas de bon, sans faux positif (100 % vérifié à la main).
- Les conversions d'unité connues (seau ↔ kg, rouleau ↔ m) donnent une comparaison exacte : 0 anomalie R03/R04 due à une unité.
- Chaque anomalie affichée cite sa règle, sa justification chiffrée et son document source (revue de 30 anomalies tirées au hasard).
- Chaque règle a au moins un test unitaire positif et un négatif (rapport pytest).
- Semi-remorque : déclencheur **non défini** par le client → voir L4-D16.

**Architecture :** on s'appuie sur les lots 1 à 3. Ce lot ajoute le module **pur** `app/modules/rules/` (moteur + une fonction par règle), l'orchestration `ingest/rapprochement.py` et `ingest/anomalies.py`, les routes `api/anomalies.py`, l'écran `web/src/pages/Anomalies.tsx`, et deux commandes CLI (rejeu du rapprochement, contrôles différés).

**Spec :** `docs/cahier-des-charges.md` (§4.5, §5, §6, §10, §11). À lire aussi : `docs/passation-lot-3.md`, `docs/lot-3-recette.md`, `docs/dette.md`.

**Statut :** plan écrit en autonomie (mandat d'Ilane du 17/09/2026 : « le lot 4 toute la nuit »), exécuté sans validation préalable. Chaque décision prise sans Ilane est listée en §4 avec son coût si elle est mauvaise.

---

## 1. Contraintes globales

Celles des lots 1 à 3 (`docs/plan-lot-3.md` §1, `CLAUDE.md`) s'appliquent toutes. Les plus exposées ici :
- `rules` est un module **pur** : ni FastAPI, ni SQLAlchemy, ni httpx, ni log ; il n'importe **aucun** autre module de `app.modules` (y compris `extract` et `normalize`) ; entrées et sorties en dataclasses ; tests sans base ni réseau.
- Chaque règle `Rxx` est une fonction pure qui reçoit des dataclasses et retourne `Anomalie | None` (ou un tuple pour les règles qui balaient une collection), avec un champ `detail` contenant **toutes** les valeurs ayant déclenché la règle, en chaînes. Au moins un test positif et un test négatif par règle.
- `ingest` reste le seul orchestrateur ; `api` n'importe que `ingest` et `app.core` ; aucune règle métier dans les routers ni dans le front.
- Montants, quantités, taux : `Decimal`, jamais `float`.
- Toute action d'un utilisateur qui modifie une donnée métier est journalisée ; les décisions automatiques le sont avec `utilisateur_id = NULL`.
- Données client : aucune valeur réelle dans le code, les tests, les commits, les logs ou les messages. Les fixtures réelles restent dans `tests/fixtures/` (ignoré par git) ; un test qui les lit fait `pytest.skip` si absentes et n'affirme que des booléens calculés d'avance (Ruling R7 du lot 3).
- Interface en français, écran Anomalies utilisable sur téléphone **et** sur ordinateur (CDC §4.6).

## 2. Constats (état au début du lot 4, `main` @ `7f22bcc`)

1. Le rapprochement « BL reçu / non reçu » existe déjà **en lecture seule** : `ingest/lecture.py` calcule `bl_recu` par bloc à l'affichage d'une facture (L2-D12) ; `bloc_facture.bl_document_id` et `bloc_facture.statut_rapprochement` ne sont **jamais écrits**. `ingest/factures.py::blocs_avec_reception` fait la même correspondance pour la CLI `bl-non-recus`.
2. Les tables `rapprochement_ligne`, `anomalie` et `parametre` existent (migration 0001) et sont **vides d'usage** : aucun code ne les écrit. `anomalie` porte `regle`, `gravite` (haute/moyenne/basse), `document_id`, `bloc_id`, `ligne_id`, `detail` (jsonb non vide), `statut` (ouverte/traitee/ignoree), `traitee_par`, `traitee_le`, `commentaire`. Aucune contrainte d'unicité.
3. `ligne.qte_fact` (quantité convertie) existe et n'est jamais renseignée. Depuis le lot 3 (L3-D24) : `ligne.qte_livree` = nombre de conditionnements, `ligne.qte_totale` = quantité facturée, pour les BL **comme** pour les factures.
4. `article` porte `unite_cdt`, `unite_fact`, `ratio`, `valide` ; `normalize/unites.py::normaliser_unite` et `normalize/article.py::proposer_ratio` existent. Il n'existe **pas** de fonction de conversion.
5. `extract/verification.py` produit déjà les motifs `somme_incoherente` (document dont la somme des lignes ≠ total) pour les BL **et** les factures, persistés dans `document.motifs`. C'est la matière de R10 et R11 (constat 2 : aucune anomalie n'est créée aujourd'hui).
6. Les seuils du CDC §5 ne sont nulle part : `parametre` est vide, `lire_parametre_decimal(session, cle, defaut)` existe (`ingest/referentiels.py`).
7. Matière réelle disponible pour la recette (mesurée le 17/09) : la facture Unikalo d'août donne **28 blocs** (28 numéros distincts), **132 lignes** dont 105 avec un code article, **44 lignes dont la quantité de conditionnement diffère de la quantité facturée** (matière de R17 et des conversions), **3 lignes négatives** (matière de R13) et **15 blocs portant un commentaire** (matière de R02). **3 des 4 photos de BL portent un numéro présent dans cette facture** : le rapprochement réel bloc ↔ BL est donc mesurable (3 reçus, 25 non reçus), mais aucune comparaison ligne à ligne réelle n'est possible sur la quatrième photo (bon Point.P, fournisseur différent).
8. Il n'y aura **pas d'autre photo** (Ilane, 17/09) : le critère du lot 3 (30 BL) reste non mesurable, et les règles de ligne (R03–R06, R17) ne seront vérifiées sur données réelles que sur les 3 BL communs.
9. L'écran « À traiter » (lot 3) prévoit une section « anomalies ouvertes de gravité haute » (CDC §4.6) qui n'existe pas encore.
10. Pre-commit lance la suite complète à chaque commit : un seul commit à la fois par base de test (bases `bl_test` et `bl_test_wt` pour un second arbre de travail, L3-D22).

## 3. Questions à Ilane (non bloquantes, décisions provisoires en §4)

- **Q1 — Semi-remorque.** Le CDC (§5) exige une anomalie de gravité haute pour toute livraison par semi-remorque, mais dit que le déclencheur sera défini avec le client à partir de cas réels. Rien dans les documents lus ne le distingue. Provisoire : **non construit** (L4-D16), à ouvrir dès qu'Ilane décrit comment ces livraisons apparaissent.
- **Q2 — Historique des prix.** R07 compare à la médiane des 6 derniers mois. Avec une seule facture réelle, il n'y a pas d'historique. Provisoire : pas d'anomalie sous 3 occurrences (L4-D9), seuils 5 % / 15 % du CDC.
- **Q3 — Qui traite une anomalie ?** Le CDC réserve le traitement des anomalies à l'admin. Provisoire : lecture et traitement **admin seulement**, l'agent ne voit pas l'écran.
- **Q4 — Anomalie qui disparaît.** Quand une correction ou un dépôt de BL fait disparaître la cause d'une anomalie encore `ouverte`, faut-il la garder ? Provisoire : elle est supprimée et sa levée journalisée (L4-D12).
- **Q5 — Avoirs.** Aucun avoir n'a été fourni : les 3 lignes négatives de la facture d'août sont traitées comme des avoirs de ligne (R13), mais un document d'avoir complet n'est toujours pas géré (dette du lot 2).
- **Q6 — Vérification des verdicts.** Le classement « reçu / non reçu / pas de bon » des 28 blocs d'août ne peut être confirmé sans Ilane : nous savons seulement que 3 BL ont été photographiés. Provisoire : la recette liste les verdicts à confirmer par le client.

## 4. Décisions prises en autonomie

| # | Décision | Pourquoi | Coût si faux |
| --- | --- | --- | --- |
| L4-D1 | Module `rules` **pur**, sans import d'`extract` ni de `normalize` : il définit ses propres dataclasses d'entrée (`rules/modeles.py`) ; `ingest` les construit depuis la base | Règle de frontière du CDC §7 et de `CLAUDE.md` | Duplication de quelques dataclasses (assumée) |
| L4-D2 | Une fonction par règle dans `rules/rules/Rxx.py`, signature `Rxx(...) -> Anomalie | None` (ou `tuple[Anomalie, ...]` pour les règles qui balaient une collection), plus `rules/engine.py` qui les enchaîne dans l'ordre du CDC §5 et renvoie `tuple[Anomalie, ...]` | CDC §5 : « chaque règle est une fonction pure, nommée, testée unitairement » | — |
| L4-D3 | Le rapprochement d'une facture est **idempotent** : `rapprocher_facture(session, facture_id)` recalcule tout (blocs, lignes, anomalies) et peut être rejoué sans doublon. Déclenché au dépôt d'une facture, après l'extraction ou la validation d'un BL dont le numéro apparaît dans des blocs, et par la CLI | Une photo arrive souvent après la facture (CDC §4.5) | — |
| L4-D4 | `bloc_facture.bl_document_id` et `statut_rapprochement` (`recu` / `non_recu` / `pas_de_bon`) sont **persistés** par le rapprochement ; la lecture des factures (L2-D12) continue d'afficher ce qui est persisté, en se rabattant sur le calcul à la volée tant qu'aucun rapprochement n'a tourné | Le CDC §6 prévoit ces colonnes ; les règles et le bilan (lot 5) en ont besoin | Recalcul à la lecture |
| L4-D5 | Correspondance bloc ↔ BL : même fournisseur **et** même numéro normalisé (`normaliser_numero_bl`), document non archivé. Plusieurs BL de même numéro → le plus ancien non archivé, les autres sont signalés en doublon par R12 | Règle déjà utilisée par la CLI du lot 1 | — |
| L4-D6 | Appariement des lignes d'un bloc : d'abord par code article normalisé (`methode = "code"`), puis, pour les lignes restantes, par désignation normalisée identique (`methode = "libelle"`). Une ligne de BL ne peut être appariée qu'une fois ; l'appariement ne franchit jamais la frontière d'un bloc. `rapprochement_ligne` porte `ecart_qte` = `qte_fact(facture) - qte_fact(BL)` | CDC §4.5 | Appariement à affiner (ex. distance de chaînes) |
| L4-D7 | `ligne.qte_fact` est renseignée par le rapprochement : quantité facturée convertie en unité de facturation de l'article. Conversion (`normalize/unites.py::convertir_en_unite_fact`) : même unité → quantité inchangée ; unité de conditionnement connue et ratio **validé** → quantité × ratio ; sinon `None`. Une ligne dont la conversion est impossible ne produit **jamais** R03/R04 : elle produit un motif de suivi (`conversion_impossible`) visible dans l'anomalie R05/R06 correspondante ou, à défaut, aucune anomalie | CDC §10 : « 0 anomalie R03/R04 due à une unité » | Comparaisons manquées, jamais fausses |
| L4-D8 | R10 et R11 ne recalculent pas la somme : elles reprennent le motif `somme_incoherente` déjà produit par l'extraction (lot 3) et persisté dans `document.motifs`, pour qu'une incohérence apparaisse **aussi** dans l'écran Anomalies avec sa justification chiffrée | Une seule source de vérité pour la somme ; CDC §5 « R10 et R11 d'abord » | — |
| L4-D9 | Historique des prix (R07/R08/R09) : lignes `article` de factures du même fournisseur, sur les 6 mois précédant la date de la facture contrôlée, hors facture contrôlée. Médiane des `pu_ht`. **Aucune anomalie sous 3 occurrences.** R09 : remise habituelle = médiane des `remise_pct` non nulles quand au moins 3 lignes en portent une | CDC §5 (R07 : « nb d'occurrences » dans la justification) ; éviter le bruit au démarrage | Seuil d'occurrences à changer |
| L4-D10 | Seuils dans `parametre`, créés avec leur valeur par défaut au premier rapprochement : `tolerance_total_ht` 0.05, `seuil_prix_pct` 5, `seuil_prix_fort_pct` 15, `occurrences_prix_min` 3, `delai_ligne_bl_non_facturee_j` 45, `delai_alias_non_resolu_h` 48, `delai_confirmation_bl_h` 24, `delai_chantier_silencieux_j` 7, `duree_ignorance_j` 90. Lus par `ingest`, passés aux règles ; l'écran de paramétrage reste au lot 5 | CDC §5 : « seuils modifiables par l'admin » | Valeurs à changer en base |
| L4-D11 | Identité d'une anomalie : `(regle, document_id, bloc_id, ligne_id)`, garantie par un index unique (migration 0006, `NULLS NOT DISTINCT`). Un rejeu met à jour `detail` et `gravite` d'une anomalie `ouverte` existante au lieu d'en créer une seconde | Idempotence (L4-D3) | Migration d'index |
| L4-D12 | Une anomalie `ouverte` dont la cause a disparu est **supprimée** au rejeu, avec une entrée de journal `anomalie_levee` (auteur `NULL`, `avant` = son detail). Une anomalie `traitee` ou `ignoree` n'est jamais supprimée ni modifiée | Q4 ; l'écran ne doit pas garder des anomalies fantômes | Statut « levée » à ajouter si Ilane veut les conserver |
| L4-D13 | Règle des 90 jours (CDC §5) : une anomalie `ignoree` depuis moins de `duree_ignorance_j` bloque la régénération d'une anomalie de **même règle** pour le même couple (fournisseur, article) — d'où la colonne `anomalie.article_id` (migration 0006). Une anomalie sans article (niveau bloc ou document) n'est jamais bloquée | CDC §5 | Colonne à retirer |
| L4-D14 | Règles de suivi (R06, R14, R15, R16) : calculées par une commande `python -m app.cli controles-differes` (idempotente, à lancer quotidiennement par cron), pas à chaque dépôt — elles dépendent du temps écoulé, pas d'un document | CDC §5 (délais) ; pas de worker (CDC §7) | Planification à ajouter |
| L4-D15 | Cycle de vie : `POST /api/anomalies/{id}/traitement` avec `{statut: "traitee" | "ignoree", commentaire}` — commentaire obligatoire (1 à 500 caractères), transition uniquement depuis `ouverte`, journal `anomalie_traitee` / `anomalie_ignoree` | CDC §4.6, §5 | — |
| L4-D16 | **Semi-remorque non construite** : aucun déclencheur défini par le client (CDC §5 le dit explicitement). Documenté dans la recette et la dette | CLAUDE.md : « si quelque chose n'y est pas, on ne le construit pas » | Règle R18 à écrire à réception du déclencheur |
| L4-D17 | Écran Anomalies réservé à l'admin (Q3), avec filtres règle / gravité / statut / chantier / fournisseur / période, chaque ligne citant la règle, sa phrase de justification construite **côté front à partir du `detail` de l'API** (même mécanique que `lib/motifs.ts`) et un lien vers le document source | CDC §4.6 | Ouvrir aux agents |
| L4-D18 | La section « anomalies ouvertes de gravité haute » de l'écran « À traiter » (constat 9) est ajoutée dans ce lot, alimentée par la même API | CDC §4.6 | — |

## 5. Structure des fichiers

```
app/modules/rules/__init__.py                    L4-T1
app/modules/rules/modeles.py                     L4-T1  dataclasses d'entrée + Anomalie + Gravite
app/modules/rules/engine.py                      L4-T1  evaluer_facture, evaluer_suivi
app/modules/rules/rules/R01.py … R17.py          L4-T2 à L4-T5
app/modules/rules/tests/                         L4-T1 à L4-T5
app/modules/normalize/unites.py                  L4-T6  convertir_en_unite_fact
app/modules/normalize/appariement.py             L4-T6  apparier_lignes
migrations/versions/0006_anomalies.py            L4-T7  index unique + anomalie.article_id
app/modules/ingest/models.py                     L4-T7
app/modules/ingest/rapprochement.py              L4-T7  rapprocher_facture (blocs, lignes, qte_fact)
app/modules/ingest/anomalies.py                  L4-T8  génération idempotente, cycle de vie, lecture
app/modules/ingest/factures.py                   L4-T7  déclenchement au dépôt
app/modules/ingest/corrections.py                L4-T7  déclenchement après validation d'un BL
app/modules/ingest/lecture.py                    L4-T7  statut persisté puis calcul de secours
app/modules/api/anomalies.py                     L4-T9
app/modules/api/schemas.py                       L4-T9
app/modules/api/a_traiter.py                     L4-T9  section anomalies hautes
app/cli.py                                       L4-T11 rapprocher, controles-differes
app/modules/ingest/suivi.py                      L4-T11 contrôles différés (R06, R14, R15, R16)
web/src/pages/Anomalies.tsx                      L4-T10
web/src/lib/regles.ts                            L4-T10 libellés et justifications
web/src/api/anomalies.ts                         L4-T10
docs/lot-4-recette.md, docs/dette.md             L4-T12
```

## 6. Tâches

Ordre et parallélisme : **flux pur** dans l'arbre séparé (L4-T1 → L4-T2 → L4-T3 → L4-T4 → L4-T5 → L4-T6) pendant que le **flux principal** attend L4-T1 (modèles) puis enchaîne L4-T7 → L4-T8 ; intégration par cherry-pick ; puis L4-T9 → L4-T10 ; L4-T11 en parallèle du front ; L4-T12 en dernier.

### L4-T1 — `rules: socle du moteur de règles`
Fichiers `rules/modeles.py`, `rules/engine.py`, `rules/rules/R10.py`, `R11.py`, tests.

```python
# modeles.py
class Gravite(StrEnum):
    HAUTE = "haute"; MOYENNE = "moyenne"; BASSE = "basse"

@dataclass(frozen=True)
class Anomalie:
    regle: str                      # "R01" … "R17"
    gravite: Gravite
    detail: dict[str, str]          # toutes les valeurs ayant déclenché la règle, jamais vide
    document_id: uuid.UUID | None = None
    bloc_id: uuid.UUID | None = None
    ligne_id: uuid.UUID | None = None
    article_id: uuid.UUID | None = None

@dataclass(frozen=True)
class LigneControlee:
    id: uuid.UUID
    ordre: int
    code: str | None                # code article normalisé, None si absent
    designation: str | None
    article_id: uuid.UUID | None
    qte_conditionnements: Decimal | None   # ligne.qte_livree
    qte_facturee: Decimal | None           # ligne.qte_totale
    qte_fact: Decimal | None               # convertie en unité de facturation, None si impossible
    unite: str | None
    pu_ht: Decimal | None
    remise_pct: Decimal | None
    montant_ht: Decimal | None
    type_ligne: str                        # "article" | "eco" | "commentaire"
    conversion_impossible: bool

@dataclass(frozen=True)
class ArticleControle:
    id: uuid.UUID
    code: str
    libelle: str | None
    unite_cdt: str | None
    unite_fact: str | None
    ratio: Decimal | None
    valide: bool

@dataclass(frozen=True)
class LigneRapprochee:
    facture: LigneControlee
    bl: LigneControlee | None
    methode: str | None             # "code" | "libelle" | None

@dataclass(frozen=True)
class DocumentControle:
    id: uuid.UUID
    numero_interne: int
    numero: str | None
    date_doc: date | None
    statut: str
    somme_lignes: Decimal | None
    total_ht: Decimal | None
    ecart_somme: Decimal | None     # None si la somme est cohérente ou non calculable
    depose_le: datetime | None
    deposant: str | None
    confirme_le: datetime | None

@dataclass(frozen=True)
class BlocControle:
    id: uuid.UUID
    numero_bl: str | None
    date_bl: date | None
    chantier_brut: str | None
    chantier: str | None            # nom canonique si résolu
    commentaire: str | None
    montant_ht: Decimal
    bl: DocumentControle | None
    lignes: tuple[LigneRapprochee, ...]
    lignes_bl_non_facturees: tuple[LigneControlee, ...]
    autre_facture_numero: str | None        # R12 : autre facture du même fournisseur portant ce n° de BL
    autre_facture_id: uuid.UUID | None

@dataclass(frozen=True)
class HistoriqueArticle:
    article_id: uuid.UUID
    mediane_pu: Decimal | None
    occurrences: int
    remise_habituelle: Decimal | None
    occurrences_remise: int

@dataclass(frozen=True)
class FactureControlee:
    document: DocumentControle
    fournisseur: str
    blocs: tuple[BlocControle, ...]
    articles: Mapping[uuid.UUID, ArticleControle]
    historiques: Mapping[uuid.UUID, HistoriqueArticle]
    lignes_negatives_sans_origine: tuple[tuple[LigneControlee, str | None], ...]  # (ligne, chantier) — origine cherchée par ingest

@dataclass(frozen=True)
class Parametres:
    tolerance_total_ht: Decimal = Decimal("0.05")
    seuil_prix_pct: Decimal = Decimal("5")
    seuil_prix_fort_pct: Decimal = Decimal("15")
    occurrences_prix_min: int = 3
    delai_ligne_bl_non_facturee_j: int = 45
    delai_alias_non_resolu_h: int = 48
    delai_confirmation_bl_h: int = 24
    delai_chantier_silencieux_j: int = 7
    duree_ignorance_j: int = 90

def evaluer_facture(facture: FactureControlee, parametres: Parametres) -> tuple[Anomalie, ...]
```
- `evaluer_facture` enchaîne dans l'ordre du CDC §5 : R10 sur la facture ; R11 sur chaque BL rapproché ; **si R10 est produite, aucune autre règle ne tourne pour cette facture** (le document est incohérent) ; sinon R01, R02, R12 (bloc), puis R03, R04, R05, R07, R08, R09, R13, R17 (ligne), dans l'ordre des blocs puis des lignes.
- `R10(document, parametres) -> Anomalie | None` : `ecart_somme` non nul et `abs(ecart) > tolerance` → gravité haute, detail `{"somme", "total", "ecart", "tolerance"}`.
- `R11(document, parametres) -> Anomalie | None` : idem sur un BL, gravité moyenne, `document_id` = le BL.
- Tests : un positif et un négatif par règle ; tolérance exactement à la limite ; `evaluer_facture` s'arrête après R10 ; ordre des anomalies renvoyées ; `detail` jamais vide ; frontières (`tests/test_frontieres.py` reste vert).

### L4-T2 — `rules: règles de bloc R01, R02, R12`
- `R01(bloc) -> Anomalie | None` : `bloc.bl is None` **et** pas de mention « pas de bon » → gravité haute, detail `{"numero_bl", "chantier", "date_bl", "montant_ht"}`.
- `R02(bloc) -> Anomalie | None` : `bloc.bl is None` **et** `mention_pas_de_bon(bloc.commentaire)` → gravité haute, detail de R01 + `{"mention"}` (l'extrait lu, tronqué à 200 caractères). R01 et R02 s'excluent.
- `mention_pas_de_bon(commentaire: str | None) -> str | None` (dans `R02.py`) : renvoie l'extrait correspondant quand le commentaire normalisé (majuscules, sans accents, espaces réduits) contient `PAS DE BON` ou `SANS BON`, sinon `None`.
- `R12(bloc, facture_numero) -> Anomalie | None` : `bloc.autre_facture_id` renseigné → gravité haute, detail `{"numero_bl", "facture", "autre_facture", "montant_ht"}`.
- Tests : positif et négatif chacun ; bloc reçu → ni R01 ni R02 ; commentaire avec mention mais BL reçu → aucune des deux ; variantes de mention (accents, casse, espaces) ; commentaire `None`.

### L4-T3 — `rules: règles de ligne R03, R04, R05, R17`
- `R03(bloc, rapprochee, articles) -> Anomalie | None` : lignes appariées, `qte_fact` des deux côtés non nulle, écart `facture - bl > 0` → haute, detail `{"article", "code", "qte_bl", "qte_facture", "unite", "ecart"}`.
- `R04` : même chose pour un écart négatif → moyenne.
- `R05(bloc, rapprochee) -> Anomalie | None` : ligne de facture `type_ligne == "article"` non appariée alors que le bloc a un BL rapproché → haute, detail `{"article", "code", "qte", "montant"}`.
- `R17(ligne, article) -> Anomalie | None` : `article.ratio` validé et `qte_conditionnements` non entier (partie décimale non nulle) → moyenne, detail `{"article", "code", "qte", "conditionnement", "ratio"}`.
- Aucune de ces règles ne se déclenche quand `conversion_impossible` est vrai pour la ligne concernée (L4-D7) ni sur une ligne `eco`/`commentaire`.
- Tests : positif et négatif par règle ; égalité exacte des quantités → ni R03 ni R04 ; conversion impossible → aucune anomalie de quantité ; ligne éco ignorée ; quantité de conditionnement entière → pas de R17 ; 2,5 conditionnements → R17.

### L4-T4 — `rules: prix et remises R07, R08, R09`
- `R07(ligne, article, historique, parametres) -> Anomalie | None` : historique avec `occurrences >= occurrences_prix_min` et médiane non nulle ; écart relatif `abs(pu - mediane) / mediane * 100` strictement supérieur à `seuil_prix_pct` et **inférieur ou égal** à `seuil_prix_fort_pct` → moyenne, detail `{"article", "code", "pu_facture", "mediane", "occurrences", "ecart_pct"}`.
- `R08` : même calcul, écart strictement supérieur à `seuil_prix_fort_pct` → haute, même detail. R07 et R08 s'excluent.
- `R09(ligne, article, historique, parametres) -> Anomalie | None` : `historique.occurrences_remise >= occurrences_prix_min` et `remise_habituelle` non nulle, ligne sans remise (`remise_pct` nulle ou zéro) → moyenne, detail `{"article", "code", "remise_habituelle", "remise_appliquee", "occurrences"}`.
- Calculs en `Decimal`, écart arrondi à 2 décimales (`ROUND_HALF_UP`) pour le `detail` mais comparé sans arrondi.
- Tests : positif et négatif par règle ; exactement au seuil (5 % et 15 %) → rien pour R07/R08 respectivement ; 2 occurrences → rien ; prix inférieur à la médiane de plus de 5 % → R07 (l'écart est absolu) ; ligne sans `pu_ht` → rien.

### L4-T5 — `rules: avoirs et suivi R13, R06, R14, R15, R16`
- `R13(ligne, chantier) -> Anomalie | None` : ligne négative signalée sans origine par `ingest` (`lignes_negatives_sans_origine`) → moyenne, detail `{"article", "code", "montant", "chantier"}`.
- `R06(bloc, ligne_bl, aujourdhui, parametres) -> Anomalie | None` : ligne du BL non facturée et `date_bl` antérieure de plus de `delai_ligne_bl_non_facturee_j` → basse, detail `{"article", "code", "qte", "date_bl", "jours"}`.
- `R14(alias, aujourdhui, parametres) -> Anomalie | None` : alias chantier non validé depuis plus de `delai_alias_non_resolu_h` → moyenne, detail `{"libelle", "fournisseur", "heures"}`. Entrée : dataclass `AliasEnAttenteControle(id, libelle, fournisseur, cree_le)`.
- `R15(document, aujourdhui, parametres) -> Anomalie | None` : BL déposé sans confirmation depuis plus de `delai_confirmation_bl_h` → basse, detail `{"deposant", "depose_le", "heures"}`.
- `R16(chantier, aujourdhui, parametres) -> Anomalie | None` : chantier actif sans dépôt depuis plus de `delai_chantier_silencieux_j` **alors que des factures y référencent des BL depuis** → basse, detail `{"chantier", "dernier_depot", "bl_factures_depuis", "jours"}`. Entrée : `ChantierSuiviControle(id, nom, dernier_depot, nb_bl_factures_depuis)`.
- `evaluer_suivi(contexte: ContexteSuivi, parametres) -> tuple[Anomalie, ...]` dans `engine.py`, où `ContexteSuivi` porte `aujourdhui: datetime`, les blocs avec lignes de BL non facturées, les alias en attente, les BL sans confirmation et les chantiers suivis.
- Tests : positif et négatif par règle ; exactement au délai → rien ; chantier silencieux sans BL facturé depuis → rien.

### L4-T6 — `normalize: conversion d'unités et appariement des lignes`
```python
# normalize/unites.py
def convertir_en_unite_fact(qte: Decimal | None, unite_lue: str | None,
                            unite_cdt: str | None, unite_fact: str | None,
                            ratio: Decimal | None, ratio_valide: bool) -> Decimal | None
# normalize/appariement.py
@dataclass(frozen=True)
class LigneAApparier:
    cle: uuid.UUID
    code: str | None
    designation: str | None
@dataclass(frozen=True)
class Appariement:
    cle_facture: uuid.UUID
    cle_bl: uuid.UUID | None
    methode: str | None            # "code" | "libelle" | None
def apparier_lignes(lignes_facture: Sequence[LigneAApparier],
                    lignes_bl: Sequence[LigneAApparier]) -> tuple[Appariement, ...]
```
- `convertir_en_unite_fact` : unité lue égale à `unite_fact` (après `normaliser_unite`) → `qte` ; unité lue égale à `unite_cdt` avec `ratio` non nul et `ratio_valide` → `qte * ratio` ; `unite_lue` absente et `unite_fact` connue → `qte` (cas Unikalo, qui n'imprime pas d'unité sur la ligne) ; tout le reste → `None`.
- `apparier_lignes` : première passe sur les codes normalisés (`normaliser_libelle` sans espaces), une ligne de BL consommée une seule fois, ordre stable ; deuxième passe sur les désignations normalisées ; une ligne de facture sans correspondance donne `cle_bl=None, methode=None`.
- Tests : conversion dans les quatre cas ; ratio non validé ignoré ; appariement par code, par libellé, doublons de code (chacun apparié une fois), lignes en trop des deux côtés, ordre stable.

### L4-T7 — `ingest: rapprochement des factures`
- Migration `0006_anomalies.py` : `anomalie.article_id` (FK `article.id`, nullable) ; index unique `(regle, document_id, bloc_id, ligne_id)` avec `postgresql_nulls_not_distinct=True`.
- `ingest/rapprochement.py` :
```python
@dataclass(frozen=True)
class ResultatRapprochement:
    facture_id: uuid.UUID
    nb_blocs: int
    nb_blocs_recus: int
    nb_blocs_pas_de_bon: int
    nb_lignes_appariees: int
    nb_anomalies: int

async def rapprocher_facture(session, facture_id: uuid.UUID) -> ResultatRapprochement
async def rapprocher_factures_du_bl(session, document_id: uuid.UUID) -> list[ResultatRapprochement]
```
  - charge la facture, ses blocs et lignes, les BL candidats (L4-D5), les articles, l'historique de prix (L4-D9), les autres factures portant les mêmes numéros de BL (R12) et les lignes négatives sans origine (recherche d'une ligne positive antérieure de même article et même chantier, toutes factures du fournisseur) ;
  - écrit `bloc_facture.bl_document_id` et `statut_rapprochement` (`pas_de_bon` si mention et pas de BL, `recu` si BL, `non_recu` sinon), `ligne.qte_fact` (facture **et** BL), les lignes de `rapprochement_ligne` (remplacées à chaque rejeu pour cette facture) ;
  - appelle `evaluer_facture` puis délègue la persistance des anomalies à `ingest/anomalies.py::synchroniser_anomalies` (L4-T8) ;
  - journalise `facture_rapprochee` (auteur `NULL`) avec les compteurs ;
  - ne fait rien et renvoie un résultat vide si la facture n'est pas `recu` (document « à vérifier » : CDC §5, ordre d'exécution).
- Déclenchements : à la fin de `deposer_facture` (même transaction), après `valider_document` d'un BL et après une extraction de BL qui donne un numéro (`rapprocher_factures_du_bl`), sans jamais faire échouer l'action appelante (erreur journalisée).
- `ingest/lecture.py` : `bl_recu` lit `statut_rapprochement` quand il est renseigné, sinon garde le calcul actuel ; le détail d'une facture expose `statut_rapprochement` et `bl_document_id` persistés.
- Tests (base) : facture + BL déposé avant → bloc `recu`, `bl_document_id` renseigné, lignes appariées, `qte_fact` calculée ; BL déposé après → un rejeu via `rapprocher_factures_du_bl` met le bloc à jour ; mention « pas de bon » sans BL → `pas_de_bon` ; rejeu complet → aucun doublon (lignes de rapprochement et anomalies stables) ; facture `a_verifier` → aucun rapprochement ; fixture réelle (skip si absente) : 28 blocs, exactement les blocs dont le numéro correspond à une photo sont `recu` (booléen calculé, message fixe).

### L4-T8 — `ingest: anomalies (génération idempotente, cycle de vie, lecture)`
- `ingest/anomalies.py` :
```python
async def synchroniser_anomalies(session, *, portee_document_id: uuid.UUID,
                                 anomalies: Sequence[AnomaliePure]) -> int
async def lister_anomalies(session, *, regle=None, gravite=None, statut=None,
                           chantier_id=None, fournisseur_id=None,
                           depuis=None, jusqu_a=None, limite=100) -> list[AnomalieLue]
async def compter_anomalies_hautes_ouvertes(session) -> int
async def traiter_anomalie(session, anomalie_id, *, statut: str, commentaire: str,
                           auteur_id) -> AnomalieLue
class AnomalieIntrouvable(Exception)
class TransitionInterdite(Exception)   # anomalie déjà traitée ou ignorée
```
  - `synchroniser_anomalies` : upsert par la clé de L4-D11 (met à jour `detail`, `gravite`, `article_id` d'une anomalie `ouverte`), supprime les anomalies `ouverte` de la portée qui ne sont plus produites (journal `anomalie_levee`), ne touche jamais une anomalie `traitee`/`ignoree`, et n'insère pas une anomalie bloquée par la règle des 90 jours (L4-D13).
  - `AnomalieLue` porte `id, regle, gravite, statut, detail, cree_le, traitee_le, traitee_par, commentaire`, le document source (`document_id`, `numero_interne`, `type`, `numero`), le bloc (`bloc_id`, `numero_bl`), le chantier (`chantier_id`, `chantier`), le fournisseur (`fournisseur_id`, `fournisseur`) et `bl_document_id` quand il existe (lien vers la photo).
  - `traiter_anomalie` : commentaire obligatoire, transition depuis `ouverte` seulement, journal `anomalie_traitee`/`anomalie_ignoree` avec avant/après.
- Tests (base) : upsert sans doublon sur rejeu ; anomalie levée supprimée + journal ; anomalie traitée jamais touchée par un rejeu ; règle des 90 jours (ignorée il y a 10 j → pas de régénération ; il y a 100 j → régénérée) ; filtres de `lister_anomalies` (chacun) ; transitions et refus ; commentaire vide refusé.

### L4-T9 — `api: anomalies`
- `GET /api/anomalies` (admin) : filtres `regle`, `gravite`, `statut` (défaut `ouverte`), `chantier_id`, `fournisseur_id`, `depuis`, `jusqu_a`, `limite` (1..500, défaut 100) → `list[AnomalieReponse]`.
- `POST /api/anomalies/{id}/traitement` (admin) `{statut, commentaire}` → 200 `AnomalieReponse` ; 404 ; 409 transition interdite ; 422 commentaire vide.
- `GET /api/a-traiter` gagne `anomalies_hautes: list[AnomalieReponse]` (ouvertes, gravité haute, 20 au plus, les plus anciennes d'abord) — L4-D18.
- `AnomalieReponse` dans `api/schemas.py` : mêmes champs qu'`AnomalieLue`, `detail` en `dict[str, str]`.
- Tests : droits (agent → 403 sur les deux routes) ; chaque filtre ; transition et refus ; présence dans `À traiter` ; schémas OpenAPI présents.

### L4-T10 — `web: écran Anomalies`
- `npm run api:schema && npm run api:types` régénérés et commités.
- `web/src/lib/regles.ts` : `libelleRegle(code)` (« R03 — Quantité facturée > quantité BL ») et `justification(anomalie)` qui construit la phrase française à partir du `detail` (valeurs formatées par `lib/formats.ts`), avec repli sur la liste brute `clé : valeur` pour une règle inconnue. **Aucun calcul** : uniquement de la mise en forme.
- Page `web/src/pages/Anomalies.tsx` (route `/anomalies`, admin) : filtres (règle, gravité, statut, chantier, fournisseur, période), cartes sur téléphone / tableau à partir de `md`, chaque anomalie affichant sa règle, sa gravité (pastille), sa justification chiffrée, le document source (lien vers `/documents/:id` ou `/factures/:id`) et, si elle est reçue, la photo du BL ; actions « Traitée » et « Ignorée » ouvrant un champ commentaire obligatoire ; invalidation de `["anomalies"]` et `["a-traiter"]` après traitement ; état vide explicite.
- Navigation : onglet « Anomalies » (admin) après « À traiter » ; section « Anomalies à traiter » dans l'écran « À traiter » (L4-D18) avec lien vers l'écran complet.
- Vérification visuelle : `.superpowers/sdd/plan-lot-4/verification-front.md` (Chromium sans interface, captures 375 et 1280 px, données inventées), écrans : liste remplie, filtres actifs, liste vide, formulaire de commentaire, erreur 409.

### L4-T11 — `ingest/cli: contrôles différés et rejeu du rapprochement`
- `ingest/suivi.py` : `async def controles_differes(session, *, maintenant: datetime) -> int` — construit le `ContexteSuivi` (lignes de BL non facturées des blocs rapprochés, alias en attente, BL sans confirmation, chantiers actifs avec leur dernier dépôt et le nombre de BL facturés depuis), appelle `evaluer_suivi`, puis `synchroniser_anomalies` par portée (document ou chantier). Idempotent.
- CLI : `python -m app.cli rapprocher [--facture <uuid> | --tout]` (affiche les compteurs par facture, code 2 si la facture est introuvable) et `python -m app.cli controles-differes` (affiche le nombre d'anomalies de suivi ouvertes).
- `docs/exploitation-lot-4.md` : la ligne de cron quotidienne à poser sur le VPS client (et le rappel qu'aucun worker n'est prévu).
- Tests (base) : chaque règle de suivi déclenchée et non déclenchée à travers la commande ; rejeu sans doublon ; CLI (codes de sortie, sortie sans donnée réelle).

### L4-T12 — `docs: recette du lot 4`
- `docs/lot-4-recette.md` : ce qui est fait, la vérification commande par commande, les **verdicts réels sur la facture d'août** (nombre de blocs reçus / non reçus / pas de bon, anomalies produites par règle, à confirmer par Ilane), ce qui n'est pas vérifiable (semi-remorque, historique de prix sur un seul mois, avoir complet, deuxième facture), les décisions L4-D1 à L4-D18 et les rulings, les questions Q1 à Q6.
- `docs/passation-lot-4.md` : même forme que `docs/passation-lot-3.md` (état, tâches et commits, décisions, questions, pièges, point de départ du lot 5).
- `docs/dette.md` et la section « Où en est le projet » de `CLAUDE.md` mises à jour.

## 7. Récapitulatif des tests

| Zone | Sans base | Avec base | Manuel |
| --- | --- | --- | --- |
| Moteur, R10, R11 | L4-T1 | | |
| R01, R02, R12 | L4-T2 | | |
| R03, R04, R05, R17 | L4-T3 | | |
| R07, R08, R09 | L4-T4 | | |
| R13, R06, R14, R15, R16 | L4-T5 | | |
| Conversion, appariement | L4-T6 | | |
| Rapprochement | | L4-T7 | facture réelle d'août (contrôleur) |
| Anomalies (cycle de vie) | | L4-T8 | |
| API | | L4-T9 | écran (L4-T10) |
| Front | typecheck, build | | parcours admin, 375 px |
| Contrôles différés, CLI | | L4-T11 | |
