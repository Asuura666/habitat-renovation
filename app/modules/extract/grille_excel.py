"""Lecture d'un fichier Excel de grille de prix fournisseur (module PUR,
phase 3, spec `docs/superpowers/specs/2026-09-27-prix-design.md` §7.1).

`lire_grille_excel(contenu: bytes) -> GrilleLue` prend les octets bruts d'un
fichier déposé par un administrateur (`ingest/grilles.py` s'occupe de la
base, de l'aperçu et de la confirmation) et rend des dataclasses : aucune
dépendance d'infrastructure (`fastapi`, `sqlalchemy`, `httpx`), aucun appel
réseau, aucun log.

Forme du fichier (D2, décision d'Ilane) : une feuille, une ligne par
produit, une seule ligne d'en-tête cherchée dans les 10 premières lignes de
chaque feuille (colonnes reconnues par leur titre, §7.1). Les deux grilles
réelles diffèrent beaucoup dans leur forme (Cedeo : 7 onglets, aucune unité
ni remise, une colonne sans titre qui répète la famille ; Point.P : une
seule feuille, aucune référence, une unité par ligne) : ce module ne suit
donc jamais un modèle figé de colonnes, seulement les titres, et une feuille
sans en-tête reconnu (« Mode d'emploi ») est ignorée plutôt que de faire
échouer tout le fichier.

`openpyxl` lit en `read_only=True, data_only=True` (valeur calculée des
formules, jamais la formule elle-même) ; `defusedxml`, installé au lot 1
(P1), neutralise les fichiers XML piégés dans le classeur.

Point de frontière (CLAUDE.md) : `extract` ne peut importer aucun autre
module métier, y compris `normalize`. La détection des doublons du fichier
utilise donc une normalisation et une clé de produit **locales**,
volontairement simplifiées et qui ne dupliquent que ce qu'il faut de
`normalize.texte.normaliser_libelle` et `normalize.prix.cle_produit` pour
comparer deux lignes du même fichier ; la clé qui compte réellement (le
rapprochement avec la grille en base) est celle de `normalize.prix`, calculée
plus loin par `ingest/grilles.py`.
"""

from __future__ import annotations

import io
import unicodedata
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

# Nombre de lignes explorées (toutes feuilles confondues, y compris les
# lignes vides) au-delà duquel le fichier est refusé (spec §7.1). Les lignes
# vides comptent aussi dans cette borne : sinon un fichier truqué peut
# empiler des millions de lignes Excel sans aucune cellule (très
# compressible) sans jamais la déclencher.
LIGNES_MAX = 20_000

# Nombre de lignes explorées, en tête de chaque feuille, à la recherche
# d'une ligne d'en-tête reconnue (spec §7.1).
_LIGNES_ENTETE_MAX = 10

_SIGNATURE_ZIP = b"PK\x03\x04"
# Signature d'un fichier composé OLE (`.xls`, ou `.xlsx` chiffré par mot de
# passe : Excel le range alors dans un conteneur OLE, pas un zip).
_SIGNATURE_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


@dataclass(frozen=True)
class LigneGrilleLue:
    """Une ligne de produit valide, lue depuis une feuille de grille."""

    feuille: str
    numero_ligne: int
    reference: str | None
    designation: str
    unite_brut: str | None
    prix_ht: Decimal
    remise_pct: Decimal | None
    marque: str | None
    famille: str | None


@dataclass(frozen=True)
class ErreurGrille:
    """Une ligne de données qui n'a pas pu être retenue, avec son motif."""

    feuille: str
    numero_ligne: int
    message: str


@dataclass(frozen=True)
class GrilleLue:
    """Résultat complet de la lecture d'un fichier de grille."""

    lignes: tuple[LigneGrilleLue, ...]
    erreurs: tuple[ErreurGrille, ...]
    feuilles_ignorees: tuple[str, ...]


class FichierGrilleInvalide(Exception):
    """Le fichier n'est, dès l'ouverture, pas exploitable comme grille
    (pas un `.xlsx`, protégé, ou trop volumineux -- spec §7.1)."""


# --------------------------------------------------------------------------
# Titres de colonnes reconnus (après normalisation locale, spec §7.1)
# --------------------------------------------------------------------------

