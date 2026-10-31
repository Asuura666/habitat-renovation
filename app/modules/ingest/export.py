"""`ingest/export.py` (L5-T4) : sérialisation CSV des vues de bilan --
double la forme JSON d'`api/bilan.py`, jamais une deuxième requête. Les
fonctions ci-dessous reçoivent les dataclasses déjà produites par
`ingest.bilan` (`bilan_par_chantier`, `bilan_par_fournisseur`, `bilan_par_bl`,
`bilan_par_fournisseur_global`) et rendent une chaîne -- aucune session,
aucun import SQLAlchemy, aucun accès réseau.

Décision du contrôleur (L5-T4) : ce module est pur au sens où il ne touche
pas la base, ce qui le rend testable sans base ni réseau (l'essentiel des
tests de la tâche tourne ainsi). Il n'est pas pur au sens strict de la
L2-D3 (`extract`/`normalize`/`rules`) : il importe les dataclasses
d'`ingest.bilan`, donc reste dans `ingest`, le seul orchestrateur --
simplement sans effet de bord.

Trois choix imposés par la cible (le contrôleur : un client qui ouvre le
fichier dans Excel, en français, sans assistant d'importation) :
- séparateur point-virgule (`delimiter=";"`) -- la virgule décimale
  française et la virgule séparatrice de colonnes ne peuvent pas coexister ;
- virgule décimale dans les montants (`_formater_montant`) -- un point
  serait lu comme du texte, pas comme un nombre ;
- BOM UTF-8 -- ajouté par le routeur (`api/bilan.py`), pas ici : ce module
  produit du CSV, une réponse HTTP en est une mise en forme distincte
  (décision du contrôleur, à ne pas mélanger).

Une fonction par niveau (L5-D5), mêmes colonnes et même ordre que la vue
JSON correspondante :
- `csv_bilan_chantiers` -- `GET /api/bilan/chantiers` ;
- `csv_bilan_fournisseurs` -- `GET /api/bilan/chantiers/{id}/fournisseurs`
  et sa vue inverse `GET /api/bilan/fournisseurs` : les deux routes
  renvoient des `LigneBilanFournisseur`, donc une seule fonction les sert
  toutes les deux (jamais deux sérialisations pour la même forme) ;
- `csv_bilan_bl` -- `GET /api/bilan/chantiers/{id}/fournisseurs/{id}/bl`.

Aucun identifiant technique (UUID) en colonne : ce sont des clés de
navigation pour le front, pas des valeurs qu'un comptable rapproche avec sa
propre comptabilité -- décision du contrôleur, à signaler dans le rapport de
tâche si elle se révèle fausse. Une valeur absente (chantier ou fournisseur
non résolu, `numero_bl`/`date_bl` non lus) rend une cellule vide, jamais la
chaîne "None" que `csv.writer` écrirait pour un `None` littéral passé sans
traitement -- voir `_cellule`.

Export détaillé (décision d'Ilane du 23/09/2026, réponse à Q3 du lot 5) :
`csv_bilan_detail` -- une ligne par ligne de facture (`ingest.bilan
.LigneBilanDetail`/`bilan_detail`), même route `/api/bilan/detail.csv`.
Deux écarts assumés par rapport aux six fonctions ci-dessus (décision du
contrôleur pour cette tâche, ce fichier étant ouvert directement par le
client dans Excel, jamais recroisé avec une vue JSON) :
- `statut du bloc` est traduit avec les libellés déjà utilisés par le front
  (`web/src/pages/BilanFournisseur.tsx::statutBl`), pas le code brut ;
- les quantités (`qte_facturee`, `qte_bl_appariee`) passent par
  `_formater_montant` comme les montants (deux décimales, virgule
  française) -- une quantité à trois décimales (front : jusqu'à trois,
  `lib/formats.ts::formaterQuantite`) y perd sa troisième décimale ; aucune
  quantité observée aujourd'hui n'en porte plus de deux, mais rien ne le
  garantit (même réserve documentée pour les montants ci-dessus).
"""

from __future__ import annotations

import csv
import io
import unicodedata
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from app.modules.ingest.bilan import (
    LigneBilanBl,
    LigneBilanChantier,
    LigneBilanDetail,
    LigneBilanFournisseur,
    LigneLivraison,
)

