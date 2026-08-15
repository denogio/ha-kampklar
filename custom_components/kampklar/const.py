"""Konstanter for Kampklar-integrationen."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "kampklar"
PLATFORMS = ["sensor", "calendar"]

CONF_USERNAME = "username"
CONF_PASSWORD = "password"

UPDATE_INTERVAL = timedelta(minutes=60)

# Antal nyeste beskeder hvor vi henter fuld body (cached pr. message_id).
MESSAGE_DETAIL_COUNT = 10

# Kendte børn gemmes på disk, fordi mit.dbu.dk's forside kun viser de
# førstkommende ~4 begivenheder — et barn kan altså midlertidigt "forsvinde"
# fra forsiden uden at være væk fra kontoen.
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.children"
