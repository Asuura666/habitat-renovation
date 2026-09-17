"""Défense en profondeur contre le CSRF (vague finale du lot 2, point 2) :
pour toute requête de méthode non sûre (`POST`, `PUT`, `PATCH`, `DELETE`)
sur `/api/*`, refuse (403 `{"detail": "Origine refusée."}`) si l'en-tête
`Origin` est présent et ne correspond pas à l'origine du service, ou si
`Sec-Fetch-Site` vaut `cross-site`.

Décision (documentée aussi dans `docs/plan-lot-2.md`, L2-D18, et
`docs/lot-2-recette.md`) : `SameSite=Lax` (déjà en place, `app/core/auth.py`)
+ pas de CORS + ce contrôle d'origine, plutôt qu'un jeton CSRF classique.
Le CDC impose « même origine, pas de CORS, pas de JWT » (front servi par la
même API, `app/core/front.py`) : aucune requête `/api/*` légitime ne porte
donc jamais un `Origin` étranger ni `Sec-Fetch-Site: cross-site` — un jeton
CSRF ajouterait une intégration front (génération, transport, vérification)
sans rien couvrir de plus que ce contrôle, qui suffit contre un navigateur
qui enverrait la requête depuis une autre origine (l'attaque que `SameSite`
seul ne couvre pas totalement selon le navigateur/la configuration).

`/tg/webhook` n'est pas concerné (hors du préfixe `/api/`) : c'est un appel
serveur à serveur (Telegram), jamais émis par un navigateur, déjà protégé
par le secret `X-Telegram-Bot-Api-Secret-Token`
(`app/modules/messaging/telegram.py::secret_valide`).

L'origine attendue est dérivée de la requête elle-même (schéma + hôte),
sans nouvelle variable d'environnement : `request.url.scheme` reflète déjà
`X-Forwarded-Proto` quand uvicorn est lancé avec `--proxy-headers` (traité
par uvicorn avant que la requête n'atteigne cette application), et l'en-tête
`Host` reçu par le service est le même en interne qu'en public (Traefik ne
le réécrit pas).

Absence des deux en-têtes (`Origin` et `Sec-Fetch-Site`) : requête acceptée
— clients non-navigateurs (`curl`, tests, appels serveur à serveur), qui
n'envoient jamais ces en-têtes.
"""

from __future__ import annotations

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

_METHODES_NON_SURES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_MESSAGE_REFUS = "Origine refusée."


def _chemin_protege(chemin: str) -> bool:
    """Même style que `app/core/front.py::_chemin_reserve` : `/api` seul ou
    tout sous-chemin `/api/...`."""
    return chemin == "/api" or chemin.startswith("/api/")


def _origine_service(request: Request) -> str:
    """Schéma + hôte du service tel que vu pour cette requête précise (le
    port, s'il y en a un, fait partie de l'en-tête `Host` reçu)."""
    return f"{request.url.scheme}://{request.headers.get('host', '')}"


def _origine_refusee(request: Request) -> bool:
    if request.headers.get("sec-fetch-site") == "cross-site":
        return True
    origine = request.headers.get("origin")
    if origine is None:
        return False
    return origine != _origine_service(request)


class ControleOrigineMiddleware(BaseHTTPMiddleware):
    """Voir le docstring de module. N'agit que sur `/api/*` en méthode non
    sûre ; laisse passer tout le reste (méthodes sûres, `/tg/webhook`, et les
    clients qui n'envoient ni `Origin` ni `Sec-Fetch-Site`)."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if (
            request.method.upper() in _METHODES_NON_SURES
            and _chemin_protege(request.url.path)
            and _origine_refusee(request)
        ):
            return JSONResponse({"detail": _MESSAGE_REFUS}, status_code=403)
        return await call_next(request)
