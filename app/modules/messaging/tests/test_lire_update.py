"""`lire_update` : extraction du fichier à traiter depuis un update Telegram
brut. Toutes les valeurs (identifiants, noms) sont inventées."""

from __future__ import annotations

from app.modules.messaging.base import FichierEntrant
from app.modules.messaging.telegram import lire_update


def test_photo_plusieurs_tailles_prend_la_derniere_et_marque_compresse() -> None:
    update = {
        "update_id": 100,
        "message": {
            "message_id": 5,
            "chat": {"id": 10},
            "from": {"id": 999},
            "photo": [
                {"file_id": "petite-invente", "width": 90, "height": 90},
                {"file_id": "grande-invente", "width": 1280, "height": 1280},
            ],
        },
    }

    resultat = lire_update(update)

    assert resultat == FichierEntrant(
        update_id=100,
        chat_id=10,
        message_id=5,
        expediteur_id=999,
        fichier_id="grande-invente",
        mime_type=None,
        nom_fichier=None,
        compresse=True,
    )


def test_document_image_jpeg_est_accepte_et_non_compresse() -> None:
    update = {
        "update_id": 101,
        "message": {
            "message_id": 6,
            "chat": {"id": 11},
            "document": {
                "file_id": "doc-jpeg-invente",
                "mime_type": "image/jpeg",
                "file_name": "bl-invente.jpg",
            },
        },
    }

    resultat = lire_update(update)

    assert resultat == FichierEntrant(
        update_id=101,
        chat_id=11,
        message_id=6,
        expediteur_id=None,
        fichier_id="doc-jpeg-invente",
        mime_type="image/jpeg",
        nom_fichier="bl-invente.jpg",
        compresse=False,
    )


def test_document_pdf_est_accepte() -> None:
    update = {
        "update_id": 102,
        "message": {
            "message_id": 7,
            "chat": {"id": 12},
            "document": {"file_id": "doc-pdf-invente", "mime_type": "application/pdf"},
        },
    }

    resultat = lire_update(update)

    assert resultat is not None
    assert resultat.mime_type == "application/pdf"
    assert resultat.compresse is False


def test_document_type_non_accepte_renvoie_none() -> None:
    update = {
        "update_id": 103,
        "message": {
            "message_id": 8,
            "chat": {"id": 13},
            "document": {"file_id": "doc-texte-invente", "mime_type": "text/plain"},
        },
    }

    assert lire_update(update) is None


def test_message_texte_renvoie_none() -> None:
    update = {
        "update_id": 104,
        "message": {"message_id": 9, "chat": {"id": 14}, "text": "bonjour"},
    }

    assert lire_update(update) is None


def test_update_sans_message_renvoie_none() -> None:
    update = {
        "update_id": 105,
        "edited_message": {
            "message_id": 10,
            "chat": {"id": 15},
            "document": {"file_id": "x", "mime_type": "application/pdf"},
        },
    }

    assert lire_update(update) is None
