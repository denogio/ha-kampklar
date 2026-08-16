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
    CONF_CALENDAR_TITLE_STATUSES,
    CONF_CALENDAR_TITLE_TYPE,
    CONF_CALENDAR_TYPES,
    CONF_LEGACY_CALENDAR_STATUSES,
    DEFAULT_CALENDAR_TITLE_STATUSES,
    DEFAULT_CALENDAR_TITLE_TYPE,
    DOMAIN,
    statuses_option_key,
)
from .coordinator import KampklarCoordinator
from .parsers import (
    Child,
    TeamActivity,
    calendar_title,
    default_statuses_for_type,
    normalize_signup_status,
)


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


def _activity_to_event(
    activity: TeamActivity,
    with_type: bool = DEFAULT_CALENDAR_TITLE_TYPE,
    title_statuses: list[str] | None = None,
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
        summary=calendar_title(
            activity,
            with_type=with_type,
            title_statuses=title_statuses
            if title_statuses is not None
            else DEFAULT_CALENDAR_TITLE_STATUSES,
        ),
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

    def _statuses_for(self, activity_type: str | None) -> list[str]:
        """Statusvalget for én aktivitetstype.

        Rækkefølgen er: dit valg for netop den type → det fælles valg fra
        v0.4.0 → standarden for typen (træning uden frameldt, resten alt).
        """
        options = self._entry.options
        key = statuses_option_key(activity_type)
        if key in options:
            return options[key]
        if CONF_LEGACY_CALENDAR_STATUSES in options:
            return options[CONF_LEGACY_CALENDAR_STATUSES]
        return default_statuses_for_type(activity_type)

    def _include(self, activity: TeamActivity) -> bool:
        """Skal aktiviteten med i kalenderen? Styres fra integrationens
        indstillinger (Konfigurer på Kampklar-integrationen)."""
        # Tom typeliste betyder alle typer — ellers ville en ny aktivitetstype
        # lydløst forsvinde fra kalenderen.
        types = self._entry.options.get(CONF_CALENDAR_TYPES) or []
        if types and activity.activity_type not in types:
            return False
        statuses = self._statuses_for(activity.activity_type)
        return normalize_signup_status(activity.signup_status) in statuses

    def _events(self) -> list[CalendarEvent]:
        options = self._entry.options
        with_type = options.get(CONF_CALENDAR_TITLE_TYPE, DEFAULT_CALENDAR_TITLE_TYPE)
        title_statuses = options.get(
            CONF_CALENDAR_TITLE_STATUSES, DEFAULT_CALENDAR_TITLE_STATUSES
        )
        activities = self.coordinator.data.activities_by_child.get(self._child_key, [])
        out = [
            _activity_to_event(a, with_type, title_statuses)
            for a in activities
            if self._include(a)
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
