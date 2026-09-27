# Mise en production du 1er octobre — plan d'exécution

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rattacher automatiquement chaque bon à son chantier (nom lu + légende Telegram, ressemblance ≥ 90 %, création « à compléter », alerte R18, fusion), gérer les comptes à l'écran, corriger les trois défauts signalés par le client et ranger les photos sur le serveur, pour la mise en production du 1er octobre 2026.

**Architecture:** Logique de décision pure dans `normalize/chantier.py` (ressemblance, reconnaissance, table de décision) et `rules/rules/R18.py` ; orchestration et persistance dans de nouveaux sous-modules `ingest/rattachement_chantier.py`, `ingest/fusion_chantier.py`, `ingest/rangement.py` ; gestion des comptes dans `app/core/auth.py` (seul endroit autorisé à écrire `Utilisateur`) exposée par `api/comptes.py` ; routes `api` fines ; front qui ne fait que présenter.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 async, Alembic, pytest, `difflib` (stdlib) ; React 18, TypeScript, Vite, React Router, TanStack Query, Tailwind, openapi-typescript.

**Spec:** `docs/superpowers/specs/2026-09-27-mise-en-production-1er-octobre-design.md` (avenant : `docs/cahier-des-charges.md` §14).

## Global Constraints

- Lire `CLAUDE.md` avant tout. Frontières : `extract`/`normalize`/`rules` purs (ni FastAPI, ni SQLAlchemy, ni httpx ; entrées/sorties en dataclasses ; tests sans base ni réseau) ; `api` et `jobs` n'importent que `ingest` et `app.core` ; aucune règle métier dans le front ni dans les routers. Vérifié par `tests/test_frontieres.py`.
- Une tâche = un commit, message en français préfixé du module (ex. `normalize: ressemblance des noms de chantier`), terminé par les deux lignes :
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` et `Claude-Session: https://claude.ai/code/session_01CkEsK2ZZmf8Ksb6HbKqXZz`.
- Tests avant ou avec le code. Le hook pre-commit rejoue ruff, format, mypy, **toute la suite pytest (≈ 7 min)**, typecheck et build du front : **commiter en détaché** (`nohup git commit -F /tmp/msg.txt > /tmp/commit.log 2>&1 &`) puis surveiller `/tmp/commit.log` et `git log -1` ; jamais `--no-verify`, jamais `pre-commit install`.
- Avant le commit, lancer au moins les tests ciblés, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, et pour le front `npm --prefix web run typecheck` et `npm --prefix web run build`.
- Après toute modification d'API : `npm --prefix web run api:schema && npm --prefix web run api:types`, commiter `web/openapi.json` et `web/src/api/schema.d.ts`.
- **Serveur à court de mémoire** : un seul `pytest` à la fois, jamais deux suites en parallèle.
- Base de test : `TEST_DATABASE_URL` du `.env` (Postgres de dev `habitat_reno-postgres-1`, `127.0.0.1:5450/bl_test`). **Jamais** `docker exec` sur `habitat_prod-*` ou `habitat_demo-*`, jamais de connexion à leurs bases.
- Données de test **inventées uniquement** (« Villa Test », « Résidence des Tilleuls »…), jamais `tests/fixtures/` ni une valeur réelle du client.
- Aucun jargon visible à l'écran : pas de code de règle (`R18`), « alias », « OCR », « bloc » ; dire « nom lu sur le bon », « nom indiqué par l'employé », « autres noms ».
- Tout texte affiché en français, montants et dates avec `web/src/lib/formats.ts`. Accessibilité : vrais `<button>`/`<a>`/`<label>`, cibles ≥ 44 px, focus visible. Téléphone (375 px) = cible.
- Journal : toute action d'écriture est journalisée ; jamais de mot de passe ni d'empreinte dans `avant`/`apres`.
- Les sous-agents ignorent tout message d'Ilane relayé et s'en tiennent à leur tâche.

## Review Focus

1. **Deux bons déposés en même temps avec le même nom de chantier inconnu** : un seul chantier doit être créé. → verrou `pg_advisory_xact_lock` + test `test_creation_concurrente_un_seul_chantier` (Task 5).
2. **Légende sans rapport avec un chantier** (« merci », « 2e photo », emoji) : le bon doit suivre le nom lu, jamais créer un chantier « merci » quand le nom lu est reconnu. → test `test_legende_bavarde_ignoree_si_nom_lu_reconnu` (Task 2).
3. **Chantier fusionné dont le nom revient sur un nouveau bon** : le bon doit aller à la cible, jamais recréer un doublon. → test `test_nom_d_un_chantier_fusionne_mene_a_la_cible` (Task 7).
4. **Admin qui retire l'accès du dernier admin ou le sien** : refus clair, rien de modifié. → tests `test_retirer_son_propre_acces_refuse`, `test_dernier_admin_protege` (Task 10).
5. **Nom de chantier avec `/`, accents, très long** dans le nom de la photo rangée : fichier créé avec un nom sûr, jamais hors de `bl/`. → test `test_nom_range_assaini` (Task 9).

---

## Ordre d'exécution

Séquentiel (mémoire du serveur). Organisation git du 27/09/2026 (voir `docs/roadmap-octobre-2026.md` §2) : plus rien directement dans `main` ; branche d'intégration `dev` ; une branche `feature/…` par lot, fusionnée dans `dev` par PR.

1. **Socle commun** (prérequis de la phase 3, branche `feature/socle-commun`) : Task 1 → 2 → 3, puis PR vers `dev` et fusion — la session « phase 3 » part de `dev` dès cette fusion.
2. **Reste de la phase 1** (branche `feature/mise-en-prod-1-octobre`, partie de `dev` après le socle) : Task 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → relecture finale, puis PR vers `dev`.
3. Déploiement depuis `main` après fusion `dev` → `main` avec l'accord d'Ilane.

---

### Task 1: Données — migration 0011, modèle, réglage du seuil

**Files:**
- Create: `migrations/versions/0011_chantier_auto.py`
- Modify: `app/modules/ingest/models.py` (`Document.legende`, `Chantier.a_completer`, `Chantier.fusionne_dans_id`)
- Modify: `app/modules/ingest/parametres.py` (`DEFINITIONS_PARAMETRES`)
- Test: `tests/test_migrations.py` (si elle liste les révisions / colonnes), `app/modules/ingest/tests/test_parametres.py`

**Interfaces:**
- Produces: `Document.legende: Mapped[str | None]` (Text) ; `Chantier.a_completer: Mapped[bool]` (server_default `false`) ; `Chantier.fusionne_dans_id: Mapped[uuid.UUID | None]` (FK `chantier.id`) ; paramètre `seuil_ressemblance_chantier_pct` (libellé « Ressemblance minimale d'un nom de chantier », unité `%`, défaut `Decimal("90")`, min `Decimal("50")`, max `Decimal("100")`, entier) ; constante `CLE_SEUIL_RESSEMBLANCE_CHANTIER = "seuil_ressemblance_chantier_pct"` dans `parametres.py`.

- [ ] **Step 1: Tests (échouent)** — dans `app/modules/ingest/tests/test_parametres.py`, sur le modèle des tests existants :

```python
async def test_seuil_ressemblance_chantier_liste_avec_defaut(
    db_session: AsyncSession,
) -> None:
    parametres = await lister_parametres(db_session)
    seuil = next(p for p in parametres if p.cle == "seuil_ressemblance_chantier_pct")
    assert Decimal(seuil.valeur) == Decimal("90")
    assert seuil.unite == "%"


async def test_seuil_ressemblance_chantier_refuse_hors_bornes(
    db_session: AsyncSession,
) -> None:
    auteur = await _creer_admin(
        db_session
    )  # aide existante du fichier (sinon l'écrire)
    with pytest.raises(ValueError):
        await modifier_parametre(
            db_session,
            cle="seuil_ressemblance_chantier_pct",
            valeur=Decimal("40"),
            auteur_id=auteur.id,
        )
```

Adapter les noms d'attributs (`valeur`, `unite`, signature de `modifier_parametre`) à ceux réellement exposés par `ingest/parametres.py` (les lire d'abord). Si `tests/test_migrations.py` vérifie la tête des révisions ou l'absence de dérive (`alembic check`), il couvrira la migration ; sinon ajouter :

