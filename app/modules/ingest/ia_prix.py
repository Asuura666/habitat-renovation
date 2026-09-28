"""Explication des alertes prix et prix trouvé sur internet
(`ingest/ia_prix.py`, T6, phase 4 IA — spec §5, §6, §7 ; route groupée pour
la page Prix, T10a — spec §6.4, brief `task-10a-brief.md`).

Orchestrateur (comme le reste d'`ingest`) : ce module lit les anomalies de
catégorie *prix* (`ingest.anomalies.CATEGORIES_REGLE`), construit le texte
envoyé à l'IA, l'interroge via `ingest.opencode.interroger` (seul point
d'entrée réseau vers l'IA du dépôt), garde la réponse via
`extract.reponses_ia.lire_explication`/`lire_prix_internet` (module pur),
puis écrit `ExplicationAlerte`/`PrixInternet`. Il expose aussi la lecture
pour l'écran (`avis_ia_anomalie`, une anomalie à la fois, et
`prix_internet_des_anomalies`, en lot -- T10a, toutes deux consommées par
`api/ia.py`) et l'essai en ligne de commande (`essayer_prix_internet`, T7 du
document d'Ilane).

Contexte (T10a) : les règles de prix au bon (R19-R25, dont R22 « Produit
absent de la grille ») sont depuis fusionnées dans `dev` (lot Prix, PR #5) --
`rules/rules/R22.py` produit exactement le `detail` que ce module attend
(`produit`, `code`, `unite_bon`, `dernier_prix`), vérifié par l'essai de bout
en bout (`ingest/tests/test_ia_prix_bout_en_bout.py`). Ce module ne dépend
toujours d'aucune liste écrite à la main : la catégorie « prix » se lit dans
`ingest.anomalies.CATEGORIES_REGLE` à l'exécution
(`regles_de_categorie("prix")`), et `REGLES_PRIX_INTERNET` n'est qu'une
constante (`{"R22"}`).

Minimisation des données envoyées à l'IA (CDC « l'IA extrait et normalise,
elle ne décide jamais ») : l'explication ne reçoit que le titre de la règle,
le nom du fournisseur et le `detail` de l'anomalie (déjà purgé de tout
identifiant par les règles elles-mêmes) ; la recherche de prix internet ne
reçoit jamais le prix du bon (`prix_bon`), seulement fournisseur/désignation/
référence/unité — la comparaison avec la grille se fait entièrement côté
serveur, jamais par l'IA.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extract.reponses_ia import (
    SCHEMA_EXPLICATION,
    SCHEMA_PRIX_INTERNET,
    PrixInternetLu,
    ReponseIAInvalide,
    lire_explication,
    lire_prix_internet,
)
from app.modules.ingest.anomalies import (
    AnomalieIntrouvable,
    condition_regles_actives,
    regles_de_categorie,
)
from app.modules.ingest.commun import regles_masquees
from app.modules.ingest.models import (
    Anomalie,
    Document,
    ExplicationAlerte,
    Fournisseur,
    PrixInternet,
)
from app.modules.ingest.opencode import ErreurIA, IAIndisponible, ia_active, interroger
from app.modules.normalize.texte import normaliser_libelle

# Constantes du brief T6 -----------------------------------------------------

# Seule règle du lot Prix qui déclenche une recherche de prix sur internet
# (« Produit absent de la grille ») -- tant que ce lot n'est pas fusionné,
# aucune anomalie de cette règle n'existe et `chercher_prix_internet` ne fait
# jamais de requête (sélection SQL vide).
REGLES_PRIX_INTERNET: frozenset[str] = frozenset({"R22"})

# Durée de réutilisation d'un résultat `trouve`/`non_verifiable` (§6.1) et
# nombre d'échecs qui suspendent les nouvelles tentatives -- pour
# l'explication (mêmes détail, §5.3) comme pour le prix internet (mêmes clé
# sur 7 jours, §6.1) : un seul et même seuil, jamais deux constantes qui
# pourraient diverger.
DUREE_CACHE_PRIX = timedelta(days=30)
ECHECS_MAX = 3

# Fenêtre glissante des échecs de prix internet (§6.1) : distincte de
# `DUREE_CACHE_PRIX` (30 jours pour un résultat exploitable), un échec ne
# bloque une nouvelle tentative que 7 jours.
_FENETRE_ECHECS_PRIX = timedelta(days=7)

# Plafond de `GET /api/ia/prix-internet` (brief T10a) : au-delà, la route
# refuse (422) plutôt que de charger un nombre arbitraire d'anomalies --
# largement au-dessus de ce qu'une page « Prix à vérifier » affiche en une
# fois (regroupée par produit, spec §8.1).
MAX_ANOMALIES_PRIX_INTERNET = 200

# Titres courts, en mots, des règles de prix -- `ui`/`libelles` n'étant pas
# côté serveur (§5.2). Reprend R07-R09 (actives sur cette branche) et R19-R25
# (lot Prix, pas encore fusionné dans `dev` -- ces règles existent déjà sur
# la branche du lot Prix, `origin/feature/phase-3-prix`) : aucune
# modification de ce fichier ne sera nécessaire à la fusion. R19, R21 et R25
# recopient mot pour mot les titres de `web/src/ui/libelles.ts` de cette
# branche (fix round 2, relecture finale, lus via `git show
# origin/feature/phase-3-prix:web/src/ui/libelles.ts`) : les cinq autres
# (R20, R22, R23, R24) correspondaient déjà.
TITRES_REGLES_PRIX: dict[str, str] = {
    "R07": "Prix un peu plus cher",
    "R08": "Prix plus cher que d'habitude",
    "R09": "Remise habituelle oubliée",
    "R19": "Prix plus cher que la grille",
    "R20": "Prix plus cher que la dernière fois",
    "R21": "Prix moins cher que la grille",
    "R22": "Produit absent de la grille",
    "R23": "Produit reconnu seulement par son nom",
    "R24": "Unités différentes",
    "R25": "Grille de prix ancienne",
}
_TITRE_REPLI = "Écart de prix"

_TIRET = "—"


# --------------------------------------------------------------------------
# Empreinte du détail et clé de cache produit (partagées par les deux
# usages de ce module)
# --------------------------------------------------------------------------


def empreinte_detail(detail: Mapping[str, Any]) -> str:
    """SHA-256 du `detail` d'une anomalie en JSON canonique (`sort_keys`,
    séparateurs compacts, accents non échappés) : deux détails égaux au sens
    Python produisent toujours la même empreinte, quel que soit l'ordre
    d'insertion des clés -- sert à savoir si le détail d'une anomalie a
    changé depuis la dernière explication (§5.1/§5.3)."""
    canonique = json.dumps(
        detail, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


def cle_produit_internet(
    fournisseur_id: uuid.UUID | None, designation: str, code: str | None
) -> str:
    """Clé de cache d'un produit pour la recherche de prix internet (§6.1) :
    fournisseur (ou `-` si absent) puis référence normalisée (espaces
    retirés, casse et ponctuation conservées -- une référence fabricant est
    un identifiant exact, pas un libellé à rapprocher) si `code` est présent
    et différent de « — », sinon désignation normalisée
    (`normaliser_libelle`, insensible à la casse/aux accents/à la
    ponctuation, comme pour un nom de chantier ou de fournisseur).

    Le `fournisseur_id` étant inclus dans la clé elle-même, deux fournisseurs
    différents ne peuvent jamais produire la même clé pour un même produit :
    `PrixInternet.cle` seul suffit donc à retrouver le cache d'un produit
    (pas besoin de recombiner avec `fournisseur_id` dans les requêtes)."""
    prefixe = str(fournisseur_id) if fournisseur_id is not None else "-"
    code_normalise = code.strip() if code is not None else ""
    if code_normalise and code_normalise != _TIRET:
        return f"{prefixe}|ref:{''.join(code_normalise.split())}"
    return f"{prefixe}|nom:{normaliser_libelle(designation)}"


def _echec_injoignable(code: str) -> bool:
    """Échec compté comme « IA injoignable » (`BilanIA.echecs_injoignable`)
    -- problème de transport ou d'authentification auprès du fournisseur de
    l'IA (réseau, délai, statut HTTP, abonnement déconnecté), jamais une
    réponse simplement invalide ou incomplète (qui reste un échec
    « ordinaire », imputable au contenu de la réponse, pas à la
    joignabilité)."""
    return code in ("reseau", "delai", "ProviderAuthError") or code.startswith("http_")


def _valeur_utile(valeur: Any) -> str | None:
    """Chaîne non vide et différente de « — », sinon `None` -- même
    convention que les autres lectures de `detail` de ce dépôt (`code`,
    `unite_bon`, `dernier_prix`)."""
    if not isinstance(valeur, str):
        return None
    nettoyee = valeur.strip()
    if not nettoyee or nettoyee == _TIRET:
        return None
    return nettoyee


# --------------------------------------------------------------------------
# Bilan commun aux deux tâches (§5.4/§6.4 du brief)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BilanIA:
    """Résultat d'un passage d'`expliquer_alertes` ou de
    `chercher_prix_internet` (brief T6) -- combiné par `python -m app.cli
    ia-prix` pour son message et son code de sortie. `non_verifiables` reste
    toujours à 0 pour `expliquer_alertes` (une explication est `ok` ou en
    `echec`, jamais « non vérifiable », concept propre au prix internet).
    `arret` : la boucle s'est arrêtée avant d'avoir traité toutes les
    anomalies sélectionnées, faute d'IA joignable (`IAIndisponible`,
    « plafond » ou « éteinte ») -- aucune tentative supplémentaire n'a alors
    été faite."""

    ok: int = 0
    non_verifiables: int = 0
    echecs: int = 0
    echecs_injoignable: int = 0
    arret: Literal["plafond", "eteinte"] | None = None


# --------------------------------------------------------------------------
# Explication des alertes prix (§5)
# --------------------------------------------------------------------------

_CONSIGNE_EXPLICATION = (
    "Explique en une à trois phrases simples, pour un dirigeant d'entreprise "
    "du bâtiment, ce que montre cet écart et ce qui peut l'expliquer (hausse "
    "de tarif, conditionnement ou unité différents, remise…). N'utilise que "
    "les chiffres ci-dessus, recopiés à l'identique ; écris les autres "
    "nombres en lettres. Ne dis pas si le prix est acceptable : un humain "
    "décidera."
)


def _texte_explication(
    titre: str, fournisseur: str | None, detail: Mapping[str, Any]
) -> str:
    """Texte envoyé à l'agent `habitat-explication` (§5.2) : titre de la
    règle, fournisseur, puis une ligne `- clé : valeur` par entrée du
    `detail` -- rien d'autre (ni chantier, ni bon, ni aucun identifiant : le
    `detail` d'une règle de prix n'en porte déjà aucun, cf. R07-R09)."""
    lignes = [
        f"Alerte : {titre}",
        f"Fournisseur : {fournisseur or _TIRET}",
        "Données :",
    ]
    lignes.extend(f"- {cle} : {valeur}" for cle, valeur in detail.items())
    lignes.append(_CONSIGNE_EXPLICATION)
    return "\n".join(lignes)


async def _enregistrer_explication_ok(
    session: AsyncSession,
    *,
    anomalie_id: uuid.UUID,
    existante: ExplicationAlerte | None,
    empreinte: str,
    texte: str,
    modele: str | None,
) -> None:
    if existante is None:
        session.add(
            ExplicationAlerte(
                anomalie_id=anomalie_id,
                empreinte_detail=empreinte,
                statut="ok",
                texte=texte,
                echecs=0,
                modele=modele,
            )
        )
    else:
        existante.empreinte_detail = empreinte
        existante.statut = "ok"
        existante.texte = texte
        existante.echecs = 0
        existante.modele = modele
    await session.commit()


async def _enregistrer_explication_echec(
    session: AsyncSession,
    *,
    anomalie_id: uuid.UUID,
    existante: ExplicationAlerte | None,
    empreinte: str,
) -> None:
    """`echecs` remis à 1 si le détail a changé depuis la dernière tentative
    (nouvelle empreinte), sinon incrémenté (§5.3 : « un nouveau détail remet
    le compteur à zéro » -- comprendre : à 1, ce premier échec sur le nouveau
    détail comptant déjà comme une tentative)."""
    if existante is None:
        session.add(
            ExplicationAlerte(
                anomalie_id=anomalie_id,
                empreinte_detail=empreinte,
                statut="echec",
                texte=None,
                echecs=1,
                modele=None,
            )
        )
    else:
        meme_empreinte = existante.empreinte_detail == empreinte
        existante.empreinte_detail = empreinte
        existante.statut = "echec"
        existante.texte = None
        existante.echecs = existante.echecs + 1 if meme_empreinte else 1
        existante.modele = None
    await session.commit()


async def expliquer_alertes(session: AsyncSession, http: httpx.AsyncClient) -> BilanIA:
    """Explique chaque alerte prix ouverte qui en a besoin (§5.1) : statut
    `ouverte`, catégorie « prix » (`ingest.anomalies.CATEGORIES_REGLE` lue à
    l'exécution via `regles_de_categorie`, jamais une liste écrite à la
    main), règle active -- `condition_regles_actives(exclues=await
    ingest.commun.regles_masquees(session))`, calculé une seule fois pour
    cet appel : depuis la fusion du lot Prix, la catégorie « prix » inclut
    R19-R25 (fix round 1, T10a), dont le masquage ne dépend pas seulement de
    `regles_desactivees()` (R07-R09/R06) mais aussi de l'interrupteur
    général `prix_controle_bl_actif` et des sept interrupteurs par alerte
    (réglages `prix_…`, en base) -- sans `regles_masquees`, l'IA expliquerait
    des alertes que la page Prix elle-même ne montre plus, gaspillant le
    plafond quotidien --, plus récentes d'abord ; à traiter si l'anomalie
    n'a pas encore d'`ExplicationAlerte`, si son détail a changé depuis
    (empreinte différente), ou si la dernière tentative a échoué sur le même
    détail et `echecs < ECHECS_MAX`.

    Chargées en lot (deux requêtes seulement, jamais une par anomalie) :
    les anomalies elles-mêmes (jointes au fournisseur de leur document) puis
    les `ExplicationAlerte` déjà connues pour ces anomalies.

    `IAIndisponible` (plafond du jour atteint, ou IA éteinte en cours de
    route) arrête la boucle immédiatement (`BilanIA.arret`) : aucune tentative
    supplémentaire, les anomalies restantes seront reprises au prochain
    passage. Une ligne `ExplicationAlerte` est commitée après chaque
    anomalie traitée (succès ou échec), jamais groupée en une seule
    transaction finale -- un échec plus loin dans la boucle ne doit jamais
    annuler les explications déjà obtenues."""
    ok = 0
    echecs = 0
    echecs_injoignable = 0
    arret: Literal["plafond", "eteinte"] | None = None

    regles_prix = regles_de_categorie("prix")
    if not regles_prix:
        return BilanIA()

    exclues = await regles_masquees(session)
    lignes = (
        await session.execute(
            select(Anomalie, Fournisseur.nom)
            .outerjoin(Document, Document.id == Anomalie.document_id)
            .outerjoin(Fournisseur, Fournisseur.id == Document.fournisseur_id)
            .where(
                Anomalie.statut == "ouverte",
                condition_regles_actives(exclues=exclues),
                Anomalie.regle.in_(tuple(regles_prix)),
            )
            .order_by(Anomalie.created_at.desc())
        )
    ).all()
    if not lignes:
        return BilanIA()

    anomalie_ids = [anomalie.id for anomalie, _ in lignes]
    explications_existantes = {
        explication.anomalie_id: explication
        for explication in (
            await session.execute(
                select(ExplicationAlerte).where(
                    ExplicationAlerte.anomalie_id.in_(anomalie_ids)
                )
            )
        ).scalars()
    }

    for anomalie, nom_fournisseur in lignes:
        empreinte = empreinte_detail(anomalie.detail)
        existante = explications_existantes.get(anomalie.id)
        a_traiter = (
            existante is None
            or existante.empreinte_detail != empreinte
            or (existante.statut == "echec" and existante.echecs < ECHECS_MAX)
        )
        if not a_traiter:
            continue

        titre = TITRES_REGLES_PRIX.get(anomalie.regle, _TITRE_REPLI)
        texte = _texte_explication(titre, nom_fournisseur, anomalie.detail)

        try:
            reponse = await interroger(
                session,
                http,
                usage="explication",
                agent="habitat-explication",
                texte=texte,
                schema=SCHEMA_EXPLICATION,
            )
        except IAIndisponible as exc:
            arret = exc.raison
            break
        except ErreurIA as exc:
            await _enregistrer_explication_echec(
                session,
                anomalie_id=anomalie.id,
                existante=existante,
                empreinte=empreinte,
            )
            echecs += 1
            if _echec_injoignable(exc.code):
                echecs_injoignable += 1
            continue

        try:
            texte_explication = lire_explication(reponse.structure, anomalie.detail)
        except ReponseIAInvalide:
            await _enregistrer_explication_echec(
                session,
                anomalie_id=anomalie.id,
                existante=existante,
                empreinte=empreinte,
            )
            echecs += 1
            continue

        await _enregistrer_explication_ok(
            session,
            anomalie_id=anomalie.id,
            existante=existante,
            empreinte=empreinte,
            texte=texte_explication,
            modele=reponse.modele,
        )
        ok += 1

    return BilanIA(
        ok=ok, echecs=echecs, echecs_injoignable=echecs_injoignable, arret=arret
    )


# --------------------------------------------------------------------------
# Prix trouvé sur internet (§6)
# --------------------------------------------------------------------------

_CONSIGNE_PRIX = (
    "Trouve le prix public actuel de ce produit sur internet, en euros, chez "
    "le fabricant ou un revendeur identifiable. Ouvre la page du produit "
    "avec webfetch avant de donner un prix. Vérifie la référence, le "
    "conditionnement et l'unité. Indique si le prix est HT ou TTC. Si tu ne "
    "peux pas vérifier, réponds prix_non_verifiable avec la raison. Ne donne "
    "jamais un prix estimé."
)


def _texte_prix(
    *, fournisseur: str | None, designation: str, code: str | None, unite: str | None
) -> str:
    """Texte envoyé à l'agent `habitat-prix` (§6.1/§6.2) : fournisseur
    habituel, désignation, référence, unité -- **jamais** le prix du bon
    (`prix_bon`), qui n'apparaît nulle part dans ce texte : la recherche ne
    doit pas être orientée par le prix qu'on cherche à vérifier."""
    lignes = [
        f"Fournisseur habituel : {fournisseur or _TIRET}",
        f"Désignation : {designation}",
        f"Référence : {code or _TIRET}",
        f"Unité : {unite or _TIRET}",
        _CONSIGNE_PRIX,
    ]
    return "\n".join(lignes)


