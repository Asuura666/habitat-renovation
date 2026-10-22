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
# Légende (`message.caption`, avenant du 27/09/2026) : nom de chantier tapé
# par l'employé au moment d'envoyer la photo, nettoyée avant stockage
# (`strip()`, vide -> `None`, tronquée à 200 caractères).
# --------------------------------------------------------------------------


def test_photo_avec_legende() -> None:
    update = {
        "update_id": 1,
        "message": {
            "message_id": 5,
            "chat": {"id": -100},
            "from": {"id": 42, "first_name": "Léa"},
            "photo": [
                {"file_id": "p1", "file_size": 10},
                {"file_id": "p2", "file_size": 20},
            ],
            "caption": "  Villa Test  ",
        },
    }

    entrant = lire_update(update)

    assert isinstance(entrant, FichierEntrant) and entrant.legende == "Villa Test"


def test_document_avec_legende_longue_tronquee() -> None:
    update = {
        "update_id": 220,
        "message": {
            "message_id": 40,
            "chat": {"id": 555},
            "document": {"file_id": "doc-invente", "mime_type": "image/jpeg"},
            "caption": "x" * 300,
        },
    }

    entrant = lire_update(update)

    assert isinstance(entrant, FichierEntrant)
    assert entrant.legende is not None
    assert len(entrant.legende) == 200


def test_legende_vide_devient_none() -> None:
    update = {
        "update_id": 221,
        "message": {
            "message_id": 41,
            "chat": {"id": 555},
            "document": {"file_id": "doc-invente", "mime_type": "image/jpeg"},
            "caption": "   ",
        },
    }

    entrant = lire_update(update)

    assert isinstance(entrant, FichierEntrant)
    assert entrant.legende is None


def test_legende_absente_renvoie_none() -> None:
    update = {
        "update_id": 222,
        "message": {
            "message_id": 42,
            "chat": {"id": 555},
            "document": {"file_id": "doc-invente", "mime_type": "image/jpeg"},
        },
    }

    entrant = lire_update(update)

    assert isinstance(entrant, FichierEntrant)
    assert entrant.legende is None


def test_legende_non_str_renvoie_none() -> None:
    update = {
        "update_id": 223,
        "message": {
            "message_id": 43,
            "chat": {"id": 555},
            "document": {"file_id": "doc-invente", "mime_type": "image/jpeg"},
            "caption": 12345,
        },
    }

    entrant = lire_update(update)

    assert isinstance(entrant, FichierEntrant)
    assert entrant.legende is None


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


def test_callback_query_numero_chiffre_unicode_exposant_renvoie_none() -> None:
    """Correction tour 1/5 : `str.isdigit()` acceptait `"²"` (exposant
    Unicode), que `int()` refuse ensuite (`ValueError` auparavant non
    rattrapée jusqu'au routeur, 500)."""
    update = {
        "update_id": 211,
        "callback_query": {
            "id": "callback-invente",
            "data": "v:²",
            "message": {"message_id": 31, "chat": {"id": 555}},
        },
    }

    assert lire_update(update) is None


def test_callback_query_numero_chiffre_unicode_encercle_renvoie_none() -> None:
    """Correction tour 1/5 : même défaut de `str.isdigit()` pour un chiffre
    encerclé (`"①"`)."""
    update = {
        "update_id": 212,
        "callback_query": {
            "id": "callback-invente",
            "data": "v:①",
            "message": {"message_id": 32, "chat": {"id": 555}},
        },
    }

    assert lire_update(update) is None


def test_callback_query_numero_trop_long_renvoie_none() -> None:
    """Correction tour 1/5 : `str.isdigit()` n'imposait aucune borne — un
    numéro de 25 chiffres dépasse un `bigint` Postgres et faisait planter
    `_decider_clic` après coup, sans jamais accuser le clic."""
    update = {
        "update_id": 213,
        "callback_query": {
            "id": "callback-invente",
            "data": "v:" + "9" * 25,
            "message": {"message_id": 33, "chat": {"id": 555}},
        },
    }

    assert lire_update(update) is None


def test_callback_query_numero_negatif_renvoie_none() -> None:
    update = {
        "update_id": 214,
        "callback_query": {
            "id": "callback-invente",
            "data": "v:-1",
            "message": {"message_id": 34, "chat": {"id": 555}},
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


def test_nom_complet_prenom_et_nom() -> None:
    """Décision d'Ilane du 02/10/2026 : nom du compte créé automatiquement
    au premier envoi = prénom et nom Telegram."""
    update = {
        "update_id": 140,
        "message": {
            "message_id": 40,
            "chat": {"id": 40},
            "from": {
                "id": 4000,
                "username": "pseudo-invente",
                "first_name": "Prénom",
                "last_name": "Inventé",
            },
            "photo": [{"file_id": "photo-invente"}],
        },
    }

    resultat = lire_update(update)

    assert isinstance(resultat, FichierEntrant)
    assert resultat.expediteur_nom_complet == "Prénom Inventé"
    assert resultat.expediteur_nom == "pseudo-invente"


def test_nom_complet_repli_sur_le_pseudo_puis_none() -> None:
    def nom_complet(expediteur: dict[str, object]) -> str | None:
        resultat = lire_update(
            {
                "update_id": 141,
                "message": {
                    "message_id": 41,
                    "chat": {"id": 41},
                    "from": expediteur,
                    "photo": [{"file_id": "photo-invente"}],
                },
            }
        )
        assert isinstance(resultat, FichierEntrant)
        return resultat.expediteur_nom_complet

    assert nom_complet({"id": 4001, "username": "pseudo-invente"}) == "pseudo-invente"
    assert nom_complet({"id": 4002, "first_name": "  "}) is None
    assert nom_complet({"id": 4003}) is None
