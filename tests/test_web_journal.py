from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).parents[1] / "web" / "src"

# Mots interdits dans un libellé affiché (fix round 1 de la revue de la
# Task 10) : code d'architecture interne, jamais montré à l'écran.
MOTS_INTERDITS = ["rapproch", "alias", "bloc", "ocr", "uuid"]


def _textes_affiches(source: str) -> str:
    """Texte réellement visible d'un composant : contenu JSX statique entre
    balises (jamais une expression dynamique `{...}`, qui n'est pas un
    libellé écrit ici) plus quelques attributs affichés (`placeholder`,
    `aria-label`). Exclut volontairement `className` : des utilitaires
    Tailwind comme `block`/`inline-block` contiennent « bloc » sans rapport
    avec le jargon métier."""
    textes = re.findall(r">([^<{]+)<", source)
    textes += re.findall(r'placeholder="([^"]*)"', source)
    textes += re.findall(r'aria-label="([^"]*)"', source)
    return " ".join(textes)


def test_route_et_navigation_journal_sont_admin() -> None:
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    gabarit = (WEB / "components" / "Gabarit.tsx").read_text(encoding="utf-8")

    assert 'path="journal"' in app
    assert "<Journal />" in app
    assert 'to="/journal"' in gabarit
    assert "Journal" in gabarit


def test_lib_journal_connait_chantier_modifie() -> None:
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    assert 'chantier_modifie: "Chantier modifié"' in journal_lib


def test_ecran_journal_a_la_charte() -> None:
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")

    assert '"../ui"' in page
    assert "<EnTetePage" in page
    assert "<Carte" in page
    assert "<Filtres" in page
    assert "EtatVide" in page
    # Ancienne palette Tailwind par défaut entièrement remplacée par les
    # jetons de la charte (habillage complet, pas un correctif partiel).
    assert "slate-" not in page


def test_ecran_journal_tableau_ordinateur_cartes_telephone() -> None:
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")

    # Tableau conservé pour l'ordinateur (>= md), masqué sur téléphone ;
    # les mêmes entrées sont présentées en cartes empilées sous `md`
    # (contrainte téléphone = cible à part entière). Chaîne de classes
    # exacte (pas seulement "hidden" et "md:block" séparément, qui
    # matcheraient n'importe quel autre usage de ces classes ailleurs sur
    # la page).
    assert "<table" in page
    assert "md:hidden" in page
    assert 'className="hidden overflow-x-auto md:block"' in page


def test_ecran_journal_tableau_ne_deborde_pas() -> None:
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")

    # `table-fixed` (pas de `min-w-[...]`) et les longues valeurs brutes
    # (JSON, identifiants) peuvent se couper n'importe où : sans ça, une
    # valeur de détail sans espace pousse le tableau, puis la page, en
    # débordement horizontal (constat de la revue, captures 1440/375 trop
    # larges) — tient seul, sans dépendre du correctif `min-w-0` que le
    # contrôleur pose séparément dans `Gabarit.tsx`.
    assert "table-fixed" in page
    assert "min-w-[900px]" not in page
    assert page.count("[overflow-wrap:anywhere]") >= 5


def test_lib_journal_libelles_sans_jargon() -> None:
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    # Valeurs des tables de correspondance (`cle: "valeur affichée"`) : pas
    # les clés techniques (identifiants internes, jamais montrées telles
    # quelles) ni les commentaires (qui citent légitimement des noms de
    # fichier comme `rapprochement.py`).
    valeurs = " ".join(re.findall(r':\s*"([^"]*)"', journal_lib)).lower()
    for mot in MOTS_INTERDITS:
        assert mot not in valeurs, (
            f"mot interdit « {mot} » dans un libellé de lib/journal.ts"
        )


def test_lib_journal_cles_detail_backend_sans_jargon() -> None:
    """Toute clé de détail (`avant`/`apres`) écrite littéralement dans
    `app/modules/ingest/` et contenant un mot interdit doit avoir une
    traduction dans `LIBELLES_CLE_DETAIL` (`lib/journal.ts`) — sinon le
    repli sur la clé brute (`libelleCleDetail`) affiche le jargon à l'écran.
    Régression du constat de la revue (`nb_demandes_alias`, oubliée au fix
    round 1 de la Task 10 : le mot « alias » se serait affiché tel quel
    pour toute entrée `facture_deposee` avec au moins un chantier non
    reconnu)."""
    app_ingest = Path(__file__).parents[1] / "app" / "modules" / "ingest"
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    cles: set[str] = set()
    for fichier in sorted(app_ingest.glob("*.py")):
        if "test" in fichier.name:
            continue
        texte = fichier.read_text(encoding="utf-8")
        for bloc in re.finditer(r"(?:avant|apres)\s*=\s*\{([^}]*)\}", texte, re.S):
            cles.update(re.findall(r'"(\w+)"\s*:', bloc.group(1)))

    cles_en_jargon = sorted(
        cle for cle in cles if any(mot in cle.lower() for mot in MOTS_INTERDITS)
    )
    assert cles_en_jargon, "aucune clé de détail suspecte trouvée : regex à revoir"
    for cle in cles_en_jargon:
        assert f'{cle}: "' in journal_lib, (
            f"clé de détail « {cle} » (app/modules/ingest/) contient un mot "
            "interdit et n'a pas de traduction dans LIBELLES_CLE_DETAIL"
        )


def test_pages_reglages_journal_sans_jargon_visible() -> None:
    reglages = (WEB / "pages" / "Reglages.tsx").read_text(encoding="utf-8")
    journal = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")

    texte = (_textes_affiches(reglages) + " " + _textes_affiches(journal)).lower()
    for mot in MOTS_INTERDITS:
        assert mot not in texte, f"mot interdit « {mot} » visible sur Réglages/Journal"


def test_lib_journal_traduit_cibles_et_detail() -> None:
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")

    assert "export function libelleCible" in journal_lib
    assert "libelleCible" in page
    # Valeurs statut/gravité/règle traduites en langage courant plutôt que
    # laissées brutes (`ouverte`/`traitee`/`ignoree`, code de règle).
    assert "titreRegle" in journal_lib
    assert "urgence" in journal_lib
    assert '"Ouvert"' in journal_lib
    assert '"Réglé"' in journal_lib
    assert '"Ignoré"' in journal_lib


def test_ecran_journal_filtre_auteur_et_element_concerne() -> None:
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")

    assert re.search(r">\s*Auteur\s*<", page) is not None
    assert re.search(r">\s*Élément concerné\s*<", page) is not None
    assert "<fieldset" in page
    assert "<legend" in page


def test_dette_documente_le_filtre_auteur() -> None:
    dette = (Path(__file__).parents[1] / "docs" / "dette.md").read_text(
        encoding="utf-8"
    )

    assert "filtre auteur" in dette.lower() or "filtre « auteur »" in dette.lower()


def test_ecran_journal_filtres_toujours_combinables() -> None:
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")

    assert "ACTIONS_CONNUES" in page
    assert "CIBLES_CONNUES" in page
    assert "utilisateurId" in page or "utilisateur_id" in page
    assert "depuis" in page
    assert "jusquA" in page


def test_ecran_journal_avant_apres_sans_calcul() -> None:
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")
    lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    # Aucune règle métier dans le front : la comparaison `avant`/`apres`
    # reste déléguée à `lib/journal.ts` (mise en forme uniquement).
    assert "lignesAvantApres" in page
    assert "lignesAvantApres" in lib
