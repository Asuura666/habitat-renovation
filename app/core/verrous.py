"""Identifiants des verrous consultatifs PostgreSQL (`pg_advisory_xact_lock`)
partagés entre modules -- module sans dépendance, importable sans lire la
configuration (contrairement à `app.core.auth`, qui la lit à l'import)."""

# Créations et modifications de comptes : écran « Comptes » et CLI
# (`app.core.auth`), et comptes créés au premier envoi Telegram
# (`app.modules.ingest.depot_telegram`, décision d'Ilane du 02/10/2026).
VERROU_ADMINS = 727_000_010
