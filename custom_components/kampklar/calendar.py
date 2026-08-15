"""Calendar-entitet for Kampklar — én pr. barn."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CALENDAR_PREFIX,
    CONF_CALENDAR_STATUSES,
    CONF_CALENDAR_TYPES,
    DEFAULT_CALENDAR_PREFIX,
    DEFAULT_CALENDAR_STATUSES,
    DOMAIN,
    PREFIX_EMOJI,
    PREFIX_TEXT,
)
from .coordinator import KampklarCoordinator
from .parsers import SIGNUP_STATUSES, Child, TeamActivity, normalize_signup_status


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: KampklarCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add_new_children() -> None:
        """Nye børn skal have en kalender uden at HA skal genstartes."""
        new = [c for c in coordinator.data.children if c.key not in known]
        if not new:
            return
        known.update(c.key for c in new)
        async_add_entities(
            [KampklarCalendar(coordinator, entry, child) for child in new]
        )

    entry.async_on_unload(coordinator.async_add_listener(_add_new_children))
    _add_new_children()


def _summary(activity: TeamActivity, prefix_mode: str) -> str:
    """Titlen, evt. med tilmeldingsstatus foran.

    Kalenderbegivenheder har kun titel, sted og beskrivelse at gøre godt med,
    så status skal ind i titlen for at kunne ses direkte i kalenderen.
    """
    title = activity.title or "(aktivitet)"
    key = normalize_signup_status(activity.signup_status)
    label, emoji = SIGNUP_STATUSES.get(key, SIGNUP_STATUSES["andet"])
    if prefix_mode == PREFIX_EMOJI:
        return f"{emoji} {title}"
    if prefix_mode == PREFIX_TEXT:
        return f"[{activity.signup_status or label}] {title}"
    return title


def _activity_to_event(
    activity: TeamActivity, prefix_mode: str = DEFAULT_CALENDAR_PREFIX
) -> CalendarEvent | None:
    if activity.date is None:
        return None
    start_time = end_time = None
    if activity.time_range:
        parts = [p.strip() for p in activity.time_range.split("-", 1)]
        try:
            sh, sm = parts[0].split(":")
            start_time = time(int(sh), int(sm))
            if len(parts) == 2:
                eh, em = parts[1].split(":")
                end_time = time(int(eh), int(em))
        except (ValueError, IndexError):
            start_time = end_time = None

    tz = dt_util.DEFAULT_TIME_ZONE
    if start_time:
        start = datetime.combine(activity.date, start_time, tzinfo=tz)
        end = (
            datetime.combine(activity.date, end_time, tzinfo=tz)
            if end_time
            else start + timedelta(hours=1)
        )
    else:
        start = datetime.combine(activity.date, time(0, 0), tzinfo=tz)
        end = start + timedelta(days=1)

    desc_parts = []
    if activity.activity_type:
        desc_parts.append(activity.activity_type)
    if activity.signup_status:
        desc_parts.append(f"Status: {activity.signup_status}")
    if activity.meeting_time:
        desc_parts.append(f"Mødetid: {activity.meeting_time}")
    if activity.pool:
        desc_parts.append(activity.pool)
    return CalendarEvent(
        start=start,
        end=end,
        summary=_summary(activity, prefix_mode),
        location=activity.location,
        description=" · ".join(desc_parts) if desc_parts else None,
        uid=str(activity.activity_id) if activity.activity_id else None,
    )


class KampklarCalendar(CoordinatorEntity[KampklarCoordinator], CalendarEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "activities"
    _attr_name = "Aktiviteter"

    def __init__(
        self,
        coordinator: KampklarCoordinator,
        entry: ConfigEntry,
        child: Child,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._child_key = child.key
        self._attr_unique_id = f"{entry.entry_id}_{child.key}_calendar"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{child.key}")},
            "name": f"Kampklar {child.short_name}",
            "manufacturer": "DBU",
            "model": child.team_name or "mit.dbu.dk",
        }

    def _include(self, activity: TeamActivity) -> bool:
        """Skal aktiviteten med i kalenderen? Styres fra integrationens
        indstillinger (tandhjulet på Kampklar-integrationen)."""
        options = self._entry.options
        statuses = options.get(CONF_CALENDAR_STATUSES, DEFAULT_CALENDAR_STATUSES)
        if normalize_signup_status(activity.signup_status) not in statuses:
            return False
        # Tom typeliste betyder alle typer — ellers ville en ny aktivitetstype
        # lydløst forsvinde fra kalenderen.
        types = options.get(CONF_CALENDAR_TYPES) or []
        return not types or activity.activity_type in types

    def _events(self) -> list[CalendarEvent]:
        prefix_mode = self._entry.options.get(
            CONF_CALENDAR_PREFIX, DEFAULT_CALENDAR_PREFIX
        )
        activities = self.coordinator.data.activities_by_child.get(self._child_key, [])
        out = [
            _activity_to_event(a, prefix_mode) for a in activities if self._include(a)
        ]
        return [e for e in out if e is not None]

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = sorted(
            (e for e in self._events() if e.end >= now), key=lambda e: e.start
        )
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            e for e in self._events() if e.end >= start_date and e.start <= end_date
        ]