_TITRES_REFERENCE = {"reference", "ref", "code", "code article", "ref fournisseur"}
_TITRES_DESIGNATION = {"designation", "article", "libelle", "produit"}
_TITRES_UNITE = {"unite", "u", "unite de vente"}
_TITRES_REMISE = {"remise", "remise pct"}
_TITRES_MARQUE = {"marque", "fabricant"}
_TITRES_FAMILLE = {"famille", "categorie"}


def _normaliser(valeur: object) -> str:
    """Normalisation locale d'un titre de colonne ou d'une cellule texte :
    NFKD sans diacritiques, casefold, non-alphanumérique -> espace, espaces
    réduits. Réplique volontairement restreinte de
    `normalize.texte.normaliser_libelle` (voir docstring de tête : `extract`
    ne peut importer `normalize`)."""
    if valeur is None:
        return ""
    chaine = str(valeur)
    decompose = unicodedata.normalize("NFKD", chaine)
    sans_diacritiques = "".join(c for c in decompose if not unicodedata.combining(c))
    minuscules = sans_diacritiques.casefold()
    caracteres = (c if c.isalnum() else " " for c in minuscules)
    return " ".join("".join(caracteres).split())


def _est_titre_prix(titre: str) -> bool:
    return titre.startswith("prix") or titre.startswith("pu")


def _valeur_texte(cellule: object) -> str:
    if cellule is None:
        return ""
    return str(cellule).strip()


def _cle_locale(reference: str | None, designation: str) -> str:
    """Clé de détection des doublons **dans un même fichier** (spec §7.1,
    dernier point) : même principe que `normalize.prix.cle_produit`
    (référence normalisée si non vide, sinon désignation normalisée), avec
    la normalisation locale de ce module (voir `_normaliser`)."""
    ref_normalisee = _normaliser(reference).replace(" ", "")
    if ref_normalisee:
        return f"ref:{ref_normalisee}"
    return f"nom:{_normaliser(designation)}"


def _lire_reference(cellule: object) -> str | None:
    """Une référence lue comme nombre par Excel (`4000493.0`) est ramenée à
    l'entier (`"4000493"`) ; un texte est gardé tel quel, espaces de bord
    retirés (spec §7.1)."""
    if cellule is None:
        return None
    if isinstance(cellule, float) and cellule.is_integer():
        return str(int(cellule))
    if isinstance(cellule, int):
        return str(cellule)
    texte = str(cellule).strip()
    return texte or None


def _decimal_depuis_cellule(cellule: object) -> Decimal | None:
    """`Decimal` depuis une cellule numérique ou un texte français (espaces
    normaux, insécables ou fines, `€`, virgule ou point décimal). `None` si
    la cellule est vide. Lève `ValueError` (message = le texte tel que lu)
    si le contenu n'est pas reconnaissable comme un nombre."""
    if cellule is None:
        return None
    if isinstance(cellule, int | float | Decimal):
        return Decimal(str(cellule))
    texte = str(cellule).strip()
    if not texte:
        return None
    nettoye = texte
    for blanc in (" ", "\xa0", "\u202f"):
        nettoye = nettoye.replace(blanc, "")
    nettoye = nettoye.replace("€", "").replace(",", ".")
    try:
        return Decimal(nettoye)
    except InvalidOperation:
        raise ValueError(texte) from None


# --------------------------------------------------------------------------
# En-tête
# --------------------------------------------------------------------------


@dataclass
class _Colonnes:
    reference: int | None
    designation: int
    unite: int | None
    prix: int
    remise: int | None
    marque: int | None
    famille: int | None


def _colonnes_entete(valeurs: tuple[object, ...]) -> _Colonnes | None:
    """Reconnaît une ligne d'en-tête : `None` si elle ne porte pas au moins
    une colonne Désignation et une colonne Prix (spec §7.1)."""
    titres = {i: _normaliser(v) for i, v in enumerate(valeurs)}
    titres = {i: t for i, t in titres.items() if t}

    col_designation = next(
        (i for i, t in titres.items() if t in _TITRES_DESIGNATION), None
    )
    candidats_prix = [i for i, t in titres.items() if _est_titre_prix(t)]
    if col_designation is None or not candidats_prix:
        return None
    col_prix = next((i for i in candidats_prix if "ht" in titres[i]), candidats_prix[0])

    return _Colonnes(
        reference=next((i for i, t in titres.items() if t in _TITRES_REFERENCE), None),
        designation=col_designation,
        unite=next((i for i, t in titres.items() if t in _TITRES_UNITE), None),
        prix=col_prix,
        remise=next((i for i, t in titres.items() if t in _TITRES_REMISE), None),
        marque=next((i for i, t in titres.items() if t in _TITRES_MARQUE), None),
        famille=next((i for i, t in titres.items() if t in _TITRES_FAMILLE), None),
    )


