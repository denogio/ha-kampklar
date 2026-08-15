"""Sensor-entiteter for Kampklar."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import KampklarCoordinator, KampklarData
from .parsers import Child, TeamActivity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: KampklarCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            RecentMessagesSensor(coordinator, entry),
            ChildrenOverviewSensor(coordinator, entry),
            AllNextActivitySensor(coordinator, entry),
            AllPendingSignupsSensor(coordinator, entry),
        ]
    )

    known: set[str] = set()

    @callback
    def _add_new_children() -> None:
        """Opret entiteter for børn vi ikke har set før.

        Børn kan dukke op længe efter opsætningen (nyt barn tilknyttet
        forældrekontoen), så vi lytter på hver opdatering i stedet for kun at
        kigge én gang ved start — ellers kræver et nyt barn en genstart.
        """
        new = [c for c in coordinator.data.children if c.key not in known]
        if not new:
            return
        known.update(c.key for c in new)
        entities: list[SensorEntity] = []
        for child in new:
            entities.extend(
                [
                    NextActivitySensor(coordinator, entry, child),
                    UpcomingActivitiesSensor(coordinator, entry, child),
                    PendingSignupsSensor(coordinator, entry, child),
                ]
            )
        async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(_add_new_children))
    _add_new_children()


def _activity_start(activity: TeamActivity) -> datetime | None:
    """Kombinér aktivitetens dato + start fra time_range til en tz-aware datetime."""
    if activity.date is None or not activity.time_range:
        return None
    start = activity.time_range.split("-", 1)[0].strip()
    try:
        h, m = start.split(":")
        return datetime.combine(
            activity.date, time(int(h), int(m)), tzinfo=dt_util.DEFAULT_TIME_ZONE
        )
    except (ValueError, IndexError):
        return None


def _upcoming(activities: list[TeamActivity]) -> list[TeamActivity]:
    """Aktiviteter fra og med i dag, sorteret kronologisk."""
    today = date.today()
    return sorted(
        (a for a in activities if a.date and a.date >= today),
        key=lambda a: (a.date, a.time_range or ""),
    )


def _pending(activities: list[TeamActivity]) -> list[TeamActivity]:
    """Kommende aktiviteter der mangler til-/framelding."""
    today = date.today()
    return [
        a
        for a in activities
        if a.date
        and a.date >= today
        and not a.signup_locked
        and (a.signup_status or "").strip().lower() in ("", "ikke svaret")
    ]


def _next_activity(activities: list[TeamActivity]) -> TeamActivity | None:
    """Første aktivitet der ikke er begyndt endnu (kræver klokkeslæt)."""
    now = dt_util.now()
    upcoming = sorted(
        (a for a in activities if (dt := _activity_start(a)) and dt >= now),
        key=lambda a: _activity_start(a) or dt_util.utc_from_timestamp(0),
    )
    return upcoming[0] if upcoming else None


def _activity_dict(activity: TeamActivity) -> dict[str, Any]:
    return {
        "id": activity.activity_id,
        "title": activity.title,
        "type": activity.activity_type,
        "date": activity.date.isoformat() if activity.date else None,
        "weekday": activity.weekday,
        "time": activity.time_range,
        "location": activity.location,
        "meeting_time": activity.meeting_time,
        "pool": activity.pool,
        "signup_status": activity.signup_status,
        "signup_locked": activity.signup_locked,
    }


def _slug(child: Child) -> str:
    return f"{child.person_id}_{child.team_id}"


def _child_device(entry_id: str, child: Child) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_{_slug(child)}")},
        # Kort navn — slugges ind i entity_id. Fx "Kampklar Emil" → kampklar_emil_*
        name=f"Kampklar {child.short_name}",
        manufacturer="DBU",
        model=child.team_name or "mit.dbu.dk",
    )


def _account_device(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Kampklar",  # → sensor.kampklar_beskeder
        manufacturer="DBU",
        model="mit.dbu.dk",
    )


class _BaseKampklarSensor(CoordinatorEntity[KampklarCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: KampklarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def data(self) -> KampklarData:
        return self.coordinator.data


class RecentMessagesSensor(_BaseKampklarSensor):
    """Antal beskeder i indbakken; attributter med de seneste 5.

    Bemærk: mit.dbu.dk eksponerer ikke "læst"-status i indbakkelisten — alle
    rækker bærer "Ny besked"-tag uanset. Derfor viser vi alle som seneste
    beskeder i stedet for ulæste.
    """

    _attr_translation_key = "recent_messages"
    _attr_name = "Beskeder"
    _attr_icon = "mdi:email"
    _attr_native_unit_of_measurement = "beskeder"

    def __init__(self, coordinator: KampklarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_recent_messages"
        self._attr_device_info = _account_device(entry)

    def _sorted(self) -> list:
        return sorted(
            self.data.inbox,
            key=lambda m: m.received or datetime.min,
            reverse=True,
        )

    @property
    def native_value(self) -> int:
        return len(self.data.inbox)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        bodies = self.data.message_bodies
        return {
            "messages": [
                {
                    "id": m.message_id,
                    "subject": m.subject,
                    "sender": m.sender,
                    "received": m.received.isoformat() if m.received else None,
                    "preview": m.preview,
                    "body": bodies.get(m.message_id) or m.preview,
                    "category": m.category,
                    "url": f"https://mit.dbu.dk/Message/MessageDetails.aspx?id={m.message_id}",
                }
                for m in self._sorted()[:10]
            ],
            "total": len(self.data.inbox),
        }


class _AccountSensorBase(_BaseKampklarSensor):
    """Sensor der dækker hele kontoen — alle børn under ét."""

    def __init__(self, coordinator: KampklarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_device_info = _account_device(entry)

    def _child_entity_ids(self, child: Child) -> dict[str, str | None]:
        """Slå barnets entity-id'er op, så dashboards kan finde dem dynamisk."""
        registry = er.async_get(self.hass)
        prefix = f"{self._entry.entry_id}_{child.key}"
        return {
            "next_activity": registry.async_get_entity_id(
                "sensor", DOMAIN, f"{prefix}_next_activity"
            ),
            "upcoming_activities": registry.async_get_entity_id(
                "sensor", DOMAIN, f"{prefix}_upcoming_activities"
            ),
            "pending_signups": registry.async_get_entity_id(
                "sensor", DOMAIN, f"{prefix}_pending_signups"
            ),
            "calendar": registry.async_get_entity_id(
                "calendar", DOMAIN, f"{prefix}_calendar"
            ),
        }

    def _child_summary(self, child: Child) -> dict[str, Any]:
        activities = self.data.activities_by_child.get(child.key, [])
        nxt = _next_activity(activities)
        return {
            "key": child.key,
            "name": child.name,
            "short_name": child.short_name,
            "team": child.team_name,
            "club": child.club_name,
            "upcoming_count": len(_upcoming(activities)),
            "pending_count": len(_pending(activities)),
            "next_activity": _activity_dict(nxt) if nxt else None,
            "next_activity_start": (
                dt.isoformat() if nxt and (dt := _activity_start(nxt)) else None
            ),
            "entity_ids": self._child_entity_ids(child),
        }


