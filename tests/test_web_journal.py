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


def test_lib_journal_toutes_les_actions_litterales_ont_un_libelle() -> None:
    """Chaque action journalisée par un littéral (`Journal(action="...")`,
    `app/modules/ingest/*.py` et `app/core/auth.py`) doit avoir une entrée
    dans `LIBELLES_ACTION` (`lib/journal.ts`) -- sinon `libelleAction`
    affiche le code brut à l'écran. Régression de Task 12 (controller
    ruling 2) : l'avenant du 27/09/2026 (rattachement automatique du
    chantier, `rattachement_chantier.py`/`fusion_chantier.py`) avait
    ajouté quatre actions (`chantier_cree_auto`, `alias_rattache_auto`,
    `chantier_choisi`, `chantier_fusionne`) jamais recensées ici.

    Deux actions sont choisies dynamiquement plutôt qu'écrites en littéral
    (`anomalies.py::_ACTION_JOURNAL_PAR_STATUT`,
    `depot_telegram.py::_ACTIONS_JOURNAL`) : la regex ci-dessous ne les voit
    pas, leurs valeurs possibles sont donc vérifiées séparément."""
    app_ingest = Path(__file__).parents[1] / "app" / "modules" / "ingest"
    fichiers = [
        *sorted(app_ingest.glob("*.py")),
        Path(__file__).parents[1] / "app" / "core" / "auth.py",
    ]
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    actions: set[str] = set()
    for fichier in fichiers:
        if "test" in fichier.name:
            continue
        texte = fichier.read_text(encoding="utf-8")
        actions.update(re.findall(r'action="(\w+)"', texte))

    assert actions, "aucune action littérale trouvée : regex à revoir"
    manquantes = sorted(
        action for action in actions if f'{action}: "' not in journal_lib
    )
    assert not manquantes, (
        f"action(s) sans libellé dans LIBELLES_CLE_DETAIL : {manquantes} — "
        "`libelleAction` afficherait le code brut"
    )

    # Actions choisies dynamiquement (non littérales, invisibles à la regex
    # ci-dessus) : couvertes séparément, mêmes valeurs que
    # `anomalies.py::_ACTION_JOURNAL_PAR_STATUT` et
    # `depot_telegram.py::_ACTIONS_JOURNAL`.
    for action_dynamique in (
        "anomalie_traitee",
        "anomalie_ignoree",
        "quantites_verifiees",
        "ecart_constate",
    ):
        assert f'{action_dynamique}: "' in journal_lib


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


def test_journal_transmet_noms_resolus_par_le_serveur() -> None:
    """Task 12 (spec §4.1) : `entree.noms` (résolution serveur des
    identifiants d'`avant`/`apres`, `ingest/journal.py`) est transmis par
    l'écran à `lignesAvantApres`, qui l'utilise pour afficher un nom plutôt
    que l'UUID brut -- jamais recalculé côté front, qui n'a pas les
    référentiels."""
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")
    lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    assert page.count("noms={entree.noms}") == 2
    assert "lignesAvantApres(avant, apres, noms)" in page
    assert "noms[brute]" in lib
    assert "(inconnu)" in lib


def _cles_table_ts(source: str, nom_table: str) -> set[str]:
    """Clés (non citées) d'une table `const NOM: Record<string, string> =
    {...}` de `lib/journal.ts` — même mécanique que `libelleCleDetail` côté
    TypeScript, pour vérifier ici qu'une clé recensée y a bien une entrée."""
    match = re.search(
        rf"const {nom_table}\s*:\s*Record<string, string>\s*=\s*\{{(.*?)\n\}};",
        source,
        re.S,
    )
    assert match is not None, f"table {nom_table} introuvable dans lib/journal.ts"
    return set(re.findall(r"^\s*(\w+):\s*\"", match.group(1), re.M))


