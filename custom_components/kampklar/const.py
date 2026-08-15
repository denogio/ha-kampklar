"""Konstanter for Kampklar-integrationen."""

from __future__ import annotations

from datetime import timedelta

from .parsers import SIGNUP_STATUSES

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

# ── Indstillinger (options flow) ────────────────────────────────────────────
# Hvilke aktiviteter der havner i kalenderen, og hvordan status vises.
CONF_CALENDAR_STATUSES = "calendar_statuses"
CONF_CALENDAR_TYPES = "calendar_types"
CONF_CALENDAR_PREFIX = "calendar_prefix"

PREFIX_EMOJI = "emoji"
PREFIX_TEXT = "text"
PREFIX_NONE = "none"

PREFIX_MODES: dict[str, str] = {
    PREFIX_EMOJI: "Emoji foran titlen (✅ Træning)",
    PREFIX_TEXT: "Status i kantet parentes ([Tilmeldt] Træning)",
    PREFIX_NONE: "Kun titlen",
}

# Som udgangspunkt vises alt — så opdager man også en status man ikke kendte.
DEFAULT_CALENDAR_STATUSES = list(SIGNUP_STATUSES)
DEFAULT_CALENDAR_PREFIX = PREFIX_EMOJI
