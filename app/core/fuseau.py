"""Fuseau horaire d'affichage de l'application.

Tout l'affichage (front, formatage d'heure côté bot Telegram) est en
Europe/Paris (CDC), alors que Postgres et tous les horodatages stockés
(`created_at`, etc., colonnes `DateTime(timezone=True)`) sont en UTC.
`FUSEAU_PARIS` est la constante unique de ce fuseau, partagée par
`ingest.depot_telegram` (formatage d'une heure affichée) et `api.anomalies`
(bornes de période, Ruling R21) : une seule source de vérité plutôt qu'un
`ZoneInfo("Europe/Paris")` recréé (chaîne en dur) à plusieurs endroits.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

FUSEAU_PARIS = ZoneInfo("Europe/Paris")