def test_lib_journal_toutes_les_cles_de_detail_ont_un_libelle() -> None:
    """Recensement exhaustif des clés `avant`/`apres` de premier niveau —
    lecture de chaque appel `Journal(...)` d'`app/modules/ingest/*.py` et
    `app/core/auth.py` (tour 2 de la revue de la Task 10, 23/09/2026), y
    compris celles produites par une compréhension de dict
    (`corriger_entete`, clés ⊂ `CHAMPS_CORRIGEABLES`) ou par une fonction
    utilitaire (`_valeurs_document_pour_journal`, `_ligne_en_chaine`) que la
    simple regex de `test_lib_journal_cles_detail_backend_sans_jargon` ne
    voit pas. Chacune doit avoir un libellé dans `LIBELLES_CLE_DETAIL`, ou
    se terminer par `_id` avec un préfixe connu de `PREFIXES_ID` — sinon
    `libelleCleDetail` retombe sur la clé technique brute, affichée telle
    quelle à l'écran (constat de la revue : `nb_articles`, `numero`,
    `total_ht`, `nb_mis_a_jour`… affichées brutes sur `bl_demo_t10`)."""
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")
    connues = _cles_table_ts(journal_lib, "LIBELLES_CLE_DETAIL")
    prefixes_id = _cles_table_ts(journal_lib, "PREFIXES_ID")

    cles_recensees = {
        "regle",
        "gravite",
        "detail",
        "statut",
        "commentaire",
        "nb_lignes",
        "motifs",
        "fournisseur_id",
        "methode_fournisseur",
        "chantier_libelle",
        "chantier_id",
        "methode_chantier",
        "valeur",
        "numero",
        "total_ht",
        "nb_blocs",
        "nb_demandes_alias",
        "nb_articles",
        "nom",
        "siret",
        "tva",
        "aliases",
        "agences_ajoutees",
        "nom_canonique",
        "agence",
        "client",
        "actif",
        "libelle",
        "methode",
        "nb_mis_a_jour",
        "unite_cdt",
        "unite_fact",
        "ratio",
        "valide",
        "confirme_le",
        "confirme_par",
        "email",
        "role",
        "telegram_user_id",
        "nb_blocs_recus",
        "nb_blocs_pas_de_bon",
        "nb_lignes_appariees",
        "nb_anomalies",
        "type",
        "date_doc",
        "chantier_brut",
        "numero_commande",
        "enleve_par",
        "total_tva",
        "total_ttc",
        "lignes",
        # Avenant du 27/09/2026 (rattachement automatique du chantier,
        # `rattachement_chantier.py`/`fusion_chantier.py`) : six clés
        # manquantes de ce recensement (Task 12, controller ruling 2).
        "score_chantier",
        "source",
        "cible_id",
        "cible_nom",
        "nb_documents",
        "a_completer",
    }

    manquantes = []
    for cle in sorted(cles_recensees):
        if cle in connues:
            continue
        if cle.endswith("_id") and cle[: -len("_id")] in prefixes_id:
            continue
        manquantes.append(cle)

    assert not manquantes, (
        "clé(s) de détail sans libellé (ni LIBELLES_CLE_DETAIL ni "
        f"PREFIXES_ID) : {manquantes} — `libelleCleDetail` afficherait la "
        "clé brute"
    )


def test_lib_journal_aucune_valeur_json_stringifiee() -> None:
    """Le repli `JSON.stringify` d'une valeur objet ou liste affichait du
    JSON brut à l'écran (`{"date_bl":…}` sur un « Problème disparu », un
    tableau de codes bruts sur `motifs`, les lignes corrigées — constat de
    la revue, tour 2 de la Task 10) : plus aucun appel à `JSON.stringify`
    dans `lib/journal.ts`, chaque forme connue a sa propre mise en forme et
    le repli générique pour une forme non prévue construit volontairement
    une chaîne sans accolade ni crochet."""
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    # `JSON.stringify(` (l'appel, jamais un simple commentaire qui cite le
    # nom de la fonction pour expliquer pourquoi elle a disparu).
    assert "JSON.stringify(" not in journal_lib


def test_lib_journal_montants_et_dates_formates() -> None:
    """Un montant ou une date bruts du journal (`total_ht : 456.30`,
    `confirme_le` en ISO — constat de la revue, tour 2) passent par les
    mêmes formateurs que le reste du front, jamais affichés bruts."""
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    assert "formaterMontant" in journal_lib
    assert "formaterDate" in journal_lib
    assert "formaterDateHeure" in journal_lib


def test_lib_journal_detail_anomalie_reutilise_phrase_probleme() -> None:
    """Le détail d'un « Problème disparu » (`detail`) réutilise la même
    phrase chiffrée que l'écran « À régler » (`phraseProbleme`,
    `ui/libelles.ts`) plutôt que le JSON brut de son détail (constat de la
    revue, tour 2)."""
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    assert "phraseProbleme" in journal_lib


def test_lib_journal_cles_precises_de_la_revue() -> None:
    """Régression ciblée sur les clés citées par le constat de la revue
    (tour 2) : observées brutes sur les entrées « Facture déposée » et
    « Nom de chantier fournisseur reconnu » de `bl_demo_t10`."""
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    for cle, libelle in [
        ("nb_articles", "Articles"),
        ("numero", "Numéro"),
        ("total_ht", "Total HT"),
        ("nb_mis_a_jour", "Documents mis à jour"),
    ]:
        assert f'{cle}: "{libelle}"' in journal_lib


def test_lib_journal_libelle_cible_id_parametre() -> None:
    """La colonne Cible d'un « Réglage modifié » affichait la clé technique
    (`delai_confirmation_bl_h`) plutôt que le libellé du réglage — contraire
    à la consigne du brief (constat de la revue, tour 2) : `libelleCibleId`
    traduit `cible_id` pour la table `parametre`, `Journal.tsx` l'appelle
    des deux côtés (tableau et carte téléphone)."""
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")

    assert "export function libelleCibleId" in journal_lib
    assert '"Délai de confirmation d\'un BL"' in journal_lib
    assert page.count("libelleCibleId(entree.cible_table, entree.cible_id)") == 2