_ENTETES_CHANTIERS: tuple[str, ...] = (
    "Chantier",
    "Agence",
    "Facturé HT",
    "Rapproché",
    "En écart",
    "Non justifié",
    "Anomalies ouvertes",
)

_ENTETES_FOURNISSEURS: tuple[str, ...] = (
    "Fournisseur",
    "Facturé HT",
    "Rapproché",
    "En écart",
    "Non justifié",
    "Anomalies ouvertes",
)

_ENTETES_BL: tuple[str, ...] = (
    "N° BL",
    "Date BL",
    "Statut rapprochement",
    "Facturé HT",
    "Rapproché",
    "En écart",
    "Non justifié",
    "Anomalies ouvertes",
)

_ENTETES_DETAIL: tuple[str, ...] = (
    "Mois",
    "Fournisseur",
    "N° Facture",
    "Date facture",
    "Chantier",
    "Agence",
    "N° BL",
    "Statut BL",
    "Type de ligne",
    "Référence article",
    "Désignation",
    "Quantité facturée",
    "Unité",
    "Prix unitaire HT",
    "Remise (%)",
    "Montant HT",
    "Quantité BL appariée",
    "Anomalies ouvertes",
    "Règles concernées",
)

_ENTETES_LIVRAISONS: tuple[str, ...] = (
    "Date",
    "N° BL",
    "Chantier",
    "Fournisseur",
    "Facturé",
    "État",
    "Montant HT",
    "Problèmes",
)

# Mêmes libellés que le front (`web/src/pages/BilanFournisseur.tsx
# ::statutBl`) -- décision explicite pour cet export détaillé (voir le
# docstring d'en-tête).
_LIBELLES_STATUT_BLOC: dict[str, str] = {
    "recu": "BL reçu",
    "pas_de_bon": "Pas de bon",
    "non_recu": "BL non reçu",
}


def _cellule(valeur: str | None) -> str:
    """Une valeur absente rend une cellule vide (décision du contrôleur),
    jamais la chaîne "None" que produirait un `csv.writer` sur un `None`
    littéral. Une apostrophe neutralise les préfixes de formule reconnus par
    les tableurs, même précédés d'espaces ou de caractères de contrôle ; le
    `csv.writer` conserve ensuite seul la responsabilité de l'échappement
    RFC4180."""
    if valeur is None:
        return ""
    contenu = valeur.lstrip()
    while contenu and unicodedata.category(contenu[0]).startswith("C"):
        contenu = contenu[1:].lstrip()
    if contenu.startswith(("=", "+", "-", "@")):
        return f"'{valeur}"
    return valeur


def _formater_montant(montant: Decimal) -> str:
    """Un montant sort avec deux décimales, virgule française. Arrondi
    (`ROUND_HALF_UP`, l'arrondi comptable usuel) plutôt que tronqué quand la
    valeur porte plus de deux décimales -- décision documentée ici et dans
    le rapport de tâche : aucune ligne `article`/`eco` n'est aujourd'hui
    saisie avec plus de deux décimales, mais l'agrégat `func.sum`
    d'`ingest.bilan` ne le garantit pas pour autant. Ne jamais recopier un
    `Decimal` brut (`str(montant)`) dans une cellule qu'Excel doit lire
    comme un nombre : `Decimal` peut porter un nombre de décimales
    variable, ce qu'aucune des deux colonnes suivantes ne doit refléter."""
    arrondi = montant.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{arrondi:.2f}".replace(".", ",")


def _ecrire_csv(entetes: tuple[str, ...], lignes: Sequence[Sequence[str]]) -> str:
    """Sérialisation commune aux trois niveaux : un `io.StringIO` (jamais un
    fichier, ce module ne touche pas le disque), séparateur point-virgule.
    L'échappement RFC4180 (guillemets doublés, champ entre guillemets dès
    qu'il contient le délimiteur ou un guillemet) est laissé au
    comportement par défaut du `csv.writer` de la bibliothèque standard
    (`QUOTE_MINIMAL`), jamais réécrit à la main."""
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, delimiter=";")
    ecrivain.writerow(entetes)
    ecrivain.writerows(lignes)
    return tampon.getvalue()