async def rechercher_prix(
    session: AsyncSession,
    http: httpx.AsyncClient,
    *,
    fournisseur: str | None,
    designation: str,
    code: str | None,
    unite: str | None,
) -> tuple[PrixInternetLu, str | None]:
    """Une recherche de prix internet pour un produit (§6.2), partagée par
    `chercher_prix_internet` (avec cache et enregistrement) et par l'essai
    (`essayer_prix_internet`, sans l'un ni l'autre). Délai de 240 s (recherche
    internet, plus longue que les autres usages de l'IA).

    Écart mineur avec le brief T6 (signature `-> PrixInternetLu`) : cette
    fonction renvoie aussi le modèle utilisé (`reponse.modele`), nécessaire
    à `chercher_prix_internet` pour remplir `PrixInternet.modele` -- une
    information que `PrixInternetLu` (module pur `extract.reponses_ia`,
    sans notion de fournisseur d'IA) ne porte pas et ne doit pas porter.
    L'essai (§7) ignore simplement ce second élément, aucune trace du modèle
    n'étant enregistrée hors `appel_ia`."""
    texte = _texte_prix(
        fournisseur=fournisseur, designation=designation, code=code, unite=unite
    )
    reponse = await interroger(
        session,
        http,
        usage="prix",
        agent="habitat-prix",
        texte=texte,
        schema=SCHEMA_PRIX_INTERNET,
        delai=240,
    )
    return lire_prix_internet(reponse.structure, reponse.pages), reponse.modele


