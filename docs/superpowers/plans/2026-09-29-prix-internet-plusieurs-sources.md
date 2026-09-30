# Prix internet à plusieurs sources — plan de réalisation

> **Pour les agents :** SOUS-COMPÉTENCE REQUISE : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans, tâche par tâche. Les étapes utilisent des cases (`- [ ]`).

**But :** l'IA rapporte jusqu'à cinq offres vérifiées par produit ; la page Prix, l'encart « Avis de l'IA » et le Laboratoire affichent le prix HT le plus bas, l'écart et les liens.

**Architecture :** la lecture et les contrôles restent purs (`extract/reponses_ia.py`) et passent d'une offre à une liste d'offres, chacune contrôlée ; `ingest/ia_prix.py` stocke la liste dans une nouvelle colonne JSONB `prix_internet.offres` (migration `0015`) et calcule le plus bas/plus haut HT pour la vue ; l'API expose ces champs en plus des champs actuels (qui décrivent l'offre la moins chère) ; le front ajoute une liste d'offres partagée.

**Stack :** Python 3.11, SQLAlchemy 2 async, Alembic, PostgreSQL, FastAPI, React 18 + TypeScript + TanStack Query + Tailwind, OpenCode 1.18.32.

**Spec :** `docs/superpowers/specs/2026-09-29-prix-internet-plusieurs-sources-design.md` (lire en entier avant chaque tâche).

## Contraintes globales

- Worktree `/home/debian/habitat_reno-ia`, branche `feature/prix-internet-plusieurs-sources` (déjà créée, spec commitée).
- Lire `CLAUDE.md` du dépôt. Frontières : `extract` n'importe ni FastAPI, ni SQLAlchemy, ni httpx ; `api` n'importe que `ingest` et `app.core` (`tests/test_frontieres.py`).
- Offres : **5 au plus** (`OFFRES_MAX = 5`), de sites différents.
- HT : `TTC ÷ 1,20` (`TVA_PRIX_INTERNET = Decimal("1.20")`), arrondi au centime `ROUND_HALF_UP` ; `taxes` absent/`inconnu` → `prix_ht = None`, hors du plus bas et de l'écart.
- Raisons de non-vérifiabilité inchangées quand elles existent déjà : `"réponse incomplète"`, `"source non ouverte"`, `"prix absent de la page"` ; nouvelle : `"aucune offre"`.
- Agent `habitat-prix` : `steps` 14 ; appel `rechercher_prix` : `delai=300`.
- Tests : `flock /tmp/habitat_reno-tests.lock uv run pytest …` ; `uv run ruff check`, `uv run ruff format --check`, `uv run mypy` avant chaque commit ; front : `cd web && npm run typecheck && npm run build`.
- Commit : un par tâche, message en français préfixé du module, terminé par les deux lignes `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` et `Claude-Session: https://claude.ai/code/session_01CkEsK2ZZmf8Ksb6HbKqXZz`. Le hook rejoue toute la suite (≈ 8 min) : `git commit -F msg.txt > commit.log 2>&1` en arrière-plan, puis vérifier `commit.log`. **Jamais `--no-verify`**, jamais `pre-commit install`.
- Interdits : lire un fichier `.env*` ou `~/.secrets` ; `docker exec` sur `habitat_prod-*`/`habitat_demo-*` ; toucher `tests/fixtures/`.

## Points de vigilance (non couverts par les tests de la spec)

1. **Réponse ancien format** (sans `offres`, champs à plat) venant d'un OpenCode pas encore mis à jour → non vérifiable « aucune offre », jamais une exception. Test en tâche 1.
2. **Offre en double sur la même page** (même adresse à la barre oblique finale ou au fragment près) → une seule gardée. Test en tâche 1.
3. **Toutes les offres en taxes « inconnu »** → trouvé, `prix_ht_min`/`max` = `None`, l'écran n'affiche pas « dès … HT » mais la première offre telle quelle. Tests en tâches 1, 3 et 5.
4. **Ligne `trouve` ancienne sans offres** (écrite avant la migration, ou `offres` vide) → la vue reconstitue une offre depuis ses colonnes. Test en tâche 3.
5. **Lien d'offre non `https:`** → jamais cliquable (réutiliser `domaineSource`). Test en tâche 5.

---

### Tâche 1 : lecture et contrôles d'une liste d'offres (`extract`, pur)

**Fichiers :**
- Modifier : `app/modules/extract/reponses_ia.py` (section « Prix trouvé sur internet », lignes ≈ 515-860)
- Tests : `app/modules/extract/tests/test_reponses_ia.py` ; données de test « trouvé » dans `app/modules/ingest/tests/test_ia_prix.py`, `app/modules/ingest/tests/test_ia_prix_bout_en_bout.py`, `app/modules/ingest/tests/test_ia_labo.py`, `app/modules/api/tests/test_ia_labo.py`, `tests/test_cli.py` s'il construit une réponse `trouve` à plat

