"""DataUpdateCoordinator for Kampklar."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DbuAuthError, DbuClient, DbuConnectionError
from .const import (
    DOMAIN,
    MESSAGE_DETAIL_COUNT,
    STORAGE_KEY,
    STORAGE_VERSION,
    UPDATE_INTERVAL,
)
from .parsers import (
    Child,
    InboxMessage,
    TeamActivity,
    assign_display_names,
)

_LOG = logging.getLogger(__name__)


@dataclass
class KampklarData:
    children: list[Child]
    inbox: list[InboxMessage]
    activities_by_child: dict[str, list[TeamActivity]]
    message_bodies: dict[int, str]  # message_id -> fuld body


class KampklarCoordinator(DataUpdateCoordinator[KampklarData]):
    """Henter data fra mit.dbu.dk i et samlet kald hver UPDATE_INTERVAL."""

    def __init__(
        self, hass: HomeAssistant, client: DbuClient, entry_id: str
    ) -> None:
        super().__init__(
            hass,
            _LOG,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self._body_cache: dict[int, str] = {}
        self._known_children: list[Child] = []
        self._store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry_id}")

    async def async_load_known_children(self) -> None:
        """Læs tidligere kendte børn fra disk. Kald før første refresh."""
        try:
            stored = await self._store.async_load()
        except Exception:  # noqa: BLE001 — korrupt store må aldrig blokere opsætning
            _LOG.warning("Kunne ikke læse gemte børn — starter forfra", exc_info=True)
            return
        if not stored:
            return
        children: list[Child] = []
        for raw in stored.get("children", []):
            try:
                children.append(Child.from_dict(raw))
            except (KeyError, TypeError, ValueError):
                _LOG.debug("Springer ugyldig gemt barn-post over: %s", raw)
        self._known_children = children
        _LOG.debug("Indlæste %d kendte børn fra storage", len(children))

    async def _async_save_known_children(self, children: list[Child]) -> None:
        if not children and self._known_children:
            # Aldrig glemme børn på baggrund af en tom hentning — så mister vi
            # de gemte nøgler, og alle entiteter ville skifte unique_id.
            _LOG.warning("Fandt ingen børn denne gang — beholder de gemte")
            return
        payload = {"children": [c.as_dict() for c in children]}
        if [c.as_dict() for c in self._known_children] == payload["children"]:
            return
        self._known_children = list(children)
        await self._store.async_save(payload)

    def _assign_stable_key(self, child: Child) -> None:
        """Giv barnet den nøgle det fik første gang vi så det.

        Nøglen bliver til entiteternes unique_id, så den må aldrig skifte.
        Normalt er den udledt af hold-ID'et og dermed allerede stabil — men
        skifter DBU hold-ID (nyt hold, ny sæson), holder vi fast i den gamle
        nøgle ved at genkende barnets navn.
        """
        for known in self._known_children:
            if child.team_id is not None and known.team_id == child.team_id:
                child.stored_key = known.key
                child.person_id = child.person_id or known.person_id
                return
        for known in self._known_children:
            if child.name and known.name == child.name:
                child.stored_key = known.key
                child.person_id = child.person_id or known.person_id
                return

    async def _async_resolve_children(self) -> tuple[list[Child], dict[str, list[TeamActivity]]]:
        """Find alle børn og hent deres aktiviteter.

        Listen kommer fra KampKlar-vælgeren, som har én række pr. barn — også
        børn uden aktiviteter. Forsiden bruges ikke: den viser kun de
        førstkommende fire begivenheder på tværs af alle børn, og med to børn
        falder det ene typisk helt ud.
        """
        pairs = await self.client.fetch_children_with_activities()

        children: list[Child] = []
        activities: dict[str, list[TeamActivity]] = {}
        for child, acts in pairs:
            self._assign_stable_key(child)
            if child.key in activities:
                _LOG.warning(
                    "To børn fik samme nøgle (%s) — springer %s over",
                    child.key,
                    child.name,
                )
                continue
            children.append(child)
            activities[child.key] = acts

        assign_display_names(children)
        await self._async_save_known_children(children)
        return children, activities

    async def _async_update_data(self) -> KampklarData:
        try:
            children, activities = await self._async_resolve_children()
            inbox = await self.client.fetch_inbox()

            # Fetch fulde bodies for de N nyeste, men kun dem vi ikke har i cache
            top = sorted(
                inbox, key=lambda m: m.received or 0, reverse=True
            )[:MESSAGE_DETAIL_COUNT]
            for m in top:
                if m.message_id in self._body_cache:
                    continue
                try:
                    details = await self.client.fetch_message_details(m.message_id)
                    self._body_cache[m.message_id] = details.body
                except (DbuAuthError, DbuConnectionError) as err:
                    _LOG.warning("Kunne ikke hente besked-body %s: %s", m.message_id, err)

            # Prune cache: kun behold IDs vi stadig ser i inbox
            live_ids = {m.message_id for m in inbox}
            self._body_cache = {
                mid: body for mid, body in self._body_cache.items() if mid in live_ids
            }

        except DbuAuthError as err:
            raise UpdateFailed(f"Login fejlede: {err}") from err
        except DbuConnectionError as err:
            raise UpdateFailed(f"Netværksfejl: {err}") from err

        return KampklarData(
            children=children,
            inbox=inbox,
            activities_by_child=activities,
            message_bodies=dict(self._body_cache),
        )