def _dernier_prix_utile(detail: Mapping[str, Any]) -> bool:
    """`True` si le détail porte un dernier prix facturé exploitable (§6.1) :
    le produit a alors une référence interne, aucune recherche internet
    n'est nécessaire."""
    return _valeur_utile(detail.get("dernier_prix")) is not None


def _ligne_prix_echec(
    *,
    fournisseur_id: uuid.UUID | None,
    cle: str,
    designation: str,
    code: str | None,
    raison: str,
    consulte_le: datetime,
) -> PrixInternet:
    return PrixInternet(
        fournisseur_id=fournisseur_id,
        cle=cle,
        designation=designation,
        code=code,
        statut="echec",
        prix=None,
        devise=None,
        taxes=None,
        unite=None,
        conditionnement=None,
        produit_trouve=None,
        source_url=None,
        confiance=None,
        raison=raison,
        modele=None,
        consulte_le=consulte_le,
    )


async def chercher_prix_internet(
    session: AsyncSession, http: httpx.AsyncClient
) -> BilanIA:
    """Cherche un prix internet pour chaque produit qui en a besoin (§6.1) :
    anomalies ouvertes, actives, de règle `REGLES_PRIX_INTERNET`, dont le
    détail n'a pas de `dernier_prix` utile -- une seule recherche par clé de
    produit dans ce passage (`cle_produit_internet`), même si plusieurs
    anomalies partagent la même clé.

    Cache et échecs vérifiés en lot (deux requêtes groupées par clé, jamais
    une par produit) : un résultat `trouve`/`non_verifiable` de moins de
    `DUREE_CACHE_PRIX` (30 jours) pour la clé -> rien ; `ECHECS_MAX` (3)
    lignes `echec` ou plus pour la clé dans les `_FENETRE_ECHECS_PRIX` (7)
    derniers jours -> rien non plus (évite d'épuiser le plafond sur un
    produit dont la recherche échoue systématiquement).

    `IAIndisponible` arrête la boucle (`BilanIA.arret`), comme
    `expliquer_alertes`. Une ligne `PrixInternet` est commitée après chaque
    produit cherché (succès, non vérifiable ou échec).

    Sélection non masquée -- `condition_regles_actives(exclues=await
    ingest.commun.regles_masquees(session))`, calculé une seule fois pour
    cet appel (fix round 1, T10a) : R22 est masquée dès que l'interrupteur
    général `prix_controle_bl_actif` est éteint (défaut) ou que son propre
    interrupteur `prix_alerte_absent_grille` l'est -- sans quoi la recherche
    internet se déclencherait pour une alerte que la page Prix ne montre
    plus, gaspillant le plafond quotidien pour rien."""
    exclues = await regles_masquees(session)
    lignes = (
        await session.execute(
            select(Anomalie, Document.fournisseur_id, Fournisseur.nom)
            .outerjoin(Document, Document.id == Anomalie.document_id)
            .outerjoin(Fournisseur, Fournisseur.id == Document.fournisseur_id)
            .where(
                Anomalie.statut == "ouverte",
                condition_regles_actives(exclues=exclues),
                Anomalie.regle.in_(tuple(REGLES_PRIX_INTERNET)),
            )
            .order_by(Anomalie.created_at.desc())
        )
    ).all()

    candidats: dict[
        str, tuple[uuid.UUID | None, str | None, str, str | None, str | None]
    ] = {}
    for anomalie, fournisseur_id, nom_fournisseur in lignes:
        if _dernier_prix_utile(anomalie.detail):
            continue
        designation = _valeur_utile(anomalie.detail.get("produit"))
        if designation is None:
            continue
        code = _valeur_utile(anomalie.detail.get("code"))
        unite = _valeur_utile(anomalie.detail.get("unite_bon"))
        cle = cle_produit_internet(fournisseur_id, designation, code)
        candidats.setdefault(
            cle, (fournisseur_id, nom_fournisseur, designation, code, unite)
        )

    if not candidats:
        return BilanIA()

    cles = list(candidats.keys())
    maintenant = datetime.now(UTC)

    cles_en_cache = set(
        (
            await session.execute(
                select(PrixInternet.cle)
                .distinct()
                .where(
                    PrixInternet.cle.in_(cles),
                    PrixInternet.statut.in_(("trouve", "non_verifiable")),
                    PrixInternet.consulte_le >= maintenant - DUREE_CACHE_PRIX,
                )
            )
        ).scalars()
    )

    echecs_par_cle = {
        cle: nombre
        for cle, nombre in (
            await session.execute(
                select(PrixInternet.cle, func.count())
                .where(
                    PrixInternet.cle.in_(cles),
                    PrixInternet.statut == "echec",
                    PrixInternet.consulte_le >= maintenant - _FENETRE_ECHECS_PRIX,
                )
                .group_by(PrixInternet.cle)
            )
        ).all()
    }

    ok = 0
    non_verifiables = 0
    echecs = 0
    echecs_injoignable = 0
    arret: Literal["plafond", "eteinte"] | None = None

    for cle, candidat in candidats.items():
        fournisseur_id, nom_fournisseur, designation, code, unite = candidat
        if cle in cles_en_cache:
            continue
        if echecs_par_cle.get(cle, 0) >= ECHECS_MAX:
            continue

        try:
            resultat, modele = await rechercher_prix(
                session,
                http,
                fournisseur=nom_fournisseur,
                designation=designation,
                code=code,
                unite=unite,
            )
        except IAIndisponible as exc:
            arret = exc.raison
            break
        except ErreurIA as exc:
            session.add(
                _ligne_prix_echec(
                    fournisseur_id=fournisseur_id,
                    cle=cle,
                    designation=designation,
                    code=code,
                    raison=exc.code,
                    consulte_le=datetime.now(UTC),
                )
            )
            await session.commit()
            echecs += 1
            if _echec_injoignable(exc.code):
                echecs_injoignable += 1
            continue
        except ReponseIAInvalide:
            session.add(
                _ligne_prix_echec(
                    fournisseur_id=fournisseur_id,
                    cle=cle,
                    designation=designation,
                    code=code,
                    raison="reponse_invalide",
                    consulte_le=datetime.now(UTC),
                )
            )
            await session.commit()
            echecs += 1
            continue

        session.add(
            PrixInternet(
                fournisseur_id=fournisseur_id,
                cle=cle,
                designation=designation,
                code=code,
                statut=resultat.statut,
                prix=resultat.prix,
                devise=resultat.devise,
                taxes=resultat.taxes,
                unite=resultat.unite,
                conditionnement=resultat.conditionnement,
                produit_trouve=resultat.produit_trouve,
                source_url=resultat.source_url,
                confiance=resultat.confiance,
                raison=resultat.raison,
                modele=modele,
                consulte_le=datetime.now(UTC),
            )
        )
        await session.commit()
        if resultat.statut == "trouve":
            ok += 1
        else:
            non_verifiables += 1

    return BilanIA(
        ok=ok,
        non_verifiables=non_verifiables,
        echecs=echecs,
        echecs_injoignable=echecs_injoignable,
        arret=arret,
    )


