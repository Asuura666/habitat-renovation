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
    LigneBilanFournisseur,
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
