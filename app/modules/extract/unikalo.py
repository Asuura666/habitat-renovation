"""Parseur de facture Unikalo sur réponse OCR Mistral (module PUR, R16).

Contexte (voir `.superpowers/sdd/plan-lot-1/T5-requalification.md`) : l'unique
facture Unikalo disponible est un scan (aucune couche texte), un parseur
pdfplumber ne peut donc rien lire. Ce module lit la réponse déjà obtenue de
l'API Mistral OCR (un `dict` JSON, fourni par l'appelant) et n'effectue
lui-même aucun appel réseau (R17) : ni `httpx`, ni `fastapi`, ni
`sqlalchemy`, aucun log. Il s'appuie sur les utilitaires génériques de
`ocr.py` (texte complet, lecture de tableau markdown, nombres français) et
n'en connaît que la forme Unikalo (CDC §13 : un parseur par fournisseur —
un futur fournisseur aura son propre `extract/<fournisseur>.py`).

Les lignes de facture (articles, éco-participation, commentaires, marqueurs
de bloc/chantier) vivent uniquement dans `page["tables"][].content`, sous
forme de tableau markdown à 8 colonnes : ARTICLE | DÉSIGNATION | QTÉ
LIVRÉE | QTÉ TOTALE | PRIX H.T. | PRIX CDT (REMISE) | MONTANT H.T. | TVA.
La colonne REMISE n'a pas de cellule dédiée (fusionnée avec PRIX CDT dans
l'en-tête) : `remise_pct` n'est donc jamais lu depuis une colonne isolée,
seulement déduit (ligne à remise 100 % : toutes les valeurs numériques
vides) ou lu quand un signe « % » apparaît explicitement dans une cellule
numérique (R7).

Formes de fusion gérées explicitement (voir T5-report.md, « Exploration OCR
Mistral ») :
1. Cellule numérique empilée : deux lignes source fusionnées par l'OCR dans
   une même ligne de tableau, chaque colonne numérique portant alors deux
   valeurs séparées par un espace (`ocr.est_ligne_empilee`/
   `ocr.diviser_valeurs_empilees`).
2. Marqueur de bloc « Concerne le B.L. » et montant d'une ligne article sur
   la même ligne de tableau (cellule ARTICLE vide, texte entier — marqueur
   puis désignation — dans la cellule DÉSIGNATION) : la ligne déclenche un
   nouveau bloc ET compte comme une ligne de ce nouveau bloc.
3. Mention CHANTIER fusionnée avec un commentaire ou mal séparée (absence de
   « : » ou de code entre parenthèses) : elle n'est alors pas reconnue comme
   marqueur et retombe en texte de commentaire, sans faire échouer l'analyse.

R6 (assoupli par la requalification) : `tva` est le taux résolu via le
récapitulatif code → taux du dernier tableau de la facture, quand ce
récapitulatif est lisible (c'est le cas sur la fixture réelle). S'il est
absent ou illisible, `tva=None` pour toutes les lignes (voir `docs/dette.md`).

En-tête de facture : `fournisseur_brut` est la première ligne du bandeau
entièrement en majuscules d'au moins deux mots et sans chiffre (exclut les
lignes SIRET/TVA, qui reprennent pourtant le nom de la société) ; `client`
est la première ligne du bloc adresse qui suit la mention « Page : x / y »
(l'OCR la rend parfois comme un titre markdown « # … », retiré).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from .facture import BlocBL, Facture, FactureIllisible, LigneFacture, TypeLigne
from .ocr import (
    date_fr,
    decimal_fr,
    decouper_ligne_tableau,
    diviser_valeurs_empilees,
    est_ligne_empilee,
    est_separateur,
    pourcentage_fr,
    tables_de_page,
    texte_ocr,
)

# --------------------------------------------------------------------------
# Expressions régulières (motifs déterministes, cf. « Règles de lecture »)
# --------------------------------------------------------------------------

_MARQUEUR_BL_RE = re.compile(
    r"Concerne\s+le\s+B\.?\s*L\.?\s*(?:[nN]\s*°|[nN]o\.?)?\s*"
    r"(?P<numero_bl>[A-Za-z0-9]+)\s+du\s+(?P<date>\d{2}/\d{2}/\d{4})"
    r"\s*\(\s*Commande\s*(?:[nN]\s*°|[nN]o\.?)?\s*(?P<numero_commande>[A-Za-z0-9]+)\s*\)"
    r"\s*-\s*(?P<ville>[^|\n]*)",
    re.IGNORECASE,
)
_MARQUEUR_CHANTIER_RE = re.compile(
    r"CHANTIER\s*:\s*(?P<libelle>.+?)\s*\(\s*(?P<code>[A-Za-z0-9]+)\s*\)",
    re.IGNORECASE,
)
_CONDITIONS_REGLEMENT_RE = re.compile(r"Conditions\s+de\s+r[eèé]glement", re.IGNORECASE)
_ECHEANCE_RE = re.compile(r"[EÉ]ch[ée]ance\s+au\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_NUMERO_FACTURE_RE = re.compile(
    r"FACTURE\s*(?:[nN]\s*°|No\.?)?\s*([A-Za-z0-9][A-Za-z0-9./-]{2,})", re.IGNORECASE
)
_DATE_FACTURE_RE = re.compile(r"Date\s*:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_PAGE_MARQUEUR_RE = re.compile(r"Page\s*:\s*\d+\s*/\s*\d+", re.IGNORECASE)
_TITRE_MARKDOWN_RE = re.compile(r"^#+\s*")

_MOTS_ECO = ("ECO", "PARTICIPATION")

# Ordre des 6 colonnes numériques d'une ligne de facture (après ARTICLE et
# DÉSIGNATION), tel qu'il apparaît dans le tableau OCR.
_COLONNES_NUMERIQUES = (
    "qte_livree",
    "qte_totale",
    "pu_ht",
    "pu_cdt",
    "montant_ht",
    "tva",
)


def _est_eco(designation: str) -> bool:
    majuscules = designation.upper()
    return all(mot in majuscules for mot in _MOTS_ECO)


def _est_entete_colonnes(cellules: list[str]) -> bool:
    """En-tête de colonnes de la facture, répété en haut de chaque page."""
    return bool(cellules) and cellules[0].strip().upper() == "ARTICLE"


# --------------------------------------------------------------------------
# Récapitulatif TVA / total HT (tableau « H.T. € | Code | Taux | T.V.A. € »)
# --------------------------------------------------------------------------


def _est_entete_recap(cellules: list[str]) -> bool:
    return (
        len(cellules) == 4
        and cellules[1].strip().upper() == "CODE"
        and cellules[2].strip().upper() == "TAUX"
    )


def _lignes_recap(pages: list[dict[str, Any]]) -> list[list[str]]:
    """Lignes de données de tous les tableaux « H.T. € | Code | Taux | T.V.A. € »."""
    lignes_recap: list[list[str]] = []
    for page in pages:
        for contenu in tables_de_page(page):
            en_recap = False
            for ligne_brute in contenu.split("\n"):
                cellules = decouper_ligne_tableau(ligne_brute)
                if cellules is None or len(cellules) != 4 or est_separateur(cellules):
                    continue
                if not en_recap:
                    en_recap = _est_entete_recap(cellules)
                    continue
                lignes_recap.append(cellules)
    return lignes_recap


def _extraire_taux_tva(pages: list[dict[str, Any]]) -> dict[str, Decimal]:
    """Correspondance code TVA -> taux (ex. `{"5": Decimal("20")}`), R6."""
    taux_par_code: dict[str, Decimal] = {}
    for cellules in _lignes_recap(pages):
        code, taux_brut = cellules[1].strip(), cellules[2].strip()
        if code and taux_brut:
            taux = pourcentage_fr(taux_brut)
            if taux is not None:
                taux_par_code[code] = taux
    return taux_par_code


def _extraire_total_ht(pages: list[dict[str, Any]]) -> Decimal | None:
    """`total_ht` : ligne du récapitulatif dont Code ET Taux sont vides (le total)."""
    for cellules in _lignes_recap(pages):
        code, taux = cellules[1].strip(), cellules[2].strip()
        if not code and not taux:
            valeur = decimal_fr(cellules[0])
            if valeur is not None:
                return valeur
    return None


# --------------------------------------------------------------------------
# En-tête de facture (première page)
# --------------------------------------------------------------------------


def _paragraphes(texte: str) -> list[str]:
    return [p.strip() for p in texte.split("\n\n") if p.strip()]


def _extraire_numero_facture(texte: str) -> str | None:
    correspondance = _NUMERO_FACTURE_RE.search(texte)
    if correspondance is None:
        return None
    return correspondance.group(1).strip(" :.,;") or None


def _extraire_date_facture(texte: str) -> date | None:
    correspondance = _DATE_FACTURE_RE.search(texte)
    if correspondance is None:
        return None
    return date_fr(correspondance.group(1))


def _est_ligne_bandeau_fournisseur(paragraphe: str) -> bool:
    """Ligne « raison sociale » du bandeau (ex. « NUANCES UNIKALO TOULOUSE »).

    Entièrement en majuscules, au moins deux mots, sans aucun chiffre :
    exclut aussi bien les lignes logo d'un seul mot (« NUANCES », « UNIKALO »
    séparément) que la phrase administrative plus longue qui reprend le nom
    de la société avec le SIRET et la TVA (celle-ci contient des chiffres).
    """
    if any(c.isdigit() for c in paragraphe):
        return False
    lettres = [c for c in paragraphe if c.isalpha()]
    if not lettres or not all(c.isupper() for c in lettres):
        return False
    return len(paragraphe.split()) >= 2


def _extraire_fournisseur(texte: str) -> str | None:
    for paragraphe in _paragraphes(texte):
        if _est_ligne_bandeau_fournisseur(paragraphe):
            return paragraphe.strip()
    return None


def _nettoyer_titre_markdown(paragraphe: str) -> str:
    """Retire un éventuel marqueur de titre markdown (« # », « ## », …)
    que l'OCR ajoute pour une ligne mise en avant (ex. le nom du client)."""
    return _TITRE_MARKDOWN_RE.sub("", paragraphe).strip()


def _est_marqueur_de_fin_paragraphe(paragraphe: str) -> bool:
    """Marqueur de continuation de page OCR (« .../... »), sans lettre ni chiffre."""
    return bool(paragraphe) and set(paragraphe) <= {".", "/"}


def _extraire_client(texte: str) -> str | None:
    """Nom du destinataire (R8) : première ligne du bloc adresse à droite,
    juste après la mention « Page : x / y » — jamais le reste de l'adresse."""
    paragraphes = _paragraphes(texte)
    index_page = next(
        (i for i, p in enumerate(paragraphes) if _PAGE_MARQUEUR_RE.search(p)), None
    )
    if index_page is None or index_page + 1 >= len(paragraphes):
        return None
    candidat = _nettoyer_titre_markdown(paragraphes[index_page + 1])
    if not candidat or _est_marqueur_de_fin_paragraphe(candidat):
        return None
    return candidat


# --------------------------------------------------------------------------
# Segmentation d'un texte de cellule en évènements bloc/chantier + texte libre
# --------------------------------------------------------------------------

_Segment = tuple[str, "re.Match[str] | None", str]


def _decouper_marqueurs(texte: str) -> list[_Segment]:
    """Découpe un texte en évènements (« bloc », « chantier ») et texte libre
    (« texte »), dans l'ordre d'apparition.

    Généralise les 3 formes de fusion observées : un marqueur peut partager
    sa ligne avec du texte de commentaire avant ou après lui (voire avec un
    autre marqueur), sans qu'aucune position de colonne ne soit supposée.
    """
    evenements: list[tuple[int, int, str, re.Match[str]]] = [
        (m.start(), m.end(), "bloc", m) for m in _MARQUEUR_BL_RE.finditer(texte)
    ] + [
        (m.start(), m.end(), "chantier", m)
        for m in _MARQUEUR_CHANTIER_RE.finditer(texte)
    ]
    evenements.sort(key=lambda e: e[0])

    segments: list[_Segment] = []
    curseur = 0
    for debut, fin, genre, correspondance in evenements:
        if debut < curseur:
            # Chevauchement (improbable) : on garde le premier marqueur trouvé.
            continue
        avant = texte[curseur:debut].strip()
        if avant:
            segments.append(("texte", None, avant))
        segments.append((genre, correspondance, ""))
        curseur = fin
    reste = texte[curseur:].strip()
    if reste:
        segments.append(("texte", None, reste))
    return segments


def _texte_chantier(correspondance: re.Match[str]) -> str:
    libelle = correspondance.group("libelle").strip()
    code = correspondance.group("code").strip()
    return f"{libelle} ({code})".strip()


# --------------------------------------------------------------------------
# Interprétation des valeurs numériques d'une ligne
# --------------------------------------------------------------------------


@dataclass
class _ValeursLigne:
    qte_livree: Decimal | None
    qte_totale: Decimal | None
    pu_ht: Decimal | None
    pu_cdt: Decimal | None
    remise_pct: Decimal | None
    montant_ht: Decimal | None
    tva: Decimal | None


def _analyser_valeurs_numeriques(
    valeurs: list[str], taux_par_code: dict[str, Decimal]
) -> _ValeursLigne:
    """Interprète les 6 cellules numériques d'une ligne (R7 : remise 100 %,
    signe « % » explicite dans une colonne de prix)."""
    bruts = dict(zip(_COLONNES_NUMERIQUES, valeurs, strict=True))
    remise_pct: Decimal | None = None
    valeurs_prix: dict[str, Decimal | None] = {}
    for nom in ("pu_ht", "pu_cdt", "montant_ht"):
        brut = bruts[nom]
        if remise_pct is None and "%" in brut:
            remise_pct = pourcentage_fr(brut)
            valeurs_prix[nom] = None
        else:
            valeurs_prix[nom] = decimal_fr(brut)

    if remise_pct is None and not any(v.strip() for v in valeurs):
        remise_pct = Decimal("100")

    code_tva = bruts["tva"].strip()
    taux_tva = taux_par_code.get(code_tva) if code_tva else None

    return _ValeursLigne(
        qte_livree=decimal_fr(bruts["qte_livree"]),
        qte_totale=decimal_fr(bruts["qte_totale"]),
        pu_ht=valeurs_prix["pu_ht"],
        pu_cdt=valeurs_prix["pu_cdt"],
        remise_pct=remise_pct,
        montant_ht=valeurs_prix["montant_ht"],
        tva=taux_tva,
    )


def _analyser_ligne_numerique(
    valeurs: list[str], taux_par_code: dict[str, Decimal]
) -> list[_ValeursLigne]:
    """Une ligne de tableau -> une ou plusieurs `_ValeursLigne` (forme 1)."""
    groupes = (
        diviser_valeurs_empilees(valeurs) if est_ligne_empilee(valeurs) else [valeurs]
    )
    return [_analyser_valeurs_numeriques(groupe, taux_par_code) for groupe in groupes]


# --------------------------------------------------------------------------
# Construction des blocs
# --------------------------------------------------------------------------


@dataclass
class _BlocEnConstruction:
    numero_bl: str
    date_bl: date | None
    numero_commande: str | None
    chantier_brut: str | None = None
    lignes: list[LigneFacture] = field(default_factory=list)

    @classmethod
    def depuis_marqueur(cls, correspondance: re.Match[str]) -> _BlocEnConstruction:
        return cls(
            numero_bl=correspondance.group("numero_bl").strip(),
            date_bl=date_fr(correspondance.group("date")),
            numero_commande=correspondance.group("numero_commande").strip() or None,
        )

    def ajouter_ligne(
        self,
        *,
        type_ligne: TypeLigne,
        code_article: str | None,
        designation: str,
        valeurs: _ValeursLigne,
    ) -> None:
        self.lignes.append(
            LigneFacture(
                ordre=len(self.lignes),
                type_ligne=type_ligne,
                code_article=code_article,
                designation=designation,
                qte_livree=valeurs.qte_livree,
                qte_totale=valeurs.qte_totale,
                unite=None,
                pu_ht=valeurs.pu_ht,
                pu_cdt=valeurs.pu_cdt,
                remise_pct=valeurs.remise_pct,
                montant_ht=valeurs.montant_ht,
                tva=valeurs.tva,
            )
        )

    def ajouter_commentaire(self, texte: str) -> None:
        self.lignes.append(
            LigneFacture(
                ordre=len(self.lignes),
                type_ligne=TypeLigne.COMMENTAIRE,
                code_article=None,
                designation=texte,
                qte_livree=None,
                qte_totale=None,
                unite=None,
                pu_ht=None,
                pu_cdt=None,
                remise_pct=None,
                montant_ht=None,
                tva=None,
            )
        )

    def construire(self) -> BlocBL:
        return BlocBL(
            numero_bl=self.numero_bl,
            date_bl=self.date_bl,
            numero_commande=self.numero_commande,
            chantier_brut=self.chantier_brut,
            lignes=tuple(self.lignes),
        )


def _appliquer_segments(
    segments: list[_Segment],
    blocs: list[_BlocEnConstruction],
    bloc_courant: _BlocEnConstruction | None,
    *,
    sur_texte: Callable[[_BlocEnConstruction, str], None] | None,
) -> _BlocEnConstruction | None:
    """Applique dans l'ordre les évènements d'une liste de segments.

    Un évènement « bloc » ouvre un nouveau bloc courant ; un évènement
    « chantier » met à jour le bloc courant existant. `sur_texte`, s'il est
    fourni, est appelé pour chaque segment de texte libre avec le bloc
    courant *au moment où ce segment apparaît* (avant ou après un marqueur
    de la même ligne, ce qui compte pour rattacher correctement un
    commentaire fusionné avec un marqueur, cf. formes de fusion 2 et 3).
    Renvoie le bloc courant après traitement.
    """
    for genre, correspondance, texte_libre in segments:
        if genre == "bloc" and correspondance is not None:
            bloc_courant = _BlocEnConstruction.depuis_marqueur(correspondance)
            blocs.append(bloc_courant)
        elif (
            genre == "chantier"
            and correspondance is not None
            and bloc_courant is not None
        ):
            bloc_courant.chantier_brut = _texte_chantier(correspondance)
        elif (
            genre == "texte"
            and texte_libre
            and bloc_courant is not None
            and sur_texte is not None
        ):
            sur_texte(bloc_courant, texte_libre)
    return bloc_courant


def _extraire_blocs(
    pages: list[dict[str, Any]], taux_par_code: dict[str, Decimal]
) -> list[BlocBL]:
    blocs: list[_BlocEnConstruction] = []
    bloc_courant: _BlocEnConstruction | None = None
    terminee = False

    for page in pages:
        if terminee:
            break
        for contenu_table in tables_de_page(page):
            if terminee:
                break
            for ligne_brute in contenu_table.split("\n"):
                cellules = decouper_ligne_tableau(ligne_brute)
                if cellules is None or len(cellules) != 8:
                    continue
                if _est_entete_colonnes(cellules) or est_separateur(cellules):
                    continue

                code_cellule, designation_cellule = cellules[0], cellules[1]
                valeurs_brutes = cellules[2:8]

                if _CONDITIONS_REGLEMENT_RE.search(
                    f"{code_cellule} {designation_cellule}"
                ):
                    terminee = True
                    break

                code_est_marqueur = bool(
                    _MARQUEUR_BL_RE.search(code_cellule)
                    or _MARQUEUR_CHANTIER_RE.search(code_cellule)
                )
                a_code_reel = bool(code_cellule.strip()) and not code_est_marqueur
                a_montant = any(v.strip() for v in valeurs_brutes)

                if a_code_reel or a_montant:
                    # Ligne chiffrée (article/éco) : les marqueurs éventuels
                    # (forme de fusion 2) ne vivent que dans la cellule
                    # DÉSIGNATION sur la facture réelle ; le code article
                    # reste une cellule propre. Le texte libre devient la
                    # désignation (jamais un commentaire séparé, cf. dette).
                    segments = _decouper_marqueurs(designation_cellule)
                    bloc_courant = _appliquer_segments(
                        segments, blocs, bloc_courant, sur_texte=None
                    )
                    designation = (
                        " ".join(
                            texte for genre, _c, texte in segments if genre == "texte"
                        ).strip()
                        or designation_cellule.strip()
                    )
                    if bloc_courant is None:
                        # Ligne chiffrée avant tout marqueur de bloc : ne
                        # devrait pas arriver sur une facture Unikalo bien
                        # formée ; on l'ignore plutôt que de la perdre dans
                        # un bloc inexistant.
                        continue
                    code_article = code_cellule.strip() if a_code_reel else None
                    type_ligne = (
                        TypeLigne.ECO if _est_eco(designation) else TypeLigne.ARTICLE
                    )
                    for valeurs in _analyser_ligne_numerique(
                        valeurs_brutes, taux_par_code
                    ):
                        bloc_courant.ajouter_ligne(
                            type_ligne=type_ligne,
                            code_article=code_article,
                            designation=designation,
                            valeurs=valeurs,
                        )
                else:
                    # Ligne texte pure : marqueur de bloc/chantier, ou
                    # commentaire (R5), cherchés sur les deux cellules (la
                    # position varie selon les lignes).
                    texte_combine = f"{code_cellule} {designation_cellule}".strip()
                    segments = _decouper_marqueurs(texte_combine)
                    bloc_courant = _appliquer_segments(
                        segments,
                        blocs,
                        bloc_courant,
                        sur_texte=lambda b, t: b.ajouter_commentaire(t),
                    )

    return [bloc.construire() for bloc in blocs]


# --------------------------------------------------------------------------
# Point d'entrée
# --------------------------------------------------------------------------


def analyser_facture_unikalo(reponse: dict[str, Any]) -> Facture:
    """Analyse la réponse OCR Mistral d'une facture Unikalo en `Facture`.

    Lève `FactureIllisible` si la structure n'est pas reconnue : pas de
    pages, en-tête de facture non identifiable, aucun bloc « Concerne le
    B.L. », ou total HT introuvable dans le récapitulatif.
    """
    pages = reponse.get("pages")
    if not isinstance(pages, list) or not pages:
        raise FactureIllisible("réponse OCR sans pages")
    pages_dict = [p for p in pages if isinstance(p, dict)]
    if not pages_dict:
        raise FactureIllisible("réponse OCR sans pages exploitables")

    texte_entete = str(pages_dict[0].get("markdown") or "")
    fournisseur_brut = _extraire_fournisseur(texte_entete)
    numero = _extraire_numero_facture(texte_entete)
    date_facture = _extraire_date_facture(texte_entete)
    if fournisseur_brut is None or numero is None or date_facture is None:
        raise FactureIllisible("en-tête de facture non reconnu")
    client = _extraire_client(texte_entete)

    texte_complet = texte_ocr(reponse)
    correspondance_echeance = _ECHEANCE_RE.search(texte_complet)
    echeance = (
        date_fr(correspondance_echeance.group(1)) if correspondance_echeance else None
    )

    taux_par_code = _extraire_taux_tva(pages_dict)
    total_ht = _extraire_total_ht(pages_dict)
    if total_ht is None:
        raise FactureIllisible("total HT introuvable dans le récapitulatif")

    blocs = _extraire_blocs(pages_dict, taux_par_code)
    if not blocs:
        raise FactureIllisible("aucun bloc « Concerne le B.L. » trouvé")

    return Facture(
        fournisseur_brut=fournisseur_brut,
        numero=numero,
        date_facture=date_facture,
        client=client,
        echeance=echeance,
        total_ht=total_ht,
        blocs=tuple(blocs),
    )