# --------------------------------------------------------------------------
# Essai avant de se fier au prix internet (§7, document d'Ilane §16)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProduitEssai:
    """Une ligne du CSV `--fichier` de `essai-prix-internet` (§7) --
    `designation` seule est obligatoire, les trois autres champs sont `None`
    quand la colonne est vide."""

    fournisseur: str | None
    designation: str
    code: str | None
    unite: str | None


@dataclass(frozen=True)
class LigneEssai:
    """Résultat de l'essai pour un produit (§7) : soit `resultat` (recherche
    réussie, `trouve` ou `non_verifiable`), soit `erreur` (code
    `ErreurIA`/`IAIndisponible`) -- jamais les deux. `duree_s` : temps
    mesuré autour de l'appel, en secondes."""

    produit: ProduitEssai
    resultat: PrixInternetLu | None
    erreur: str | None
    duree_s: float


async def essayer_prix_internet(
    session: AsyncSession, http: httpx.AsyncClient, produits: Sequence[ProduitEssai]
) -> list[LigneEssai]:
    """Essaie la recherche de prix internet sur une liste de produits réels
    (§7, document d'Ilane §16) : pour chacun, `rechercher_prix` sans cache ni
    enregistrement (seul `appel_ia`, écrit par `ingest.opencode.interroger`,
    garde une trace) -- jamais de ligne `PrixInternet`.

    Un produit en échec (`ErreurIA`/`IAIndisponible`/`ReponseIAInvalide`)
    n'arrête pas l'essai : chaque produit est indépendant, le but étant de
    juger la qualité d'ensemble sur une vingtaine de produits, y compris
    quand certains échouent (plafond du jour atteint en cours d'essai,
    produit introuvable, etc.)."""
    lignes: list[LigneEssai] = []
    for produit in produits:
        debut = time.monotonic()
        resultat: PrixInternetLu | None = None
        erreur: str | None = None
        try:
            resultat, _modele = await rechercher_prix(
                session,
                http,
                fournisseur=produit.fournisseur,
                designation=produit.designation,
                code=produit.code,
                unite=produit.unite,
            )
        except IAIndisponible as exc:
            erreur = exc.raison
        except ErreurIA as exc:
            erreur = exc.code
        except ReponseIAInvalide:
            erreur = "reponse_invalide"
        duree_s = time.monotonic() - debut
        lignes.append(
            LigneEssai(
                produit=produit, resultat=resultat, erreur=erreur, duree_s=duree_s
            )
        )
    return lignes