def _cellule(valeurs: tuple[object, ...], indice: int | None) -> object:
    if indice is None or indice >= len(valeurs):
        return None
    return valeurs[indice]


def _ligne_vide(valeurs: tuple[object, ...]) -> bool:
    return all(_valeur_texte(v) == "" for v in valeurs)


# --------------------------------------------------------------------------
# Lecture d'une feuille
# --------------------------------------------------------------------------


def _traiter_ligne(
    feuille: str,
    numero: int,
    valeurs: tuple[object, ...],
    colonnes: _Colonnes,
    famille_par_defaut: str,
    lignes: list[LigneGrilleLue],
    erreurs: list[ErreurGrille],
    cles_vues: dict[str, tuple[str, int]],
) -> None:
    designation = _valeur_texte(_cellule(valeurs, colonnes.designation))
    if not designation:
        erreurs.append(ErreurGrille(feuille, numero, "désignation manquante"))
        return

    try:
        prix_ht = _decimal_depuis_cellule(_cellule(valeurs, colonnes.prix))
    except ValueError as exc:
        erreurs.append(ErreurGrille(feuille, numero, f"prix illisible : « {exc} »"))
        return
    if prix_ht is None:
        erreurs.append(ErreurGrille(feuille, numero, "prix manquant"))
        return
    if prix_ht <= 0:
        erreurs.append(ErreurGrille(feuille, numero, "le prix doit être supérieur à 0"))
        return

    try:
        remise_pct = _decimal_depuis_cellule(_cellule(valeurs, colonnes.remise))
    except ValueError as exc:
        erreurs.append(ErreurGrille(feuille, numero, f"remise illisible : « {exc} »"))
        return
    if remise_pct is not None and (remise_pct < 0 or remise_pct >= 100):
        erreurs.append(
            ErreurGrille(
                feuille, numero, "la remise doit être comprise entre 0 et 100 (exclu)"
            )
        )
        return

    reference = _lire_reference(_cellule(valeurs, colonnes.reference))
    unite_brut = _valeur_texte(_cellule(valeurs, colonnes.unite)) or None
    marque = _valeur_texte(_cellule(valeurs, colonnes.marque)) or None
    famille = _valeur_texte(_cellule(valeurs, colonnes.famille)) or famille_par_defaut

    cle = _cle_locale(reference, designation)
    premiere_occurrence = cles_vues.get(cle)
    if premiere_occurrence is not None:
        feuille_premiere, numero_premier = premiere_occurrence
        erreurs.append(
            ErreurGrille(
                feuille,
                numero,
                f"même produit déjà présent ligne {numero_premier} "
                f"({feuille_premiere})",
            )
        )
        return
    cles_vues[cle] = (feuille, numero)

    lignes.append(
        LigneGrilleLue(
            feuille=feuille,
            numero_ligne=numero,
            reference=reference,
            designation=designation,
            unite_brut=unite_brut,
            prix_ht=prix_ht,
            remise_pct=remise_pct,
            marque=marque,
            famille=famille,
        )
    )


