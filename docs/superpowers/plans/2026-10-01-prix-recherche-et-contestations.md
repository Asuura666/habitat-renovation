# Recherche internet à la demande et contestations de prix — plan de réalisation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Méthode choisie par Ilane (01/10/2026) :** pas de relecture par tâche ;
> une seule relecture complète de la branche à la fin.

**Goal:** Sur l'onglet Prix, un bouton lance la recherche internet d'un produit ; les contestations de prix apparaissent dans la grille du fournisseur et dans le résumé de la semaine.

**Architecture:** Tout le métier dans `app/modules/ingest` : un nouveau module `contestations_prix.py` lit les contestations (alertes de prix `traitee` au commentaire « Contesté : … ») pour la grille et pour la synthèse ; `ia_prix.py` gagne une recherche à la demande en tâche de fond (`BackgroundTasks`, état en mémoire, même mécanique que le Laboratoire IA) ; `ia_synthese.py` envoie aussi les contestations (`pN`). Les routeurs `api/grilles.py` et `api/ia.py` valident, appellent, sérialisent. Le front (`GrilleFournisseur.tsx`, `Prix.tsx`, `PrixInternetCellule.tsx`, `SyntheseCommentaires.tsx`) affiche.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL 18, pytest ; React 18 + TypeScript + TanStack Query + Tailwind ; openapi-typescript.

**Spec:** `docs/superpowers/specs/2026-10-01-prix-recherche-et-contestations-design.md`

## Global Constraints

