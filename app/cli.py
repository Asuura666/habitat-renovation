"""CLI de recette (T7) : `python -m app.cli bl-non-recus <facture.pdf>`.

Lit une facture PDF via l'OCR Mistral et affiche, pour chaque bloc
« Concerne le B.L. », si une photo de bon a déjà été reçue — le livrable
visible du lot 1. CLI en lecture seule (décision D14 du brief) : elle parse
la facture et interroge la base, mais n'enregistre rien.

N'importe que `app.core` (config, db) et `app.modules.ingest` (`service.py`,
`mistral.py`), plus `FactureIllisible` d'`extract` (nécessaire pour
distinguer le code de sortie) : `ingest/service.py` reste le seul
orchestrateur, la CLI ne fait que construire ses dépendances (client HTTP,
moteur DB) et les brancher (décisions du contrôleur T7).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from functools import partial
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.db import creer_engine, creer_sessionmaker
from app.modules.extract.facture import FactureIllisible
from app.modules.ingest.mistral import ErreurOCR, ocr_document
from app.modules.ingest.service import (
    blocs_avec_reception,
    formater_blocs,
    lire_facture,
)

_SIGNATURE_PDF = b"%PDF-"


def _est_pdf(contenu: bytes) -> bool:
    return contenu[:5] == _SIGNATURE_PDF


class _LectureEchouee(Exception):
    """Fichier absent, illisible ou non-PDF (message déjà prêt pour stderr)."""


def _lire_fichier(chemin_pdf: Path) -> bytes:
    """Lecture bloquante du PDF (I/O disque), exécutée hors de la boucle
    asyncio via `asyncio.to_thread` (même principe que `_ecrire_atomique`
    dans `ingest/service.py`). Lève `_LectureEchouee` (message déjà prêt,
    sans contenu de fichier) si le fichier est absent, illisible ou n'a pas
    la signature d'un PDF."""
    if not chemin_pdf.is_file():
        raise _LectureEchouee(f"fichier introuvable : {chemin_pdf}")
    try:
        contenu = chemin_pdf.read_bytes()
    except OSError:
        raise _LectureEchouee(f"lecture du fichier impossible : {chemin_pdf}") from None
    if not _est_pdf(contenu):
        raise _LectureEchouee(f"fichier non PDF : {chemin_pdf}")
    return contenu


async def _bl_non_recus(chemin_pdf: Path) -> int:
    """Implémentation de `bl-non-recus`.

    Codes de sortie (décisions du contrôleur T7, révision après T5
    requalifiée) :
    - fichier absent, illisible ou non-PDF -> 2, message sur stderr, aucun
      appel réseau ni lecture de configuration ;
    - configuration manquante -> échec fail-fast (`get_settings()`,
      exception non interceptée) ;
    - `ErreurOCR` ou `FactureIllisible` -> 2, message court sur stderr,
      jamais le contenu du document ni la clé API ;
    - sinon -> tableau des blocs sur stdout, 0.
    """
    try:
        contenu = await asyncio.to_thread(_lire_fichier, chemin_pdf)
    except _LectureEchouee as exc:
        print(str(exc), file=sys.stderr)
        return 2

    settings = get_settings()

    async with httpx.AsyncClient() as http:
        ocr = partial(ocr_document, http, settings.mistral_api_key.get_secret_value())
        try:
            facture = await lire_facture(contenu, ocr)
        except (ErreurOCR, FactureIllisible) as exc:
            print(
                f"lecture de la facture impossible ({type(exc).__name__})",
                file=sys.stderr,
            )
            return 2

    engine = creer_engine(settings.database_url)
    try:
        sessions = creer_sessionmaker(engine)
        async with sessions() as session:
            blocs = await blocs_avec_reception(session, facture)
    finally:
        await engine.dispose()

    print(formater_blocs(blocs))
    return 0


def _construire_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli")
    sous_parsers = parser.add_subparsers(dest="commande", required=True)

    parser_bl_non_recus = sous_parsers.add_parser(
        "bl-non-recus",
        help="Liste les blocs BL d'une facture avec l'indicateur « photo reçue »",
    )
    parser_bl_non_recus.add_argument(
        "facture", type=Path, help="chemin du PDF de la facture"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _construire_parser().parse_args(argv)
    return asyncio.run(_bl_non_recus(args.facture))


if __name__ == "__main__":
    raise SystemExit(main())