def _ligne_csv_chantier(ligne: LigneBilanChantier) -> tuple[str, ...]:
    return (
        _cellule(ligne.nom_canonique),
        _cellule(ligne.agence),
        _formater_montant(ligne.montants.facture_ht),
        _formater_montant(ligne.montants.rapproche),
        _formater_montant(ligne.montants.en_ecart),
        _formater_montant(ligne.montants.non_justifie),
        str(ligne.montants.nb_anomalies_ouvertes),
    )


def csv_bilan_chantiers(lignes: Sequence[LigneBilanChantier]) -> str:
    """`GET /api/bilan/chantiers` en CSV -- mêmes colonnes, même ordre, même
    tri que la vue JSON (le tri vient de la requête SQL d'`ingest.bilan`,
    jamais refait ici)."""
    return _ecrire_csv(
        _ENTETES_CHANTIERS, [_ligne_csv_chantier(ligne) for ligne in lignes]
    )


def _ligne_csv_fournisseur(ligne: LigneBilanFournisseur) -> tuple[str, ...]:
    return (
        _cellule(ligne.nom),
        _formater_montant(ligne.montants.facture_ht),
        _formater_montant(ligne.montants.rapproche),
        _formater_montant(ligne.montants.en_ecart),
        _formater_montant(ligne.montants.non_justifie),
        str(ligne.montants.nb_anomalies_ouvertes),
    )


def csv_bilan_fournisseurs(lignes: Sequence[LigneBilanFournisseur]) -> str:
    """`GET /api/bilan/chantiers/{id}/fournisseurs` et sa vue inverse
    `GET /api/bilan/fournisseurs` en CSV -- les deux routes partagent la
    dataclasse `LigneBilanFournisseur` (`ingest.bilan`), donc une seule
    fonction les sert toutes les deux (décision du contrôleur : jamais deux
    sérialisations pour la même forme)."""
    return _ecrire_csv(
        _ENTETES_FOURNISSEURS, [_ligne_csv_fournisseur(ligne) for ligne in lignes]
    )


def _ligne_csv_bl(ligne: LigneBilanBl) -> tuple[str, ...]:
    date_bl = ligne.date_bl.isoformat() if ligne.date_bl is not None else None
    return (
        _cellule(ligne.numero_bl),
        _cellule(date_bl),
        _cellule(ligne.statut_rapprochement),
        _formater_montant(ligne.montants.facture_ht),
        _formater_montant(ligne.montants.rapproche),
        _formater_montant(ligne.montants.en_ecart),
        _formater_montant(ligne.montants.non_justifie),
        str(ligne.montants.nb_anomalies_ouvertes),
    )


def csv_bilan_bl(lignes: Sequence[LigneBilanBl]) -> str:
    """`GET /api/bilan/chantiers/{id}/fournisseurs/{id}/bl` en CSV --
    `date_bl` au format ISO (`AAAA-MM-JJ`), identique à la sérialisation
    JSON de Pydantic pour un `date`, pour que le contenu corresponde ligne
    pour ligne à la vue JSON (exigence du contrôleur). `statut_rapprochement`
    reste la valeur brute (`recu`/`non_recu`/`pas_de_bon`, ou absente) telle
    que renvoyée par la vue JSON, jamais traduite ici : une traduction en
    français ("Reçu", ...) est une mise en forme d'écran (L5-D1, réservée au
    front d'une tâche ultérieure), pas une règle de sérialisation."""
    return _ecrire_csv(_ENTETES_BL, [_ligne_csv_bl(ligne) for ligne in lignes])


# --------------------------------------------------------------------------
# Export détaillé (décision d'Ilane du 23/09/2026, réponse à Q3 du lot 5) --
# voir le docstring d'en-tête pour les deux écarts assumés par rapport aux
# six fonctions ci-dessus.
# --------------------------------------------------------------------------


def _libelle_statut_bloc(statut: str | None) -> str | None:
    """`None` (bloc jamais rapproché) reste `None`, rendu comme une cellule
    vide par `_cellule` -- jamais un libellé inventé. Une valeur non
    reconnue (défensif : `statut_rapprochement_valide` en base n'autorise
    que les trois clés de `_LIBELLES_STATUT_BLOC`, donc inatteignable en
    pratique) retombe sur le code brut, même esprit que `libelleRegle` côté
    front pour un code de règle inconnu."""
    if statut is None:
        return None
    return _LIBELLES_STATUT_BLOC.get(statut, statut)