- Travailler dans `/home/debian/habitat_reno-ia`, branche `feature/prix-contestations-recherche` ; jamais sur `main` ni `dev`.
- Frontières (`tests/test_frontieres.py`) : `extract`, `normalize`, `rules` n'importent ni FastAPI, ni SQLAlchemy, ni httpx ; `api` n'importe que `app.core` et `app.modules.ingest`. Aucune règle métier dans le front ni dans les routeurs.
- L'IA ne décide rien : aucun prix internet ni aucune synthèse ne crée, ne ferme ou ne modifie une anomalie ou une grille.
- Une tâche = un commit, message en français préfixé du module (ex. `ingest: contestations de prix lues pour la grille`), terminé par les deux lignes d'attribution données par le contrôleur.
- Tests avant ou avec le code. Avant chaque commit : `uv run ruff check`, `uv run ruff format --check`, `uv run mypy` ; tests lancés sous le verrou commun : `flock /tmp/habitat_reno-tests.lock uv run pytest <fichiers> -q`. Le hook de commit relance toute la suite (10 à 25 min) : attendre sa fin, ne jamais utiliser `--no-verify`, ne jamais lancer `pre-commit install`.
- Front : `npm --prefix web run typecheck` et `flock /tmp/habitat_reno-tests.lock npm --prefix web run build`. Types d'API régénérés après tout changement de schéma : `npm --prefix web run api:schema && npm --prefix web run api:types` (commiter `web/openapi.json` et `web/src/api/schema.d.ts`).
- Données : uniquement des valeurs inventées dans les tests (`example.invalid`, « Produit inventé ») ; jamais de fichier de `tests/fixtures/`, jamais de donnée réelle dans un log ou un message.
- Interdits : toute commande `docker`, toute connexion aux bases ou conteneurs `habitat_prod`/`habitat_demo`, ouvrir un `.env*` ou `~/.secrets`, lancer un sous-agent, une boucle d'attente `pgrep -f`.
- Textes visibles en français simple, sans jargon (pas de « R19 » à l'écran : `titreRegle`).

## Review Focus

1. Double clic ou deux admins sur le même produit → une seule recherche (`deja_en_cours`) — test en tâche 5.
2. Recherche en tâche de fond qui plante de façon imprévue → l'état ne reste jamais « en cours » (passe en `echec`) — test en tâche 5.
3. Produit contesté puis retiré de la grille → listé dans la section avec « absent de la grille », plus rattaché à une rangée — test en tâche 1.
4. Contestation faite un dimanche à 23 h 30 (heure de Paris) → dans la synthèse de cette semaine-là, pas de la suivante — test en tâche 4.
5. Rangée dont la seule alerte est R25 (ni `prix_bon` ni `unite_bon`) → la contestation s'affiche sans prix et la recherche marche sans unité — tests en tâches 1 et 5.

---

### Task 1: Lecture des contestations (`ingest/contestations_prix.py`)

**Files:**
- Create: `app/modules/ingest/contestations_prix.py`
- Modify: `app/modules/ingest/prix_bl.py` (constante `PREFIXE_CONTESTATION`, fonction publique `cle_produit_alerte`)
- Test: `app/modules/ingest/tests/test_contestations_prix.py`

**Interfaces:**
- Produces:
  - `prix_bl.PREFIXE_CONTESTATION: str = "Contesté : "` (utilisé par `contester_prix`).
  - `prix_bl.cle_produit_alerte(ligne: Ligne, anomalies: Sequence[Anomalie]) -> str` (corps actuel de `_cle_groupe`, qui l'appelle désormais).
  - `contestations_prix.Contestation` (dataclass gelée) : `conteste_le: datetime`, `auteur: str | None`, `fournisseur_id: uuid.UUID`, `fournisseur_nom: str`, `document_id: uuid.UUID`, `numero_bon: str | None`, `date_bon: date | None`, `produit: str`, `code: str | None`, `prix_bon: Decimal | None`, `unite_bon: str | None`, `prix_grille: Decimal | None`, `regles: tuple[str, ...]`, `commentaire: str`, `cle_produit: str`, `dans_la_grille: bool = False`.
  - `contestations_prix.CONTESTATIONS_MAX = 500`.
  - `async charger_contestations(session, *, fournisseur_id: uuid.UUID | None = None, depuis: datetime | None = None, avant: datetime | None = None, limite: int = CONTESTATIONS_MAX) -> list[Contestation]` — plus récentes d'abord, `dans_la_grille` toujours `False`.
  - `async contestations_du_fournisseur(session, fournisseur_id: uuid.UUID) -> list[Contestation]` — `FournisseurIntrouvable` (de `ingest.grilles`) si le fournisseur n'existe pas ; `dans_la_grille` renseigné.

- [ ] **Step 1: Refactor `prix_bl.py` (comportement inchangé)**

Juste avant `contester_prix`, ajouter la constante et l'utiliser :

```python
# Préfixe du commentaire d'une alerte contestée (spec 2026-10-01 §4.1) :
# seul marqueur d'une contestation, relu par `ingest.contestations_prix`.
PREFIXE_CONTESTATION = "Contesté : "
```

et dans `contester_prix` : `commentaire=f"{PREFIXE_CONTESTATION}{commentaire_normalise}",`.

Remplacer `_cle_groupe` par une fonction publique et un appel :

```python
def cle_produit_alerte(ligne: Ligne, anomalies: Sequence[Anomalie]) -> str:
    """<reprendre mot pour mot la docstring actuelle de `_cle_groupe`>
    Publique (spec 2026-10-01 §4.1) : aussi la clé d'une contestation,
    relue par `ingest.contestations_prix`."""
    for anomalie in anomalies:
        if anomalie.regle in _REGLES_GRILLE:
            designation_grille = anomalie.detail.get("designation_grille")
            if designation_grille:
                methode = anomalie.detail.get("methode")
                code = anomalie.detail.get("code")
                reference = code if methode == "reference" and code != _TIRET else None
                return cle_produit(reference, str(designation_grille))
    return cle_produit(ligne.code_brut, ligne.article_brut)


def _cle_groupe(ligne_alerte: _LigneAlerte) -> str:
    return cle_produit_alerte(ligne_alerte.ligne, ligne_alerte.anomalies)
```

- [ ] **Step 2: Write the failing tests**

`app/modules/ingest/tests/test_contestations_prix.py` (marqueurs `pytestmark = [pytest.mark.anyio, pytest.mark.db]`). Réutiliser les aides de `app/modules/ingest/tests/test_prix_page.py` (import direct, comme `test_conforme_strict.py` le fait avec `test_bilan`) : `_creer_fournisseur`, `_creer_utilisateur`, `_creer_bl`, `_creer_ligne`, `_creer_prix_grille`, `_activer_controle`, `_controler`, `_anomalies_ouvertes_du_bon`. Ajouter une aide locale qui crée une anomalie déjà fermée :

```python
async def _creer_anomalie_fermee(
    db_session: AsyncSession,
    *,
    document: Document,
    ligne: Ligne,
    regle: str = "R19",
    statut: str = "traitee",
    commentaire: str = "Contesté : prix négocié inventé",
    traitee_par: uuid.UUID | None = None,
    traitee_le: datetime = datetime(2026, 9, 30, 10, 0, tzinfo=UTC),
    detail: dict[str, str] | None = None,
) -> Anomalie:
    anomalie = Anomalie(
        regle=regle,
        gravite="haute",
        document_id=document.id,
        ligne_id=ligne.id,
        detail=detail
        if detail is not None
        else {
            "produit": "Produit inventé",
            "code": "REF1",
            "prix_bon": "12.00",
            "unite_bon": "u",
            "prix_grille": "10.00",
            "designation_grille": "Produit inventé",
            "methode": "reference",
        },
        statut=statut,
        commentaire=commentaire,
        traitee_par=traitee_par,
        traitee_le=traitee_le,
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)
    return anomalie
```

Tests à écrire (un `async def test_...` chacun, assertions explicites) :

1. `test_contestation_reelle_visible_dans_la_grille` — flux réel : grille `REF1` à 10.00, bon à 12.00 (`_creer_ligne(pu_ht=Decimal("12.00"))`), `_activer_controle`, `_controler`, puis `contester_prix(session, anomalie_ids=[ids ouverts], commentaire="Remise oubliée inventée", auteur_id=utilisateur.id)`. `contestations_du_fournisseur` rend 1 élément : `commentaire == "Remise oubliée inventée"` (sans préfixe), `dans_la_grille is True`, `cle_produit == cle_produit("REF1", "Produit inventé")`, `prix_bon == Decimal("12.00")`, `prix_grille == Decimal("10.00")` (ou la valeur exacte écrite par R19), `auteur == utilisateur.email` (pas de `nom`), `numero_bon == document.numero`, `"R19" in regles`.
2. `test_ignoree_et_validee_exclues` — anomalies `ignoree` (« Ignoré depuis la page Prix ») et `traitee` au commentaire « Prix validé … » → liste vide.
3. `test_regle_hors_prix_exclue` — anomalie `traitee`, commentaire « Contesté : … », `regle="R01"` → exclue.
4. `test_deux_regles_meme_ligne_une_seule_contestation` — R19 et R20 sur la même ligne, même commentaire → 1 élément, `regles == ("R19", "R20")`.
5. `test_bon_archive_exclu` — `document.statut = "archive"` → exclue.
6. `test_autre_fournisseur_exclu` — contestation d'un autre fournisseur → absente.
7. `test_produit_retire_absent_de_la_grille` (Review Focus 3) — produit `REF1` en grille puis ligne `retire` (`GrillePrix` avec `retire=True` ou la marque de retrait utilisée par `ingest.grilles.retirer_produit` — appeler `retirer_produit` directement) → `dans_la_grille is False`.
8. `test_r25_seule_sans_prix_du_bon` (Review Focus 5) — détail R25 `{"produit": "Produit inventé", "code": "REF1", "prix_grille": "10.00", "date_grille": "2025-01-01", "age_mois": "20"}` → `prix_bon is None`, `unite_bon is None`, `prix_grille == Decimal("10.00")`.
9. `test_ordre_et_limite` — trois contestations à des `traitee_le` différents → plus récente d'abord ; `charger_contestations(..., limite=2)` rend 2 éléments.
10. `test_bornes_depuis_avant` — `charger_contestations(depuis=..., avant=...)` exclut une contestation à `avant` exactement et inclut une à `depuis` exactement.
11. `test_fournisseur_inconnu` — `contestations_du_fournisseur(session, uuid.uuid4())` lève `FournisseurIntrouvable`.
12. `test_auteur_nom_prefere_a_email` — utilisateur avec `nom="Admin inventé"` → `auteur == "Admin inventé"`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `flock /tmp/habitat_reno-tests.lock uv run pytest app/modules/ingest/tests/test_contestations_prix.py -q`
Expected: FAIL (`ModuleNotFoundError: app.modules.ingest.contestations_prix`).

- [ ] **Step 4: Write `contestations_prix.py`**

```python
"""Contestations de prix (spec 2026-10-01 §4 et §5) : lecture des alertes de
prix contestées depuis la page Prix (`ingest.prix_bl.contester_prix`), pour
la grille du fournisseur (`contestations_du_fournisseur`) et pour la synthèse
de la semaine (`charger_contestations`, appelée par `ingest.ia_synthese`).

Aucune table propre : une contestation est une alerte de prix (R19-R25)
`traitee` dont le commentaire commence par `PREFIXE_CONTESTATION`, sur un bon
non archivé ; une ligne de bon et un commentaire donnent une seule
contestation (R19 et R20 contestées ensemble n'en font qu'une)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.grilles import FournisseurIntrouvable, prix_en_vigueur
from app.modules.ingest.models import (
    Anomalie,
    Document,
    Fournisseur,
    Ligne,
    Utilisateur,
)
from app.modules.ingest.prix_bl import PREFIXE_CONTESTATION, cle_produit_alerte
from app.modules.rules.engine import REGLES_PRIX_BL

CONTESTATIONS_MAX = 500
_TIRET = "—"


@dataclass(frozen=True)
class Contestation:
    """Une contestation (une ligne de bon) -- `dans_la_grille` n'est
    renseigné que par `contestations_du_fournisseur`."""

    conteste_le: datetime
    auteur: str | None
    fournisseur_id: uuid.UUID
    fournisseur_nom: str
    document_id: uuid.UUID
    numero_bon: str | None
    date_bon: date | None
    produit: str
    code: str | None
    prix_bon: Decimal | None
    unite_bon: str | None
    prix_grille: Decimal | None
    regles: tuple[str, ...]
    commentaire: str
    cle_produit: str
    dans_la_grille: bool = False


def _texte_utile(valeur: Any) -> str | None:
    if not isinstance(valeur, str):
        return None
    nettoyee = valeur.strip()
    if not nettoyee or nettoyee == _TIRET:
        return None
    return nettoyee


def _premiere_valeur(anomalies: tuple[Anomalie, ...], cle: str) -> str | None:
    for anomalie in anomalies:
        valeur = _texte_utile(anomalie.detail.get(cle))
        if valeur is not None:
            return valeur
    return None


def _decimal_ou_aucun(valeur: str | None) -> Decimal | None:
    if valeur is None:
        return None
    try:
        return Decimal(valeur)
    except InvalidOperation:
        return None


async def charger_contestations(
    session: AsyncSession,
    *,
    fournisseur_id: uuid.UUID | None = None,
    depuis: datetime | None = None,
    avant: datetime | None = None,
    limite: int = CONTESTATIONS_MAX,
) -> list[Contestation]:
    """Contestations, plus récentes d'abord (`traitee_le` décroissant),
    `limite` au plus -- filtrées par fournisseur et/ou par date de
    contestation (`depuis` inclus, `avant` exclu)."""
    conditions = [
        Anomalie.statut == "traitee",
        Anomalie.regle.in_(tuple(REGLES_PRIX_BL)),
        Anomalie.commentaire.startswith(PREFIXE_CONTESTATION, autoescape=True),
        Anomalie.ligne_id.is_not(None),
        Anomalie.traitee_le.is_not(None),
        Document.statut != "archive",
    ]
    if fournisseur_id is not None:
        conditions.append(Document.fournisseur_id == fournisseur_id)
    if depuis is not None:
        conditions.append(Anomalie.traitee_le >= depuis)
    if avant is not None:
        conditions.append(Anomalie.traitee_le < avant)

    resultat = await session.execute(
        select(
            Anomalie,
            Ligne,
            Document,
            Fournisseur.nom,
            Utilisateur.nom,
            Utilisateur.email,
        )
        .join(Ligne, Ligne.id == Anomalie.ligne_id)
        .join(Document, Document.id == Anomalie.document_id)
        .join(Fournisseur, Fournisseur.id == Document.fournisseur_id)
        .outerjoin(Utilisateur, Utilisateur.id == Anomalie.traitee_par)
        .where(*conditions)
        .order_by(Anomalie.traitee_le.desc(), Anomalie.id)
    )

    groupes: dict[tuple[uuid.UUID, str], list[Any]] = {}
    for rangee in resultat.all():
        anomalie, ligne = rangee[0], rangee[1]
        groupes.setdefault((ligne.id, anomalie.commentaire or ""), []).append(rangee)

    contestations: list[Contestation] = []
    for rangees in list(groupes.values())[:limite]:
        anomalies = tuple(r[0] for r in rangees)
        plus_recente, ligne, document, fournisseur_nom, auteur_nom, auteur_email = (
            rangees[0]
        )
        assert plus_recente.traitee_le is not None  # garanti par la requête
        assert document.fournisseur_id is not None  # jointure interne
        contestations.append(
            Contestation(
                conteste_le=plus_recente.traitee_le,
                auteur=auteur_nom or auteur_email,
                fournisseur_id=document.fournisseur_id,
                fournisseur_nom=fournisseur_nom,
                document_id=document.id,
                numero_bon=document.numero,
                date_bon=document.date_doc,
                produit=_premiere_valeur(anomalies, "produit")
                or ligne.article_brut
                or _TIRET,
                code=_premiere_valeur(anomalies, "code"),
                prix_bon=_decimal_ou_aucun(_premiere_valeur(anomalies, "prix_bon")),
                unite_bon=_premiere_valeur(anomalies, "unite_bon"),
                prix_grille=_decimal_ou_aucun(
                    _premiere_valeur(anomalies, "prix_grille")
                ),
                regles=tuple(sorted({a.regle for a in anomalies})),
                commentaire=(plus_recente.commentaire or "").removeprefix(
                    PREFIXE_CONTESTATION
                ),
                cle_produit=cle_produit_alerte(ligne, anomalies),
            )
        )
    return contestations


async def contestations_du_fournisseur(
    session: AsyncSession, fournisseur_id: uuid.UUID
) -> list[Contestation]:
    """Contestations d'un fournisseur pour sa grille (spec 2026-10-01 §4.1) :
    `dans_la_grille` vaut vrai si la clé produit correspond à un produit
    actuellement dans sa grille (un produit retiré n'y est plus)."""
    if await session.get(Fournisseur, fournisseur_id) is None:
        raise FournisseurIntrouvable(str(fournisseur_id))
    contestations = await charger_contestations(session, fournisseur_id=fournisseur_id)
    if not contestations:
        return []
    en_vigueur = await prix_en_vigueur(
        session,
        fournisseur_id,
        datetime.now(FUSEAU_PARIS).date(),
        cles={c.cle_produit for c in contestations},
    )
    return [
        replace(c, dans_la_grille=c.cle_produit in en_vigueur) for c in contestations
    ]
```

Si `mypy` refuse le dépaquetage typé des rangées, typer `rangees` en `list[Row[...]]` ou extraire les colonnes par index ; garder la logique.

- [ ] **Step 5: Run tests to verify they pass**

Run: `flock /tmp/habitat_reno-tests.lock uv run pytest app/modules/ingest/tests/test_contestations_prix.py app/modules/ingest/tests/test_prix_page.py -q`
Expected: PASS. Puis `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`.

- [ ] **Step 6: Commit**

```bash
git add app/modules/ingest/contestations_prix.py app/modules/ingest/prix_bl.py app/modules/ingest/tests/test_contestations_prix.py
git commit -F <fichier message>   # « ingest: contestations de prix lues pour la grille et la synthèse »
```

---

### Task 2: Route `GET /api/grilles/fournisseurs/{id}/contestations`

**Files:**
- Modify: `app/modules/api/schemas.py` (nouveau `ContestationReponse`, après `LigneHistoriqueReponse`)
- Modify: `app/modules/api/grilles.py`
- Test: `app/modules/api/tests/test_grilles.py`

**Interfaces:**
- Consumes: `contestations_prix.contestations_du_fournisseur`, `Contestation` (Task 1).
- Produces: `GET /api/grilles/fournisseurs/{fournisseur_id}/contestations` → `list[ContestationReponse]` (admin ; 404 « fournisseur introuvable » comme les autres routes du fichier).

- [ ] **Step 1: Write the failing tests** (dans `app/modules/api/tests/test_grilles.py`, mêmes fixtures de client admin/agent que les tests existants du fichier) :
  - admin, fournisseur avec une contestation créée en base (même aide `_creer_anomalie_fermee` que Task 1, recopiée localement ou importée de `test_contestations_prix`) → 200, un élément avec `commentaire`, `numero_bon`, `dans_la_grille`, `regles` (liste), `prix_bon` en texte décimal ;
  - fournisseur sans contestation → 200, `[]` ;
  - fournisseur inconnu → 404 ;
  - compte non admin → 403 (même attente que les autres routes `grilles`).
- [ ] **Step 2: Run tests to verify they fail** — `flock /tmp/habitat_reno-tests.lock uv run pytest app/modules/api/tests/test_grilles.py -q` → FAIL (404 sur la route).
- [ ] **Step 3: Implement**

`schemas.py` :

```python
class ContestationReponse(BaseModel):
    """`GET /api/grilles/fournisseurs/{id}/contestations` -- mêmes attributs
    qu'`ingest.contestations_prix.Contestation` (sans le fournisseur, déjà
    connu de l'écran)."""

    model_config = ConfigDict(from_attributes=True)

    conteste_le: datetime
    auteur: str | None
    document_id: uuid.UUID
    numero_bon: str | None
    date_bon: date | None
    produit: str
    code: str | None
    prix_bon: Decimal | None
    unite_bon: str | None
    prix_grille: Decimal | None
    regles: list[str]
    commentaire: str
    cle_produit: str
    dans_la_grille: bool
```

`grilles.py` (docstring du module : ajouter la route) :

```python
@router.get(
    "/grilles/fournisseurs/{fournisseur_id}/contestations",
    response_model=list[ContestationReponse],
)
async def contestations_fournisseur_endpoint(
    fournisseur_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ContestationReponse]:
    del utilisateur
    try:
        contestations = await contestations_du_fournisseur(session, fournisseur_id)
    except FournisseurIntrouvable as exc:
        raise _erreur_fournisseur_introuvable() from exc
    return [ContestationReponse.model_validate(c) for c in contestations]
```

- [ ] **Step 4: Run tests to verify they pass** + ruff, format, mypy ; `uv run pytest tests/test_frontieres.py -q`.
- [ ] **Step 5: Régénérer les types** — `npm --prefix web run api:schema && npm --prefix web run api:types`.
- [ ] **Step 6: Commit** — `api: contestations de prix d'un fournisseur` (avec `web/openapi.json`, `web/src/api/schema.d.ts`).

---

### Task 3: Écran grille — contestations sur la rangée et section

**Files:**
- Modify: `web/src/api/grilles.ts`
- Modify: `web/src/pages/GrilleFournisseur.tsx`

**Interfaces:**
- Consumes: `ContestationReponse` (Task 2, `components["schemas"]["ContestationReponse"]`).
- Produces: rien pour les autres tâches.

- [ ] **Step 1: Client d'API** (`web/src/api/grilles.ts`, même forme qu'`obtenirGrilleFournisseur`) :

```ts
export type ContestationPrix = components["schemas"]["ContestationReponse"];

/** Clé de requête : sous `["grille", fournisseurId]`, donc rafraîchie par
 * les invalidations déjà faites après un import ou un retrait. */
export function cleContestations(fournisseurId: string): readonly [string, string, string] {
  return ["grille", fournisseurId, "contestations"] as const;
}

/** `GET /api/grilles/fournisseurs/{id}/contestations` (admin) : les prix
 * contestés depuis la page Prix, plus récents d'abord. */
export function listerContestations(fournisseurId: string): Promise<ContestationPrix[]> {
  return appelerApi<ContestationPrix[]>(`/api/grilles/fournisseurs/${fournisseurId}/contestations`);
}
```

(adapter l'appel à la signature réelle d'`appelerApi` utilisée par `obtenirGrilleFournisseur`.)

- [ ] **Step 2: Composants** dans `GrilleFournisseur.tsx` :

```tsx
/** Historique des contestations d'un produit (spec 2026-10-01 §4.2) :
 * date · bon (lien) · prix du bon · auteur, puis le commentaire. */
function HistoriqueContestations({ contestations }: { contestations: readonly ContestationPrix[] }): ReactElement {
  return (
    <ul className="space-y-2 text-sm">
      {contestations.map((c) => (
        <li key={`${c.document_id}-${c.conteste_le}`} className="border-l-2 border-bordure pl-3">
          <p className="text-encre-2">
            {formaterDate(c.conteste_le)} · bon{" "}
            <Link to={<même chemin que le lien « Voir le bon » de la page Prix>} className="font-medium text-accent underline">
              {c.numero_bon ?? "sans numéro"}
            </Link>
            {c.prix_bon !== null && <> · {formaterMontant(c.prix_bon)}{c.unite_bon !== null ? ` / ${c.unite_bon}` : ""}</>}
            {c.prix_grille !== null && <> · grille {formaterMontant(c.prix_grille)}</>}
            {c.auteur !== null && <> · {c.auteur}</>}
          </p>
          <p className="text-encre">« {c.commentaire} »</p>
          <p className="text-xs text-encre-2">{c.regles.map(titreRegle).join(" · ")}</p>
        </li>
      ))}
    </ul>
  );
}

function texteNbContestations(nombre: number): string {
  return `⚑ ${nombre} contestation${nombre > 1 ? "s" : ""}`;
}
```

- [ ] **Step 3: Brancher dans la page**
  - `const contestations = useQuery({ queryKey: cleContestations(fournisseurId ?? ""), queryFn: () => listerContestations(fournisseurId ?? ""), enabled: fournisseurId !== undefined });`
  - `const contestationsParCle = useMemo(() => { const m = new Map<string, ContestationPrix[]>(); for (const c of contestations.data ?? []) { m.set(c.cle_produit, [...(m.get(c.cle_produit) ?? []), c]); } return m; }, [contestations.data]);`
  - `const [clesDepliees, setClesDepliees] = useState<ReadonlySet<string>>(new Set());` + `basculer(cle)`.
  - **Tableau** : sous la désignation de chaque produit ayant `contestationsParCle.get(produit.cle_produit)`, un bouton-lien (`type="button"`, `aria-expanded`, classes `text-xs font-medium text-accent underline`) `texteNbContestations(n)` + ` ▾`/` ▴`. Chaque produit devient un `<Fragment key=…>` ; si déplié, une seconde rangée `<tr><td colSpan={6} className="bg-fond px-5 py-3"><HistoriqueContestations …/></td></tr>` (liste simple, jamais une grille à colonnes : voir le commentaire existant sur `produitEnEdition`).
  - **Carte téléphone** (`CarteProduit`) : nouvelles props `contestations: readonly ContestationPrix[]`, `deplie: boolean`, `surBasculer: () => void` ; même lien sous la référence, historique sous le `<dl>`.
  - **Section** : entre la `Carte` de la grille et `<SectionImport>`, si `(contestations.data?.length ?? 0) > 0` : `<Carte titre={`Contestations de prix (${n})`}>` ; regrouper par `cle_produit` (ordre : contestation la plus récente d'abord) ; pour chaque groupe, un titre `produit` (+ `code` en petit) et, si `!dans_la_grille`, une pastille « absent de la grille » ; puis `<HistoriqueContestations>`.
  - Erreur de chargement des contestations : un `<p className="text-sm text-alerte">Impossible de charger les contestations.</p>` dans la section, la grille reste affichée.
- [ ] **Step 4: Vérifier** — `npm --prefix web run typecheck` ; `flock /tmp/habitat_reno-tests.lock npm --prefix web run build`.
- [ ] **Step 5: Commit** — `web: contestations de prix dans la grille du fournisseur`.

---

### Task 4: Contestations dans la synthèse de la semaine (migration 0016)

**Files:**
- Create: `migrations/versions/0016_synthese_nb_contestations.py`
- Modify: `app/modules/ingest/models.py` (`SyntheseCommentaires.nb_contestations`)
- Modify: `app/modules/ingest/ia_synthese.py`
- Modify: `app/modules/ingest/ia_labo.py` (`lancer_essai_synthese`)
- Modify: `app/modules/api/schemas.py` (`SyntheseReponse.nb_contestations`), `app/modules/api/ia.py` si la construction est manuelle
- Modify: `deploy/opencode/opencode.json` (consigne `habitat-synthese`)
- Modify: `web/src/components/SyntheseCommentaires.tsx`, `web/src/lib/journal.ts`
- Test: `app/modules/ingest/tests/test_ia_synthese.py`, `app/modules/ingest/tests/test_ia_labo.py`, `tests/test_opencode_config.py` si une phrase y est vérifiée

**Interfaces:**
- Consumes: `contestations_prix.charger_contestations`, `Contestation` (Task 1).
- Produces: `SyntheseVue.nb_contestations: int`, `SyntheseReponse.nb_contestations: int`.

- [ ] **Step 1: Migration** (`revision = "0016"`, `down_revision = "0015"`) :

```python
"""Synthèse de la semaine : nombre de contestations de prix (spec
2026-10-01 §5)."""

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "synthese_commentaires",
        sa.Column("nb_contestations", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("synthese_commentaires", "nb_contestations")
```

(recopier l'en-tête exact — imports, annotations — de `0015_prix_internet_offres.py`.) Modèle : `nb_contestations: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)`.

- [ ] **Step 2: Write the failing tests** (`test_ia_synthese.py`, mêmes aides que le fichier ; pour créer une contestation, réutiliser `_creer_anomalie_fermee` de `test_contestations_prix` avec un document du fournisseur du test) :
  1. `_texte_synthese` avec une `_ContestationEnvoyee` : ligne `[p1] mardi 30/09 — <fournisseur> — produit « … » — bon(s) N1, N2 — prix du bon 12,00 € / u, grille 10,00 € : <commentaire>` ; aucun nom d'auteur dans le texte ; titre « Prix contestés cette semaine : » présent ; phrase de troncature quand `nb_contestations > len(contestations)`.
  2. semaine avec seulement des contestations → l'IA est appelée (transport factice qui répond une synthèse citant `p1`), synthèse `ok`, `nb_commentaires == 0`, `nb_contestations == 1`, l'action a `commentaire_ids == []` et `document_ids == [str(document.id)]`.
  3. semaine sans commentaire ni contestation → `vide`, aucune requête (`_aucune_requete`), résumé `_RESUME_VIDE == "Aucun commentaire ni contestation cette semaine."`.
  4. regroupement : deux bons du même produit contestés avec le même commentaire → une seule entrée `p1` avec deux numéros de bons ; deux commentaires différents → `p1` et `p2`.
  5. bornes (Review Focus 4) : contestation `traitee_le` = dimanche 23 h 30 heure de Paris → dans la semaine de ce dimanche ; lundi 00 h 05 → semaine suivante.
  6. journal `synthese_generee` : `apres["nb_contestations"]` présent (vide et ok).
  7. référence `p9` inexistante citée par l'IA → action écartée par `lire_synthese` (comportement existant, références valides = `cN` ∪ `pN`).
  8. `test_ia_labo.py` : `lancer_essai_synthese` sur une semaine avec seulement une contestation → essai lancé (pas « semaine vide »), texte envoyé contenant `[p1]`.
- [ ] **Step 3: Run tests to verify they fail.**
- [ ] **Step 4: Implement `ia_synthese.py`**

```python
from app.modules.ingest.contestations_prix import Contestation, charger_contestations

_CONTESTATIONS_MAX = 50
_RESUME_VIDE = "Aucun commentaire ni contestation cette semaine."

_CONSIGNE_SYNTHESE = (
    "Voici les commentaires laissés cette semaine par l'équipe sur des "
    "lignes de bons de livraison, puis les prix contestés cette semaine "
    "depuis la page Prix. Résume-les en quelques phrases simples pour le "
    "dirigeant, puis propose au plus dix actions concrètes à mener ; chaque "
    "action cite, sans crochets, les références sur lesquelles elle "
    "s'appuie (c1, c2, ... pour un commentaire ; p1, p2, ... pour une "
    "contestation). Tu ne décides rien : un humain choisira."
)


@dataclass(frozen=True)
class _ContestationEnvoyee:
    """Une contestation telle qu'elle part vers l'IA (spec 2026-10-01 §5) --
    jamais l'auteur, le chantier ni le client."""

    reference: str
    jour: date
    fournisseur: str
    produit: str
    numeros_bons: tuple[str, ...]
    prix_bon: Decimal | None
    unite_bon: str | None
    prix_grille: Decimal | None
    commentaire: str


def _montant(valeur: Decimal) -> str:
    return f"{valeur:.2f}".replace(".", ",") + " €"


def _texte_prix_conteste(contestation: _ContestationEnvoyee) -> str:
    morceaux: list[str] = []
    if contestation.prix_bon is not None:
        unite = f" / {contestation.unite_bon}" if contestation.unite_bon else ""
        morceaux.append(f"prix du bon {_montant(contestation.prix_bon)}{unite}")
    if contestation.prix_grille is not None:
        morceaux.append(f"grille {_montant(contestation.prix_grille)}")
    return f" — {', '.join(morceaux)}" if morceaux else ""
```

`_texte_synthese(commentaires, nb_total, contestations=(), nb_contestations=0)` : garder tout l'existant, puis si `contestations` :

```python
lignes.append("Prix contestés cette semaine :")
if nb_contestations > len(contestations):
    lignes.append(
        f"{nb_contestations} contestations cette semaine ; "
        f"les {len(contestations)} plus récentes ci-dessous."
    )
for contestation in contestations:
    jour_libelle = f"{_JOURS_FR[contestation.jour.weekday()]} {contestation.jour:%d/%m}"
    bons = ", ".join(contestation.numeros_bons) or "inconnu"
    lignes.append(
        f"[{contestation.reference}] {jour_libelle} — {contestation.fournisseur} — "
        f"produit « {contestation.produit} » — bon(s) {bons}"
        f"{_texte_prix_conteste(contestation)} : {contestation.commentaire}"
    )
```

Chargement :

```python
async def _contestations_de_la_semaine(
    session: AsyncSession, debut_dt: datetime, fin_dt: datetime
) -> tuple[list[_ContestationEnvoyee], dict[str, tuple[uuid.UUID, ...]], int]:
    """Contestations de la semaine regroupées par (fournisseur, produit,
    commentaire), numérotées p1..pN du plus ancien au plus récent ;
    `_CONTESTATIONS_MAX` plus récentes au plus (le nombre réel est rendu)."""
    contestations = await charger_contestations(session, depuis=debut_dt, avant=fin_dt)
    groupes: dict[tuple[uuid.UUID, str, str], list[Contestation]] = {}
    for contestation in contestations:  # plus récentes d'abord
        cle = (
            contestation.fournisseur_id,
            contestation.cle_produit,
            contestation.commentaire,
        )
        groupes.setdefault(cle, []).append(contestation)
    nb_total = len(groupes)
    retenus = list(groupes.values())[:_CONTESTATIONS_MAX]
    retenus.reverse()
    envoyees: list[_ContestationEnvoyee] = []
    documents: dict[str, tuple[uuid.UUID, ...]] = {}
    for indice, groupe in enumerate(retenus, start=1):
        reference = f"p{indice}"
        recente = groupe[0]
        documents[reference] = tuple(dict.fromkeys(c.document_id for c in groupe))
        envoyees.append(
            _ContestationEnvoyee(
                reference=reference,
                jour=recente.conteste_le.astimezone(FUSEAU_PARIS).date(),
                fournisseur=recente.fournisseur_nom,
                produit=recente.produit,
                numeros_bons=tuple(
                    dict.fromkeys(c.numero_bon or "inconnu" for c in groupe)
                ),
                prix_bon=recente.prix_bon,
                unite_bon=recente.unite_bon,
                prix_grille=recente.prix_grille,
                commentaire=recente.commentaire,
            )
        )
    return envoyees, documents, nb_total


@dataclass(frozen=True)
class _ElementsSemaine:
    """Tout ce qui part vers l'IA pour une semaine -- partagé par
    `generer_synthese` et l'essai du Laboratoire IA (jamais deux
    implémentations)."""

    commentaires: list[_CommentaireEnvoye]
    commentaire_par_reference: dict[str, Commentaire]
    nb_commentaires: int
    contestations: list[_ContestationEnvoyee]
    documents_par_contestation: dict[str, tuple[uuid.UUID, ...]]
    nb_contestations: int

    @property
    def vide(self) -> bool:
        return self.nb_commentaires == 0 and self.nb_contestations == 0

    @property
    def references_valides(self) -> frozenset[str]:
        return frozenset(self.commentaire_par_reference) | frozenset(
            self.documents_par_contestation
        )

    def texte(self) -> str:
        return _texte_synthese(
            self.commentaires,
            self.nb_commentaires,
            self.contestations,
            self.nb_contestations,
        )


async def _elements_de_la_semaine(
    session: AsyncSession, debut_dt: datetime, fin_dt: datetime
) -> _ElementsSemaine:
    commentaires, par_reference, nb_commentaires = await _commentaires_de_la_semaine(
        session, debut_dt, fin_dt
    )
    contestations, documents, nb_contestations = await _contestations_de_la_semaine(
        session, debut_dt, fin_dt
    )
    return _ElementsSemaine(
        commentaires=commentaires,
        commentaire_par_reference=par_reference,
        nb_commentaires=nb_commentaires,
        contestations=contestations,
        documents_par_contestation=documents,
        nb_contestations=nb_contestations,
    )
```

`generer_synthese` : remplacer le chargement par `elements = await _elements_de_la_semaine(...)` ; `if elements.vide:` → vide ; `texte_envoye = elements.texte()` ; `lire_synthese(reponse.structure, elements.references_valides)` ; passer `nb_commentaires=elements.nb_commentaires`, `nb_contestations=elements.nb_contestations`, `commentaire_par_reference=elements.commentaire_par_reference`, `documents_par_contestation=elements.documents_par_contestation` à `_enregistrer_synthese_ok`. Mettre à jour la docstring (étapes 4 à 6).

`_enregistrer_synthese_ok` : nouveaux paramètres `nb_contestations: int`, `documents_par_contestation: Mapping[str, tuple[uuid.UUID, ...]]` ; `SyntheseCommentaires(..., nb_contestations=nb_contestations)` ; par action :

```python
        commentaires_cites = [
            commentaire_par_reference[reference]
            for reference in action_lue.references
            if reference in commentaire_par_reference
        ]
        document_ids: list[str] = []
        for commentaire in commentaires_cites:
            document_id = str(commentaire.document_id)
            if document_id not in document_ids:
                document_ids.append(document_id)
        for reference in action_lue.references:
            for document_id_uuid in documents_par_contestation.get(reference, ()):
                document_id = str(document_id_uuid)
                if document_id not in document_ids:
                    document_ids.append(document_id)
```

Journal (`ok` et `vide`) : ajouter `"nb_contestations"`. `SyntheseVue` : champ `nb_contestations: int`, renseigné dans `vue_accueil` depuis la ligne.

`ia_labo.lancer_essai_synthese` : importer `_elements_de_la_semaine` (à la place de `_commentaires_de_la_semaine`/`_texte_synthese`) ; `if elements.vide:` → `_essai_synthese_semaine_vide` ; `texte = elements.texte()` ; `references_valides = elements.references_valides`. `_RESUME_SEMAINE_VIDE` : « Aucun commentaire ni contestation cette semaine : pas de synthèse, l'IA n'est pas appelée (comme en production). »

- [ ] **Step 5: Consigne OpenCode** — dans `deploy/opencode/opencode.json`, remplacer le `prompt` de `habitat-synthese` par :

```
Tu résumes des commentaires laissés par des agents d'Habitat & Rénovation sur des lignes de bons de livraison, et les prix contestés depuis la page Prix. Chaque commentaire te sera donné avec une référence courte (c1, c2, ...), le jour, le nom du fournisseur, le numéro du bon et le libellé de la ligne concernée ; chaque contestation de prix avec une référence courte (p1, p2, ...), le jour, le nom du fournisseur, le produit, les numéros des bons, le prix du bon et celui de la grille s'ils sont connus, et le commentaire de la contestation -- jamais le nom de l'auteur, ni celui d'un chantier ou d'un client. Rédige un résumé factuel et neutre en français simple (1200 caractères au plus), qui relaie ce que disent les commentaires et les contestations sans les interpréter. Propose ensuite une liste d'actions concrètes à mener (300 caractères au plus chacune) ; chaque action doit être reliée à au moins une référence réellement fournie (commentaire ou contestation), à mettre dans le champ « commentaires » -- n'invente jamais une référence, un chiffre, un nom de fournisseur, un numéro de bon ou un fait absent des éléments transmis. Tu ne décides jamais si une anomalie est justifiée, si un fournisseur doit être relancé, ni si un montant est correct : tu résumes et tu relaies, l'humain décide. Réponds uniquement selon le schéma JSON demandé, sans texte hors de ce schéma.
```

Adapter `tests/test_opencode_config.py` seulement si une assertion portait sur l'ancienne phrase.

- [ ] **Step 6: API et écran**
  - `SyntheseReponse` : `nb_contestations: int`.
  - `SyntheseCommentaires.tsx` : remplacer le compteur par `texteCompteurs(derniere.nb_commentaires, derniere.nb_contestations)` :

```tsx
function texteCompteurs(nbCommentaires: number, nbContestations: number): string {
  const morceaux: string[] = [];
  if (nbCommentaires > 0) morceaux.push(`${nbCommentaires} commentaire${nbCommentaires > 1 ? "s" : ""}`);
  if (nbContestations > 0) morceaux.push(`${nbContestations} contestation${nbContestations > 1 ? "s" : ""}`);
  return morceaux.length > 0 ? morceaux.join(" · ") : "0 commentaire";
}
```

  - `lib/journal.ts` : libellé `nb_contestations: "Contestations"` à côté de `nb_commentaires`.
  - Régénérer les types (`api:schema`, `api:types`), puis typecheck et build.
- [ ] **Step 7: Run tests** — `flock /tmp/habitat_reno-tests.lock uv run pytest app/modules/ingest/tests/test_ia_synthese.py app/modules/ingest/tests/test_ia_labo.py app/modules/api/tests/test_ia.py tests/test_opencode_config.py tests/test_migrations.py -q` + ruff, format, mypy.
- [ ] **Step 8: Commit** — `ingest: contestations de prix dans la synthèse de la semaine (migration 0016)`.

---

### Task 5: Recherche internet à la demande (service)

**Files:**
- Modify: `app/modules/ingest/ia_prix.py`
- Test: `app/modules/ingest/tests/test_ia_prix.py` (réutiliser `_creer_fournisseur`, `_creer_anomalie`, `_detail_r22`, `_creer_prix_internet`, `_handler_json`, `_aucune_requete`, `_reponses_prix_trouve`, `_reponses_prix_non_verifiable`, `_reponses_erreur`, `_activer_controle_prix_bl` ; fixture `sessions_test`)

**Interfaces:**
- Produces:
  - `class RechercheImpossible(Exception)` avec `raison: Literal["eteinte", "plafond"]`, `str(exc)` = « IA éteinte » / « Plafond du jour atteint ».
  - `@dataclass(frozen=True) class RechercheVue: etat: Literal["en_cours", "echec"]; message: str | None`.
  - `async lancer_recherche_prix(session: AsyncSession, sessions: async_sessionmaker[AsyncSession], http: httpx.AsyncClient, background_tasks: BackgroundTasks, anomalie_id: uuid.UUID) -> Literal["lancee", "deja_en_cours"]` — `AnomalieIntrouvable` si l'anomalie n'est pas une alerte de prix R19–R25 ouverte et non masquée (ou sans désignation) ; `RechercheImpossible`.
  - `PrixInternetLot.recherches: dict[uuid.UUID, RechercheVue]` (défaut vide) ; `prix_internet_des_anomalies` couvre R19–R25.

- [ ] **Step 1: Write the failing tests** (le registre en mémoire doit être vidé entre les tests : fixture `autouse` qui fait `ia_prix._RECHERCHES.clear()`) :
  1. `test_lancer_recherche_enregistre_le_resultat` — anomalie R19 ouverte (détail `_detail_r22()` + `"prix_grille": "7.00"` avec `regle="R19"`), transport `_reponses_prix_trouve(...)`, `BackgroundTasks()` ; `lancer_recherche_prix` → `"lancee"` ; `await background_tasks()` ; une ligne `PrixInternet` `trouve` pour `cle_produit_internet(fournisseur.id, "Plaque std 13", "PL13")` ; `etat_recherche(cle)` → `None` (terminé, pas d'état affiché).
  2. `test_clic_ignore_le_cache_et_les_echecs` — une ligne `trouve` d'il y a 2 jours et 3 lignes `echec` récentes pour la même clé → la recherche est quand même faite (nouvelle ligne).
  3. `test_deja_en_cours` (Review Focus 1) — deux appels successifs sans exécuter les tâches → `"lancee"` puis `"deja_en_cours"` ; une seule tâche ajoutée (`len(background_tasks.tasks) == 1`).
  4. `test_ia_eteinte_409` — `ia_active` faux → `RechercheImpossible`, `raison == "eteinte"`, aucune tâche.
  5. `test_plafond_au_clic` — plafond à 0 (même mécanique que les tests du plafond existants) → `RechercheImpossible("plafond")`.
  6. `test_plafond_pendant_la_recherche` — plafond atteint entre le clic et l'exécution (monkeypatch de `interroger` qui lève `IAIndisponible("plafond")`) → aucune ligne `PrixInternet`, `etat_recherche(cle) == RechercheVue("echec", "Plafond du jour atteint")`.
  7. `test_erreur_ia_enregistre_un_echec` — `_reponses_erreur(...)` → ligne `echec` écrite, état `echec` « La recherche a échoué ».
  8. `test_erreur_imprevue_ne_reste_pas_en_cours` (Review Focus 2) — monkeypatch `_rechercher_et_enregistrer` qui lève `RuntimeError` → après `await background_tasks()`, `etat_recherche(cle).etat == "echec"`.
  9. `test_anomalie_non_prix_ou_fermee_404` — anomalie `R01` ouverte, anomalie R19 `traitee`, identifiant inconnu → `AnomalieIntrouvable`.
  10. `test_anomalie_masquee_404` — R22 alors que le contrôle des prix est éteint (masquée) → `AnomalieIntrouvable`.
  11. `test_r25_sans_unite` (Review Focus 5) — détail R25 sans `unite_bon` → lancée ; le texte envoyé contient « Unité : — ».
  12. `test_etat_echec_expire_apres_15_minutes` — inscrire un état `echec` daté de 16 min → `etat_recherche` rend `None` ; un `en_cours` de 16 min est ignoré par `lancer_recherche_prix` (relance possible).
  13. `test_lot_couvre_toutes_les_regles_de_prix` — `prix_internet_des_anomalies` rend une clé pour une anomalie R19 ouverte (valeur `None` sans résultat) ; `recherches[id] == RechercheVue("en_cours", None)` quand sa clé est en cours.
  14. Mettre à jour les tests existants qui affirmaient qu'une alerte de prix non R22 est absente du lot (décision D1) ; les autres règles (hors prix) restent absentes.
  15. Les tests existants de `chercher_prix_internet` (`ia-prix`) passent sans changement (même enregistrement, toujours R22 seulement).
- [ ] **Step 2: Run tests to verify they fail.**
- [ ] **Step 3: Implement** dans `ia_prix.py`.

Factoriser l'enregistrement (utilisé par `chercher_prix_internet` et par la recherche à la demande) :

```python
async def _rechercher_et_enregistrer(
    session: AsyncSession,
    http: httpx.AsyncClient,
    *,
    cle: str,
    fournisseur_id: uuid.UUID | None,
    fournisseur_nom: str | None,
    designation: str,
    code: str | None,
    unite: str | None,
) -> Literal["trouve", "non_verifiable", "echec", "echec_injoignable"]:
    """Une recherche et son enregistrement (une ligne `PrixInternet`
    commitée) -- partagé par `chercher_prix_internet` et la recherche à la
    demande (spec 2026-10-01 §3.1). `IAIndisponible` remonte sans rien
    écrire."""
    try:
        resultat, modele = await rechercher_prix(
            session, http, fournisseur=fournisseur_nom, designation=designation,
            code=code, unite=unite,
        )
    except ErreurIA as exc:
        session.add(
            _ligne_prix_echec(
                fournisseur_id=fournisseur_id, cle=cle, designation=designation,
                code=code, raison=exc.code, consulte_le=datetime.now(UTC),
            )
        )
        await session.commit()
        return "echec_injoignable" if _echec_injoignable(exc.code) else "echec"
    except ReponseIAInvalide:
        session.add(
            _ligne_prix_echec(
                fournisseur_id=fournisseur_id, cle=cle, designation=designation,
                code=code, raison="reponse_invalide", consulte_le=datetime.now(UTC),
            )
        )
        await session.commit()
        return "echec"
    session.add(PrixInternet(<mêmes champs qu'aujourd'hui dans chercher_prix_internet>))
    await session.commit()
    return "trouve" if resultat.statut == "trouve" else "non_verifiable"
```

et dans la boucle de `chercher_prix_internet` :

```python
try:
    issue = await _rechercher_et_enregistrer(
        session,
        http,
        cle=cle,
        fournisseur_id=fournisseur_id,
        fournisseur_nom=nom_fournisseur,
        designation=designation,
        code=code,
        unite=unite,
    )
except IAIndisponible as exc:
    arret = exc.raison
    break
if issue == "trouve":
    ok += 1
elif issue == "non_verifiable":
    non_verifiables += 1
else:
    echecs += 1
    if issue == "echec_injoignable":
        echecs_injoignable += 1
```

Recherche à la demande (nouvelle section après `chercher_prix_internet`) :

```python
# Recherche à la demande depuis la page Prix (spec 2026-10-01 §3) : état en
# mémoire du processus (une seule instance d'API, comme les essais du
# Laboratoire IA) -- perdu au redémarrage, la cellule revient à son bouton.
_DUREE_ETAT_RECHERCHE = timedelta(minutes=15)
_MESSAGES_RECHERCHE: dict[str, str] = {
    "eteinte": "IA éteinte",
    "plafond": "Plafond du jour atteint",
}
_MESSAGE_ECHEC_RECHERCHE = "La recherche a échoué"


@dataclass(frozen=True)
class _EtatRecherche:
    etat: Literal["en_cours", "termine", "echec"]
    message: str | None
    depuis: datetime


_RECHERCHES: dict[str, _EtatRecherche] = {}


@dataclass(frozen=True)
class RechercheVue:
    etat: Literal["en_cours", "echec"]
    message: str | None


class RechercheImpossible(Exception):
    def __init__(self, raison: Literal["eteinte", "plafond"]) -> None:
        super().__init__(_MESSAGES_RECHERCHE[raison])
        self.raison = raison


def etat_recherche(cle: str, maintenant: datetime | None = None) -> RechercheVue | None:
    etat = _RECHERCHES.get(cle)
    if etat is None:
        return None
    if (maintenant or datetime.now(UTC)) - etat.depuis >= _DUREE_ETAT_RECHERCHE:
        return None
    if etat.etat == "en_cours":
        return RechercheVue(etat="en_cours", message=None)
    if etat.etat == "echec":
        return RechercheVue(etat="echec", message=etat.message)
    return None


@dataclass(frozen=True)
class _ProduitRecherche:
    cle: str
    fournisseur_id: uuid.UUID | None
    fournisseur_nom: str | None
    designation: str
    code: str | None
    unite: str | None


async def _produit_a_rechercher(
    session: AsyncSession, anomalie_id: uuid.UUID
) -> _ProduitRecherche:
    exclues = await regles_masquees(session)
    rangee = (
        await session.execute(
            select(Anomalie, Document.fournisseur_id, Fournisseur.nom)
            .outerjoin(Document, Document.id == Anomalie.document_id)
            .outerjoin(Fournisseur, Fournisseur.id == Document.fournisseur_id)
            .where(
                Anomalie.id == anomalie_id,
                Anomalie.statut == "ouverte",
                condition_regles_actives(exclues=exclues),
                Anomalie.regle.in_(tuple(REGLES_PRIX_BL)),
            )
        )
    ).one_or_none()
    if rangee is None:
        raise AnomalieIntrouvable(str(anomalie_id))
    anomalie, fournisseur_id, fournisseur_nom = rangee
    designation = _valeur_utile(anomalie.detail.get("produit"))
    if designation is None:
        raise AnomalieIntrouvable(str(anomalie_id))
    code = _valeur_utile(anomalie.detail.get("code"))
    return _ProduitRecherche(
        cle=cle_produit_internet(fournisseur_id, designation, code),
        fournisseur_id=fournisseur_id,
        fournisseur_nom=fournisseur_nom,
        designation=designation,
        code=code,
        unite=_valeur_utile(anomalie.detail.get("unite_bon")),
    )


async def _executer_recherche_prix(
    produit: _ProduitRecherche,
    sessions: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
) -> None:
    # `except Exception` seulement (une annulation se propage) ; `finally`
    # garantit qu'aucune clé ne reste « en cours » après la tâche.
    etat_final = _EtatRecherche("echec", _MESSAGE_ECHEC_RECHERCHE, datetime.now(UTC))
    try:
        async with sessions() as session:
            try:
                issue = await _rechercher_et_enregistrer(
                    session,
                    http,
                    cle=produit.cle,
                    fournisseur_id=produit.fournisseur_id,
                    fournisseur_nom=produit.fournisseur_nom,
                    designation=produit.designation,
                    code=produit.code,
                    unite=produit.unite,
                )
            except IAIndisponible as exc:
                etat_final = _EtatRecherche(
                    "echec", _MESSAGES_RECHERCHE[exc.raison], datetime.now(UTC)
                )
            else:
                if issue in ("trouve", "non_verifiable"):
                    etat_final = _EtatRecherche("termine", None, datetime.now(UTC))
                else:
                    etat_final = _EtatRecherche(
                        "echec", _MESSAGE_ECHEC_RECHERCHE, datetime.now(UTC)
                    )
    except Exception:
        logger.exception("erreur imprévue pendant une recherche de prix à la demande")
    finally:
        _RECHERCHES[produit.cle] = etat_final


async def lancer_recherche_prix(
    session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    background_tasks: BackgroundTasks,
    anomalie_id: uuid.UUID,
) -> Literal["lancee", "deja_en_cours"]:
    """Bouton « Chercher sur internet » de la page Prix (spec 2026-10-01
    §3.1) : ignore le cache de 30 jours et la limite d'échecs (décision
    humaine), respecte le plafond du jour ; une seule recherche à la fois
    par produit."""
    produit = await _produit_a_rechercher(session, anomalie_id)
    if not ia_active():
        raise RechercheImpossible("eteinte")
    if await appels_du_jour(session) >= ia_appels_max_jour():
        raise RechercheImpossible("plafond")
    maintenant = datetime.now(UTC)
    etat = _RECHERCHES.get(produit.cle)
    if (
        etat is not None
        and etat.etat == "en_cours"
        and maintenant - etat.depuis < _DUREE_ETAT_RECHERCHE
    ):
        return "deja_en_cours"
    _RECHERCHES[produit.cle] = _EtatRecherche("en_cours", None, maintenant)
    background_tasks.add_task(_executer_recherche_prix, produit, sessions, http)
    return "lancee"
```

Imports à ajouter : `from fastapi import BackgroundTasks`, `async_sessionmaker`, `appels_du_jour` et `ia_appels_max_jour` (de `ingest.opencode`), `REGLES_PRIX_BL` (de `app.modules.rules.engine`), un `logger` (même source que celui d'`ia_labo.py`, jamais de désignation dans le message).

`prix_internet_des_anomalies` : filtre `Anomalie.regle.in_(tuple(REGLES_PRIX_BL))` au lieu de `REGLES_PRIX_INTERNET` ; `PrixInternetLot` gagne `recherches: dict[uuid.UUID, RechercheVue] = field(default_factory=dict)` ; remplir avec `etat_recherche(cle)` non nul pour chaque anomalie ayant une clé. Mettre à jour les docstrings (`PrixInternetLot`, `prix_internet_des_anomalies`, `_cle_produit_pour_anomalie` : « une alerte de prix », plus seulement R22). `REGLES_PRIX_INTERNET` et `chercher_prix_internet` gardent R22.

- [ ] **Step 4: Run tests** — `flock /tmp/habitat_reno-tests.lock uv run pytest app/modules/ingest/tests/test_ia_prix.py app/modules/ingest/tests/test_ia_prix_bout_en_bout.py -q` + ruff, format, mypy.
- [ ] **Step 5: Commit** — `ingest: recherche de prix internet à la demande depuis la page Prix`.

---

### Task 6: Route `POST /api/ia/prix-internet/recherches`

**Files:**
- Modify: `app/modules/api/schemas.py`, `app/modules/api/ia.py`
- Test: `app/modules/api/tests/test_ia.py`

**Interfaces:**
- Consumes: `lancer_recherche_prix`, `RechercheImpossible`, `RechercheVue`, `PrixInternetLot.recherches` (Task 5).
- Produces: `POST /api/ia/prix-internet/recherches` (202 `{"etat": "lancee" | "deja_en_cours"}`, 404, 409 avec `detail` = message) ; `GET /api/ia/prix-internet` rend aussi `recherches: {id: {etat, message}}`.

- [ ] **Step 1: Write the failing tests** — admin : 202 `lancee` puis `deja_en_cours` (fausse fonction `lancer_recherche_prix` substituée par `monkeypatch` dans le module `app.modules.api.ia`, ou vrai service avec transport factice selon les fixtures du fichier) ; 404 anomalie inconnue ; 409 « IA éteinte » ; 403 non admin ; `GET /api/ia/prix-internet` contient `recherches` (vide par défaut).
- [ ] **Step 2: Run tests to verify they fail.**
- [ ] **Step 3: Implement**

`schemas.py` :

```python
class RecherchePrixRequete(BaseModel):
    """`POST /api/ia/prix-internet/recherches` : l'alerte de prix dont le
    produit est à chercher."""

    anomalie_id: uuid.UUID


class RechercheLanceeReponse(BaseModel):
    etat: Literal["lancee", "deja_en_cours"]


class RechercheReponse(BaseModel):
    """État d'une recherche à la demande (mêmes attributs qu'`ingest.ia_prix
    .RechercheVue`)."""

    model_config = ConfigDict(from_attributes=True)

    etat: Literal["en_cours", "echec"]
    message: str | None
```

`PrixInternetLotReponse` : `recherches: dict[str, RechercheReponse] = {}` (rempli par le routeur : `{str(i): RechercheReponse.model_validate(v) for i, v in lot.recherches.items()}`).

`ia.py` — la route se place **après** `_get_sessionmaker`/`_get_http` (les `Depends` sont évalués à la définition) :

```python
@router.post(
    "/ia/prix-internet/recherches",
    response_model=RechercheLanceeReponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def lancer_recherche_prix_endpoint(
    corps: RecherchePrixRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    background_tasks: BackgroundTasks,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(_get_sessionmaker)],
    http: Annotated[httpx.AsyncClient, Depends(_get_http)],
) -> RechercheLanceeReponse:
    del utilisateur
    try:
        etat = await lancer_recherche_prix(
            session, sessions, http, background_tasks, corps.anomalie_id
        )
    except AnomalieIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="alerte de prix introuvable"
        ) from exc
    except RechercheImpossible as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return RechercheLanceeReponse(etat=etat)
```

Docstring du module : ajouter la route.
- [ ] **Step 4: Run tests** + ruff, format, mypy, `tests/test_frontieres.py`.
- [ ] **Step 5: Régénérer les types** (`api:schema`, `api:types`).
- [ ] **Step 6: Commit** — `api: lancer une recherche de prix internet depuis la page Prix`.

---

### Task 7: Écran Prix — bouton, état, relance

**Files:**
- Modify: `web/src/api/ia.ts`, `web/src/pages/Prix.tsx`, `web/src/components/PrixInternetCellule.tsx`

**Interfaces:**
- Consumes: `RechercheLanceeReponse`, `RechercheReponse`, `PrixInternetLotReponse.recherches` (Task 6).

- [ ] **Step 1: Client** (`api/ia.ts`) :

```ts
export type RecherchePrix = components["schemas"]["RechercheReponse"];
export type RechercheLancee = components["schemas"]["RechercheLanceeReponse"];

/** `POST /api/ia/prix-internet/recherches` (admin) : lance la recherche du
 * produit de l'alerte en tâche de fond ; le résultat arrive par la lecture
 * groupée. 409 : IA éteinte ou plafond du jour atteint. */
export function lancerRecherchePrix(anomalieId: string): Promise<RechercheLancee> {
  return appelerApi<RechercheLancee>("/api/ia/prix-internet/recherches", {
    method: "POST",
    json: { anomalie_id: anomalieId },
  });
}
```

Mettre à jour les docstrings de `clePrixInternet`/`lirePrixInternet` (toutes les rangées, plus seulement R22).

- [ ] **Step 2: `Prix.tsx`**
  - Remplacer `idsInternetPour` par `idInternetPour(produit) => produit.anomalie_ids[0]` (un identifiant par rangée ; toutes les alertes de prix sont couvertes, décision D1) ; `ids = alertes.data.map(idInternetPour).slice(0, MAX_IDS_PRIX_INTERNET)`.
  - `prixInternetPour(produit)` lit `prix[idInternetPour(produit)]` ; `recherchePour(produit)` lit `prixInternetLot.data?.recherches?.[idInternetPour(produit)]`.
  - Relecture tant qu'une recherche est en cours :

```ts
  const prixInternetLot = useQuery({
    queryKey: clePrixInternet(ids),
    queryFn: () => lirePrixInternet(ids),
    enabled: alertesChargees && ids.length > 0,
    refetchInterval: (requete) =>
      Object.values(requete.state.data?.recherches ?? {}).some((r) => r.etat === "en_cours")
        ? 10_000
        : false,
  });
```

  - Mutation :

```ts
  const [erreursRecherche, setErreursRecherche] = useState<Record<string, string>>({});
  const rechercheMutation = useMutation({
    mutationFn: (anomalieId: string) => lancerRecherchePrix(anomalieId),
    onMutate: (anomalieId) =>
      setErreursRecherche(({ [anomalieId]: _ancienne, ...reste }) => reste),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["ia", "prix-internet"] });
    },
    onError: (erreur, anomalieId) =>
      setErreursRecherche((e) => ({ ...e, [anomalieId]: <message de l'erreur API, même extraction que les autres actions de la page> })),
  });
```

  - Passer à `PrixInternetCellule` (tableau et carte) : `recherche={recherchePour(produit)}`, `lancementEnCours={rechercheMutation.isPending && rechercheMutation.variables === idInternetPour(produit)}`, `erreurLancement={erreursRecherche[idInternetPour(produit)] ?? null}`, `onRechercher={() => rechercheMutation.mutate(idInternetPour(produit))}`.
  - Mettre à jour le commentaire du tableau (colonne « Internet » sur toutes les rangées).

- [ ] **Step 3: `PrixInternetCellule.tsx`** — retirer la garde « R22 seulement » ; nouvelles props `recherche: RecherchePrix | undefined`, `lancementEnCours: boolean`, `erreurLancement: string | null`, `onRechercher: () => void`. Ordre d'affichage :

```tsx
  const lienAction = (libelle: string): ReactElement => (
    <button
      type="button"
      onClick={onRechercher}
      className="ml-1 font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      {libelle}
    </button>
  );

  if (lancementEnCours || recherche?.etat === "en_cours") {
    return <span className="text-encre-2">Recherche en cours…</span>;
  }
  const message = erreurLancement ?? (recherche?.etat === "echec" ? recherche.message ?? "La recherche a échoué" : null);
  const resultat = <affichage actuel du résultat `trouve` / `non_verifiable`, ou null s'il n'y en a pas>;
  if (resultat !== null) {
    return (
      <>
        {resultat}
        {message !== null && <p className="text-xs text-alerte">{message}</p>}
        {lienAction(message !== null ? "Réessayer" : "Relancer")}
      </>
    );
  }
  if (message !== null) {
    return (<><span className="text-alerte">{message}</span>{lienAction("Réessayer")}</>);
  }
  return (
    <Bouton variante="secondaire" className="whitespace-nowrap" onClick={onRechercher}>
      Chercher sur internet
    </Bouton>
  );
```

(garder tel quel l'affichage du résultat et la garde https des liens ; « introuvable » garde sa raison en `title`). Mettre à jour la docstring du composant.
- [ ] **Step 4: Vérifier** — typecheck, build.
- [ ] **Step 5: Commit** — `web: bouton « Chercher sur internet » sur l'onglet Prix`.

---

### Task 8: Documentation

**Files:**
- Modify: `README.md` (sections onglet Prix, grille, synthèse IA, migrations — 0016 —, routes API, état), `docs/dette.md`, `docs/phase-4-ia.md` (usages de l'IA), `CLAUDE.md` (une ligne dans « Où en est le projet »)

- [ ] **Step 1:** Décrire : bouton « Chercher sur internet » (démo seulement tant que l'IA est éteinte en production), contestations dans la grille (marche sans IA), contestations dans le résumé (`pN`, migration 0016, consigne OpenCode à reconstruire), décisions D1–D4 d'Ilane du 01/10/2026.
- [ ] **Step 2:** `docs/dette.md` : état des recherches en mémoire (perdu au redémarrage, une seule instance d'API supposée) ; une contestation n'est ni modifiable ni annulable ; les prix ignorés ne sont visibles nulle part hors du journal ; le front n'a pas de tests automatiques.
- [ ] **Step 3: Commit** — `docs: recherche à la demande et contestations de prix`.

---

## Après le plan (contrôleur)

1. Relecture complète de la branche (un relecteur, Sonnet 5.5), une vague de corrections, une relecture ciblée.
2. PR vers `dev`.
3. Déploiement **démo seulement** : sauvegarde de la base démo, migration 0016, reconstruction de l'API et de l'image OpenCode, contrôle visuel. Production : rien sans l'accord d'Ilane.