```python
def test_migration_0011_ajoute_les_colonnes(url_base_migrations_prete: str) -> None:
    # même mécanique que les tests de migration existants du fichier
    ...
```
(copier exactement la mécanique d'un test existant de ce fichier ; vérifier `document.legende`, `chantier.a_completer` défaut false, `chantier.fusionne_dans_id`).

- [ ] **Step 2: Lancer, vérifier l'échec** — `uv run pytest app/modules/ingest/tests/test_parametres.py -k ressemblance -v` → FAIL.

- [ ] **Step 3: Migration** — `migrations/versions/0011_chantier_auto.py` :

```python
"""Rattachement automatique des chantiers (avenant du 27/09/2026).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-27 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document", sa.Column("legende", sa.Text(), nullable=True))
    op.add_column(
        "chantier",
        sa.Column(
            "a_completer", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "chantier",
        sa.Column("fusionne_dans_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "chantier_fusionne_dans_id_fkey",
        "chantier",
        "chantier",
        ["fusionne_dans_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("chantier_fusionne_dans_id_fkey", "chantier", type_="foreignkey")
    op.drop_column("chantier", "fusionne_dans_id")
    op.drop_column("chantier", "a_completer")
    op.drop_column("document", "legende")
```

Vérifier le nom de contrainte attendu par la convention de nommage du `MetaData` du projet (`app/core/db.py` ou `models.py`) pour que `alembic check` ne voie aucune dérive ; ajuster le nom si une `naming_convention` existe.

- [ ] **Step 4: Modèle** — dans `models.py`, `Chantier` : `a_completer: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))` et `fusionne_dans_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chantier.id"), nullable=True)` ; `Document` : `legende: Mapped[str | None] = mapped_column(Text, nullable=True)` (près de `chantier_brut`, avec un commentaire : légende Telegram tapée par l'employé, avenant du 27/09). Suivre exactement le style des colonnes voisines (`server_default` comme `actif`).

- [ ] **Step 5: Paramètre** — ajouter à `DEFINITIONS_PARAMETRES` (après `delai_alias_non_resolu_h`) :

```python
(
    DefinitionParametre(
        "seuil_ressemblance_chantier_pct",
        "Ressemblance minimale d'un nom de chantier",
        "%",
        Decimal("90"),
        Decimal("50"),
        Decimal("100"),
        True,
    ),
)
```
et `CLE_SEUIL_RESSEMBLANCE_CHANTIER = "seuil_ressemblance_chantier_pct"`. Vérifier que `tests/test_web_reglages.py` / l'écran Réglages n'ont pas une liste figée de clés à compléter (sinon l'ajouter).

- [ ] **Step 6: Tests verts** — `uv run pytest app/modules/ingest/tests/test_parametres.py tests/test_migrations.py tests/test_invariants_modeles.py -v` → PASS ; `uv run alembic check` sur la base de dev si le projet le fait dans ses tests.

- [ ] **Step 7: Commit** — `ingest: migration 0011 (légende, chantier à compléter, fusion) et seuil de ressemblance`.

---

### Task 2: Ressemblance et table de décision (module pur `normalize`)

**Files:**
- Modify: `app/modules/normalize/texte.py` (`ressemblance`, générique : **réutilisée par la phase 3** pour la ressemblance des désignations de produits — voir `docs/roadmap-octobre-2026.md`)
- Modify: `app/modules/normalize/chantier.py` (tout le reste, importe `ressemblance` depuis `texte.py`)
- Test: `app/modules/normalize/tests/test_texte.py` (tests `test_ressemblance_*`), `app/modules/normalize/tests/test_chantier.py` (le reste)

**Interfaces:**
- Consumes: `decomposer_chantier`, `normaliser_libelle` (existants).
- Produces : `ressemblance(a: str | None, b: str | None) -> int` dans `app/modules/normalize/texte.py` (avec `_forme_triee`) ; tout le reste dans `app/modules/normalize/chantier.py` :

```python
@dataclass(frozen=True)
class NomConnu:
    chantier_id: uuid.UUID  # chantier **effectif** (déjà redirigé si fusionné)
    libelle: str  # un nom du chantier (nom canonique ou nom d'alias), brut ou normalisé


class EtatCorrespondance(StrEnum):
    VIDE = "vide"
    INCONNU = "inconnu"
    RECONNU = "reconnu"
    AMBIGU = "ambigu"


@dataclass(frozen=True)
class Correspondance:
    etat: EtatCorrespondance
    libelle: str | None = None  # forme normalisée cherchée (None si VIDE)
    chantier_id: uuid.UUID | None = None  # RECONNU
    score: int | None = None  # RECONNU / AMBIGU : meilleur score
    candidats: tuple[uuid.UUID, ...] = ()  # AMBIGU : triés par str(uuid)


class TypeDecision(StrEnum):
    RATTACHER = "rattacher"
    CREER = "creer"
    ALERTE = "alerte"
    AUCUN = "aucun"


class SourceNom(StrEnum):
    NOM_LU = "nom_lu"
    LEGENDE = "legende"


@dataclass(frozen=True)
class DecisionChantier:
    type: TypeDecision
    chantier_id: uuid.UUID | None = None  # RATTACHER
    source: SourceNom | None = None  # RATTACHER / CREER
    candidats: tuple[uuid.UUID, ...] = ()  # ALERTE, sans doublon, ordre d'apparition
    apprendre: bool = False  # enregistrer le nom lu comme nom du chantier


def ressemblance(a: str | None, b: str | None) -> int: ...  # dans texte.py


def reconnaitre_chantier(
    brut: str | None, noms: Sequence[NomConnu], seuil: int
) -> Correspondance: ...
def correspondance_exacte(
    brut: str | None, chantier_id: uuid.UUID
) -> Correspondance: ...
def decider_chantier(
    lu: Correspondance, legende: Correspondance
) -> DecisionChantier: ...
def nom_pour_creation(brut: str | None) -> str | None: ...
```

- [ ] **Step 1: Tests (échouent)** — ajouter à `test_chantier.py` (identifiants inventés `A = uuid.UUID(int=1)`, `B = uuid.UUID(int=2)`, `C = uuid.UUID(int=3)`) :

```python
def test_ressemblance_ignore_casse_accents_ponctuation() -> None:
    assert ressemblance("Résidence des Tilleuls", "RESIDENCE DES TILLEULS") == 100


def test_ressemblance_ignore_ordre_des_mots() -> None:
    assert ressemblance("Tilleuls résidence", "Résidence Tilleuls") == 100


def test_ressemblance_vide_vaut_zero() -> None:
    assert ressemblance("", "Villa Test") == 0
    assert ressemblance(None, "Villa Test") == 0


def test_ressemblance_est_un_entier_arrondi_vers_le_bas() -> None:
    # "villa tes" / "villa test" : 2*9/19 = 94,7 -> 94
    assert ressemblance("Villa tes", "Villa test") == 94


def test_reconnaitre_vide() -> None:
    assert (
        reconnaitre_chantier("  ", [NomConnu(A, "Villa Test")], 90).etat
        is EtatCorrespondance.VIDE
    )
    assert (
        reconnaitre_chantier("(12345)", [NomConnu(A, "Villa Test")], 90).etat
        is EtatCorrespondance.VIDE
    )


def test_reconnaitre_au_seuil_exact() -> None:
    noms = [NomConnu(A, "Villa test")]
    assert (
        reconnaitre_chantier("Villa tes", noms, 94).etat is EtatCorrespondance.RECONNU
    )
    assert (
        reconnaitre_chantier("Villa tes", noms, 95).etat is EtatCorrespondance.INCONNU
    )


def test_reconnaitre_ignore_code_et_prefixe() -> None:
    c = reconnaitre_chantier(
        "Chantier : VILLA TEST (99887766)", [NomConnu(A, "Villa Test")], 90
    )
    assert (
        c.etat is EtatCorrespondance.RECONNU and c.chantier_id == A and c.score == 100
    )


def test_reconnaitre_meilleur_nom_du_chantier() -> None:
    noms = [NomConnu(A, "Villa Test"), NomConnu(A, "vt nord"), NomConnu(B, "Tilleuls")]
    c = reconnaitre_chantier("VT NORD", noms, 90)
    assert c.chantier_id == A


def test_reconnaitre_egalite_entre_deux_chantiers_est_ambigue() -> None:
    noms = [NomConnu(A, "Residence les Pins 1"), NomConnu(B, "Residence les Pins 2")]
    c = reconnaitre_chantier("Residence les Pins", noms, 90)
    assert c.etat is EtatCorrespondance.AMBIGU
    assert c.candidats == tuple(sorted((A, B), key=str))


def test_reconnaitre_meme_chantier_deux_noms_egaux_reste_reconnu() -> None:
    noms = [NomConnu(A, "Villa Test"), NomConnu(A, "VILLA TEST")]
    assert (
        reconnaitre_chantier("villa test", noms, 90).etat is EtatCorrespondance.RECONNU
    )


def test_nom_pour_creation_retire_code_et_prefixe() -> None:
    assert nom_pour_creation("  Chantier : VILLA TEST (99887766) ") == "VILLA TEST"
    assert nom_pour_creation("(99887766)") is None
    assert nom_pour_creation(None) is None
```

Puis **un test par ligne de la table de décision** (spec §2.3), avec des aides `vide()`, `inconnu()`, `reconnu(x)`, `ambigu(*xs)` construisant des `Correspondance` :

```python
def reconnu(x: uuid.UUID) -> Correspondance:
    return Correspondance(
        EtatCorrespondance.RECONNU, libelle="x", chantier_id=x, score=95
    )


def ambigu(*xs: uuid.UUID) -> Correspondance:
    return Correspondance(
        EtatCorrespondance.AMBIGU, libelle="x", score=95, candidats=xs
    )


def inconnu() -> Correspondance:
    return Correspondance(EtatCorrespondance.INCONNU, libelle="x")


def vide() -> Correspondance:
    return Correspondance(EtatCorrespondance.VIDE)


def test_lu_reconnu_legende_vide_rattache_nom_lu() -> None:
    d = decider_chantier(reconnu(A), vide())
    assert d == DecisionChantier(
        TypeDecision.RATTACHER, chantier_id=A, source=SourceNom.NOM_LU, apprendre=True
    )


def test_legende_bavarde_ignoree_si_nom_lu_reconnu() -> None:
    assert decider_chantier(reconnu(A), inconnu()).chantier_id == A


def test_lu_et_legende_meme_chantier() -> None:
    assert decider_chantier(reconnu(A), reconnu(A)).type is TypeDecision.RATTACHER


def test_lu_reconnu_legende_ambigue_contenant_lu() -> None:
    assert decider_chantier(reconnu(A), ambigu(A, B)).chantier_id == A


def test_lu_reconnu_legende_autre_chantier_alerte() -> None:
    d = decider_chantier(reconnu(A), reconnu(B))
    assert d.type is TypeDecision.ALERTE and d.candidats == (A, B)


def test_lu_reconnu_legende_ambigue_sans_lu_alerte() -> None:
    assert decider_chantier(reconnu(A), ambigu(B, C)).candidats == (A, B, C)


def test_lu_ambigu_alerte_avec_legende_reconnue() -> None:
    assert decider_chantier(ambigu(A, B), reconnu(C)).candidats == (A, B, C)


def test_lu_ambigu_legende_parmi_candidats_sans_doublon() -> None:
    assert decider_chantier(ambigu(A, B), reconnu(B)).candidats == (A, B)


def test_lu_inconnu_legende_reconnue_rattache_legende_et_apprend() -> None:
    d = decider_chantier(inconnu(), reconnu(B))
    assert d == DecisionChantier(
        TypeDecision.RATTACHER, chantier_id=B, source=SourceNom.LEGENDE, apprendre=True
    )


def test_lu_inconnu_sans_legende_cree_depuis_nom_lu() -> None:
    assert decider_chantier(inconnu(), vide()) == DecisionChantier(
        TypeDecision.CREER, source=SourceNom.NOM_LU, apprendre=True
    )
    assert decider_chantier(inconnu(), inconnu()).type is TypeDecision.CREER


def test_lu_inconnu_legende_ambigue_alerte() -> None:
    assert decider_chantier(inconnu(), ambigu(A, B)).candidats == (A, B)


def test_lu_vide_legende_reconnue_rattache_sans_apprendre() -> None:
    assert decider_chantier(vide(), reconnu(B)) == DecisionChantier(
        TypeDecision.RATTACHER, chantier_id=B, source=SourceNom.LEGENDE, apprendre=False
    )


def test_lu_vide_legende_inconnue_cree_depuis_legende() -> None:
    assert decider_chantier(vide(), inconnu()) == DecisionChantier(
        TypeDecision.CREER, source=SourceNom.LEGENDE, apprendre=False
    )


def test_lu_vide_legende_ambigue_alerte() -> None:
    assert decider_chantier(vide(), ambigu(A, B)).type is TypeDecision.ALERTE


def test_rien_du_tout_aucun() -> None:
    assert decider_chantier(vide(), vide()).type is TypeDecision.AUCUN
```

Les quatre tests `test_ressemblance_*` ci-dessus vont dans `test_texte.py` (import depuis `app.modules.normalize.texte`), les autres dans `test_chantier.py`.

- [ ] **Step 2: Lancer, vérifier l'échec** — `uv run pytest app/modules/normalize/tests/test_texte.py app/modules/normalize/tests/test_chantier.py -v` → FAIL (ImportError).

- [ ] **Step 3: Implémentation** — `_forme_triee` et `ressemblance` dans `normalize/texte.py` (stdlib `difflib.SequenceMatcher`), le reste dans `normalize/chantier.py` (imports stdlib seulement : `uuid`, `enum.StrEnum`, `collections.abc.Sequence`, plus `from .texte import normaliser_libelle, ressemblance`) :

```python
# --- normalize/texte.py ---
def _forme_triee(texte: str | None) -> str:
    return " ".join(sorted(normaliser_libelle(texte).split()))


def ressemblance(a: str | None, b: str | None) -> int:
    """Ressemblance entière 0-100 entre deux noms, insensible à la casse, aux
    accents, à la ponctuation et à l'ordre des mots (mots triés puis
    `SequenceMatcher`). Calcul exact en entiers (200 * M // T) : jamais un
    arrondi flottant qui ferait basculer un score pile au seuil."""
    fa, fb = _forme_triee(a), _forme_triee(b)
    if not fa or not fb:
        return 0
    appariement = SequenceMatcher(None, fa, fb, autojunk=False)
    communs = sum(bloc.size for bloc in appariement.get_matching_blocks())
    return (200 * communs) // (len(fa) + len(fb))


# --- normalize/chantier.py ---
def reconnaitre_chantier(
    brut: str | None, noms: Sequence[NomConnu], seuil: int
) -> Correspondance:
    decompose = decomposer_chantier(brut)
    if decompose is None:
        return Correspondance(EtatCorrespondance.VIDE)
    meilleurs: dict[uuid.UUID, int] = {}
    for nom in noms:
        score = ressemblance(decompose.libelle, nom.libelle)
        if score > meilleurs.get(nom.chantier_id, -1):
            meilleurs[nom.chantier_id] = score
    if not meilleurs:
        return Correspondance(EtatCorrespondance.INCONNU, libelle=decompose.libelle)
    meilleur = max(meilleurs.values())
    if meilleur < seuil:
        return Correspondance(EtatCorrespondance.INCONNU, libelle=decompose.libelle)
    gagnants = sorted((cid for cid, s in meilleurs.items() if s == meilleur), key=str)
    if len(gagnants) == 1:
        return Correspondance(
            EtatCorrespondance.RECONNU,
            libelle=decompose.libelle,
            chantier_id=gagnants[0],
            score=meilleur,
        )
    return Correspondance(
        EtatCorrespondance.AMBIGU,
        libelle=decompose.libelle,
        score=meilleur,
        candidats=tuple(gagnants),
    )


def correspondance_exacte(brut: str | None, chantier_id: uuid.UUID) -> Correspondance:
    """Nom lu déjà connu tel quel chez ce fournisseur (alias exact rattaché) :
    reconnu à 100 sans comparaison."""
    decompose = decomposer_chantier(brut)
    libelle = decompose.libelle if decompose is not None else None
    return Correspondance(
        EtatCorrespondance.RECONNU, libelle=libelle, chantier_id=chantier_id, score=100
    )


def _sans_doublon(*groupes: Sequence[uuid.UUID]) -> tuple[uuid.UUID, ...]:
    vus: list[uuid.UUID] = []
    for groupe in groupes:
        for cid in groupe:
            if cid not in vus:
                vus.append(cid)
    return tuple(vus)


def decider_chantier(lu: Correspondance, legende: Correspondance) -> DecisionChantier:
    """Table de décision de la spec §2.3 — voir ses tests, une par ligne."""
    R, A, I = (
        EtatCorrespondance.RECONNU,
        EtatCorrespondance.AMBIGU,
        EtatCorrespondance.INCONNU,
    )
    if lu.etat is R:
        assert lu.chantier_id is not None
        if legende.etat is R and legende.chantier_id != lu.chantier_id:
            return DecisionChantier(
                TypeDecision.ALERTE,
                candidats=_sans_doublon(
                    (lu.chantier_id,),
                    (legende.chantier_id,) if legende.chantier_id else (),
                ),
            )
        if legende.etat is A and lu.chantier_id not in legende.candidats:
            return DecisionChantier(
                TypeDecision.ALERTE,
                candidats=_sans_doublon((lu.chantier_id,), legende.candidats),
            )
        return DecisionChantier(
            TypeDecision.RATTACHER,
            chantier_id=lu.chantier_id,
            source=SourceNom.NOM_LU,
            apprendre=True,
        )
    if lu.etat is A:
        extra = (
            (legende.chantier_id,) if legende.etat is R and legende.chantier_id else ()
        )
        return DecisionChantier(
            TypeDecision.ALERTE, candidats=_sans_doublon(lu.candidats, extra)
        )
    if lu.etat is I:
        if legende.etat is R:
            return DecisionChantier(
                TypeDecision.RATTACHER,
                chantier_id=legende.chantier_id,
                source=SourceNom.LEGENDE,
                apprendre=True,
            )
        if legende.etat is A:
            return DecisionChantier(TypeDecision.ALERTE, candidats=legende.candidats)
        return DecisionChantier(
            TypeDecision.CREER, source=SourceNom.NOM_LU, apprendre=True
        )
    if legende.etat is R:
        return DecisionChantier(
            TypeDecision.RATTACHER,
            chantier_id=legende.chantier_id,
            source=SourceNom.LEGENDE,
        )
    if legende.etat is I:
        return DecisionChantier(TypeDecision.CREER, source=SourceNom.LEGENDE)
    if legende.etat is A:
        return DecisionChantier(TypeDecision.ALERTE, candidats=legende.candidats)
    return DecisionChantier(TypeDecision.AUCUN)


def nom_pour_creation(brut: str | None) -> str | None:
    """Nom lisible d'un chantier créé automatiquement : le brut sans le
    préfixe « chantier : » ni le code final entre parenthèses, casse d'origine
    conservée, espaces réduits. `None` s'il ne reste rien."""
    if brut is None:
        return None
    sans_prefixe = _PREFIXE_CHANTIER_RE.sub("", brut)
    code = _CODE_FINAL_RE.search(sans_prefixe)
    reste = sans_prefixe[: code.start()] if code is not None else sans_prefixe
    nom = " ".join(reste.split())
    return nom or None
```

Remplacer les `assert` de typage par des gardes explicites si mypy/ruff le demandent (pas d'`assert` en code de prod si la config ruff l'interdit). Compléter la docstring de module (nouvelles fonctions, décision d'Ilane du 27/09).

- [ ] **Step 4: Tests verts** — `uv run pytest app/modules/normalize -v && uv run pytest tests/test_frontieres.py -v` → PASS.

- [ ] **Step 5: Commit** — `normalize: ressemblance des noms de chantier et table de décision (avenant du 27/09)`.

---

### Task 3: Règle R18 « Chantier à confirmer » et son câblage d'affichage

**Files:**
- Create: `app/modules/rules/rules/R18.py`, `app/modules/rules/tests/test_R18.py`
- Modify: `app/modules/rules/modeles.py` (`ChantierIncertainControle`), `app/modules/rules/engine.py` (`REGLES_CHANTIER`, `evaluer_chantier`), `app/modules/rules/rules/__init__.py` (docstring « R01 … R18 »)
- Modify: `app/modules/rules/tests/test_engine.py:1028-1031` (`range(1, 19)`, union des trois ensembles)
- Modify: `app/modules/api/anomalies.py` (`RegleAnomalie` + `"R18"`), `tests/test_regle_anomalie_couverture.py` (union avec `REGLES_CHANTIER`)
- Modify: `app/modules/ingest/anomalies.py` (`CATEGORIES_REGLE["R18"] = "rattacher"`), `app/modules/ingest/tests/test_categories_regles.py` si elle fige la table
- Modify: `web/src/ui/libelles.ts` (titre et phrase R18), `web/src/pages/ProblemeDetail.tsx` (lien source du document pour R18, comme R15 qui porte `document_id`)

**Interfaces:**
- Produces:

```python
# rules/modeles.py
@dataclass(frozen=True)
class ChantierIncertainControle:
    document_id: uuid.UUID
    nom_lu: str | None
    legende: str | None
    candidats: tuple[str, ...]        # noms des chantiers candidats, dans l'ordre de la décision
    candidats_ids: tuple[uuid.UUID, ...]
    incertain: bool

# rules/rules/R18.py
def R18(controle: ChantierIncertainControle) -> Anomalie | None

# rules/engine.py
REGLES_CHANTIER: frozenset[str] = frozenset({"R18"})
def evaluer_chantier(controle: ChantierIncertainControle) -> tuple[Anomalie, ...]
```

`Anomalie.detail` de R18 : `{"nom_lu": <nom lu ou "—">, "legende": <légende ou "—">, "candidats": "Nom 1 / Nom 2", "candidats_ids": "<uuid1>,<uuid2>"}`, gravité `Gravite.MOYENNE`, `document_id=controle.document_id`.

- [ ] **Step 1: Tests (échouent)** — `app/modules/rules/tests/test_R18.py` :

```python
DOC = uuid.UUID(int=10)
A, B = uuid.UUID(int=1), uuid.UUID(int=2)


def _controle(incertain: bool) -> ChantierIncertainControle:
    return ChantierIncertainControle(
        document_id=DOC,
        nom_lu="VILLA TEST",
        legende="tilleuls",
        candidats=("Villa Test", "Résidence des Tilleuls"),
        candidats_ids=(A, B),
        incertain=incertain,
    )


def test_R18_positif_detail_complet() -> None:
    anomalie = R18(_controle(True))
    assert anomalie is not None
    assert anomalie.regle == "R18" and anomalie.gravite is Gravite.MOYENNE
    assert anomalie.document_id == DOC
    assert anomalie.detail == {
        "nom_lu": "VILLA TEST",
        "legende": "tilleuls",
        "candidats": "Villa Test / Résidence des Tilleuls",
        "candidats_ids": f"{A},{B}",
    }


def test_R18_negatif_chantier_certain() -> None:
    assert R18(_controle(False)) is None


def test_R18_valeurs_absentes_en_tiret() -> None:
    c = ChantierIncertainControle(
        document_id=DOC,
        nom_lu=None,
        legende=None,
        candidats=("A", "B"),
        candidats_ids=(A, B),
        incertain=True,
    )
    anomalie = R18(c)
    assert (
        anomalie is not None
        and anomalie.detail["nom_lu"] == "—"
        and anomalie.detail["legende"] == "—"
    )
```

et dans `test_engine.py`, l'invariant devient `{f"R{i:02d}" for i in range(1, 19)} == REGLES_FACTURE | REGLES_SUIVI | REGLES_CHANTIER`, plus `test_evaluer_chantier_renvoie_R18` (tuple d'une anomalie si incertain, vide sinon). `tests/test_regle_anomalie_couverture.py` compare avec l'union des trois ensembles.

- [ ] **Step 2: Lancer, vérifier l'échec** — `uv run pytest app/modules/rules tests/test_regle_anomalie_couverture.py -v` → FAIL.

- [ ] **Step 3: Implémentation** — `R18.py` sur le modèle de `R14.py` (docstring : avenant du 27/09, justification = nom lu, légende, candidats ; `TIRET = "—"`). `evaluer_chantier` renvoie `tuple(a for a in (R18(controle),) if a is not None)`. Ajouter `"R18"` à `RegleAnomalie`, `CATEGORIES_REGLE["R18"] = "rattacher"` (mettre à jour le commentaire de la table).

- [ ] **Step 4: Front** — `web/src/ui/libelles.ts` : `R18: "Chantier à confirmer"` dans `TITRES_REGLE` et dans la fonction de phrase :

```ts
    case "R18":
      return (
        `Le nom lu sur le bon (« ${texteOuTiret(detail, "nom_lu")} ») et le nom indiqué par l'employé ` +
        `(« ${texteOuTiret(detail, "legende")} ») ne désignent pas un seul chantier. ` +
        `Chantiers possibles : ${texteOuTiret(detail, "candidats")}.`
      );
```
`ProblemeDetail.tsx` : traiter R18 comme les règles qui portent `document_id` (lien vers la page du bon). Chercher les `switch`/listes de règles du front (`grep -n "R15" web/src`) et y ajouter R18 là où R15 figure pour la même raison (document source). Si `tests/test_web_a_regler.py` ou `tests/test_web_*.py` vérifient la couverture des titres de règles, les faire passer.

- [ ] **Step 5: Tests verts** — `uv run pytest app/modules/rules app/modules/ingest/tests/test_categories_regles.py tests/test_regle_anomalie_couverture.py tests/test_web_a_regler.py -v`, `npm --prefix web run typecheck`, `npm --prefix web run api:schema && npm --prefix web run api:types` (le `Literal` a changé).

- [ ] **Step 6: Commit** — `rules: R18 chantier à confirmer (nom lu et légende en désaccord)`.

---

### Task 4: Légende Telegram lue, conservée et affichée

**Files:**
- Modify: `app/modules/messaging/base.py` (`FichierEntrant.legende: str | None = None`, dernier champ)
- Modify: `app/modules/messaging/telegram.py` (`lire_update` lit `message.get("caption")` une fois et la passe à `_fichier_depuis_photo`/`_fichier_depuis_document`)
- Modify: `app/modules/ingest/depot_telegram.py` (insertion `Document(..., legende=entrant.legende)`)
- Modify: `app/modules/ingest/corrections.py` (`DocumentDetail.legende`, alimenté dans `_charger_detail`)
- Modify: `app/modules/api/schemas.py` (`DocumentDetailReponse.legende: str | None`)
- Modify: `web/src/pages/PageBl.tsx` (à côté du chantier, ligne ~561), `web/src/pages/DocumentDetail.tsx` (ligne ~1075, en lecture seule)
- Test: `app/modules/messaging/tests/test_lire_update.py`, `app/modules/ingest/tests/test_service.py`, `app/modules/ingest/tests/test_corrections.py`

**Interfaces:**
- Produces: `FichierEntrant.legende: str | None` (légende nettoyée : `strip()`, vide → `None`, tronquée à 200 caractères) ; `Document.legende` renseigné au dépôt ; `DocumentDetail.legende` / `DocumentDetailReponse.legende`.

- [ ] **Step 1: Tests (échouent)**

```python
# test_lire_update.py
def test_photo_avec_legende() -> None:
    update = {
        "update_id": 1,
        "message": {
            "message_id": 5,
            "chat": {"id": -100},
            "from": {"id": 42, "first_name": "Léa"},
            "photo": [
                {"file_id": "p1", "file_size": 10},
                {"file_id": "p2", "file_size": 20},
            ],
            "caption": "  Villa Test  ",
        },
    }
    entrant = lire_update(update)
    assert isinstance(entrant, FichierEntrant) and entrant.legende == "Villa Test"


def test_document_avec_legende_longue_tronquee() -> (
    None
): ...  # "document" image/jpeg, caption de 300 caractères -> len(entrant.legende) == 200


def test_legende_vide_devient_none() -> None: ...  # caption "   " -> legende is None
```
(copier la forme exacte des updates des tests existants du fichier, y compris les champs requis). Dans `test_service.py` : `test_depot_conserve_la_legende` — `_entrant(..., legende="Villa Test")` puis le `Document` inséré a `legende == "Villa Test"`. Dans `test_corrections.py` : le détail renvoie `legende`.

- [ ] **Step 2: Lancer, vérifier l'échec.**

- [ ] **Step 3: Implémentation** — `LONGUEUR_LEGENDE_MAX = 200` dans `telegram.py` ; `_legende(message: dict[str, Any]) -> str | None` (non-`str` → `None`). Mettre à jour les assertions d'égalité existantes de `test_lire_update.py` seulement si elles cassent (le défaut `None` doit les garder vertes). Insérer `legende=entrant.legende` dans `Document(...)` de `traiter_fichier`. `DocumentDetail.legende` lu depuis `document.legende`.

- [ ] **Step 4: Front** — `PageBl.tsx` : sous le chantier, si `donnees.legende` : `<span>Indiqué par l'employé : « {donnees.legende} »</span>` (même style que les voisins). `DocumentDetail.tsx` : `· Nom indiqué par l'employé : {donnees.legende ?? "—"}` en lecture seule près de « Chantier rattaché ». Régénérer les types.

- [ ] **Step 5: Tests verts** — `uv run pytest app/modules/messaging app/modules/ingest/tests/test_service.py app/modules/ingest/tests/test_corrections.py -v`, typecheck, build.

- [ ] **Step 6: Commit** — `messaging/ingest/web: légende de la photo Telegram conservée et affichée`.

---

### Task 5: Rattachement automatique du chantier (bons et factures)

**Files:**
- Create: `app/modules/ingest/rattachement_chantier.py`
- Modify: `app/modules/ingest/extraction_bl.py:419-429` (remplace l'appel à `resoudre_chantier`), `app/modules/ingest/corrections.py:713-725` (`_resoudre_chantier_document`), `app/modules/ingest/factures.py:417-425` (blocs)
- Test: `app/modules/ingest/tests/test_rattachement_chantier.py` (nouveau), compléments dans `test_extraction_bl.py`, `test_corrections.py`, `test_deposer_facture.py`

**Interfaces:**
- Consumes: Task 1 (colonnes, `CLE_SEUIL_RESSEMBLANCE_CHANTIER`), Task 2 (pur), Task 3 (`ChantierIncertainControle`, `evaluer_chantier`, `REGLES_CHANTIER`), `referentiels.lire_parametre_decimal`, `referentiels.candidats_alias`, `anomalies.synchroniser_anomalies`.
- Produces:

```python
@dataclass(frozen=True)
class ResultatRattachement:
    chantier_id: uuid.UUID | None
    methode: str | None      # "nom connu" | "ressemblance" | "légende" | "création" | "alerte" | None
    score: int | None
    cree: bool               # un chantier vient d'être créé
    alerte: bool             # R18 ouverte sur le bon

async def charger_noms_chantiers(session: AsyncSession) -> list[NomConnu]
async def chantier_effectif(session: AsyncSession, chantier_id: uuid.UUID) -> uuid.UUID
async def rattacher_chantier_document(session: AsyncSession, document: Document) -> ResultatRattachement
async def rattacher_chantier_bloc(session: AsyncSession, fournisseur_id: uuid.UUID, chantier_brut: str | None) -> uuid.UUID | None
```
Aucune de ces fonctions ne commite (l'appelant décide).

Comportement de `rattacher_chantier_document(session, document)` (bon `bl`/`enlevement`) :
1. `await session.execute(select(func.pg_advisory_xact_lock(VERROU_CHANTIERS)))` avec `VERROU_CHANTIERS = 727_000_018` (constante du module) : sérialise toute décision de chantier jusqu'au commit de l'appelant.
2. Seuil = `int(await lire_parametre_decimal(session, CLE_SEUIL_RESSEMBLANCE_CHANTIER, Decimal("90")))` (vérifier la signature réelle).
3. `noms = await charger_noms_chantiers(session)` : pour chaque chantier, `NomConnu(effectif, nom_canonique)` ; pour chaque alias rattaché, `NomConnu(effectif(alias.chantier_id), alias.libelle_brut)` ; `effectif` suit `fusionne_dans_id` (au plus deux sauts, voir Task 7). Deux requêtes, jamais une par chantier.
4. Nom lu : si `document.fournisseur_id` est connu et qu'un alias exact `(fournisseur_id, decomposer_chantier(chantier_brut).libelle, code_brut=NULL)` est rattaché → `correspondance_exacte(...)` ; sinon `reconnaitre_chantier(document.chantier_brut, noms, seuil)`.
5. Légende : `reconnaitre_chantier(document.legende, noms, seuil)`.
6. `decision = decider_chantier(lu, legende)` puis :
   - `RATTACHER` → `document.chantier_id = decision.chantier_id` ;
   - `CREER` → `nom = nom_pour_creation(chantier_brut si source NOM_LU sinon legende)` ; si un chantier non fusionné a déjà `normaliser_libelle(nom_canonique) == normaliser_libelle(nom)`, le prendre ; sinon `Chantier(nom_canonique=nom, agence=None, client=None, actif=True, a_completer=True)`, `flush`, journal `chantier_cree_auto` (`utilisateur_id=None`, `cible_table="chantier"`, `apres={"nom_canonique": nom, "source": "nom lu" | "légende", "document_id": str(document.id)}`) ;
   - `ALERTE` → `document.chantier_id = None` ;
   - `AUCUN` → `document.chantier_id = None`.
7. Apprentissage si `decision.apprendre` et `document.fournisseur_id` et libellé lu non vide : upsert de l'alias `(fournisseur_id, libelle, NULL)` → chantier retenu (`insert ... on_conflict_do_nothing` puis relecture, comme `resoudre_chantier`) ; si l'alias existait avec `chantier_id NULL` → le rattacher (`valide_par=None`, `valide_le=now`) et propager `chantier_id` aux candidats (`candidats_alias(session, fournisseur_id, libelle)` : documents et blocs), journal `alias_rattache_auto` (`apres={"libelle", "chantier_id", "methode", "nb_mis_a_jour"}`). Un alias déjà rattaché à un autre chantier n'est jamais modifié.
8. R18 : construire `ChantierIncertainControle(document_id, nom_lu=document.chantier_brut, legende=document.legende, candidats=<noms canoniques des candidats, même ordre>, candidats_ids=decision.candidats, incertain=decision.type is ALERTE)` puis `synchroniser_anomalies(session, anomalies=evaluer_chantier(controle), portee_document_id=document.id, portee_regles=sorted(REGLES_CHANTIER))` — lève automatiquement une R18 devenue sans objet.
9. Renvoyer `ResultatRattachement` (méthode : exacte → « nom connu », RATTACHER nom lu → « ressemblance », RATTACHER légende → « légende », CREER → « création », ALERTE → « alerte »).

`rattacher_chantier_bloc(session, fournisseur_id, chantier_brut)` (bloc de facture, sans légende) : même verrou, même alias exact, même `reconnaitre_chantier` ; RECONNU → apprendre + renvoyer l'id ; INCONNU → créer (source nom lu) + apprendre ; AMBIGU → **ancien flux** : `resoudre_chantier(session, fournisseur_id, chantier_brut)` (alias en attente) et renvoyer `None` ; VIDE → `None`.

Intégrations :
- `extraction_bl.py` : remplacer le bloc `if fournisseur_id is not None: resolution_chantier = await resoudre_chantier(...)` par l'affectation de `document.chantier_brut`/`fournisseur_id` **puis** `resultat = await rattacher_chantier_document(session, document)` (déplacer l'appel après `document.chantier_brut = ...`, avant le journal). Le journal `extraction_bl` porte `chantier_id`, `methode_chantier=resultat.methode`, `score_chantier=resultat.score`.
- `corrections._resoudre_chantier_document` : `await rattacher_chantier_document(session, document)` (plus de retour à `None` quand le fournisseur manque : la logique gère ce cas).
- `factures.py` : `chantier_id = await rattacher_chantier_bloc(session, fournisseur_id, bloc.chantier_brut)`.

- [ ] **Step 1: Tests (échouent)** — `test_rattachement_chantier.py` (`pytestmark = [pytest.mark.anyio, pytest.mark.db]`, fixtures `db_session` du `conftest.py` d'ingest ; aides locales `_chantier(db_session, nom)`, `_fournisseur(db_session)`, `_bon(db_session, *, fournisseur_id, chantier_brut, legende)` qui insèrent des lignes inventées) :

```python
async def test_nom_lu_ressemblant_rattache_et_apprend(db_session: AsyncSession) -> None:
    f = await _fournisseur(db_session)
    villa = await _chantier(db_session, "Villa Test")
    bon = await _bon(
        db_session, fournisseur_id=f.id, chantier_brut="VILLA TEST (123)", legende=None
    )
    r = await rattacher_chantier_document(db_session, bon)
    await db_session.commit()
    assert r.chantier_id == villa.id and r.methode == "ressemblance"
    alias = (
        await db_session.execute(
            select(ChantierAlias).where(ChantierAlias.libelle_brut == "villa test")
        )
    ).scalar_one()
    assert alias.chantier_id == villa.id


async def test_nom_inconnu_cree_un_chantier_a_completer(
    db_session: AsyncSession,
) -> None: ...  # aucun chantier ; brut "RESIDENCE DES TILLEULS (9)" -> chantier "RESIDENCE DES TILLEULS", a_completer True, journal chantier_cree_auto, r.cree


async def test_nom_lu_inconnu_legende_reconnue(
    db_session: AsyncSession,
) -> None: ...  # chantier "Villa Test" ; brut "VT-NORD" ; legende "villa test" -> rattaché Villa Test, méthode "légende", alias "vt nord" appris


async def test_desaccord_leve_R18_et_laisse_sans_chantier(
    db_session: AsyncSession,
) -> None:
    ...  # chantiers A "Villa Test", B "Résidence des Tilleuls" ; brut "VILLA TEST" ; legende "tilleuls residence"
    # -> document.chantier_id None, une Anomalie R18 ouverte (document_id), detail["candidats"] == "Villa Test / Résidence des Tilleuls"


async def test_correction_du_nom_leve_R18(
    db_session: AsyncSession,
) -> None: ...  # après le cas précédent, document.legende = None puis rattacher à nouveau -> R18 levée (plus d'anomalie ouverte), chantier A


async def test_creation_concurrente_un_seul_chantier(
    db_engine: AsyncEngine,
) -> None: ...  # deux sessions distinctes, deux bons "NOUVEAU CHANTIER" ; asyncio.gather des deux (rattacher + commit) -> un seul Chantier en base


async def test_seuil_lu_dans_les_reglages(
    db_session: AsyncSession,
) -> (
    None
): ...  # seuil réglé à 100 : "Villa tes" ne reconnaît plus "Villa test" -> création


async def test_bloc_facture_ambigu_garde_l_alias_en_attente(
    db_session: AsyncSession,
) -> None: ...  # chantiers "Residence les Pins 1" et "Residence les Pins 2" ; rattacher_chantier_bloc(f, "RESIDENCE LES PINS") -> None et un ChantierAlias chantier_id NULL


async def test_alias_en_attente_rattache_et_propage(
    db_session: AsyncSession,
) -> None: ...  # alias en attente "villa test" + un bloc de facture sans chantier portant "VILLA TEST" ; un bon "VILLA TEST" reconnu -> alias rattaché, bloc.chantier_id posé
```
Dans `test_extraction_bl.py` : un test de bout en bout `test_extraction_rattache_le_chantier_par_ressemblance` (réponse OCR factice avec chantier « VILLA TEST », chantier « Villa Test » existant). Dans `test_corrections.py` : corriger `chantier_brut` relance le rattachement.

- [ ] **Step 2: Lancer, vérifier l'échec.**
- [ ] **Step 3: Implémenter `rattachement_chantier.py`** (docstring de module : décision d'Ilane du 27/09, table §2.3, verrou, apprentissage, jamais de commit) et les trois intégrations.
- [ ] **Step 4: Adapter les tests existants** qui supposaient qu'un nom inconnu crée un alias en attente sur un **bon** (désormais : chantier créé) — grep `demande_creee`, `alias` dans `test_extraction_bl.py`, `test_a_traiter.py`, `test_suivi.py` (R14), `test_service.py`. Ne modifier une assertion que si elle décrit l'ancien comportement remplacé par la spec ; noter chaque adaptation dans le message de commit.
- [ ] **Step 5: Tests verts** — `uv run pytest app/modules/ingest -v` puis la suite complète.
- [ ] **Step 6: Commit** — `ingest: rattachement automatique des chantiers (ressemblance, création à compléter, R18)`.

---

### Task 6: « À régler », chantiers à compléter et choix du chantier d'un bon

**Files:**
- Modify: `app/modules/ingest/a_traiter.py` (section `chantiers_a_completer`, compte), `app/modules/ingest/referentiels.py` (`ChantierResume.a_completer`, `lister_chantiers` exclut les fusionnés, `modifier_chantier` remet `a_completer=False`)
- Modify: `app/modules/ingest/rattachement_chantier.py` (`choisir_chantier_document`)
- Modify: `app/modules/api/a_traiter.py`, `app/modules/api/referentiels.py`, `app/modules/api/documents.py` (`PUT /api/documents/{id}/chantier`), `app/modules/api/schemas.py`
- Modify: `web/src/pages/ARegler.tsx` (section « Nouveaux chantiers à compléter » ; panneau R18 avec boutons), `web/src/pages/ChantiersListe.tsx` et `FicheChantier.tsx` (étiquette « À compléter »), `web/src/pages/DocumentDetail.tsx` (sélecteur « Chantier du bon » pour l'admin), `web/src/api/*.ts`
- Test: `app/modules/ingest/tests/test_a_traiter.py`, `test_referentiels.py`, `test_rattachement_chantier.py`, `app/modules/api/tests/test_documents.py`, `test_a_traiter.py`, `tests/test_web_a_regler.py`, `tests/test_web_chantiers.py`

**Interfaces:**
- Consumes: Task 5.
- Produces:

```python
@dataclass(frozen=True)
class ChantierACompleter:
    id: uuid.UUID
    nom: str
    nb_bons: int
    cree_le: datetime
# ATraiter.chantiers_a_completer: list[ChantierACompleter]  (compté dans compter_problemes_a_regler)

async def choisir_chantier_document(session, document_id: uuid.UUID, *, chantier_id: uuid.UUID, auteur_id: uuid.UUID) -> uuid.UUID
# pose document.chantier_id = chantier_effectif(chantier_id) ; ferme la R18 ouverte du bon (statut "traitee",
# commentaire "Chantier choisi : <nom>", traitee_par, traitee_le, journal "anomalie_traitee" comme traiter_anomalie) ;
# journal "chantier_choisi" (avant/apres chantier_id) ; commit ; renvoie le chantier retenu.
# Lève DocumentIntrouvable (bl/enlevement non archivé seulement), ChantierIntrouvable.
```
- `PUT /api/documents/{id}/chantier` corps `{"chantier_id": uuid}` → `{"chantier_id": uuid}` (admin ; 404 document ou chantier inconnu ; 403 agent).
- `ChantierReponse.a_completer: bool`.
- `ATraiterReponse.chantiers_a_completer: list[ChantierACompleterReponse]`.

- [ ] **Step 1: Tests (échouent)** — service : `test_chantier_cree_auto_apparait_a_completer`, `test_modifier_chantier_sort_de_a_completer`, `test_compte_a_regler_inclut_chantiers_a_completer`, `test_choisir_chantier_ferme_R18_et_journalise`, `test_choisir_chantier_document_archive_refuse`, `test_lister_chantiers_exclut_les_fusionnes` ; API : `test_put_chantier_document_admin`, `test_put_chantier_document_agent_403` (copier `_app_test`/`_login` de `app/modules/api/tests/test_parametres.py`).
- [ ] **Step 2: Lancer, vérifier l'échec.**
- [ ] **Step 3: Serveur** — implémenter ; `lister_chantiers` filtre `Chantier.fusionne_dans_id.is_(None)`.
- [ ] **Step 4: Front** — `ARegler.tsx` :
  - section « Nouveaux chantiers à compléter » (carte par chantier : nom, « créé automatiquement le … », nombre de bons, bouton-lien « Compléter » vers `/chantiers/<id>`) ;
  - pour un problème R18, dans le panneau de détail : un bouton « C'est <nom> » par candidat (`detail.candidats_ids` découpé sur `,`, `detail.candidats` sur ` / `, même ordre), plus « Autre chantier… » (liste `listerChantiers`) ; chaque choix appelle `PUT /api/documents/{document_id}/chantier` puis `invaliderApresChangementAnomalies` + invalidations chantiers/documents.
  - `ChantiersListe.tsx`/`FicheChantier.tsx` : pastille « À compléter » (couleur écart, doublée du libellé) si `a_completer`.
  - `DocumentDetail.tsx` (admin) : « Chantier du bon » avec `<select>` des chantiers + « Enregistrer » (même route).
  Mettre à jour les contrats `tests/test_web_*.py` touchés.
- [ ] **Step 5: Tests verts** — ciblés + typecheck + build + `api:schema`/`api:types`.
- [ ] **Step 6: Commit** — `ingest/api/web: chantiers à compléter et choix du chantier d'un bon`.

---

### Task 7: Fusion de deux chantiers

**Files:**
- Create: `app/modules/ingest/fusion_chantier.py`, `app/modules/ingest/tests/test_fusion_chantier.py`
- Modify: `app/modules/api/referentiels.py` (`POST /api/chantiers/{id}/fusionner`), `app/modules/api/schemas.py`, `app/modules/ingest/referentiels.py` (`ChantierResume.fusionne_dans_id`, `fusionne_dans_nom` pour la fiche)
- Modify: `web/src/pages/FicheChantier.tsx` (bouton « Fusionner avec… », message « fusionné dans »), `web/src/api/referentiels.ts`
- Test: `app/modules/api/tests/test_referentiels.py`, `tests/test_web_chantiers.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class ResultatFusion:
    cible_id: uuid.UUID
    nb_documents: int
    nb_blocs: int
    nb_alias: int
    nb_anomalies: int

class FusionImpossible(Exception):  # message lisible : "même chantier", "déjà fusionné", "cible fusionnée"
    ...

async def fusionner_chantiers(session, *, source_id: uuid.UUID, cible_id: uuid.UUID, auteur_id: uuid.UUID) -> ResultatFusion
```
- `POST /api/chantiers/{id}/fusionner` `{"cible_id": uuid}` → `ResultatFusionReponse` ; 404 inconnu, 409 `FusionImpossible`, 403 agent.
- `GET /api/chantiers` n'inclut pas les fusionnés ; ajouter `GET /api/chantiers/{id}` → `ChantierReponse` (y compris fusionné, avec `fusionne_dans_id`/`fusionne_dans_nom`) pour la fiche.

Comportement : verrou `VERROU_CHANTIERS` (importé de `rattachement_chantier`) ; `UPDATE document/bloc_facture/chantier_alias SET chantier_id = cible WHERE chantier_id = source` ; anomalies `ouverte` avec `chantier_id = source` : si une anomalie de même `(regle, document_id, bloc_id, ligne_id, alias_id)` existe déjà avec `chantier_id = cible`, supprimer celle de la source (journal `anomalie_levee` comme `synchroniser_anomalies`), sinon la déplacer ; les anomalies fermées restent ; `UPDATE chantier SET fusionne_dans_id = cible WHERE fusionne_dans_id = source` (pas de chaîne) ; source `actif=False`, `a_completer=False`, `fusionne_dans_id=cible` ; journal `chantier_fusionne` (`avant={"chantier_id": source, "nom": ...}`, `apres={"cible_id", "cible_nom", "nb_documents", "nb_blocs", "nb_alias", "nb_anomalies"}`) ; commit.

- [ ] **Step 1: Tests (échouent)** — `test_fusion_deplace_bons_blocs_noms`, `test_fusion_conflit_R16_leve_l_anomalie_de_la_source`, `test_fusion_refuse_meme_chantier`, `test_fusion_refuse_source_deja_fusionnee`, `test_fusion_refuse_cible_fusionnee`, `test_fusion_redirige_les_anciens_fusionnes`, `test_nom_d_un_chantier_fusionne_mene_a_la_cible` (après fusion de « Villa Test » dans « Résidence des Tilleuls », un bon « VILLA TEST » passé à `rattacher_chantier_document` est rattaché à la cible, aucun chantier créé), API 200/409/403.
- [ ] **Step 2: Lancer, vérifier l'échec.**
- [ ] **Step 3: Implémenter** ; vérifier que `charger_noms_chantiers`/`chantier_effectif` (Task 5) redirigent bien via `fusionne_dans_id`.
- [ ] **Step 4: Front** — `FicheChantier.tsx` : bouton secondaire « Fusionner avec… » (admin) ouvrant une carte : `<select>` des autres chantiers, phrase « Tous les bons, factures et problèmes de <source> passeront sur <cible>. <source> disparaîtra de la liste. », bouton « Fusionner » ; au succès, navigation vers la fiche cible + invalidations (chantiers, bilan, tableau de bord, à régler). Si le chantier est fusionné : bandeau « Ce chantier a été fusionné dans <lien cible> » et rien d'autre à éditer.
- [ ] **Step 5: Tests verts** + typecheck + build + types.
- [ ] **Step 6: Commit** — `ingest/api/web: fusion de deux chantiers`.

---

### Task 8: Reprise des noms en attente

**Files:**
- Modify: `app/modules/ingest/rattachement_chantier.py` (`reprendre_chantiers`)
- Modify: `app/cli.py` (sous-commande `rattacher-chantiers`)
- Test: `app/modules/ingest/tests/test_rattachement_chantier.py`, `tests/test_cli.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class BilanReprise:
    alias_rattaches: int
    chantiers_crees: int
    alias_ambigus: int
    bons_rattaches: int
    bons_en_alerte: int

async def reprendre_chantiers(session: AsyncSession) -> BilanReprise   # commite une fois à la fin
```
Comportement : pour chaque `ChantierAlias` `chantier_id IS NULL` (ordre `created_at`) : `rattacher_chantier_bloc(session, alias.fournisseur_id, alias.libelle_brut)` (qui rattache/crée et propage aux candidats, ou laisse en attente si ambigu) ; puis chaque document `bl`/`enlevement` non archivé avec `chantier_brut` ou `legende` non vide et `chantier_id IS NULL` : `rattacher_chantier_document`. Idempotent : un second appel renvoie des zéros (sauf ambigus). CLI : `python -m app.cli rattacher-chantiers` affiche `Noms rattachés : X · chantiers créés : Y · noms ambigus : Z · bons rattachés : U · bons en alerte : V`, code 0.

- [ ] **Step 1: Tests (échouent)** — `test_reprise_rattache_les_alias_en_attente`, `test_reprise_idempotente`, `test_cli_rattacher_chantiers` (sur le modèle des tests `rapprocher --tout` de `tests/test_cli.py`).
- [ ] **Step 2–4: Implémenter, tests verts.**
- [ ] **Step 5: Commit** — `ingest/cli: reprise des noms de chantier en attente (rattacher-chantiers)`.

---

### Task 9: Photos rangées sur le serveur

**Files:**
- Create: `app/core/segments.py` (`normaliser_segment` déplacé depuis `jobs/drive.py`, mêmes regex et `_LONGUEUR_MAX`), `app/modules/ingest/rangement.py`, `app/modules/ingest/tests/test_rangement.py`
- Modify: `app/modules/jobs/drive.py` (importe `normaliser_segment` depuis `app.core.segments`, réexport pour ne rien casser), `app/modules/ingest/depot_telegram.py` (après l'OCR), `rattachement_chantier.py` (`choisir_chantier_document`, `reprendre_chantiers`), `fusion_chantier.py`, `corrections.py` (`corriger_entete`, relance d'extraction), `app/cli.py` (`ranger-photos`)
- Test: `tests/test_cli.py`, `app/modules/ingest/tests/test_service.py`

**Interfaces:**
- Produces:

```python
def chemin_range(docs_dir: Path, *, depose_le: datetime, deposant: str | None, chantier: str | None,
                 numero_interne: int, extension: str) -> Path
# docs_dir / "bl" / AAAA / MM / f"{JJ}_{seg(deposant) or 'inconnu'}_{seg(chantier) or 'sans-chantier'}_n{numero_interne}.{seg(ext)}"
# date en heure de Paris (app.core.fuseau) ; segments en minuscules via normaliser_segment(...).lower()

async def ranger_document(session: AsyncSession, docs_dir: Path, document_id: uuid.UUID) -> Path | None
# lit document (bl/enlevement non archivé), déposant (nom ou e-mail), chantier (nom canonique) ; supprime tout lien
# existant `bl/*/*/*_n{numero_interne}.*` différent du chemin attendu ; crée les dossiers en 0750 ; os.link(fichier_path, cible)
# si absent ; renvoie le chemin, None si non concerné. Toute OSError est journalisée (logger) et renvoie None : jamais levée.

async def ranger_tout(session: AsyncSession, docs_dir: Path) -> int   # nombre de bons rangés
```
Les appels après un changement de chantier se font **après le commit** de l'opération (le rangement lit l'état commité), avec `docs_dir` venant de `get_settings().docs_dir` côté API (routes qui appellent `choisir_chantier_document`, fusion, correction) et du paramètre existant côté dépôt Telegram. `ranger_document` n'écrit rien en base.

- [ ] **Step 1: Tests (échouent)** — `test_chemin_range_forme` (dépôt 2026-10-01 23:30 UTC → dossier `2026/10`, jour `02` en heure de Paris), `test_nom_range_assaini` (chantier « Résidence / Les Pins » et déposant « Léa Dupont » → segments ASCII sans `/`, fichier sous `docs_dir/bl`), `test_ranger_document_cree_un_lien` (même inode que l'original : `os.stat(...).st_ino`), `test_ranger_document_renomme_quand_le_chantier_change`, `test_bon_sans_chantier_sans_chantier_dans_le_nom`, `test_echec_de_rangement_ne_leve_pas` (docs_dir en lecture seule → None), `test_depot_telegram_range_la_photo` (dans `test_service.py`), `test_cli_ranger_photos`.
- [ ] **Step 2–4: Implémenter, tests verts** (y compris ceux de `jobs` qui utilisent `normaliser_segment`).
- [ ] **Step 5: Commit** — `ingest/cli: photos des bons rangées par année, mois, déposant et chantier`.

---

### Task 10: Comptes — serveur

**Files:**
- Modify: `app/core/auth.py` (à la suite de `creer_utilisateur`/`desactiver_utilisateur`)
- Create: `app/modules/api/comptes.py`, `app/modules/api/tests/test_comptes.py`
- Modify: `app/modules/api/__init__.py` (inclure le routeur), `app/modules/api/schemas.py`
- Test: `app/core/tests/` (tests des fonctions de `auth.py`, sur le modèle des tests existants de `creer_utilisateur`)

**Interfaces:**
- Produces (dans `app/core/auth.py`) :

```python
@dataclass(frozen=True)
class CompteLu:
    id: uuid.UUID; nom: str | None; email: str; role: str; agence: str | None
    telegram_user_id: int | None; actif: bool; cree_le: datetime

class DernierAdmin(Exception): ...          # retirer l'accès / le rôle admin du dernier admin actif
class ActionSurSoiInterdite(Exception): ... # retirer son propre accès

async def lister_comptes(session) -> list[CompteLu]                       # actifs d'abord, puis nom/e-mail
async def creer_compte(session, *, email, nom, role, agence, telegram_user_id, mot_de_passe, auteur_id) -> CompteLu
async def modifier_compte(session, compte_id, *, email, nom, role, agence, telegram_user_id, auteur_id) -> CompteLu
async def changer_mot_de_passe(session, compte_id, *, mot_de_passe, auteur_id) -> None
async def retirer_acces(session, compte_id, *, auteur_id) -> CompteLu
async def retablir_acces(session, compte_id, *, auteur_id) -> CompteLu
```
`creer_compte` réutilise la validation de `creer_utilisateur` (rôle, longueur ≥ 12, e-mail normalisé et unique insensible à la casse, identifiant Telegram unique) — factoriser plutôt que dupliquer, et journaliser avec `utilisateur_id=auteur_id` (action `compte_cree`). `modifier_compte` : mêmes unicités (hors le compte lui-même), `DernierAdmin` si le compte est le dernier admin actif et passe `agent` ; journal `compte_modifie` (avant/après sans mot de passe). `changer_mot_de_passe` : longueur ≥ 12, hash `_password_helper`, `DELETE FROM jeton_session WHERE utilisateur_id = compte_id`, journal `mot_de_passe_change` (`avant=None`, `apres=None`). `retirer_acces` : `ActionSurSoiInterdite` si `compte_id == auteur_id`, `DernierAdmin` si dernier admin actif, `is_active=False`, suppression des jetons, journal `acces_retire`. `retablir_acces` : `is_active=True`, journal `acces_retabli`. Toutes commitent. `UtilisateurIntrouvable` si l'id n'existe pas.

Routes (`api/comptes.py`, toutes `admin_requis`) : `GET /api/comptes`, `POST /api/comptes` (201), `PUT /api/comptes/{id}`, `PUT /api/comptes/{id}/mot-de-passe` (204), `POST /api/comptes/{id}/retirer-acces`, `POST /api/comptes/{id}/retablir-acces`. Erreurs : 404 introuvable, 409 e-mail/Telegram déjà utilisé, 422 mot de passe trop court ou rôle invalide, 409 `DernierAdmin`/`ActionSurSoiInterdite` avec un `detail` lisible en français.

- [ ] **Step 1: Tests (échouent)** — `test_creer_compte_journalise_sans_mot_de_passe`, `test_email_deja_utilise_insensible_casse`, `test_telegram_deja_attribue`, `test_modifier_compte`, `test_dernier_admin_protege` (retirer l'accès et passer agent), `test_retirer_son_propre_acces_refuse`, `test_changer_mot_de_passe_coupe_les_sessions` (un `JetonSession` existant est supprimé ; l'ancien cookie reçoit 401), `test_retirer_acces_coupe_les_sessions`, `test_retablir_acces`, `test_routes_comptes_agent_403`, `test_liste_comptes_sans_empreinte` (la réponse ne contient jamais `hashed_password`/`mdp_hash`).
- [ ] **Step 2–4: Implémenter, tests verts**, `api:schema`/`api:types`.
- [ ] **Step 5: Commit** — `core/api: gestion des comptes par un admin (créer, modifier, mot de passe, accès)`.

---

### Task 11: Comptes — écran

**Files:**
- Create: `web/src/pages/Comptes.tsx`, `web/src/api/comptes.ts`
- Modify: `web/src/App.tsx` (route `comptes` sous `GardeAdmin`), `web/src/components/Gabarit.tsx` (lien discret « Comptes » à côté de Réglages/Journal, barre latérale et en-tête téléphone), `web/src/pages/Reglages.tsx` (lien « Gérer les comptes »)
- Test: `tests/test_web_comptes.py` (contrat par lecture du source, sur le modèle de `tests/test_web_reglages.py`)

**Interfaces:**
- Consumes: routes de Task 10 (types générés `CompteReponse`…).
- Produces: page `/comptes`.

Contenu : `EnTetePage` « Comptes » ; liste (cartes sur téléphone, tableau sur ordinateur) : nom, e-mail, rôle (« Administrateur »/« Employé »), agence, Telegram (« relié »/« non relié »), état (« Accès actif »/« Accès retiré ») ; bouton « Nouveau compte » ouvrant un formulaire (nom, e-mail, rôle, agence, identifiant Telegram, mot de passe provisoire avec la mention « 12 caractères minimum, à transmettre à la personne ») ; par compte : « Modifier », « Changer le mot de passe », « Retirer l'accès » (confirmation : « <nom> ne pourra plus se connecter ni déposer de bons. Son nom reste sur les bons déjà déposés. ») ou « Rétablir l'accès ». Les erreurs du serveur (`ErreurApi.detail`) s'affichent sous le formulaire. Aucun mot de passe n'est jamais réaffiché.

- [ ] **Step 1: Contrat (échoue)** — `tests/test_web_comptes.py` : la route `comptes` est gardée par `GardeAdmin` ; `Gabarit.tsx` contient le lien `/comptes` ; `Comptes.tsx` contient « Retirer l'accès », « Rétablir l'accès », « Changer le mot de passe », `type="password"`, et aucune occurrence de `hashed_password`.
- [ ] **Step 2–4: Implémenter**, typecheck, build, contrat vert.
- [ ] **Step 5: Commit** — `web: écran de gestion des comptes`.

---

### Task 12: Journal — noms au lieu des identifiants

**Files:**
- Modify: `app/modules/ingest/journal.py` (`JournalLue.noms: dict[str, str]`), `app/modules/api/schemas.py` (`JournalReponse.noms`), `web/src/lib/journal.ts` (`valeurDetail` utilise `noms`), `web/src/pages/Journal.tsx` (transmettre `entree.noms`)
- Test: `app/modules/ingest/tests/test_journal.py`, `tests/test_web_journal.py`

**Interfaces:**
- Produces: `JournalLue.noms: dict[str, str]` — pour chaque entrée, identifiant (texte) → nom, pour toute valeur d'`avant`/`apres` dont la clé est `confirme_par`, `utilisateur_id`, `deposant_id`, `traitee_par` (→ `coalesce(nom, email)` de `utilisateur`), `chantier_id`, `cible_id` (si la clé vaut un chantier) (→ `nom_canonique`), `fournisseur_id` (→ `fournisseur.nom`). Résolution **groupée** : une requête par table pour toute la page, jamais une par entrée. Identifiant introuvable ou non-UUID → absent de `noms`.

Front : dans `valeurDetail`, si `typeof brute === "string"` et `noms[brute]` existe → afficher le nom ; si la clé est une clé d'identifiant connue et le nom absent → « (inconnu) » plutôt que l'UUID.

- [ ] **Step 1: Tests (échouent)** — `test_journal_resout_confirme_par_en_nom` (entrée `quantites_verifiees` avec `apres.confirme_par` = id d'un utilisateur « Léa Test » → `noms[id] == "Léa Test"`), `test_journal_resout_chantier_et_fournisseur`, `test_journal_noms_en_requetes_groupees` (compter les requêtes n'est pas nécessaire : vérifier seulement 3 entrées différentes résolues en un appel), contrat front : `journal.ts` lit `noms`.
- [ ] **Step 2–4: Implémenter, tests verts**, types régénérés.
- [ ] **Step 5: Commit** — `ingest/web: le journal affiche des noms au lieu des identifiants`.

---

### Task 13: Fiche fournisseur par mois et bons conformes cliquables

**Files:**
- Modify: `app/modules/ingest/bilan.py` (`lister_livraisons`), `app/modules/api/bilan.py` (`GET /api/bilan/livraisons`), `app/modules/api/schemas.py`
- Create: `web/src/components/TableauLivraisons.tsx` (extrait de `FicheChantier.tsx` : `EtatBon`, `lienLivraison`, tableau ordinateur + cartes téléphone, filtre d'état), `web/src/pages/Livraisons.tsx` (route `/livraisons`)
- Modify: `web/src/ui/Chiffre.tsx` (prop facultative `vers?: string` → `<Link>`), `web/src/pages/FicheChantier.tsx` (utilise `TableauLivraisons`, tuile « Conforme » → `#livraisons` avec filtre « Conformes »), `web/src/pages/FicheFournisseur.tsx` (sélecteur de mois ; carte « Livraisons » ; tuile « Conforme » cliquable), `web/src/pages/VueEnsemble.tsx` (tuile « Conforme » → `/livraisons?mois=…&etat=conforme`), `web/src/App.tsx`, `web/src/api/bilan.ts`
- Test: `app/modules/ingest/tests/test_bilan.py`, `app/modules/api/tests/test_bilan.py`, `tests/test_web_fournisseurs.py`, `tests/test_web_vue_ensemble.py`, `tests/test_web_chantiers.py`

**Interfaces:**
- Produces:

```python
async def lister_livraisons(session, *, mois: date | None, agence: str | None,
                            chantier_id: uuid.UUID | None, fournisseur_id: uuid.UUID | None) -> list[LigneLivraison]
# LigneLivraison = les champs de LigneBilanBl + chantier_id, chantier (nom), fournisseur_id, fournisseur (nom)
```
Même source et même définition des montants que `bilan_par_bl` (réutiliser ses expressions ; ne jamais redéfinir « conforme ») : une ligne par bloc de facture du périmètre, triée par date de BL décroissante. `GET /api/bilan/livraisons?mois=AAAA-MM&agence=&chantier=&fournisseur=` (admin). Front : état d'une livraison = logique existante d'`EtatBon` (conforme si reçu et aucun problème ouvert) ; filtre `Filtres` « Toutes / Conformes / À vérifier / Sans bon », initialisé par `?etat=` ; chaque ligne ouvre `/bl/<id>` (sinon la facture), comme aujourd'hui sur la fiche chantier. `FicheFournisseur` : `<input type="month">` identique à `FournisseursListe.tsx:261-272`, écrit dans `?mois=` (`setSearchParams`, `replace: true`) ; ses requêtes relisent déjà le mois de l'URL.

- [ ] **Step 1: Tests (échouent)** — `test_lister_livraisons_par_fournisseur_tous_chantiers`, `test_lister_livraisons_conforme_meme_definition_que_bilan` (le total des montants « conforme » de la liste = `bilan_par_chantier` du même mois), `test_route_livraisons_agent_403` ; contrats front : `FicheFournisseur.tsx` contient `type="month"` ; `Chiffre.tsx` accepte `vers` ; `VueEnsemble.tsx` passe `vers` à la tuile « Conforme » ; route `/livraisons` gardée par `GardeAdmin`.
- [ ] **Step 2–4: Implémenter, tests verts**, types régénérés, vérification visuelle rapide (1440 et 375 px) si un outil de capture est disponible.
- [ ] **Step 5: Commit** — `bilan/web: fiche fournisseur par mois et bons conformes cliquables`.

---

### Relecture finale et déploiement (hors sous-agents d'implémentation)

- Relecture de toute la branche sous plusieurs angles (frontières et pureté, table de décision et R18, fusion et données, comptes et sécurité, front et textes), chaque constat vérifié avant correction ; suite complète, ruff, format, mypy, typecheck, build.
- Fusion dans `main`, mise à jour de `docs/dette.md`, d'une recette `docs/mise-en-production-1er-octobre-recette.md`, de `CLAUDE.md` (« Où en est le projet ») et de `memory.md`.
- Déploiement (procédure `memory.md` §6) : dump de chaque base dans `~/sauvegardes-habitat/avant-1er-octobre-*`, démo puis production : `build`, `stop api`, `alembic upgrade head` (0011), `up -d --wait`, puis `python -m app.cli rattacher-chantiers` et `python -m app.cli ranger-photos` ; vérifier `/health`, le webhook Telegram et l'écran.