def _formater_montant_optionnel(valeur: Decimal | None) -> str:
    """`_formater_montant` n'accepte pas `None` : plusieurs colonnes de
    l'export détaillé le sont réellement (une ligne "commentaire" n'a ni
    prix ni montant, un article non apparié n'a pas de quantité BL) --
    cellule vide plutôt qu'un `None` recopié tel quel (même convention que
    `_cellule`, jamais la chaîne "None")."""
    if valeur is None:
        return ""
    return _formater_montant(valeur)


def _ligne_csv_detail(ligne: LigneBilanDetail) -> tuple[str, ...]:
    date_facture = (
        ligne.date_facture.isoformat() if ligne.date_facture is not None else None
    )
    return (
        ligne.mois.strftime("%Y-%m"),
        _cellule(ligne.fournisseur_nom),
        _cellule(ligne.numero_facture),
        _cellule(date_facture),
        _cellule(ligne.nom_chantier),
        _cellule(ligne.agence),
        _cellule(ligne.numero_bl),
        _cellule(_libelle_statut_bloc(ligne.statut_rapprochement)),
        _cellule(ligne.type_ligne),
        _cellule(ligne.code_article),
        _cellule(ligne.designation),
        _formater_montant_optionnel(ligne.qte_facturee),
        _cellule(ligne.unite),
        _formater_montant_optionnel(ligne.pu_ht),
        _formater_montant_optionnel(ligne.remise_pct),
        _formater_montant_optionnel(ligne.montant_ht),
        _formater_montant_optionnel(ligne.qte_bl_appariee),
        str(ligne.nb_anomalies_ouvertes),
        _cellule(", ".join(ligne.codes_regles)),
    )


def csv_bilan_detail(lignes: Sequence[LigneBilanDetail]) -> str:
    """`GET /api/bilan/detail.csv` (décision d'Ilane du 23/09/2026, réponse
    à Q3 du lot 5) -- une ligne par ligne de facture, colonnes détaillées ;
    voir `ingest.bilan.bilan_detail` pour la construction (même service,
    mêmes filtres `mois`/`agence` que les six autres exports de ce module,
    jamais une deuxième requête) et le docstring d'en-tête pour les deux
    écarts assumés par rapport à eux."""
    return _ecrire_csv(_ENTETES_DETAIL, [_ligne_csv_detail(ligne) for ligne in lignes])


# --------------------------------------------------------------------------
# Liste des livraisons (lot 2, B3, 31/10/2026) : lignes de facture et bons
# pas encore facturés, comme à l'écran.
# --------------------------------------------------------------------------


def _libelle_etat_livraison(ligne: LigneLivraison) -> str:
    """Mêmes libellés que `TableauLivraisons.tsx::libelleEtatBon`."""
    if ligne.categorie == "conforme":
        return "Conforme"
    if ligne.categorie == "a_verifier":
        return "À vérifier"
    if ligne.categorie == "probleme_ouvert":
        return "Problème ouvert"
    if ligne.categorie == "recu":
        return "Reçu"
    return (
        "Livré sans bon"
        if ligne.statut_rapprochement == "pas_de_bon"
        else "Jamais reçu"
    )


def _ligne_csv_livraison(ligne: LigneLivraison) -> tuple[str, ...]:
    date_bl = ligne.date_bl.isoformat() if ligne.date_bl is not None else None
    return (
        _cellule(date_bl),
        _cellule(ligne.numero_bl),
        _cellule(ligne.chantier),
        _cellule(ligne.fournisseur),
        "Oui" if ligne.facture else "Non",
        _libelle_etat_livraison(ligne),
        _formater_montant(ligne.montants.facture_ht) if ligne.facture else "",
        str(ligne.montants.nb_anomalies_ouvertes),
    )


def csv_livraisons(lignes: Sequence[LigneLivraison]) -> str:
    """`GET /api/bilan/livraisons` en CSV : une ligne par livraison, la
    colonne « Facturé » dit Oui (ligne de facture) ou Non (bon pas encore
    retrouvé sur une facture, montant vide)."""
    return _ecrire_csv(
        _ENTETES_LIVRAISONS, [_ligne_csv_livraison(ligne) for ligne in lignes]
    )