# --------------------------------------------------------------------------
# Avis d'une anomalie (§6.4, consommé par `api/ia.py`)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExplicationVue:
    """Explication affichée pour une anomalie -- `cree_le` est
    `ExplicationAlerte.updated_at` (dernière fois que ce texte a été produit
    ou mis à jour), pas `created_at` (qui daterait la toute première
    tentative, potentiellement bien antérieure et sur un détail différent)."""

    texte: str
    cree_le: datetime


@dataclass(frozen=True)
class PrixInternetVue:
    """Dernier résultat de prix internet affiché pour une anomalie -- une
    ligne `echec` n'est jamais montrée (§5.3/§6.4 : seul `trouve` ou
    `non_verifiable` fait sens pour un humain)."""

    statut: str
    prix: Decimal | None
    devise: str | None
    taxes: str | None
    unite: str | None
    conditionnement: str | None
    produit_trouve: str | None
    source_url: str | None
    confiance: str | None
    raison: str | None
    consulte_le: datetime


@dataclass(frozen=True)
class AvisIA:
    """Réponse de `avis_ia_anomalie` (`GET /api/ia/anomalies/{id}`)."""

    ia_active: bool
    explication: ExplicationVue | None
    prix_internet: PrixInternetVue | None


def _cle_produit_pour_anomalie(
    detail: Mapping[str, Any], fournisseur_id: uuid.UUID | None
) -> str | None:
    """Clé de cache produit (`cle_produit_internet`) d'une anomalie R22, ou
    `None` si son `detail` ne porte pas de désignation exploitable (cas
    défensif, jamais atteint en pratique -- `rules/R22.py` renseigne
    toujours `produit`) -- factorise le calcul partagé par
    `avis_ia_anomalie` et `prix_internet_des_anomalies` (brief T10a, « aucune
    duplication avec avis_ia_anomalie »)."""
    designation = _valeur_utile(detail.get("produit"))
    if designation is None:
        return None
    code = _valeur_utile(detail.get("code"))
    return cle_produit_internet(fournisseur_id, designation, code)