def test_ecran_journal_aide_auteur_sans_document_interne() -> None:
    """L'aide sous le filtre Auteur renvoyait à « la dette technique », un
    document interne (`docs/dette.md`) inaccessible au dirigeant — jargon de
    développeur laissé par le fix round 1 (constat de la revue, tour 2). La
    limite reste documentée dans `docs/dette.md`, ce qui suffit."""
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")

    assert "dette technique" not in page.lower()


def test_lib_journal_lignes_corrigees_detail_pas_seulement_resume() -> None:
    """Tour 3 de la revue de la Task 10 (23/09/2026) : pour une entrée
    « Lignes corrigées », le résumé posé au tour 2 (`formaterNombreLignes`,
    « n lignes ») ne montre pas ce qui a été corrigé — et quand la
    correction ne change ni le nombre ni l'ordre des lignes, l'avant et
    l'après affichaient la même chaîne (« 3 lignes » des deux côtés),
    laissant croire à tort que rien n'a changé. L'écran du document
    (`pages/DocumentDetail.tsx`) ne montre que l'état *actuel* d'un
    document, jamais l'état d'avant une correction : le Journal reste le
    seul endroit de l'interface où cet avant/après est visible.
    `formaterNombreLignes` doit donc rester utilisé (l'en-tête « n lignes »)
    sans être la seule mise en forme appliquée à la clé `lignes` : une
    fonction distincte détaille chaque ligne, avec les mêmes libellés et
    les mêmes formateurs (`formaterQuantite`/`formaterMontant`) que le
    tableau des lignes de `pages/DocumentDetail.tsx` — jamais l'identifiant
    technique de la ligne (`_ligne_en_chaine::id`, `corrections.py`), sans
    intérêt pour retracer qui a corrigé quoi."""
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    assert "function formaterNombreLignes" in journal_lib
    assert "function formaterLigneCorrigee" in journal_lib
    assert "function formaterLignes" in journal_lib

    # La clé `lignes` passe maintenant par le détail complet, pas par le
    # résumé seul.
    motif_lignes = (
        r'if \(cle === "lignes" && Array\.isArray\(brute\)\) \{'
        r"\n\s*return (\w+)\(brute\);"
    )
    appel_lignes = re.search(motif_lignes, journal_lib)
    assert appel_lignes is not None, 'bloc `cle === "lignes"` introuvable'
    assert appel_lignes.group(1) == "formaterLignes"

    # Mêmes formateurs que le reste du front (aucun montant/quantité brut).
    assert "formaterQuantite" in journal_lib

    # Jamais l'identifiant technique de la ligne dans sa mise en forme.
    corps = re.search(r"function formaterLigneCorrigee\(.*?\n\}", journal_lib, re.S)
    assert corps is not None, "corps de formaterLigneCorrigee introuvable"
    assert '"id"' not in corps.group(0)
    assert ".id" not in corps.group(0)


def test_journal_sans_identifiant_brut_et_filtre_auteur_replie() -> None:
    """Revue finale de la refonte du front (constat COUVERTURE-10) : plus
    d'UUID brut sous chaque cible (sauf un compte, recopiable dans le
    filtre « Auteur »), et le filtre « Auteur », qui demande un
    identifiant, est replié sous « Filtre avancé »."""
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")
    fonction = journal_lib.split("export function libelleCibleId", 1)[1].split(
        "\n}\n", 1
    )[0]
    assert "string | null" in fonction
    assert 'cibleTable === "utilisateur"' in fonction
    assert "return null;" in fonction

    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")
    assert page.count("idCible !== null &&") == 2
    filtre = page.split("Filtre avancé", 1)[1].split("</details>", 1)[0]
    assert 'id="filtre-utilisateur-id"' in filtre


def test_libelles_des_reglages_alignes_avec_le_serveur() -> None:
    """Revue finale (constat COUVERTURE-9) : mêmes libellés en français
    courant côté serveur (`ingest/parametres.py`, écran Réglages) et côté
    journal (`lib/journal.ts`), sans « occurrence » ni « anomalie »."""
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")
    parametres = (
        Path(__file__).parents[1] / "app" / "modules" / "ingest" / "parametres.py"
    ).read_text(encoding="utf-8")
    for libelle in (
        "Nombre minimum de factures pour établir le prix habituel",
        "Durée pendant laquelle un problème ignoré reste masqué",
    ):
        assert libelle in journal_lib, libelle
        assert libelle in parametres, libelle
    assert "Occurrences minimales" not in journal_lib
    assert "Durée d'ignorance" not in journal_lib