class ChildrenOverviewSensor(_AccountSensorBase):
    """Ét samlet overblik over alle børn — grundlaget for et generisk dashboard.

    Attributterne holder ikke de fulde aktivitetslister (de ville sprænge
    recorderens 16 KiB-grænse ved flere børn) men til gengæld hvert barns
    entity-id'er, så et dashboard kan slå resten op uden hardcodede navne.
    """

    _attr_translation_key = "children"
    _attr_name = "Børn"
    _attr_icon = "mdi:account-child"
    _attr_native_unit_of_measurement = "børn"

    def __init__(self, coordinator: KampklarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_children"

    @property
    def native_value(self) -> int:
        return len(self.data.children)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "children": [self._child_summary(c) for c in self.data.children],
            "names": [c.short_name for c in self.data.children],
        }


class AllNextActivitySensor(_AccountSensorBase):
    """Næste aktivitet på tværs af alle børn."""

    _attr_translation_key = "next_activity_all"
    _attr_name = "Næste aktivitet"
    _attr_icon = "mdi:soccer"
    _attr_device_class = "timestamp"

    def __init__(self, coordinator: KampklarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_next_activity_all"

    def _next(self) -> tuple[Child, TeamActivity, datetime] | None:
        best: tuple[Child, TeamActivity, datetime] | None = None
        for child in self.data.children:
            activity = _next_activity(self.data.activities_by_child.get(child.key, []))
            if activity is None:
                continue
            start = _activity_start(activity)
            if start and (best is None or start < best[2]):
                best = (child, activity, start)
        return best

    @property
    def native_value(self) -> datetime | None:
        best = self._next()
        return best[2] if best else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        best = self._next()
        if best is None:
            return {"child": None}
        child, activity, _ = best
        return {
            "child": child.short_name,
            "child_full_name": child.name,
            "team": child.team_name,
            **_activity_dict(activity),
        }


class AllPendingSignupsSensor(_AccountSensorBase):
    """Samlet antal aktiviteter der mangler svar — for alle børn."""

    _attr_translation_key = "pending_signups_all"
    _attr_name = "Mangler tilmelding"
    _attr_icon = "mdi:account-question"
    _attr_native_unit_of_measurement = "aktiviteter"

    def __init__(self, coordinator: KampklarCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_pending_signups_all"

    @property
    def native_value(self) -> int:
        return sum(
            len(_pending(self.data.activities_by_child.get(c.key, [])))
            for c in self.data.children
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        activities: list[dict[str, Any]] = []
        for child in self.data.children:
            for a in _pending(self.data.activities_by_child.get(child.key, [])):
                activities.append(
                    {"child": child.short_name, "team": child.team_name, **_activity_dict(a)}
                )
        activities.sort(key=lambda a: (a["date"] or "", a["time"] or ""))
        return {
            "activities": activities,
            "by_child": {
                c.short_name: len(_pending(self.data.activities_by_child.get(c.key, [])))
                for c in self.data.children
            },
        }


class _ChildSensorBase(_BaseKampklarSensor):
    def __init__(
        self,
        coordinator: KampklarCoordinator,
        entry: ConfigEntry,
        child: Child,
    ) -> None:
        super().__init__(coordinator, entry)
        self._child_key = child.key
        self._attr_device_info = _child_device(entry.entry_id, child)

    @property
    def _activities(self) -> list[TeamActivity]:
        return self.data.activities_by_child.get(self._child_key, [])

    @property
    def _child(self) -> Child | None:
        for c in self.data.children:
            if c.key == self._child_key:
                return c
        return None

    @property
    def _child_attrs(self) -> dict[str, Any]:
        child = self._child
        return {
            "child": child.short_name if child else None,
            "child_full_name": child.name if child else None,
            "team": child.team_name if child else None,
        }


class NextActivitySensor(_ChildSensorBase):
    _attr_translation_key = "next_activity"
    _attr_name = "Næste aktivitet"
    _attr_icon = "mdi:soccer"
    _attr_device_class = "timestamp"

    def __init__(
        self,
        coordinator: KampklarCoordinator,
        entry: ConfigEntry,
        child: Child,
    ) -> None:
        super().__init__(coordinator, entry, child)
        self._attr_unique_id = f"{entry.entry_id}_{child.key}_next_activity"

    @property
    def native_value(self) -> datetime | None:
        activity = _next_activity(self._activities)
        return _activity_start(activity) if activity else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        activity = _next_activity(self._activities)
        if activity is None:
            return self._child_attrs
        return {**self._child_attrs, **_activity_dict(activity)}


class UpcomingActivitiesSensor(_ChildSensorBase):
    """Alle kommende aktiviteter som liste — antal i state, detaljer i attributter."""

    _attr_translation_key = "upcoming_activities"
    _attr_name = "Kommende aktiviteter"
    _attr_icon = "mdi:calendar-clock"
    _attr_native_unit_of_measurement = "aktiviteter"

    def __init__(
        self,
        coordinator: KampklarCoordinator,
        entry: ConfigEntry,
        child: Child,
    ) -> None:
        super().__init__(coordinator, entry, child)
        self._attr_unique_id = f"{entry.entry_id}_{child.key}_upcoming_activities"

    @property
    def native_value(self) -> int:
        return len(_upcoming(self._activities))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "activities": [_activity_dict(a) for a in _upcoming(self._activities)],
            **self._child_attrs,
        }


class PendingSignupsSensor(_ChildSensorBase):
    """Antal kommende aktiviteter som mangler tilmelding/afmelding."""

    _attr_translation_key = "pending_signups"
    _attr_name = "Mangler tilmelding"
    _attr_icon = "mdi:account-question"
    _attr_native_unit_of_measurement = "aktiviteter"

    def __init__(
        self,
        coordinator: KampklarCoordinator,
        entry: ConfigEntry,
        child: Child,
    ) -> None:
        super().__init__(coordinator, entry, child)
        self._attr_unique_id = f"{entry.entry_id}_{child.key}_pending_signups"

    @property
    def native_value(self) -> int:
        return len(_pending(self._activities))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "activities": [_activity_dict(a) for a in _pending(self._activities)],
            **self._child_attrs,
        }