def _vue_prix_internet(ligne: PrixInternet) -> PrixInternetVue:
    """`PrixInternet` (ligne de base) -> `PrixInternetVue` (dataclass
    affichée) -- factorise la construction partagée par `avis_ia_anomalie`
    et `prix_internet_des_anomalies` (brief T10a)."""
    return PrixInternetVue(
        statut=ligne.statut,
        prix=ligne.prix,
        devise=ligne.devise,
        taxes=ligne.taxes,
        unite=ligne.unite,
        conditionnement=ligne.conditionnement,
        produit_trouve=ligne.produit_trouve,
        source_url=ligne.source_url,
        confiance=ligne.confiance,
        raison=ligne.raison,
        consulte_le=ligne.consulte_le,
    )


async def _dernieres_vues_prix_internet(
    session: AsyncSession, cles: Sequence[str]
) -> dict[str, PrixInternetVue]:
    """Dernière ligne `trouve`/`non_verifiable` (jamais `echec`, §5.3/§6.4)
    de chacune de `cles`, en une seule requête (triée par `consulte_le`
    décroissant : la première ligne rencontrée pour une clé est la plus
    récente) -- factorise la lecture du cache de prix internet, partagée par
    `avis_ia_anomalie` (une seule clé) et `prix_internet_des_anomalies`
    (potentiellement des dizaines, brief T10a : « une requête ... pour les
    PrixInternet de toutes les clés concernées »)."""
    cles_uniques = tuple(dict.fromkeys(cles))
    if not cles_uniques:
        return {}
    lignes = (
        await session.execute(
            select(PrixInternet)
            .where(
                PrixInternet.cle.in_(cles_uniques),
                PrixInternet.statut.in_(("trouve", "non_verifiable")),
            )
            .order_by(PrixInternet.consulte_le.desc())
        )
    ).scalars()
    vues: dict[str, PrixInternetVue] = {}
    for ligne in lignes:
        vues.setdefault(ligne.cle, _vue_prix_internet(ligne))
    return vues