**Interfaces produites :**
- `SCHEMA_PRIX_INTERNET` (nouvelle forme, §3 de la spec) ; `OFFRES_MAX = 5` ; `TVA_PRIX_INTERNET = Decimal("1.20")`
- `def prix_ht(prix: Decimal, taxes: str | None) -> Decimal | None`
- `@dataclass(frozen=True) class OffreLue: prix: Decimal; devise: str; taxes: Literal["HT","TTC"] | None; prix_ht: Decimal | None; unite: str | None; conditionnement: str | None; produit_trouve: str; source_url: str; confiance: str`
- `PrixInternetLu` : champs actuels inchangés (= offre la moins chère en HT, à défaut la première gardée) + `offres: tuple[OffreLue, ...] = ()` (triées : `prix_ht` croissant, `None` à la fin, ordre de l'IA à égalité)
- `lire_prix_internet(structure, pages) -> PrixInternetLu` et `controles_prix_internet(structure, pages) -> tuple[Controle, ...]` : mêmes signatures

- [ ] **Étape 1 : tests qui échouent** (dans `test_reponses_ia.py`). Remplacer l'aide `_structure_trouve` pour qu'elle produise la nouvelle forme, puis ajouter :

```python
def _offre(
    *,
    prix: float,
    source_url: str,
    taxes: str = "HT",
    produit_trouve: str = "Produit inventé",
    confiance: str = "elevee",
) -> dict[str, Any]:
    return {
        "produit_trouve": produit_trouve,
        "prix": prix,
        "devise": "EUR",
        "taxes": taxes,
        "unite": "u",
        "conditionnement": "boîte de 10",
        "source_url": source_url,
        "confiance": confiance,
    }


def _structure_trouve(**offre: Any) -> dict[str, Any]:
    """Une réponse `trouve` à une seule offre (forme du 29/09/2026)."""
    return {"statut": "trouve", "raison": "", "offres": [_offre(**offre)]}


def _page(adresse: str, texte: str) -> PageLue:
    return PageLue(outil="webfetch", adresse=adresse, texte=texte)


def test_prix_ht_ttc_divise_par_1_20_au_centime() -> None:
    assert prix_ht(Decimal("13.91"), "TTC") == Decimal("11.59")
    assert prix_ht(Decimal("12.34"), "HT") == Decimal("12.34")
    assert prix_ht(Decimal("12.34"), None) is None
    assert prix_ht(Decimal("12.34"), "inconnu") is None


def test_lire_prix_internet_plusieurs_offres_triees_la_moins_chere_en_tete() -> None:
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=13.91, taxes="TTC", source_url="https://a.test/p"),
            _offre(prix=12.00, taxes="HT", source_url="https://b.test/p"),
            _offre(prix=9.99, taxes="inconnu", source_url="https://c.test/p"),
        ],
    }
    pages = [
        _page("https://a.test/p", "Prix : 13,91 € TTC"),
        _page("https://b.test/p", "12,00 € HT"),
        _page("https://c.test/p", "9,99 €"),
    ]

    resultat = lire_prix_internet(structure, pages)

    assert resultat.statut == "trouve"
    assert [o.source_url for o in resultat.offres] == [
        "https://a.test/p",  # 11,59 HT
        "https://b.test/p",  # 12,00 HT
        "https://c.test/p",  # inconnu : à la fin
    ]
    assert resultat.prix == Decimal("13.9100")
    assert resultat.taxes == "TTC"
    assert resultat.source_url == "https://a.test/p"
    assert [o.prix_ht for o in resultat.offres] == [
        Decimal("11.59"),
        Decimal("12.00"),
        None,
    ]


def test_lire_prix_internet_offre_en_echec_ecartee_les_autres_gardees() -> None:
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=10.00, source_url="https://a.test/p"),  # page jamais ouverte
            _offre(prix=11.00, source_url="https://b.test/p"),  # prix absent
            _offre(prix=12.00, source_url="https://c.test/p"),  # gardée
        ],
    }
    pages = [_page("https://b.test/p", "rien"), _page("https://c.test/p", "12,00 €")]

    resultat = lire_prix_internet(structure, pages)

    assert resultat.statut == "trouve"
    assert [o.source_url for o in resultat.offres] == ["https://c.test/p"]


def test_lire_prix_internet_aucune_offre_gardee_raison_de_la_premiere() -> None:
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=10.00, source_url="https://a.test/p"),
            _offre(prix=11.00, source_url="https://b.test/p"),
        ],
    }
    pages = [_page("https://b.test/p", "rien")]

    resultat = lire_prix_internet(structure, pages)

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "source non ouverte"
    assert resultat.offres == ()


def test_lire_prix_internet_liste_vide_aucune_offre() -> None:
    resultat = lire_prix_internet({"statut": "trouve", "raison": "", "offres": []}, [])

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "aucune offre"


def test_lire_prix_internet_ancien_format_a_plat_aucune_offre() -> None:
    """Point de vigilance 1 : un OpenCode pas encore mis à jour répond à
    l'ancienne forme (champs à plat, sans `offres`)."""
    structure = {
        "statut": "trouve",
        "produit_trouve": "Produit",
        "prix": 12.0,
        "devise": "EUR",
        "taxes": "HT",
        "source_url": "https://a.test/p",
        "confiance": "elevee",
        "raison": "",
    }

    resultat = lire_prix_internet(structure, [_page("https://a.test/p", "12,00 €")])

    assert resultat.statut == "non_verifiable"
    assert resultat.raison == "aucune offre"


def test_lire_prix_internet_meme_page_une_seule_offre() -> None:
    """Point de vigilance 2 : barre oblique finale et fragment ignorés."""
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=12.00, source_url="https://a.test/p"),
            _offre(prix=12.00, source_url="https://A.test/p/#avis"),
        ],
    }

    resultat = lire_prix_internet(structure, [_page("https://a.test/p", "12,00 €")])

    assert len(resultat.offres) == 1


def test_lire_prix_internet_cinq_offres_au_plus() -> None:
    offres = [
        _offre(prix=10.00 + i, source_url=f"https://s{i}.test/p") for i in range(7)
    ]
    pages = [_page(f"https://s{i}.test/p", f"{10 + i},00 €") for i in range(7)]

    resultat = lire_prix_internet(
        {"statut": "trouve", "raison": "", "offres": offres}, pages
    )

    assert [o.source_url for o in resultat.offres] == [
        f"https://s{i}.test/p" for i in range(5)
    ]


def test_lire_prix_internet_toutes_inconnues_premiere_offre_en_tete() -> None:
    """Point de vigilance 3."""
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=15.00, taxes="inconnu", source_url="https://a.test/p"),
            _offre(prix=9.00, taxes="inconnu", source_url="https://b.test/p"),
        ],
    }
    pages = [_page("https://a.test/p", "15,00 €"), _page("https://b.test/p", "9,00 €")]

    resultat = lire_prix_internet(structure, pages)

    assert resultat.source_url == "https://a.test/p"
    assert all(o.prix_ht is None for o in resultat.offres)


def test_controles_prix_internet_une_ligne_par_offre() -> None:
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=10.00, source_url="https://www.a.test/p"),
            _offre(prix=11.00, source_url="https://b.test/p"),
        ],
    }
    pages = [_page("https://www.a.test/p", "10,00 €")]

    controles = controles_prix_internet(structure, pages)

    assert [(c.nom, c.ok) for c in controles] == [
        ("L'IA annonce un prix, pas « non vérifiable »", True),
        ("Offre 1 — a.test", True),
        ("Offre 2 — b.test", False),
    ]
    assert (
        controles[2].detail
        == "écartée : aucune page ouverte à l'adresse https://b.test/p"
    )


def test_controles_prix_internet_coherents_avec_lire() -> None:
    structure = {
        "statut": "trouve",
        "raison": "",
        "offres": [
            _offre(prix=10.00, source_url="https://a.test/p"),
            _offre(prix=11.00, source_url="https://b.test/p"),
        ],
    }
    pages = [_page("https://a.test/p", "10,00 €"), _page("https://b.test/p", "11,00 €")]

    gardees = sum(1 for c in controles_prix_internet(structure, pages)[1:] if c.ok)

    assert gardees == len(lire_prix_internet(structure, pages).offres)
```

Adapter ensuite les tests existants de la section prix : ceux qui lisent les quatre contrôles d'une seule offre (`controles_prix_internet`) attendent désormais le contrôle du statut puis **une ligne « Offre 1 — domaine »** dont le `detail` porte la raison (`"écartée : champ manquant ou invalide (prix, devise, source ou confiance)"`, `"écartée : aucune page ouverte à l'adresse …"`, `"écartée : prix absent du texte de la page lue"`) ou `"gardée : page … lue, prix retrouvé"`. Les tests de la garde 4 (formats de prix) passent par `_structure_trouve` et gardent leurs assertions.

- [ ] **Étape 2 : lancer, constater l'échec.** `flock /tmp/habitat_reno-tests.lock uv run pytest app/modules/extract/tests/test_reponses_ia.py -q` → échecs (`prix_ht` introuvable, `offres` absent).

- [ ] **Étape 3 : implémentation.** Dans `reponses_ia.py` :

```python
SCHEMA_PRIX_INTERNET: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["statut", "raison", "offres"],
    "properties": {
        "statut": {"type": "string", "enum": ["trouve", "prix_non_verifiable"]},
        "raison": {"type": "string"},
        "offres": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "produit_trouve",
                    "prix",
                    "devise",
                    "taxes",
                    "unite",
                    "conditionnement",
                    "source_url",
                    "confiance",
                ],
                "properties": {
                    "produit_trouve": {"type": "string"},
                    "prix": {"type": "number"},
                    "devise": {"type": "string"},
                    "taxes": {"type": "string", "enum": ["HT", "TTC", "inconnu"]},
                    "unite": {"type": "string"},
                    "conditionnement": {"type": "string"},
                    "source_url": {"type": "string"},
                    "confiance": {
                        "type": "string",
                        "enum": ["faible", "moyenne", "elevee"],
                    },
                },
            },
        },
    },
}

OFFRES_MAX = 5
TVA_PRIX_INTERNET = Decimal("1.20")
_CENTIME = Decimal("0.01")


def prix_ht(prix: Decimal, taxes: str | None) -> Decimal | None:
    """Prix ramené en HT pour comparer des offres entre elles et au prix
    facturé (HT) : `HT` tel quel, `TTC` ÷ 1,20 (TVA 20 %), au centime ;
    `None` quand le site ne dit ni HT ni TTC (décision d'Ilane du
    29/09/2026 : une telle offre reste listée mais ne compte ni dans le plus
    bas ni dans l'écart)."""
    if taxes == "HT":
        return prix.quantize(_CENTIME, rounding=ROUND_HALF_UP)
    if taxes == "TTC":
        return (prix / TVA_PRIX_INTERNET).quantize(_CENTIME, rounding=ROUND_HALF_UP)
    return None


@dataclass(frozen=True)
class OffreLue:
    prix: Decimal
    devise: str
    taxes: Literal["HT", "TTC"] | None
    prix_ht: Decimal | None
    unite: str | None
    conditionnement: str | None
    produit_trouve: str
    source_url: str
    confiance: str
```

Ajouter `offres: tuple[OffreLue, ...] = ()` à la fin de `PrixInternetLu` (importer `ROUND_HALF_UP` depuis `decimal`, `urlsplit` est déjà importé). Remplacer `_gardes_prix_internet` par une évaluation offre par offre, en réutilisant **sans les dupliquer** `_est_prix_valide`, `_page_ouverte`, `_normaliser_adresse`, `_prix_dans_texte`, `_texte_ou_none` :

```python
_NOM_GARDE_STATUT = "L'IA annonce un prix, pas « non vérifiable »"
_NOM_AUCUNE_OFFRE = "Au moins une offre"


def _domaine(adresse: Any) -> str | None:
    if not isinstance(adresse, str):
        return None
    hote = urlsplit(adresse).netloc.lower()
    return hote.removeprefix("www.") or None


def _nom_offre(indice: int, offre_brute: Any) -> str:
    domaine = (
        _domaine(offre_brute.get("source_url"))
        if isinstance(offre_brute, dict)
        else None
    )
    return f"Offre {indice} — {domaine}" if domaine else f"Offre {indice}"


def _evaluer_offre(
    offre_brute: Any, pages: Sequence[PageLue]
) -> tuple[OffreLue | None, str, str]:
    """Gardes 2 à 4 du §6.2 sur une offre -> `(offre gardée ou None,
    raison courte, détail pour le Laboratoire)`."""
    if not isinstance(offre_brute, dict):
        return None, "réponse incomplète", _DETAIL_INCOMPLETE
    prix_brut = offre_brute.get("prix")
    devise_brute = offre_brute.get("devise")
    source_url = _texte_ou_none(offre_brute.get("source_url"))
    produit_trouve = _texte_ou_none(offre_brute.get("produit_trouve"))
    confiance = offre_brute.get("confiance")
    if (
        not (
            _est_prix_valide(prix_brut)
            and isinstance(devise_brute, str)
            and devise_brute.strip().upper() == "EUR"
            and source_url is not None
            and source_url.startswith("https://")
            and produit_trouve is not None
            and confiance in _CONFIANCES_VALIDES
        )
        or source_url is None
        or produit_trouve is None
    ):
        return None, "réponse incomplète", _DETAIL_INCOMPLETE
    page = _page_ouverte(source_url, pages)
    if page is None:
        return (
            None,
            "source non ouverte",
            f"écartée : aucune page ouverte à l'adresse {source_url}",
        )
    prix = Decimal(str(prix_brut)).quantize(Decimal("0.0001"))
    if not _prix_dans_texte(prix, page.texte):
        return (
            None,
            "prix absent de la page",
            "écartée : prix absent du texte de la page lue",
        )
    taxes_brut = offre_brute.get("taxes")
    taxes: Literal["HT", "TTC"] | None = (
        taxes_brut if taxes_brut in _TAXES_VALIDES else None
    )
    offre = OffreLue(
        prix=prix,
        devise="EUR",
        taxes=taxes,
        prix_ht=prix_ht(prix, taxes),
        unite=_texte_ou_none(offre_brute.get("unite")),
        conditionnement=_texte_ou_none(offre_brute.get("conditionnement")),
        produit_trouve=produit_trouve,
        source_url=source_url,
        confiance=str(confiance),
    )
    return offre, "", f"gardée : page {source_url} lue, prix retrouvé"


_DETAIL_INCOMPLETE = (
    "écartée : champ manquant ou invalide (prix, devise, source ou confiance)"
)
```

`_gardes_prix_internet(structure, pages) -> tuple[PrixInternetLu, tuple[Controle, ...]]` :
1. `statut == "prix_non_verifiable"` → `_non_verifiable(structure, raison)` (raison actuelle), contrôles `(Controle(_NOM_GARDE_STATUT, False, "l'IA répond « prix non vérifiable »"),)` ;
2. `statut != "trouve"` → « réponse incomplète », `(Controle(_NOM_GARDE_STATUT, False, "réponse de l'IA sans statut exploitable"),)` ;
3. sinon `Controle(_NOM_GARDE_STATUT, True, "l'IA répond « trouvé »")`, puis pour chaque élément de `offres` (liste, sinon `[]`), avec `indice` à partir de 1 : si `OFFRES_MAX` offres sont déjà gardées → `"écartée : au-delà des 5 offres gardées"` ; sinon `_evaluer_offre` ; une offre gardée dont `_normaliser_adresse(source_url)` est déjà gardée → `"écartée : même page qu'une offre déjà gardée"` ; mémoriser la raison de la **première** offre écartée par `_evaluer_offre` ;
4. liste vide → ajouter `Controle(_NOM_AUCUNE_OFFRE, False, "aucune offre dans la réponse")` ;
5. aucune gardée → `_non_verifiable(structure, premiere_raison or "aucune offre")` ;
6. sinon trier `sorted(gardees, key=lambda o: (o.prix_ht is None, o.prix_ht or Decimal(0)))` (tri stable) et renvoyer `PrixInternetLu(statut="trouve", prix=m.prix, devise="EUR", taxes=m.taxes, unite=m.unite, conditionnement=m.conditionnement, produit_trouve=m.produit_trouve, source_url=m.source_url, confiance=m.confiance, raison=None, offres=tuple(triees))` avec `m = triees[0]`.

`_non_verifiable(structure, raison)` : `produit_trouve` et `source_url` pris dans la **première offre** de `offres` quand elle existe (dict), sinon `None`. `controles_prix_internet` sur une structure qui n'est pas un dict → `(Controle(_NOM_GARDE_STATUT, False, "réponse de l'IA invalide"),)`. Supprimer les constantes et branches devenues inutiles (`_NOM_GARDE_COMPLETE`, etc.) seulement si plus aucun code ne les utilise ; mettre à jour les docstrings (§6.2 de la spec d'origine + ce plan).

- [ ] **Étape 4 : adapter les données de test des autres modules.** Lancer `flock /tmp/habitat_reno-tests.lock uv run pytest app/modules/ingest app/modules/api tests -q -x -k "prix or labo or essai"` ; chaque réponse `trouve` construite à plat dans ces tests (ex. `_reponses_prix_trouve` de `test_ia_prix.py`, `_reponses_opencode_prix_trouve` de `test_ia_prix_bout_en_bout.py`, les essais de `test_ia_labo.py`) devient `{"statut": "trouve", "raison": "", "offres": [{…les mêmes champs…}]}`. Aucune assertion métier ne change (une seule offre = même résultat qu'avant).

- [ ] **Étape 5 : vérifier.** Toute la suite ciblée ci-dessus + `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, `flock /tmp/habitat_reno-tests.lock uv run pytest tests/test_frontieres.py -q`.

- [ ] **Étape 6 : commit** `extract: prix internet, jusqu'à cinq offres contrôlées une à une et ramenées en HT`.

---

### Tâche 2 : colonne `prix_internet.offres` (migration `0015`)

**Fichiers :**
- Créer : `migrations/versions/0015_prix_internet_offres.py`
- Modifier : `app/modules/ingest/models.py` (classe `PrixInternet`)
- Tests : `tests/test_migrations.py`

**Interfaces produites :** `PrixInternet.offres: Mapped[list[dict[str, Any]]]` — chaque élément `{"prix": "13.9100", "devise": "EUR", "taxes": "HT"|"TTC"|None, "unite", "conditionnement", "produit_trouve", "source_url", "confiance"}` (prix en **texte** décimal).

- [ ] **Étape 1 : test qui échoue** (dans `tests/test_migrations.py`) :

```python
def test_migration_0015_reprend_les_prix_trouves_comme_une_offre(
    test_database_url: str,
) -> None:
    url = url_base_migrations(test_database_url)
    preparer_base(url)
    command.downgrade(_config(url), "0014")

    async def _inserer() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connexion:
                await connexion.execute(
                    text(
                        "INSERT INTO prix_internet (cle, designation, statut, prix, "
                        "devise, taxes, unite, conditionnement, produit_trouve, "
                        "source_url, confiance, consulte_le) VALUES "
                        "('ref:a', 'Produit A', 'trouve', 13.91, 'EUR', 'TTC', 'u', "
                        "'sac de 25 kg', 'Produit A trouvé', 'https://a.test/p', "
                        "'elevee', now()), "
                        "('ref:b', 'Produit B', 'non_verifiable', NULL, NULL, NULL, "
                        "NULL, NULL, NULL, NULL, NULL, now())"
                    )
                )
        finally:
            await engine.dispose()

    async def _lire() -> dict[str, Any]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connexion:
                lignes = await connexion.execute(
                    text("SELECT cle, offres FROM prix_internet ORDER BY cle")
                )
                return {cle: offres for cle, offres in lignes}
        finally:
            await engine.dispose()

    asyncio.run(_inserer())
    command.upgrade(_config(url), "head")
    offres = asyncio.run(_lire())

    assert offres["ref:b"] == []
    assert offres["ref:a"] == [
        {
            "prix": "13.9100",
            "devise": "EUR",
            "taxes": "TTC",
            "unite": "u",
            "conditionnement": "sac de 25 kg",
            "produit_trouve": "Produit A trouvé",
            "source_url": "https://a.test/p",
            "confiance": "elevee",
        }
    ]

    command.downgrade(_config(url), "0014")
    command.upgrade(_config(url), "head")
```

(Importer `Any` depuis `typing`. Nettoyer ces deux lignes à la fin n'est pas nécessaire : la base `_migrations` est dédiée.)

- [ ] **Étape 2 : lancer, constater l'échec** : `flock /tmp/habitat_reno-tests.lock uv run pytest tests/test_migrations.py -q` → colonne `offres` inexistante.

- [ ] **Étape 3 : modèle et migration.** Dans `PrixInternet` (après `modele`) :

```python
    # Jusqu'à cinq offres vérifiées (migration 0015, spec du 29/09/2026) ;
    # les colonnes ci-dessus décrivent la moins chère en HT.
    offres: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
```

Migration (docstring en français sur le modèle de `0014_ia.py`, `revision = "0015"`, `down_revision = "0014"`) :

```python
def upgrade() -> None:
    op.add_column(
        "prix_internet",
        sa.Column(
            "offres",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE prix_internet
        SET offres = jsonb_build_array(jsonb_build_object(
            'prix', prix::text,
            'devise', devise,
            'taxes', taxes,
            'unite', unite,
            'conditionnement', conditionnement,
            'produit_trouve', produit_trouve,
            'source_url', source_url,
            'confiance', confiance
        ))
        WHERE statut = 'trouve'
        """
    )


def downgrade() -> None:
    op.drop_column("prix_internet", "offres")
```

- [ ] **Étape 4 : vérifier** : `tests/test_migrations.py` entier (dont `test_alembic_check_sans_derive` : aucune dérive modèle/base), puis `flock /tmp/habitat_reno-tests.lock uv run pytest app/modules/ingest/tests/test_ia_prix.py -q`, ruff, mypy.

- [ ] **Étape 5 : commit** `migrations: 0015, colonne prix_internet.offres et reprise des prix trouvés`.

---

### Tâche 3 : enregistrer et restituer les offres (`ingest`, consignes, CLI, Laboratoire)

**Fichiers :**
- Modifier : `app/modules/ingest/ia_prix.py`, `app/modules/ingest/ia_labo.py` (`_resultat_prix`), `app/cli.py` (`_ENTETE_CSV_ESSAI`, `_champs_csv_essai`), `deploy/opencode/opencode.json` (agent `habitat-prix`), `docs/phase-4-ia.md` (§ prix internet : une phrase sur les cinq offres et le HT)
- Tests : `app/modules/ingest/tests/test_ia_prix.py`, `app/modules/ingest/tests/test_ia_labo.py`, `tests/test_opencode_config.py`, `tests/test_cli.py` (essai `essai-prix-internet`)

**Interfaces consommées :** `OffreLue`, `PrixInternetLu.offres`, `prix_ht` (tâche 1) ; `PrixInternet.offres` (tâche 2).

**Interfaces produites :**
- `@dataclass(frozen=True) class OffreVue: prix: Decimal; devise: str | None; taxes: str | None; prix_ht: Decimal | None; unite: str | None; conditionnement: str | None; produit_trouve: str | None; source_url: str | None; confiance: str | None`
- `PrixInternetVue` gagne `offres: tuple[OffreVue, ...]`, `prix_ht_min: Decimal | None`, `prix_ht_max: Decimal | None`, `nb_sources: int` (0 pour `non_verifiable`)
- `_resultat_prix` (Laboratoire) gagne la clé `"offres"` : liste de dicts `{prix, taxes, prix_ht, unite, conditionnement, produit_trouve, source_url, confiance}` (décimaux en texte)

- [ ] **Étape 1 : tests qui échouent.**
  - `test_ia_prix.py` : une recherche `trouve` à deux offres (TTC 13,91 et HT 12,00, pages ouvertes) enregistre une ligne dont `offres` contient les deux offres (prix en texte), les colonnes = celle à 11,59 HT ; la vue (`avis_ia_anomalie` ou `prix_internet_des_anomalies`) renvoie `nb_sources == 2`, `prix_ht_min == Decimal("11.59")`, `prix_ht_max == Decimal("12.00")`, offres triées ; une ligne `trouve` **sans** offres (insérée à la main avec `offres=[]`) donne `nb_sources == 1` et une offre reconstituée depuis ses colonnes (point de vigilance 4) ; offres toutes « inconnu » → `prix_ht_min is None and prix_ht_max is None` (point de vigilance 3) ; le texte envoyé contient « jusqu'à cinq offres » et « sites différents ».
  - `tests/test_opencode_config.py` : `steps` de `habitat-prix` = 14 ; la consigne contient « jusqu'à cinq » et « même conditionnement ».
  - `test_ia_labo.py` : le résultat d'un essai `trouve` porte `resultat["offres"]` (liste, prix en texte).
  - test du CLI : l'en-tête CSV se termine par `nb_sources`, `prix_ht_min`, `prix_ht_max` (après `duree_s`).
- [ ] **Étape 2 : lancer, constater l'échec.**
- [ ] **Étape 3 : implémentation.**
  - `_CONSIGNE_PRIX` (texte envoyé) : ajouter, après l'identification du produit : « Cherche jusqu'à cinq offres de sites différents pour ce même produit au même format, chacune avec son prix pour le même conditionnement (jamais un prix au mètre à côté d'un prix à la pièce), et ouvre la page de chacune avec webfetch. Une seule offre sûre vaut mieux que plusieurs douteuses. » ; `rechercher_prix` : `delai=300`.
  - `opencode.json`, agent `habitat-prix` : `"steps": 14` ; consigne : remplacer « fais au plus trois recherches et ouvre au plus trois pages » par « fais au plus cinq recherches et ouvre au plus six pages » et ajouter la phrase des cinq offres ci-dessus (même formulation).
  - Écriture (`chercher_prix_internet`) : `offres=[_offre_json(o) for o in resultat.offres]` avec

```python
def _offre_json(offre: OffreLue) -> dict[str, Any]:
    return {
        "prix": str(offre.prix),
        "devise": offre.devise,
        "taxes": offre.taxes,
        "unite": offre.unite,
        "conditionnement": offre.conditionnement,
        "produit_trouve": offre.produit_trouve,
        "source_url": offre.source_url,
        "confiance": offre.confiance,
    }
```

    (`_ligne_prix_echec` : `offres=[]` explicite.)
  - Vue (`_vue_prix_internet(ligne)`) : offres lues depuis `ligne.offres` (`Decimal(o["prix"])`, `prix_ht(prix, o.get("taxes"))`) ; si `ligne.statut == "trouve"` et `ligne.offres` vide → une offre depuis les colonnes ; tri identique à la tâche 1 ; `prix_ht_min`/`max` = min/max des `prix_ht` non nuls (sinon `None`) ; `nb_sources = len(offres)`.
  - `_resultat_prix` : ajouter `"offres"`.
  - CLI : trois colonnes en fin de ligne (`len(resultat.offres)`, min et max des `prix_ht` non nuls en texte, vides sinon ; ligne d'échec : trois champs vides).
- [ ] **Étape 4 : vérifier** : `flock /tmp/habitat_reno-tests.lock uv run pytest app/modules/ingest tests/test_opencode_config.py tests/test_frontieres.py -q` + `tests/test_cli.py`, ruff, mypy.
- [ ] **Étape 5 : commit** `ingest: prix internet, offres enregistrées, plus bas et plus haut HT, consignes à cinq offres`.

---

### Tâche 4 : API

**Fichiers :**
- Modifier : `app/modules/api/schemas.py` (`PrixInternetReponse`), `web/openapi.json`, `web/src/api/schema.d.ts`
- Tests : `app/modules/api/tests/test_ia.py`

**Interfaces consommées :** `OffreVue`, `PrixInternetVue` (tâche 3).
**Interfaces produites :** `OffrePrixInternetReponse` (mêmes champs qu'`OffreVue`) ; `PrixInternetReponse` + `offres: list[OffrePrixInternetReponse]`, `prix_ht_min: Decimal | None`, `prix_ht_max: Decimal | None`, `nb_sources: int`.

- [ ] **Étape 1 : test qui échoue** dans `test_ia.py` : `GET /api/ia/prix-internet?anomalie_id=…` sur un prix à deux offres renvoie `nb_sources == 2`, `prix_ht_min == "11.59"`, `prix_ht_max == "12.00"` et `offres[0]["source_url"]` = la moins chère ; `GET /api/ia/anomalies/{id}` porte les mêmes champs.
- [ ] **Étape 2 : lancer, constater l'échec.**
- [ ] **Étape 3 : implémentation** (`ConfigDict(from_attributes=True)`, docstrings en français), puis régénérer : `cd web && npm run api:schema && npm run api:types` (lit `.env` via `uv run --env-file` : ne jamais afficher ce fichier).
- [ ] **Étape 4 : vérifier** : tests API ciblés, `cd web && npm run typecheck`, ruff, mypy.
- [ ] **Étape 5 : commit** `api: prix internet, offres, plus bas et plus haut HT, nombre de sources`.

---

### Tâche 5 : écrans (page Prix, Avis de l'IA, Laboratoire)

**Fichiers :**
- Créer : `web/src/components/OffresPrixInternet.tsx`
- Modifier : `web/src/lib/prixInternet.ts`, `web/src/components/PrixInternetCellule.tsx`, `web/src/components/AvisIA.tsx`, `web/src/pages/LaboIA.tsx`
- Tests : créer `tests/test_web_offres_prix_internet.py` (tests texte, style de `tests/test_web_labo_ia.py`)

**Interfaces consommées :** `PrixInternet` (`offres`, `prix_ht_min`, `prix_ht_max`, `nb_sources`) de `web/src/api/ia.ts` ; `texteMontantPrixInternet`, `domaineSource`, `MontantPrixInternet` de `lib/prixInternet.ts`.

- [ ] **Étape 1 : tests texte qui échouent** : `OffresPrixInternet.tsx` existe, exporte `OffresPrixInternet`, utilise `domaineSource` (aucun lien sans `https:`, point de vigilance 5), `rel="noopener noreferrer"`, `<details>`, `min-h-[44px]` ; `lib/prixInternet.ts` exporte `texteResumeOffres` et contient « dès », « sources », « jusqu'à » ; `PrixInternetCellule.tsx` et `AvisIA.tsx` utilisent `OffresPrixInternet` et `texteResumeOffres` ; `LaboIA.tsx` affiche `resultat.offres`.
- [ ] **Étape 2 : lancer, constater l'échec.**
- [ ] **Étape 3 : implémentation.**
  - `lib/prixInternet.ts` :

```ts
/** « dès 11,59 € HT · 3 sources (jusqu'à 13,91 € HT) » -- `null` quand il
 * n'y a qu'une source (l'affichage d'une offre unique reste celui d'avant)
 * ou qu'aucune offre n'a de prix HT connu (point de vigilance 3). */
export function texteResumeOffres(prixInternet: PrixInternet): string | null {
  if (prixInternet.nb_sources < 2 || prixInternet.prix_ht_min === null) {
    return null;
  }
  const jusqua =
    prixInternet.prix_ht_max !== null && prixInternet.prix_ht_max !== prixInternet.prix_ht_min
      ? ` (jusqu'à ${formaterMontant(prixInternet.prix_ht_max)} HT)`
      : "";
  return `dès ${formaterMontant(prixInternet.prix_ht_min)} HT · ${prixInternet.nb_sources} sources${jusqua}`;
}
```

  - `components/OffresPrixInternet.tsx` : `<details>` « Voir les N offres » (cible 44 px), liste `<ul>` ; par offre : `texteMontantPrixInternet(offre)`, puis « soit X € HT » si `offre.taxes === "TTC" && offre.prix_ht !== null`, puis lien `source (domaine)` seulement si `domaineSource(offre.source_url)` n'est pas `null`, `target="_blank" rel="noopener noreferrer"`. Téléphone : éléments empilés.
  - `PrixInternetCellule` (statut `trouve`) : si `texteResumeOffres` renvoie un texte → ce texte, la date, puis `<OffresPrixInternet offres={prixInternet.offres} />` ; sinon affichage actuel inchangé.
  - `AvisIA.tsx::LignePrixInternet` : même logique (« Prix trouvé sur internet : dès … — consulté le … » + liste).
  - `LaboIA.tsx` (résultat `prix`, statut `trouve`) : sous « Prix trouvé : … », la liste des offres de `resultat.offres` (conversion avec `texteOuNull` déjà présent ; chaque offre : montant via `texteMontantPrixInternet`, lien via `domaineSource`).
- [ ] **Étape 4 : vérifier** : `flock /tmp/habitat_reno-tests.lock uv run pytest tests -q -k web`, `cd web && npm run typecheck && npm run build`, ruff.
- [ ] **Étape 5 : commit** `web: prix internet, plus bas HT, nombre de sources et liste des offres`.

---

### Après les tâches (contrôleur)

- Relecture de toute la branche (sous-agent Sonnet), corrections éventuelles.
- Suite complète verte, PR vers `dev`, fusion.
- Démo : dump, `build`, `alembic upgrade head` (0015), `up -d --wait api`, image OpenCode reconstruite depuis la branche, arbre de déploiement remis sur l'étiquette.
- Essai réel sur les 20 produits de l'essai du 29/09 ; compte rendu à Ilane.