def _lire_feuille(
    feuille: object,
    lignes: list[LigneGrilleLue],
    erreurs: list[ErreurGrille],
    feuilles_ignorees: list[str],
    cles_vues: dict[str, tuple[str, int]],
    total_utiles: int,
) -> int:
    nom_feuille = feuille.title  # type: ignore[attr-defined]
    colonnes: _Colonnes | None = None
    lignes_entete_vues = 0

    # Cellules (pas `values_only=True`) : chaque cellule porte son vrai
    # numéro de ligne Excel (`.row`), y compris quand des lignes entièrement
    # absentes du fichier créent des trous dans la numérotation -- un simple
    # compteur (`enumerate`) s'en écarterait (spec §7.1, « numéros de ligne
    # Excel exacts »).
    for ligne_cellules in feuille.iter_rows():  # type: ignore[attr-defined]
        # Borne sur le nombre de lignes *explorées*, avant tout traitement de
        # contenu : une ligne entièrement dépourvue de cellule (`EmptyCell`
        # partout, ou aucune cellule du tout -- un fichier XLSX truqué peut
        # contenir des millions de balises `<row>` vides, très compressibles)
        # doit compter dans la borne au même titre qu'une ligne utile, sinon
        # elle ne la déclenche jamais et le fichier boucle indéfiniment.
        total_utiles += 1
        if total_utiles > LIGNES_MAX:
            raise FichierGrilleInvalide(
                f"le fichier dépasse {LIGNES_MAX} lignes utiles"
            )

        # Une cellule sans aucune valeur ni style (`EmptyCell`, comblant les
        # colonnes creuses en tête de ligne) ne porte pas `.row` : on prend
        # le numéro sur la première cellule qui en porte un ; une ligne
        # entièrement faite d'`EmptyCell` (aucune donnée nulle part) est
        # ignorée -- il n'y a rien à y lire.
        numero: int | None = None
        for cellule in ligne_cellules:
            if hasattr(cellule, "row"):
                numero = cellule.row
                break
        else:
            continue
        valeurs = tuple(getattr(cellule, "value", None) for cellule in ligne_cellules)

        if colonnes is None:
            if lignes_entete_vues >= _LIGNES_ENTETE_MAX:
                feuilles_ignorees.append(nom_feuille)
                return total_utiles
            lignes_entete_vues += 1
            colonnes = _colonnes_entete(valeurs)
            continue

        if _ligne_vide(valeurs):
            continue

        famille_par_defaut = nom_feuille if colonnes.famille is None else ""
        _traiter_ligne(
            nom_feuille,
            numero,
            valeurs,
            colonnes,
            famille_par_defaut,
            lignes,
            erreurs,
            cles_vues,
        )

    if colonnes is None:
        feuilles_ignorees.append(nom_feuille)

    return total_utiles


# --------------------------------------------------------------------------
# Ouverture du fichier
# --------------------------------------------------------------------------


def _valider_signature(contenu: bytes) -> None:
    entete = contenu[:8]
    if entete.startswith(_SIGNATURE_ZIP):
        return
    if entete.startswith(_SIGNATURE_OLE):
        raise FichierGrilleInvalide(
            "le fichier est protégé (chiffré) : retirez la protection avant "
            "de l'importer"
        )
    raise FichierGrilleInvalide("le fichier n'est pas un classeur Excel valide (.xlsx)")


def lire_grille_excel(contenu: bytes) -> GrilleLue:
    """Lit un fichier de grille de prix Excel (spec §7.1).

    Refuse immédiatement (`FichierGrilleInvalide`) un fichier qui n'est pas
    un `.xlsx` (signature ZIP puis ouverture `openpyxl`), un fichier
    protégé, ou plus de `LIGNES_MAX` lignes utiles au total (toutes feuilles
    confondues). Sinon, lit chaque feuille : celles sans en-tête Désignation
    et Prix reconnu dans les 10 premières lignes sont ignorées
    (`feuilles_ignorees`) ; chaque ligne de donnée devient une
    `LigneGrilleLue` ou une `ErreurGrille`, jamais les deux.
    """
    _valider_signature(contenu)

    try:
        classeur = openpyxl.load_workbook(
            io.BytesIO(contenu), read_only=True, data_only=True
        )
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError) as exc:
        raise FichierGrilleInvalide(
            "le fichier est illisible ou n'est pas un classeur Excel valide (.xlsx)"
        ) from exc

    lignes: list[LigneGrilleLue] = []
    erreurs: list[ErreurGrille] = []
    feuilles_ignorees: list[str] = []
    cles_vues: dict[str, tuple[str, int]] = {}
    total_utiles = 0
    try:
        for feuille in classeur.worksheets:
            total_utiles = _lire_feuille(
                feuille, lignes, erreurs, feuilles_ignorees, cles_vues, total_utiles
            )
    finally:
        classeur.close()

    return GrilleLue(
        lignes=tuple(lignes),
        erreurs=tuple(erreurs),
        feuilles_ignorees=tuple(feuilles_ignorees),
    )