async def avis_ia_anomalie(session: AsyncSession, anomalie_id: uuid.UUID) -> AvisIA:
    """Avis de l'IA sur une anomalie (§6.4) : `AnomalieIntrouvable` si
    l'anomalie n'existe pas ou si sa règle est masquée côté serveur
    (`ingest.commun.regles_masquees`, même fonction que le reste d'`ingest`
    -- fix round 1, T10a : avant cette correction, seul `regles_desactivees`
    était vérifié, ce qui ne masquait jamais R19-R25 malgré leurs propres
    interrupteurs `prix_…` ; corrigé pour la même raison que `traiter_
    anomalie`, dont cette route reprend le principe : une alerte masquée est
    introuvable pour tout le reste de l'application).

    `explication` n'est rendue que si la dernière tentative a réussi
    (`statut="ok"`) **et** que son empreinte correspond encore au détail
    actuel de l'anomalie -- sinon `None` (explication périmée, en cours de
    remplacement par le prochain passage de `expliquer_alertes`).

    `prix_internet` n'est jamais rendu pour une règle hors
    `REGLES_PRIX_INTERNET` (le concept n'a pas de sens pour un simple écart
    de prix face à l'historique) ; sinon, la dernière ligne `trouve`/
    `non_verifiable` de la clé du produit -- une ligne `echec` n'est jamais
    montrée."""
    anomalie = await session.get(Anomalie, anomalie_id)
    if anomalie is None or anomalie.regle in await regles_masquees(session):
        raise AnomalieIntrouvable(str(anomalie_id))

    explication_vue: ExplicationVue | None = None
    explication = (
        await session.execute(
            select(ExplicationAlerte).where(
                ExplicationAlerte.anomalie_id == anomalie_id
            )
        )
    ).scalar_one_or_none()
    if (
        explication is not None
        and explication.statut == "ok"
        and explication.texte is not None
        and explication.empreinte_detail == empreinte_detail(anomalie.detail)
    ):
        explication_vue = ExplicationVue(
            texte=explication.texte, cree_le=explication.updated_at
        )

    prix_vue: PrixInternetVue | None = None
    if anomalie.regle in REGLES_PRIX_INTERNET:
        fournisseur_id: uuid.UUID | None = None
        if anomalie.document_id is not None:
            fournisseur_id = (
                await session.execute(
                    select(Document.fournisseur_id).where(
                        Document.id == anomalie.document_id
                    )
                )
            ).scalar_one_or_none()
        cle = _cle_produit_pour_anomalie(anomalie.detail, fournisseur_id)
        if cle is not None:
            vues = await _dernieres_vues_prix_internet(session, (cle,))
            prix_vue = vues.get(cle)

    return AvisIA(
        ia_active=ia_active(), explication=explication_vue, prix_internet=prix_vue
    )


