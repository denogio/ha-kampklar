"""Konstanter for Kampklar-integrationen."""

from __future__ import annotations

from datetime import timedelta

from .parsers import NOTABLE_STATUSES, SIGNUP_STATUSES, type_slug

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
CONF_CALENDAR_TYPES = "calendar_types"
CONF_CALENDAR_TITLE_TYPE = "calendar_title_type"
CONF_CALENDAR_TITLE_STATUSES = "calendar_title_statuses"

# Statusvalget er pr. aktivitetstype: "calendar_statuses_kamp",
# "calendar_statuses_traening" osv. Ved træning er status kun interessant hvis
# man har meldt fra, mens en kamp har flere trin der er værd at se.
CALENDAR_STATUSES_PREFIX = "calendar_statuses_"

# v0.4.0 havde ét fælles statusvalg. Nøglen læses stadig, så et eksisterende
# valg bliver udgangspunkt for alle typer i stedet for at gå tabt.
CONF_LEGACY_CALENDAR_STATUSES = "calendar_statuses"

DEFAULT_CALENDAR_TITLE_TYPE = True
DEFAULT_CALENDAR_TITLE_STATUSES = list(NOTABLE_STATUSES)
ALL_STATUSES = list(SIGNUP_STATUSES)


def statuses_option_key(activity_type: str | None) -> str:
    """Options-nøglen der gemmer statusvalget for én aktivitetstype."""
    return f"{CALENDAR_STATUSES_PREFIX}{type_slug(activity_type)}"
