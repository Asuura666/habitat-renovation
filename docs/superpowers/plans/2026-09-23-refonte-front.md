# Refonte du front — plan d'exécution

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer les 14 écrans techniques par une interface « Registre » (direction A) pensée pour un dirigeant non technique, sur ordinateur et téléphone, prête pour la démo du samedi 26/09/2026.

**Architecture:** Trois ajouts serveur minimes dans `ingest` (client du chantier et modification, tableau de bord, téléchargement + comparaison d'un BL) exposés par des routes `api` fines ; côté web, un socle commun (`web/src/ui/` : jetons Tailwind, polices auto-hébergées, composants, libellés en langage courant, gabarit barre latérale / barre basse) puis un écran par tâche qui ne fait que présenter les données du serveur.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 async, Alembic, pytest ; React 18, TypeScript, Vite, React Router 7, TanStack Query 5, Tailwind 3 (`extend`), openapi-typescript, `@fontsource/*`.

**Spec:** `docs/superpowers/specs/2026-09-23-refonte-front-design.md` (maquettes : https://claude.ai/artifact/VwiXWPUt4Vg8uQULB8BrLG, artboards `Main`, `ARegler`, `FicheChantier`, `BL`).

## Global Constraints

- Lire `CLAUDE.md` avant tout : frontières (`extract`/`normalize`/`rules` purs ; `api` et `jobs` n'importent que `ingest` et `app.core` ; aucune règle métier dans le front ni les routers), une tâche = un commit en français préfixé du module, tests avant ou avec le code.
- Contrôles avant chaque commit : `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, `npm --prefix web run typecheck`, `npm --prefix web run build` (le hook pre-commit les rejoue).
- Types front générés : `npm --prefix web run api:schema && npm --prefix web run api:types` après toute modification d'API (commiter `web/openapi.json` et `web/src/api/schema.d.ts`).
- Couleurs : fond `#f6f4ef`, surface `#ffffff`, bordure `#e3dfd5`, texte `#1c1b18`, texte secondaire `#5f5b52`, accent `#1f4d3a`, conforme `#2f7a55`, écart `#c77700` (texte `#a86400`), sans bon/urgent `#b3261e` ; toujours doublées d'un libellé.
- Polices : Fraunces (titres, grands chiffres), IBM Plex Sans (texte), IBM Plex Mono (montants, numéros), **auto-hébergées via `@fontsource/*`** (la CSP `default-src 'self'` interdit Google Fonts). Aucune autre nouvelle dépendance front.
- Aucun jargon visible : pas de code de règle (`R08`), « bloc », « alias », « rapprochement », « OCR » dans les textes affichés ; titres de règles = table §5 de la spec, gravité haute/moyenne/basse → « Urgent » / « À voir » / « Info ».
- Montants `1 310,00 €` (fonctions de `web/src/lib/formats.ts`), dates `12/09/2026`.
- Téléphone (375 px) = cible à part entière : barre de navigation en bas, tuiles en grille 2 colonnes, tableaux en cartes empilées, détail d'« À régler » en page plein écran. Largeurs vérifiées : 1440, 1280, 375.
- Accessibilité : vrais `<button>`, `<a>`, `<label>` ; contraste 4,5:1 ; cibles ≥ 44 px ; focus visible.
- Données de test : **inventées uniquement**, jamais `tests/fixtures/`.
- Les anciennes routes redirigent vers les nouvelles (liens déjà envoyés par Telegram).
- Tests pytest : une seule suite par base ; un arbre de travail utilise sa propre base (`TEST_DATABASE_URL` pointant vers `bl_test_<nom>` + `bl_test_<nom>_migrations`, à créer sur `habitat_reno-postgres-1`).

## Review Focus

1. **Mois sans aucune facture** (début de mois) : le tableau de bord doit afficher des zéros et « Aucun chantier ce mois-ci », jamais une erreur ni des `NaN`. → test `test_tableau_de_bord_mois_vide` (Task 2) et état vide vérifié en Task 5.
2. **Chantier non résolu** (`chantier_id = null`) : il doit apparaître comme « Chantier à rattacher » avec l'état `a_rattacher`, cliquable vers « À régler », jamais disparaître ni faire planter la fiche chantier. → test `test_tableau_de_bord_chantier_non_resolu` (Task 2) et contrat front en Task 5.
3. **Anomalie à `detail` incomplet ou règle inconnue** : le libellé en langage courant doit se replier sur un titre générique sans casser la liste. → test `test_libelles_couvre_toutes_les_regles` (Task 4).
4. **Agent connecté** qui tape une URL admin (`/`, `/a-regler`, `/chantiers`) : il doit être renvoyé vers `/documents` sans voir de chiffre. → contrat `test_routes_admin_sont_gardees` (Task 4).
5. **Nom de fichier téléchargé** avec accents, espaces, `/` dans le nom du chantier ou numéro absent : le fichier doit se télécharger avec un nom sûr. → test `test_nom_telechargement_assaini` (Task 3).

---

## Vagues d'exécution

- **Vague 1 (en parallèle)** : Task 1 → Task 2 (même arbre, séquentiel, serveur) ; Task 3 (serveur) ; Task 4 (socle web).
- **Vague 2 (en parallèle, après la vague 1 fusionnée)** : Task 5, 6, 7, 8, 9, 10.
- **Vague 3** : Task 11 (recette, déploiement).

Priorité si le temps manque : 4 → 5 → 6 → 7 → 8, puis 9 et 10.

---

### Task 1: Client du chantier et modification d'un chantier

**Files:**
- Create: `migrations/versions/0010_chantier_client.py`
- Modify: `app/modules/ingest/models.py` (classe `Chantier`)
- Modify: `app/modules/ingest/referentiels.py` (`ChantierResume`, `lister_chantiers`, `creer_chantier`, nouvelle `modifier_chantier`)
- Modify: `app/modules/ingest/bilan.py` (`LigneBilanChantier` + sélection dans `_bilan_par_chantier_interne`)
- Modify: `app/modules/api/schemas.py` (`ChantierReponse`, `ChantierCreationRequete`, nouvelle `ChantierModificationRequete`, `LigneBilanChantierReponse`)
- Modify: `app/modules/api/referentiels.py` (POST transmet `client`, nouvelle route `PUT /api/chantiers/{chantier_id}`)
- Test: `app/modules/ingest/tests/test_referentiels.py`, `app/modules/api/tests/test_referentiels.py`, `app/modules/ingest/tests/test_bilan.py`, `tests/test_migrations.py` (s'il liste les révisions)

**Interfaces:**
- Produces: `Chantier.client: Mapped[str | None]` ; `ChantierResume(id, nom_canonique, agence, client, actif)` ; `creer_chantier(session, *, nom_canonique: str, agence: str | None, client: str | None = None, auteur_id: uuid.UUID) -> ChantierResume` ; `modifier_chantier(session, *, chantier_id: uuid.UUID, nom_canonique: str, agence: str | None, client: str | None, actif: bool, auteur_id: uuid.UUID) -> ChantierResume` (lève `ChantierIntrouvable`, `ChantierEnDouble`) ; `LigneBilanChantier.client: str | None` ; `PUT /api/chantiers/{id}` corps `{nom_canonique, agence, client, actif}` → `ChantierReponse` (404 inconnu, 409 doublon, 403 agent).

- [ ] **Step 1: Tests service (échouent)** — dans `app/modules/ingest/tests/test_referentiels.py`, ajouter :

```python
async def test_creer_chantier_enregistre_le_client(db_session: AsyncSession) -> None:
    auteur = await _creer_admin(
        db_session
    )  # aide existante du fichier, sinon créer un Utilisateur admin inventé
    chantier = await creer_chantier(
        db_session,
        nom_canonique="Villa Test",
        agence="Lyon",
        client="  M. et Mme Martin  ",
        auteur_id=auteur.id,
    )
    assert chantier.client == "M. et Mme Martin"


async def test_modifier_chantier_change_tout_et_journalise(
    db_session: AsyncSession,
) -> None:
    auteur = await _creer_admin(db_session)
    cree = await creer_chantier(
        db_session, nom_canonique="Villa Test", agence=None, auteur_id=auteur.id
    )
    modifie = await modifier_chantier(
        db_session,
        chantier_id=cree.id,
        nom_canonique="Villa Test B",
        agence="Villeurbanne",
        client="SCI Test",
        actif=False,
        auteur_id=auteur.id,
    )
    assert (modifie.nom_canonique, modifie.agence, modifie.client, modifie.actif) == (
        "Villa Test B",
        "Villeurbanne",
        "SCI Test",
        False,
    )
    entree = (
        await db_session.execute(
            select(Journal).where(Journal.action == "chantier_modifie")
        )
    ).scalar_one()
    assert entree.avant["client"] is None and entree.apres["client"] == "SCI Test"


async def test_modifier_chantier_vide_devient_none(db_session: AsyncSession) -> None:
    auteur = await _creer_admin(db_session)
    cree = await creer_chantier(
        db_session,
        nom_canonique="Villa Test",
        agence="Lyon",
        client="X",
        auteur_id=auteur.id,
    )
    modifie = await modifier_chantier(
        db_session,
        chantier_id=cree.id,
        nom_canonique="Villa Test",
        agence="  ",
        client="",
        actif=True,
        auteur_id=auteur.id,
    )
    assert modifie.agence is None and modifie.client is None


async def test_modifier_chantier_refuse_un_doublon(db_session: AsyncSession) -> None:
    auteur = await _creer_admin(db_session)
    await creer_chantier(
        db_session, nom_canonique="Maison Alpha", agence=None, auteur_id=auteur.id
    )
    beta = await creer_chantier(
        db_session, nom_canonique="Maison Beta", agence=None, auteur_id=auteur.id
    )
    with pytest.raises(ChantierEnDouble):
        await modifier_chantier(
            db_session,
            chantier_id=beta.id,
            nom_canonique="maison ALPHA",
            agence=None,
            client=None,
            actif=True,
            auteur_id=auteur.id,
        )


async def test_modifier_chantier_inconnu(db_session: AsyncSession) -> None:
    auteur = await _creer_admin(db_session)
    with pytest.raises(ChantierIntrouvable):
        await modifier_chantier(
            db_session,
            chantier_id=uuid.uuid4(),
            nom_canonique="X",
            agence=None,
            client=None,
            actif=True,
            auteur_id=auteur.id,
        )
```

Et dans `app/modules/ingest/tests/test_bilan.py`, un test qui crée un chantier avec `client="SCI Test"`, une facture et un bloc (réutiliser les aides du fichier) et vérifie `lignes[0].client == "SCI Test"`.

- [ ] **Step 2: Lancer** `uv run pytest app/modules/ingest/tests/test_referentiels.py app/modules/ingest/tests/test_bilan.py -k "client or modifier" -v` → FAIL (`client` inconnu, `modifier_chantier` absent).

- [ ] **Step 3: Migration** `migrations/versions/0010_chantier_client.py` :

```python
"""Client final du chantier (ajout hors CDC demandé le 23/09/2026).

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-23 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chantier", sa.Column("client", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("chantier", "client")
```

Modèle : dans `Chantier`, après `agence`, `client: Mapped[str | None] = mapped_column(Text, nullable=True)`.

- [ ] **Step 4: Service** dans `referentiels.py` : ajouter `client: str | None` à `ChantierResume` (après `agence`), le renseigner dans `lister_chantiers` et `creer_chantier` (paramètre `client: str | None = None`, même normalisation que `agence` : `strip()` puis vide → `None`, ajouté à `apres` du journal). Ajouter :

```python
def _texte_ou_none(valeur: str | None) -> str | None:
    if valeur is None:
        return None
    return valeur.strip() or None


async def modifier_chantier(
    session: AsyncSession,
    *,
    chantier_id: uuid.UUID,
    nom_canonique: str,
    agence: str | None,
    client: str | None,
    actif: bool,
    auteur_id: uuid.UUID,
) -> ChantierResume:
    """Remplace nom, agence, client et état actif d'un chantier. Même règle
    de doublon que `creer_chantier` (autres chantiers seulement). Journalise
    `chantier_modifie` avec l'état avant/après."""
    chantier = await session.get(Chantier, chantier_id)
    if chantier is None:
        raise ChantierIntrouvable(str(chantier_id))
    nom = nom_canonique.strip()
    cible = normaliser_libelle(nom)
    for existant in (await session.execute(select(Chantier))).scalars().all():
        if (
            existant.id != chantier_id
            and normaliser_libelle(existant.nom_canonique) == cible
        ):
            raise ChantierEnDouble(existant.id)
    avant = {
        "nom_canonique": chantier.nom_canonique,
        "agence": chantier.agence,
        "client": chantier.client,
        "actif": chantier.actif,
    }
    chantier.nom_canonique = nom
    chantier.agence = _texte_ou_none(agence)
    chantier.client = _texte_ou_none(client)
    chantier.actif = actif
    chantier.updated_by = auteur_id
    apres = {
        "nom_canonique": chantier.nom_canonique,
        "agence": chantier.agence,
        "client": chantier.client,
        "actif": chantier.actif,
    }
    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="chantier_modifie",
            cible_table="chantier",
            cible_id=str(chantier.id),
            avant=avant,
            apres=apres,
        )
    )
    await session.commit()
    await session.refresh(chantier)
    return ChantierResume(
        id=chantier.id,
        nom_canonique=chantier.nom_canonique,
        agence=chantier.agence,
        client=chantier.client,
        actif=chantier.actif,
    )
```

Bilan : ajouter `client: str | None` à `LigneBilanChantier` (après `agence`), sélectionner `Chantier.client` là où `Chantier.nom_canonique` et `Chantier.agence` sont sélectionnés dans `_bilan_par_chantier_interne` (et le `group_by` correspondant), le passer au constructeur. `None` pour la ligne non résolue.

- [ ] **Step 5: Lancer les tests service** → PASS.

- [ ] **Step 6: Tests route (échouent)** dans `app/modules/api/tests/test_referentiels.py` (réutiliser `_app_test`, `_creer_utilisateur`, `_ip_isolee` et l'aide de connexion du fichier) :

```python
async def test_put_chantier_modifie_et_renvoie_le_client(db_session, sessions_test, tmp_path) -> None:
    # admin connecté ; chantier créé via POST {"nom_canonique": "Villa Test"}
    # PUT /api/chantiers/{id} {"nom_canonique": "Villa Test", "agence": "Lyon", "client": "SCI Test", "actif": true}
    # → 200, corps["client"] == "SCI Test", corps["agence"] == "Lyon"

async def test_put_chantier_inconnu_404(...)  # uuid4() → 404
async def test_put_chantier_doublon_409(...)  # renommer vers un nom existant → 409 + "original_id"
async def test_put_chantier_agent_403(...)    # agent connecté → 403
async def test_get_chantiers_expose_client(...)  # GET /api/chantiers → chaque élément a la clé "client"
```

Écrire ces tests complètement sur le modèle exact des tests `POST /api/chantiers` existants du fichier (mêmes aides, même `Origin`).

- [ ] **Step 7: Route** : dans `schemas.py`, `client: str | None` sur `ChantierReponse` et `LigneBilanChantierReponse` ; `client: str | None = Field(default=None, max_length=200)` sur `ChantierCreationRequete` ; nouvelle

```python
class ChantierModificationRequete(BaseModel):
    """Corps de `PUT /api/chantiers/{id}` : remplace nom, agence, client et
    état actif."""

    nom_canonique: str = Field(min_length=1, max_length=200)
    agence: str | None = Field(default=None, max_length=200)
    client: str | None = Field(default=None, max_length=200)
    actif: bool

    @field_validator("nom_canonique")
    @classmethod
    def _nom_non_blanc(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("nom vide")
        return valeur
```

Dans `api/referentiels.py`, transmettre `client=requete.client` au POST et ajouter `@router.put("/chantiers/{chantier_id}", response_model=ChantierReponse)` (admin requis) : `ChantierIntrouvable` → 404 `{"detail": "chantier introuvable"}`, `ChantierEnDouble` → même `JSONResponse` 409 que le POST.

- [ ] **Step 8: Lancer** `uv run pytest app/modules/api/tests/test_referentiels.py app/modules/ingest/tests -q` puis la suite complète et les contrôles → PASS ; régénérer les types front (`api:schema`, `api:types`) et vérifier `npm --prefix web run typecheck`.

- [ ] **Step 9: Commit** `ingest/api: client du chantier et modification d'un chantier` (ajouter une entrée dans `docs/dette.md` : « client du chantier = ajout hors CDC du 23/09, texte libre sans référentiel »).

---

### Task 2: Tableau de bord du mois

**Files:**
- Create: `app/modules/ingest/tableau_de_bord.py`
- Create: `app/modules/ingest/tests/test_tableau_de_bord.py`
- Create: `app/modules/api/tableau_de_bord.py` (router), enregistrer dans `app/modules/api/__init__.py` comme les autres routers
- Modify: `app/modules/api/schemas.py`
- Create: `app/modules/api/tests/test_tableau_de_bord.py`

**Interfaces:**
- Consumes: `bilan_par_chantier(session, *, mois, agence)` et `LigneBilanChantier.client` (Task 1) ; `lister_anomalies(session, statut="ouverte", limite=...)` → `list[AnomalieLue]` ; `MontantsBilan`.
- Produces:

```python
ETATS = ("a_rattacher", "bl_manquant", "prix", "quantites", "a_voir", "conforme")

@dataclass(frozen=True)
class TotauxMois:
    facture_ht: Decimal
    rapproche: Decimal
    en_ecart: Decimal
    non_justifie: Decimal
    conforme: Decimal  # rapproche - en_ecart, jamais négatif

@dataclass(frozen=True)
class ChantierTableau:
    chantier_id: uuid.UUID | None
    nom_canonique: str | None
    client: str | None
    agence: str | None
    etat: str  # une valeur de ETATS
    montants: MontantsBilan
    a_verifier: Decimal  # en_ecart + non_justifie

@dataclass(frozen=True)
class ProblemePrioritaire:
    anomalie: AnomalieLue
    montant_en_jeu: Decimal | None

@dataclass(frozen=True)
class TableauDeBord:
    mois: date
    totaux: TotauxMois
    nb_problemes_ouverts: int
    nb_problemes_urgents: int
    nb_bl_factures: int
    nb_bl_recus: int
    chantiers: list[ChantierTableau]
    priorites: list[ProblemePrioritaire]  # 4 au plus

async def tableau_de_bord(session: AsyncSession, *, mois: date) -> TableauDeBord
```

Route : `GET /api/tableau-de-bord?mois=AAAA-MM-01` (admin, `mois` obligatoire, même type `date` que `/api/bilan/chantiers`), réponse `TableauDeBordReponse` avec montants en chaînes (même sérialisation que `MontantsBilanReponse`) et `priorites[].anomalie` au format `AnomalieReponse`.

Règles de calcul (toutes côté serveur) :
- `totaux` = somme des `montants` des lignes de `bilan_par_chantier(mois=mois, agence=None)` ; `conforme = max(rapproche - en_ecart, 0)`.
- `etat` d'un chantier, dans cet ordre : `chantier_id is None` → `a_rattacher` ; `non_justifie > 0` → `bl_manquant` ; une anomalie ouverte du chantier en R07/R08/R09 → `prix` ; en R03/R04/R05/R17 → `quantites` ; `nb_anomalies_ouvertes > 0` → `a_voir` ; sinon `conforme`.
- Anomalies ouvertes du mois : `lister_anomalies(statut="ouverte", limite=500)` filtrées sur les chantiers présents dans le bilan du mois (par `chantier_id`, `None` compris) ; `nb_problemes_ouverts` = leur nombre, `nb_problemes_urgents` = celles de gravité `haute`.
- `nb_bl_factures` = nombre de blocs non archivés du mois ; `nb_bl_recus` = ceux dont `statut_rapprochement == "recu"` (réutiliser les conditions de mois de `bilan.py` : `_conditions_base(mois)` / `_sous_requete_blocs`, importables dans le même paquet `ingest`).
- `montant_en_jeu` : R01/R02 → `Decimal(detail["montant_ht"])` ; R05/R13 → `abs(Decimal(detail["montant"]))` ; sinon `None` ; valeur non convertible → `None`.
- `priorites` : tri gravité (haute, moyenne, basse), puis `montant_en_jeu` décroissant (`None` en dernier), puis `cree_le` ; 4 premières.
- `chantiers` : tri `a_verifier` décroissant puis `nom_canonique` (non résolu en dernier à égalité).

- [ ] **Step 1: Tests service (échouent)** — `test_tableau_de_bord.py`, données inventées construites avec les mêmes aides que `test_bilan.py` (copier `_creer_facture`, `_creer_bloc`, `_creer_ligne` ou équivalents de ce fichier) :

```python
pytestmark = [pytest.mark.anyio, pytest.mark.db]
_SEPT = date(2026, 9, 1)


async def test_tableau_de_bord_mois_vide(db_session: AsyncSession) -> None:
    tdb = await tableau_de_bord(db_session, mois=_SEPT)
    assert tdb.totaux == TotauxMois(
        Decimal(0), Decimal(0), Decimal(0), Decimal(0), Decimal(0)
    )
    assert (
        tdb.chantiers,
        tdb.priorites,
        tdb.nb_bl_factures,
        tdb.nb_problemes_ouverts,
    ) == ([], [], 0, 0)


async def test_tableau_de_bord_totaux_et_conforme(db_session) -> None:
    # facture de septembre : bloc reçu 100,00 € sans anomalie, bloc reçu 50,00 € avec R08 ouverte,
    # bloc non reçu 30,00 € avec R01 ouverte
    tdb = await tableau_de_bord(db_session, mois=_SEPT)
    assert tdb.totaux.facture_ht == Decimal("180.00")
    assert tdb.totaux.en_ecart == Decimal("50.00")
    assert tdb.totaux.non_justifie == Decimal("30.00")
    assert tdb.totaux.conforme == Decimal("100.00")
    assert (tdb.nb_bl_factures, tdb.nb_bl_recus) == (3, 2)
    assert (tdb.nb_problemes_ouverts, tdb.nb_problemes_urgents) == (2, 2)


async def test_tableau_de_bord_etats(db_session) -> None:
    # 4 chantiers : A conforme ; B avec bloc non reçu ; C avec R08 ouverte ; D avec R03 ouverte
    etats = {
        c.nom_canonique: c.etat
        for c in (await tableau_de_bord(db_session, mois=_SEPT)).chantiers
    }
    assert etats == {"A": "conforme", "B": "bl_manquant", "C": "prix", "D": "quantites"}


async def test_tableau_de_bord_chantier_non_resolu(db_session) -> None:
    # bloc dont ni le bloc ni le document n'ont de chantier
    tdb = await tableau_de_bord(db_session, mois=_SEPT)
    ligne = next(c for c in tdb.chantiers if c.chantier_id is None)
    assert ligne.etat == "a_rattacher" and ligne.nom_canonique is None


async def test_tableau_de_bord_priorites_triees_et_limitees(db_session) -> None:
    # 5 anomalies ouvertes : R07 (moyenne), R01 30 €, R02 200 €, R08 (haute, sans montant), R01 90 €
    regles = [
        p.anomalie.regle
        for p in (await tableau_de_bord(db_session, mois=_SEPT)).priorites
    ]
    assert regles == ["R02", "R01", "R01", "R08"]


async def test_tableau_de_bord_ignore_les_autres_mois(db_session) -> None:
    # une facture d'août seulement → septembre vide
    assert (await tableau_de_bord(db_session, mois=_SEPT)).chantiers == []
```

Écrire chaque scénario complètement (construction des données inventées, pas de commentaire à la place du code). Les anomalies sont créées par `synchroniser_anomalies` ou insérées comme dans `test_bilan.py`.

- [ ] **Step 2: Lancer** `uv run pytest app/modules/ingest/tests/test_tableau_de_bord.py -v` → FAIL (module absent).
- [ ] **Step 3: Implémenter** `ingest/tableau_de_bord.py` selon les interfaces et règles ci-dessus (aucun import FastAPI ; docstring de module qui renvoie à la spec §6.2).
- [ ] **Step 4: Lancer** → PASS.
- [ ] **Step 5: Tests route (échouent)** `app/modules/api/tests/test_tableau_de_bord.py` (aides copiées de `app/modules/api/tests/test_bilan.py`, IP `10.84.0.x`) : admin → 200 et clés `totaux.conforme` (chaîne), `chantiers[0].etat`, `priorites` ; agent → 403 ; `mois` absent → 422 ; mois vide → 200 avec `chantiers == []`.
- [ ] **Step 6: Implémenter** schémas `TotauxMoisReponse`, `ChantierTableauReponse`, `ProblemePrioritaireReponse`, `TableauDeBordReponse` et le router ; l'enregistrer ; lancer → PASS ; suite complète et contrôles ; régénérer les types front.
- [ ] **Step 7: Commit** `ingest/api: tableau de bord du mois`.

---

### Task 3: Téléchargement d'un document et comparaison d'un BL

**Files:**
- Modify: `app/modules/ingest/lecture.py` (`FichierDocument.nom_telechargement`, `_fichier_ou_404`)
- Create: `app/modules/ingest/comparaison_bl.py`, `app/modules/ingest/tests/test_comparaison_bl.py`
- Modify: `app/modules/api/documents.py` (paramètre `telechargement`, route `GET /api/documents/{id}/comparaison`), `app/modules/api/schemas.py`
- Test: `app/modules/ingest/tests/test_lecture*.py` (fichier qui teste `fichier_document`), `app/modules/api/tests/test_documents*.py`

**Interfaces:**
- Produces: `FichierDocument(chemin: Path, type_mime: str, nom_telechargement: str)` ; `nom_telechargement(type: str, numero: str | None, numero_interne: int, chantier: str | None, extension: str) -> str` ; `GET /api/documents/{id}/fichier?telechargement=true` → `Content-Disposition: attachment; filename*=UTF-8''…` ; 

```python
@dataclass(frozen=True)
class LigneComparee:
    ordre: int
    code: str | None
    article: str | None
    qte_livree: Decimal | None      # ligne du BL
    qte_facturee: Decimal | None    # ligne de facture appariée (rapprochement_ligne), None si aucune
    pu_facture: Decimal | None
    regles_ouvertes: list[str]      # codes des anomalies ouvertes portant sur la ligne BL ou sa ligne facture

@dataclass(frozen=True)
class ComparaisonBl:
    document_id: uuid.UUID
    facture_id: uuid.UUID | None
    numero_facture: str | None
    montant_facture_ht: Decimal | None  # montant du bloc de facture qui cite ce BL
    lignes: list[LigneComparee]

async def comparer_bl(session: AsyncSession, document_id: uuid.UUID) -> ComparaisonBl
# lève DocumentIntrouvable si absent ou si type != "bl"
```

Route `GET /api/documents/{id}/comparaison` (admin) → `ComparaisonBlReponse` (décimaux en chaînes), 404 sinon.

- [ ] **Step 1: Test du nom (échoue)** :

```python
@pytest.mark.parametrize(
    ("args", "attendu"),
    [
        (
            ("bl", "BLD0005", 12, "Villa des Tilleuls", "jpg"),
            "BL_BLD0005_Villa-des-Tilleuls.jpg",
        ),
        (("bl", None, 12, None, "png"), "BL_12_sans-chantier.png"),
        (
            ("facture", "F/2026 09", 3, "Rés. Été", "pdf"),
            "FACTURE_F-2026-09_Res-Ete.pdf",
        ),
    ],
)
def test_nom_telechargement_assaini(args, attendu) -> None:
    assert nom_telechargement(*args) == attendu
```

Règle : type en majuscules ; numéro sinon numéro interne ; chantier sinon `sans-chantier` ; accents retirés (`unicodedata.normalize("NFKD")` puis ASCII), tout caractère hors `[A-Za-z0-9]` → `-`, tirets consécutifs fusionnés, bords retirés.

- [ ] **Step 2: Implémenter** `nom_telechargement` dans `lecture.py`, l'utiliser dans `_fichier_ou_404` (qui reçoit alors le chantier résolu : charger `Chantier.nom_canonique` si `document.chantier_id`), ajouter le champ à `FichierDocument`. Route : `telechargement: bool = False` ; si vrai, `FileResponse(..., filename=fichier.nom_telechargement, content_disposition_type="attachment")`. Test route : `?telechargement=true` → en-tête `content-disposition` commence par `attachment` et contient le nom ; sans paramètre → pas d'`attachment`.
- [ ] **Step 3: Tests `comparer_bl` (échouent)** — données inventées : un BL à 3 lignes, une facture dont le bloc cite ce BL (`bloc.bl_document_id` ou statut rapproché selon le modèle réel), 2 lignes appariées via `RapprochementLigne`, une R08 ouverte sur une ligne facture. Vérifier : ordre des lignes, `qte_facturee` de la ligne non appariée = `None`, `regles_ouvertes == ["R08"]` sur la bonne ligne, `numero_facture`, `montant_facture_ht` ; `DocumentIntrouvable` pour un id inconnu et pour une facture.
- [ ] **Step 4: Implémenter** `comparaison_bl.py` (lecture seule ; lignes du BL par `ordre` ; jointure externe `rapprochement_ligne` → ligne facture ; anomalies ouvertes par `ligne_id` ; bloc via le lien BL ↔ bloc déjà utilisé par `bilan_par_bl`, champ `bl_document_id`).
- [ ] **Step 5: Route + tests route** (admin 200, agent 403, id inconnu 404) ; suite complète et contrôles ; types front.
- [ ] **Step 6: Commit** `ingest/api: téléchargement nommé et comparaison d'un BL`.

---

### Task 4: Socle web — charte, composants, libellés, gabarit, routes

**Files:**
- Modify: `web/package.json` (+ `@fontsource/fraunces`, `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono`), `web/package-lock.json`
- Modify: `web/tailwind.config.js` (ou `.cjs`, fichier existant), `web/src/index.css`, `web/src/main.tsx` (imports des polices)
- Create: `web/src/ui/Carte.tsx`, `ui/Chiffre.tsx`, `ui/PastilleEtat.tsx`, `ui/Bouton.tsx`, `ui/Filtres.tsx`, `ui/FilAriane.tsx`, `ui/EnTetePage.tsx`, `ui/EtatVide.tsx`, `ui/libelles.ts`, `ui/index.ts`
- Rewrite: `web/src/components/Gabarit.tsx` (barre latérale ≥ `md`, barre basse < `md`)
- Modify: `web/src/App.tsx` (nouvelles routes + redirections), `web/src/routes/RedirectionAccueil.tsx`, `web/src/pages/Connexion.tsx` (habillage)
- Create: `tests/test_web_socle.py` ; Modify: `tests/test_web_bilan.py`, `tests/test_web_bilan_navigation.py`, `tests/test_web_cache.py`, `tests/test_web_reglages.py` (chemins/nav mis à jour, sans affaiblir ce qu'ils protègent)

**Interfaces:**
- Produces (utilisés par les tâches 5 à 10) :
  - Tailwind `theme.extend.colors` : `fond`, `surface`, `bordure`, `encre`, `encre-2`, `accent`, `accent-fonce`, `conforme`, `ecart`, `ecart-texte`, `alerte` (valeurs des Global Constraints) ; `fontFamily` : `titre` (Fraunces), `sans` (IBM Plex Sans), `mono` (IBM Plex Mono) ; `borderRadius.carte = 14px`.
  - `Carte({titre?, action?, children, className?})`, `Chiffre({libelle, valeur, sousTexte?, ton?: "neutre"|"conforme"|"ecart"|"alerte"})`, `PastilleEtat({etat})` avec `etat` ∈ `ETATS` de Task 2 et libellés : `a_rattacher` « À rattacher », `bl_manquant` « BL manquant », `prix` « Prix à contester », `quantites` « Quantités à vérifier », `a_voir` « À voir », `conforme` « Tout est conforme » ; `Bouton({variante: "principal"|"secondaire", ...props})`, `Filtres({options: {valeur, libelle, compte?}[], valeur, onChange})` (boutons `aria-pressed`), `FilAriane({elements: {libelle, vers?}[]})`, `EnTetePage({surtitre?, titre, actions?})`, `EtatVide({message})`.
  - `libelles.ts` : `titreRegle(code: string): string`, `urgence(gravite: string): "Urgent"|"À voir"|"Info"`, `phraseProbleme(a: Anomalie): string`, `categorieProbleme(regle: string): "bl"|"prix"|"quantites"|"rattacher"|"autre"`. Réutiliser les phrases chiffrées existantes de `web/src/lib/regles.ts` en supprimant les codes et le jargon ; `lib/regles.ts` devient un simple ré-export ou est supprimé une fois les usages migrés.
  - Routes (spec §3) : `/` Vue d'ensemble (admin), `/a-regler`, `/chantiers`, `/chantiers/:id`, `/fournisseurs`, `/fournisseurs/:id`, `/documents`, `/documents/:id`, `/bl/:id`, `/reglages`, `/journal`. Redirections : `/a-traiter` et `/anomalies` → `/a-regler` ; `/bilan` → `/chantiers` ; `/bilan/fournisseurs` → `/fournisseurs` ; `/bilan/fournisseurs/:f` → `/fournisseurs/:f` ; `/bilan/:c` et `/bilan/:c/:f` → `/chantiers/:c` ; `/factures` et `/bl` → `/documents` ; `/factures/:id` → `/documents/:id`. Les tâches 5–10 remplacent un composant `EcranEnConstruction` posé ici sur chaque nouvelle route par l'écran réel (les anciens écrans restent branchés tant que leur remplaçant n'existe pas : `/a-regler` monte d'abord `ATraiter`, `/chantiers` monte `Bilan`, etc.).
  - Agent : `RedirectionAccueil` envoie l'agent vers `/documents` ; `GardeAdmin` renvoie l'agent vers `/documents`.

- [ ] **Step 1: Tests de contrat (échouent)** `tests/test_web_socle.py` :

```python
from pathlib import Path

WEB = Path(__file__).parents[1] / "web"
SRC = WEB / "src"


def test_polices_auto_hebergees() -> None:
    assert "fonts.googleapis" not in (WEB / "index.html").read_text()
    main = (SRC / "main.tsx").read_text()
    for paquet in (
        "@fontsource/fraunces",
        "@fontsource/ibm-plex-sans",
        "@fontsource/ibm-plex-mono",
    ):
        assert paquet in main


def test_jetons_de_la_charte() -> None:
    config = next(WEB.glob("tailwind.config.*")).read_text()
    for valeur in (
        "#f6f4ef",
        "#1f4d3a",
        "#2f7a55",
        "#c77700",
        "#b3261e",
        "Fraunces",
        "IBM Plex Mono",
    ):
        assert valeur in config


def test_libelles_couvre_toutes_les_regles() -> None:
    libelles = (SRC / "ui" / "libelles.ts").read_text()
    for n in range(1, 18):
        assert f"R{n:02d}:" in libelles
    assert "Bon de livraison jamais reçu" in libelles
    assert (
        "Prix plus cher que d'habitude" in libelles
        or "Prix plus cher que d’habitude" in libelles
    )
    assert "Problème à vérifier" in libelles  # repli pour une règle inconnue


def test_navigation_cinq_entrees_sans_jargon() -> None:
    gabarit = (SRC / "components" / "Gabarit.tsx").read_text()
    for libelle in (
        "Vue d'ensemble",
        "À régler",
        "Chantiers",
        "Fournisseurs",
        "Documents",
        "Réglages",
        "Journal",
    ):
        assert libelle in gabarit
    for jargon in ("Anomalies", "Bilan", "BL déposés", "À traiter"):
        assert f">{jargon}<" not in gabarit
    assert "md:hidden" in gabarit and "fixed bottom-0" in gabarit


def test_anciennes_routes_redirigent() -> None:
    app = (SRC / "App.tsx").read_text()
    for ancien in ('"a-traiter"', '"anomalies"', '"bilan"', '"factures"', '"bl"'):
        assert f"path={ancien}" in app
    assert "Navigate" in app


def test_routes_admin_sont_gardees() -> None:
    app = (SRC / "App.tsx").read_text()
    for chemin in (
        'path="/"',
        'path="a-regler"',
        'path="chantiers"',
        'path="fournisseurs"',
        'path="journal"',
        'path="reglages"',
    ):
        # la déclaration de route va jusqu'au prochain `path=` : elle doit monter GardeAdmin
        declaration = app.split(chemin, 1)[1].split("path=", 1)[0]
        assert "GardeAdmin" in declaration, chemin
```

- [ ] **Step 2: Lancer** `uv run pytest tests/test_web_socle.py -v` → FAIL.
- [ ] **Step 3: Implémenter** : `npm --prefix web install @fontsource/fraunces @fontsource/ibm-plex-sans @fontsource/ibm-plex-mono` ; imports dans `main.tsx` (`import "@fontsource/fraunces/500.css"`, `600.css`, `ibm-plex-sans/400.css`, `500.css`, `600.css`, `ibm-plex-mono/500.css`) ; jetons Tailwind ; `index.css` : `body { @apply bg-fond text-encre font-sans; }` ; composants `ui/` ; `libelles.ts` ; `Gabarit` (barre latérale fixe 232 px sur `md+` : titre « Habitat & Rénovation », sous-titre « Contrôle des livraisons », 5 liens `NavLink` dont « À régler » avec pastille du nombre de problèmes ouverts (`compter_anomalies_hautes_ouvertes` déjà exposé ? sinon laisser la pastille à la Task 6), liens discrets Réglages/Journal, nom de l'utilisateur et « Se déconnecter » en bas ; sous `md` : en-tête compact + `<nav className="fixed bottom-0 inset-x-0 md:hidden ...">` à 5 icônes SVG inline + libellés, `pb-20` sur le contenu) ; agents : seules « Documents » et la déconnexion ; routes et redirections ; `Connexion` à la charte (carte centrée, titre Fraunces). Mettre à jour les tests `test_web_*` existants pour les nouveaux chemins.
- [ ] **Step 4: Lancer** les tests de contrat, `typecheck`, `build`, suite complète → PASS.
- [ ] **Step 5: Vérification visuelle** : `npm --prefix web run dev` (proxy vers l'API de dev) ou build servi par l'instance démo ; captures 1440 et 375 de la connexion et du gabarit avec Chromium headless (`/usr/bin/chromium --headless --screenshot=... --window-size=375,812`), rangées sous `var/captures/refonte/`.
- [ ] **Step 6: Commit** `web: socle de la refonte (charte, composants, navigation)`.

---

### Task 5: Vue d'ensemble

**Files:**
- Create: `web/src/api/tableauDeBord.ts`, `web/src/pages/VueEnsemble.tsx`, `tests/test_web_vue_ensemble.py`
- Modify: `web/src/App.tsx` (route `/` → `VueEnsemble`)

**Interfaces:**
- Consumes: `GET /api/tableau-de-bord?mois=` (Task 2), composants `ui/` et `libelles.ts` (Task 4), `urlExportBilanDetail` (existant, `api/bilan.ts`).
- Produces: `obtenirTableauDeBord(mois: string): Promise<TableauDeBord>`, `cleTableauDeBord(mois)`.

Contenu (maquette `Main`) : `EnTetePage` (surtitre « Bonjour {prénom} », titre « Septembre 2026 » dérivé du mois, actions : sélecteur `<input type="month" id="mois">` libellé « Mois » et lien « Exporter pour Excel » vers l'export détaillé du mois) ; six `Chiffre` : Facturé ce mois, Conforme (`conforme`), Écart prix ou quantité (`ecart`), Sans bon de livraison (`alerte`), Problèmes à régler (« dont N urgents »), Bons de livraison reçus (« N / M », « K manquants à réclamer ») — grille `grid-cols-2 md:grid-cols-3 xl:grid-cols-6` ; carte « Chantiers » : tableau `md+` (Chantier · client / agence, État = `PastilleEtat`, Facturé, À vérifier, Problèmes) et cartes empilées `< md` ; chaque ligne est un lien vers `/chantiers/:id`, la ligne non résolue vers `/a-regler?filtre=rattacher` avec le nom « Chantier à rattacher » ; carte « À régler en priorité » : 4 problèmes (`titreRegle`, `phraseProbleme`, contexte chantier · fournisseur, `montant_en_jeu` formaté ou vide) + lien « Voir les N problèmes → » ; `EtatVide` « Aucune facture ce mois-ci. » quand `chantiers` est vide. Mois par défaut : mois courant Europe/Paris, conservé dans l'URL (`?mois=AAAA-MM`).

- [ ] **Step 1: Contrat (échoue)** `tests/test_web_vue_ensemble.py` : le fichier page contient `obtenirTableauDeBord`, `useSearchParams`, `type="month"`, les six libellés de tuiles exacts ci-dessus, `PastilleEtat`, `"Chantier à rattacher"`, `"Aucune facture ce mois-ci."`, `"Exporter pour Excel"`, `md:hidden` ; aucun calcul `+`/`-` sur des montants (vérifier l'absence de `parseFloat` et de `Number(` sur les champs `montants`) ; `api/tableauDeBord.ts` contient `"/api/tableau-de-bord"` et `components["schemas"]["TableauDeBordReponse"]`.
- [ ] **Step 2: Lancer** → FAIL. **Step 3: Implémenter.** **Step 4: Lancer** contrat, typecheck, build → PASS.
- [ ] **Step 5: Vérification visuelle** sur l'instance démo (build déployé localement ou `npm run dev` pointé sur la base de démo) : captures 1440 / 375, mois 2026-09 et un mois vide ; comparer à la maquette `Main`.
- [ ] **Step 6: Commit** `web: vue d'ensemble`.

---

### Task 6: À régler

**Files:**
- Create: `web/src/pages/ARegler.tsx`, `web/src/pages/ProblemeDetail.tsx` (panneau à droite en `lg+`, page plein écran `/a-regler/:id` en dessous), `tests/test_web_a_regler.py`
- Modify: `web/src/App.tsx` (`/a-regler`, `/a-regler/:id`), `web/src/components/Gabarit.tsx` (pastille du compte)
- Delete (une fois migré et contrats mis à jour) : `web/src/pages/Anomalies.tsx` ; `web/src/pages/ATraiter.tsx` si tout son contenu est repris

**Interfaces:**
- Consumes: `GET /api/anomalies` (filtres existants `statut`, `regle`…), `POST /api/anomalies/{id}/traitement` (existant : `statut` `traitee`/`ignoree` + `commentaire`), `GET /api/a-traiter` (documents à vérifier, alias et articles en attente — réutiliser les appels et composants existants d'`ATraiter.tsx`, `AliasCarte`), `libelles.ts`.

Contenu (maquette `ARegler`) : `EnTetePage` (surtitre « N problèmes ouverts · M urgents », titre « À régler ») ; `Filtres` : Tous, Urgents, BL manquants (`categorieProbleme == "bl"`), Prix, Quantités, À rattacher (R14 + alias en attente), Bons illisibles (documents « à vérifier »), Déjà réglés (`statut` traitee/ignoree) — filtre dans l'URL `?filtre=` ; liste : pastille d'urgence, titre, phrase, contexte (chantier · fournisseur · n° BL), montant en jeu à droite ; les documents « à vérifier » apparaissent comme « Bon illisible à corriger » (lien vers `/bl/:id` section correction) et les alias comme « Chantier à rattacher » (réutiliser `AliasCarte` dans le détail) ; détail : « Pourquoi c'est signalé » (valeurs de `detail` présentées en 2–3 chiffres nommés, via une fonction `chiffresProbleme(a): {libelle, valeur, ton?}[]` ajoutée à `libelles.ts`), liens « Voir la facture » (`/documents/:document_id`) et « Voir le bon de livraison » (`/bl/:bl_document_id`), `<label>` « Commentaire (obligatoire) » + `<textarea>`, boutons « Contesté auprès du fournisseur » (traitee) et « C'est normal, ignorer » (ignoree), désactivés tant que le commentaire est vide ; après succès, invalider `anomalies`, `tableau-de-bord`, `bilan` et passer au problème suivant.

- [ ] **Step 1: Contrat (échoue)** : libellés exacts des filtres et boutons ci-dessus, `Commentaire (obligatoire)`, `aria-pressed`, invalidation de `CLE_TABLEAU_DE_BORD` (exportée par `api/tableauDeBord.ts` — si la Task 5 n'est pas encore fusionnée, créer ici `api/tableauDeBord.ts` avec seulement la clé et laisser la Task 5 compléter), absence de `R0` dans les chaînes JSX affichées, `useSearchParams`, route `a-regler/:id`.
- [ ] **Step 2–4:** FAIL → implémenter → PASS (contrat, typecheck, build, suite).
- [ ] **Step 5: Vérification visuelle** démo : liste, détail, traitement d'une anomalie fictive, 1440 et 375 (détail plein écran).
- [ ] **Step 6: Commit** `web: écran À régler`.

---

### Task 7: Chantiers et fiche chantier

**Files:**
- Create: `web/src/pages/ChantiersListe.tsx`, `web/src/pages/FicheChantier.tsx`, `tests/test_web_chantiers.py`
- Modify: `web/src/api/referentiels.ts` (`modifierChantier`, `client` dans la création), `web/src/App.tsx`
- Delete après reprise : `web/src/pages/Bilan.tsx`, `web/src/pages/Chantiers.tsx` (contenu repris : création, agences, alias, activité, chantiers silencieux)

**Interfaces:**
- Consumes: `GET /api/bilan/chantiers?mois&agence` (+ `client`, Task 1), `GET /api/bilan/chantiers/{id}/fournisseurs`, `GET /api/bilan/chantiers/{id}/fournisseurs/{f}/bl` (lignes de livraison), `GET /api/anomalies?chantier_id=`, `POST /api/chantiers`, `PUT /api/chantiers/{id}`, `GET /api/referentiels/chantiers-silencieux`, `GET /api/referentiels/agences`, exports CSV existants.

Liste : `EnTetePage` « Chantiers » avec « Nouveau chantier » ; filtres mois (optionnel, « Tous les mois » par défaut) et agence ; tableau identique à la vue d'ensemble (sans état calculé : pastille dérivée côté serveur absente ici → afficher « Problèmes » et « À vérifier » ; si l'état est souhaité, appeler `/api/tableau-de-bord` quand un mois est choisi) ; bandeau « Chantiers sans bon déposé depuis 7 jours » (silencieux) ; formulaire de création (nom, client, agence). Fiche (maquette `FicheChantier`) : `FilAriane` Chantiers › nom ; en-tête (nom, « Client : … », « Agence : … », « Dernier BL déposé : … », bouton « Modifier » ouvrant un formulaire nom/client/agence/actif → `PUT`) ; quatre `Chiffre` (Facturé, Conforme = rapproché − en écart **fourni par le serveur** : utiliser `/api/tableau-de-bord` pour le mois choisi, sinon n'afficher que Facturé / Écart / Sans bon) ; carte « Livraisons » : toutes les lignes BL de tous les fournisseurs du chantier (date, n° BL, fournisseur, état du bon « Reçu », « Jamais reçu », « Livré sans bon », montant, problèmes), chaque ligne → `/bl/:bl_document_id` si présent, sinon vers la facture `/documents/:facture_id` ; carte « Problèmes ouverts · N » ; liens « Voir les documents du chantier » (`/documents?chantier=id`) et « Exporter pour Excel ».

- [ ] **Step 1: Contrat (échoue)** : `"Client :"`, `"Nouveau chantier"`, `"Modifier"`, `"Livraisons"`, `"Problèmes ouverts"`, `modifierChantier`, `'"PUT"'`, lien `` `/bl/${`` , `md:hidden`, `FilAriane`.
- [ ] **Step 2–4:** FAIL → implémenter → PASS.
- [ ] **Step 5: Vérification visuelle** démo (Villa des Tilleuls) 1440/375 ; modification du client d'un chantier fictif.
- [ ] **Step 6: Commit** `web: chantiers et fiche chantier`.

---

### Task 8: Page BL et Documents

**Files:**
- Create: `web/src/pages/PageBl.tsx`, `web/src/pages/DocumentsListe.tsx`, `tests/test_web_documents.py`
- Modify: `web/src/api/documents.ts` (`obtenirComparaisonBl`, `urlTelechargement(id)`), `web/src/pages/FactureDetail.tsx` et `web/src/pages/DocumentDetail.tsx` (habillage et vocabulaire ; la logique de correction existante est conservée et montée depuis `PageBl` via une section « Corriger la lecture du bon »), `web/src/App.tsx`
- Delete après reprise : `web/src/pages/FacturesListe.tsx`, `web/src/pages/BlDeposes.tsx`

**Interfaces:**
- Consumes: `GET /api/documents/{id}`, `GET /api/documents/{id}/fichier` (+ `?telechargement=true`, Task 3), `GET /api/documents/{id}/comparaison` (Task 3, admin), `GET /api/documents`, `GET /api/factures`, `POST /api/factures`, `GET /api/factures/{id}`.

Page BL (maquette `BL`) : `FilAriane` Chantiers › chantier › n° BL ; titre « Bon de livraison {numero} », « Livré le … · fournisseur · chantier » ; pastille ; à gauche l'image (`<img src="/api/documents/{id}/fichier" alt="Photo du bon de livraison {numero}">`, PDF → lien) + boutons « Télécharger la photo » (`<a href=urlTelechargement(id) download>`) et « Ouvrir en grand » (`target="_blank"`), « Déposé par … via Telegram, le … à … », « Quantités vérifiées par l'équipe : oui / écart signalé / pas encore » ; à droite (admin) « Livré et facturé » : colonnes Article, Livré, Facturé, Prix unit., Contrôle (`titreRegle` des `regles_ouvertes` ou « Conforme »), « Montant facturé pour ce bon », liens « Voir la facture » et « Régler les N problèmes » (`/a-regler?document=`) ; section repliable « Corriger la lecture du bon » = formulaire de correction existant de `DocumentDetail`. Agent : image, téléchargement, statut de confirmation, pas de comparaison. Documents : `Filtres` Tous / Factures / Bons de livraison / À corriger ; filtres mois, chantier (`?chantier=`) ; liste en tableau/cartes ; dépôt de facture PDF (admin, reprise de `FacturesListe`) ; détail facture (`/documents/:id` quand le type est facture) présente les blocs comme « livraisons ».

- [ ] **Step 1: Contrat (échoue)** : `"Télécharger la photo"`, `download`, `urlTelechargement`, `"telechargement=true"`, `"Livré et facturé"`, `"Corriger la lecture du bon"`, `"Quantités vérifiées par l'équipe"`, `"Bons de livraison"`, `"À corriger"`, `alt="Photo du bon de livraison`, `obtenirComparaisonBl`, `'"/comparaison"'` ou chemin équivalent.
- [ ] **Step 2–4:** FAIL → implémenter → PASS.
- [ ] **Step 5: Vérification visuelle** : téléchargement effectif (en-tête `attachment` vérifié avec `curl -I`), page BL 1440/375, en admin et en agent.
- [ ] **Step 6: Commit** `web: page BL et documents`.

---

### Task 9: Fournisseurs

**Files:**
- Create: `web/src/pages/FournisseursListe.tsx`, `web/src/pages/FicheFournisseur.tsx`, `tests/test_web_fournisseurs.py`
- Delete après reprise : `web/src/pages/BilanFournisseur.tsx`

**Interfaces:**
- Consumes: `GET /api/bilan/fournisseurs?mois`, `GET /api/bilan/fournisseurs/{id}/chantiers`, `GET /api/fournisseurs` (agences), `GET /api/anomalies?fournisseur_id=`, exports CSV fournisseurs existants.

Liste : tableau/cartes (Fournisseur, Facturé, Écart, Sans bon, Problèmes) ; fiche : `FilAriane`, trois `Chiffre`, « Chantiers concernés » (liens `/chantiers/:id`), « Problèmes ouverts » (liens `/a-regler/:id`), agences connues, export.

- [ ] **Step 1: Contrat (échoue)** : `"Chantiers concernés"`, `"Problèmes ouverts"`, `FilAriane`, `md:hidden`, liens `` `/chantiers/${`` et `` `/a-regler/${``.
- [ ] **Step 2–4:** FAIL → implémenter → PASS. **Step 5:** captures 1440/375. **Step 6: Commit** `web: fournisseurs`.

---

### Task 10: Réglages et Journal à la charte

**Files:**
- Modify: `web/src/pages/Reglages.tsx`, `web/src/pages/Journal.tsx`, `web/src/lib/journal.ts` (libellés d'action en français courant : `chantier_modifie` « Chantier modifié », etc.), `tests/test_web_reglages.py`, nouveau `tests/test_web_journal.py`

Contenu inchangé, habillage `ui/` (Carte, EnTetePage, Bouton, Filtres), libellés sans jargon (« Seuil de tolérance de prix » plutôt que la clé technique ; les libellés viennent déjà du serveur via `ingest/parametres.py`), tableaux en cartes sous `md`. Ajouter le libellé `chantier_modifie` dans `lib/journal.ts`.

- [ ] **Step 1: Contrat (échoue)** : `EnTetePage` utilisé dans les deux pages, `"Chantier modifié"` dans `lib/journal.ts`, `md:hidden` dans `Journal.tsx`.
- [ ] **Step 2–4:** FAIL → implémenter → PASS. **Step 5:** captures. **Step 6: Commit** `web: réglages et journal à la charte`.

---

### Task 11: Recette, déploiement et passation

**Files:**
- Modify: `docs/deploiement-et-tests.md` (§1.1 : migration 0010), `docs/dette.md`, `CLAUDE.md` (« Où en est le projet »)
- Create: `docs/refonte-front-recette.md`

- [ ] **Step 1:** Revue de l'ensemble de la branche (`main..HEAD`) par un relecteur indépendant, découpée en périmètres (serveur ; socle + navigation ; écrans) ; corriger les constats bloquants.
- [ ] **Step 2:** Suite complète, Ruff, format, mypy, typecheck, build → tout vert ; consigner les sorties réelles dans `docs/refonte-front-recette.md`.
- [ ] **Step 3:** Déployer sur les deux instances : `C="-f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml"` ; pour `i` dans `demo prod` : `docker compose -p habitat_$i --env-file .env.$i $C build api`, `stop api`, `run --rm -T api alembic upgrade head`, `up -d --wait api` ; `curl https://habitat.ellumena.fr/health` et `https://demo.habitat.ellumena.fr/health`.
- [ ] **Step 4:** Recette navigateur sur la démo (données fictives uniquement pour les captures) : parcours Vue d'ensemble → À régler (traiter une anomalie) → Chantiers → fiche → page BL (télécharger) → Documents → Fournisseurs → Réglages → Journal, à 1440 et 375 ; connexion agent (seulement Documents) ; anciennes URL redirigées. Captures sous `var/captures/refonte/` (hors dépôt).
- [ ] **Step 5:** Sur la production, vérifier seulement que les écrans s'ouvrent avec les données d'août (aucune capture, aucune donnée client recopiée).
- [ ] **Step 6: Commit** `docs: recette de la refonte du front`.