# --------------------------------------------------------------------------
# Prix internet de plusieurs anomalies (brief T10a) -- route groupée de la
# page « Prix à vérifier » (`GET /api/ia/prix-internet`, lot Prix session B) :
# le contrôleur a tranché pour une route dédiée plutôt que d'enrichir
# `GET /api/prix/alertes`, afin de ne jamais faire dépendre le service du lot
# Prix (`ingest.prix_bl`) de l'IA.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PrixInternetLot:
    """Réponse de `prix_internet_des_anomalies` (`GET /api/ia/prix-internet`)
    : le prix internet de plusieurs anomalies en un seul appel, pour la 3ᵉ
    colonne « Internet » de la page « Prix à vérifier ». `par_anomalie` ne
    porte une clé que pour les identifiants qui désignent une anomalie R22
    (`REGLES_PRIX_INTERNET`) ouverte et non masquée -- toute autre entrée de
    `anomalie_ids` (inconnue, masquée, fermée, autre règle) est simplement
    absente du dictionnaire, jamais une erreur (la page peut envoyer les
    identifiants de rangées qui n'ont pas d'alerte R22)."""

    ia_active: bool
    par_anomalie: dict[uuid.UUID, PrixInternetVue | None]


async def prix_internet_des_anomalies(
    session: AsyncSession, anomalie_ids: Sequence[uuid.UUID]
) -> PrixInternetLot:
    """Prix internet de plusieurs anomalies en une seule fois (brief T10a) :
    même sélection qu'`avis_ia_anomalie` (anomalie ouverte, non masquée --
    `condition_regles_actives(exclues=await ingest.commun.regles_masquees
    (session))`, calculé une seule fois pour cet appel : même fonction que
    le reste d'`ingest` (`ingest.prix_bl.lister_alertes_prix`, notamment),
    qui tient compte à la fois de `regles_desactivees()` (R07-R09/R06) et des
    interrupteurs `prix_…` du lot Prix (général et par alerte) -- fix round
    1, T10a --, règle ∈ `REGLES_PRIX_INTERNET`) et même lecture du cache
    (`_cle_produit_pour_anomalie`/`_dernieres_vues_prix_internet`, aucune
    duplication de calcul entre les deux fonctions -- le comportement
    d'`avis_ia_anomalie` ne change pas), mais en lot : une seule requête pour
    les anomalies (jointes à leur document pour le fournisseur), une seule
    pour les `PrixInternet` de toutes les clés concernées -- jamais une
    requête par anomalie.

    Doublons de `anomalie_ids` ignorés (`dict.fromkeys`, même idiome que
    `ingest.prix_bl._charger_groupe`). `ValueError` si, une fois dédupliqués,
    il en reste plus de `MAX_ANOMALIES_PRIX_INTERNET` (200) -- l'API traduit
    en 422 (message en français)."""
    ids_uniques = tuple(dict.fromkeys(anomalie_ids))
    if len(ids_uniques) > MAX_ANOMALIES_PRIX_INTERNET:
        raise ValueError(
            f"{MAX_ANOMALIES_PRIX_INTERNET} identifiants d'anomalies au plus"
        )
    if not ids_uniques:
        return PrixInternetLot(ia_active=ia_active(), par_anomalie={})

    exclues = await regles_masquees(session)
    lignes = (
        await session.execute(
            select(Anomalie, Document.fournisseur_id)
            .outerjoin(Document, Document.id == Anomalie.document_id)
            .where(
                Anomalie.id.in_(ids_uniques),
                Anomalie.statut == "ouverte",
                condition_regles_actives(exclues=exclues),
                Anomalie.regle.in_(tuple(REGLES_PRIX_INTERNET)),
            )
        )
    ).all()

    par_anomalie: dict[uuid.UUID, PrixInternetVue | None] = {}
    cle_par_anomalie: dict[uuid.UUID, str] = {}
    for anomalie, fournisseur_id in lignes:
        par_anomalie[anomalie.id] = None
        cle = _cle_produit_pour_anomalie(anomalie.detail, fournisseur_id)
        if cle is not None:
            cle_par_anomalie[anomalie.id] = cle

    vues_par_cle = await _dernieres_vues_prix_internet(
        session, tuple(cle_par_anomalie.values())
    )
    for anomalie_id, cle in cle_par_anomalie.items():
        vue = vues_par_cle.get(cle)
        if vue is not None:
            par_anomalie[anomalie_id] = vue

    return PrixInternetLot(ia_active=ia_active(), par_anomalie=par_anomalie)
