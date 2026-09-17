"""`lire_update` : extraction du fichier à traiter, ou du clic sur un bouton
de confirmation (L2-T3), depuis un update Telegram brut. Toutes les valeurs
(identifiants, noms) sont inventées."""

from __future__ import annotations

from app.modules.messaging.base import (
    PREFIXE_ECART_CONSTATE,
    PREFIXE_QUANTITES_VERIFIEES,
    ClicBouton,
    FichierEntrant,
)
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

    assert isinstance(resultat, FichierEntrant)
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


def test_expediteur_avec_username_utilise_le_username() -> None:
    update = {
        "update_id": 106,
        "message": {
            "message_id": 11,
            "chat": {"id": 16},
            "from": {"id": 1000, "username": "agent-invente", "first_name": "Prénom"},
            "document": {"file_id": "doc-invente", "mime_type": "application/pdf"},
        },
    }

    resultat = lire_update(update)

    assert isinstance(resultat, FichierEntrant)
    assert resultat.expediteur_nom == "agent-invente"


def test_expediteur_sans_username_utilise_le_prenom() -> None:
    update = {
        "update_id": 107,
        "message": {
            "message_id": 12,
            "chat": {"id": 17},
            "from": {"id": 1001, "first_name": "Prénom-invente"},
            "document": {"file_id": "doc-invente", "mime_type": "application/pdf"},
        },
    }

    resultat = lire_update(update)

    assert isinstance(resultat, FichierEntrant)
    assert resultat.expediteur_nom == "Prénom-invente"


def test_expediteur_sans_username_ni_prenom_renvoie_expediteur_nom_none() -> None:
    update = {
        "update_id": 108,
        "message": {
            "message_id": 13,
            "chat": {"id": 18},
            "from": {"id": 1002},
            "document": {"file_id": "doc-invente", "mime_type": "application/pdf"},
        },
    }

    resultat = lire_update(update)

    assert isinstance(resultat, FichierEntrant)
    assert resultat.expediteur_nom is None


def test_message_sans_from_renvoie_expediteur_nom_none() -> None:
    update = {
        "update_id": 109,
        "message": {
            "message_id": 14,
            "chat": {"id": 19},
            "document": {"file_id": "doc-invente", "mime_type": "application/pdf"},
        },
    }

    resultat = lire_update(update)

    assert isinstance(resultat, FichierEntrant)
    assert resultat.expediteur_nom is None


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


# --------------------------------------------------------------------------
# `callback_query` (L2-T3, L2-D9/L2-D10) : clic sur un des deux boutons de
# confirmation. `callback_data` attendu : `"v:<numero_interne>"` ou
# `"e:<numero_interne>"`. Chaque test construit son propre update, en dict
# littéral (même style que les tests ci-dessus), pour éviter toute ambiguïté
# de typage sur un dict partagé et muté.
# --------------------------------------------------------------------------


def test_callback_query_quantites_verifiees_renvoie_clicbouton() -> None:
    update = {
        "update_id": 200,
        "callback_query": {
            "id": "callback-invente",
            "data": "v:42",
            "from": {"id": 999},
            "message": {"message_id": 20, "chat": {"id": 555}},
        },
    }

    resultat = lire_update(update)

    assert resultat == ClicBouton(
        update_id=200,
        callback_id="callback-invente",
        chat_id=555,
        message_id=20,
        expediteur_id=999,
        action=PREFIXE_QUANTITES_VERIFIEES,
        numero_interne=42,
    )


def test_callback_query_ecart_constate_renvoie_clicbouton() -> None:
    update = {
        "update_id": 201,
        "callback_query": {
            "id": "callback-invente",
            "data": "e:7",
            "from": {"id": 999},
            "message": {"message_id": 21, "chat": {"id": 555}},
        },
    }

    resultat = lire_update(update)

    assert resultat == ClicBouton(
        update_id=201,
        callback_id="callback-invente",
        chat_id=555,
        message_id=21,
        expediteur_id=999,
        action=PREFIXE_ECART_CONSTATE,
        numero_interne=7,
    )


def test_callback_query_prefixe_inconnu_renvoie_none() -> None:
    update = {
        "update_id": 202,
        "callback_query": {
            "id": "callback-invente",
            "data": "x:42",
            "message": {"message_id": 22, "chat": {"id": 555}},
        },
    }

    assert lire_update(update) is None


def test_callback_query_numero_non_entier_renvoie_none() -> None:
    update = {
        "update_id": 203,
        "callback_query": {
            "id": "callback-invente",
            "data": "v:abc",
            "message": {"message_id": 23, "chat": {"id": 555}},
        },
    }

    assert lire_update(update) is None


def test_callback_query_numero_absent_renvoie_none() -> None:
    update = {
        "update_id": 204,
        "callback_query": {
            "id": "callback-invente",
            "data": "v:",
            "message": {"message_id": 24, "chat": {"id": 555}},
        },
    }

    assert lire_update(update) is None


def test_callback_query_donnee_sans_separateur_renvoie_none() -> None:
    update = {
        "update_id": 205,
        "callback_query": {
            "id": "callback-invente",
            "data": "vabc",
            "message": {"message_id": 25, "chat": {"id": 555}},
        },
    }

    assert lire_update(update) is None


def test_callback_query_sans_data_renvoie_none() -> None:
    update = {
        "update_id": 206,
        "callback_query": {
            "id": "callback-invente",
            "message": {"message_id": 26, "chat": {"id": 555}},
        },
    }

    assert lire_update(update) is None


def test_callback_query_sans_id_renvoie_none() -> None:
    update = {
        "update_id": 207,
        "callback_query": {
            "data": "v:42",
            "message": {"message_id": 27, "chat": {"id": 555}},
        },
    }

    assert lire_update(update) is None


def test_callback_query_sans_message_renvoie_none() -> None:
    update = {
        "update_id": 208,
        "callback_query": {"id": "callback-invente", "data": "v:42"},
    }

    assert lire_update(update) is None


def test_callback_query_sans_chat_renvoie_none() -> None:
    update = {
        "update_id": 209,
        "callback_query": {
            "id": "callback-invente",
            "data": "v:42",
            "message": {"message_id": 28},
        },
    }

    assert lire_update(update) is None


def test_callback_query_sans_from_renvoie_expediteur_id_none() -> None:
    update = {
        "update_id": 210,
        "callback_query": {
            "id": "callback-invente",
            "data": "v:42",
            "message": {"message_id": 29, "chat": {"id": 555}},
        },
    }

    resultat = lire_update(update)

    assert isinstance(resultat, ClicBouton)
    assert resultat.expediteur_id is None


def test_callback_query_sans_update_id_renvoie_none() -> None:
    update = {
        "callback_query": {
            "id": "callback-invente",
            "data": "v:42",
            "message": {"message_id": 30, "chat": {"id": 555}},
        },
    }

    assert lire_update(update) is None
