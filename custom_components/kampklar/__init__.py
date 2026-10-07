"""Kampklar custom_component — mit.dbu.dk integration."""

from __future__ import annotations

import logging
import re

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import DbuActionError, DbuAuthError, DbuClient, DbuConnectionError
from .const import DOMAIN, PLATFORMS
from .coordinator import KampklarCoordinator

_LOG = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SIGN_UP = "tilmeld"
SERVICE_DECLINE = "frameld"
ATTR_ACTIVITY_ID = "activity_id"
ATTR_COMMENT = "comment"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

_BASE_ACTION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ACTIVITY_ID): cv.positive_int,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)
_DECLINE_SCHEMA = _BASE_ACTION_SCHEMA.extend(
    {
        vol.Required(ATTR_COMMENT): vol.All(
            cv.string, lambda value: value.strip(), vol.Length(min=1)
        )
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registrér Kampklar-actions én gang for hele integrationen."""

    def _coordinator(call: ServiceCall) -> KampklarCoordinator:
        coordinators = hass.data.get(DOMAIN, {})
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        if entry_id:
            if coordinator := coordinators.get(entry_id):
                return coordinator
            raise ServiceValidationError("Den valgte Kampklar-konto er ikke indlæst")
        if len(coordinators) == 1:
            return next(iter(coordinators.values()))
        raise ServiceValidationError(
            "Angiv config_entry_id når der ikke er præcis én Kampklar-konto"
        )

    async def _set_signup(call: ServiceCall, *, attending: bool) -> None:
        coordinator = _coordinator(call)
        try:
            await coordinator.client.set_signup(
                call.data[ATTR_ACTIVITY_ID],
                attending=attending,
                comment=call.data.get(ATTR_COMMENT, ""),
            )
        except DbuActionError as err:
            raise ServiceValidationError(str(err)) from err
        except (DbuAuthError, DbuConnectionError) as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    async def _sign_up(call: ServiceCall) -> None:
        await _set_signup(call, attending=True)

    async def _decline(call: ServiceCall) -> None:
        await _set_signup(call, attending=False)

    hass.services.async_register(
        DOMAIN, SERVICE_SIGN_UP, _sign_up, schema=_BASE_ACTION_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DECLINE, _decline, schema=_DECLINE_SCHEMA
    )
    return True


async def _async_migrate_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Flyt entiteter fra <person>_<hold> til <hold> som nøgle.

    Tidligere versioner byggede unique_id af barnets person-ID, som kun stod
    på forsiden — og forsiden viser ikke altid alle børn. Hold-ID'et står på
    barnets egen holdside og er derfor det eneste vi altid kan slå op.
    Omskrivningen er ren tekst, så entiteterne beholder deres entity_id.
    """
    pattern = re.compile(rf"^{re.escape(entry.entry_id)}_(\d+)_(\d+)_(.+)$")

    @callback
    def _migrate(registry_entry: er.RegistryEntry) -> dict | None:
        match = pattern.match(registry_entry.unique_id)
        if not match:
            return None
        new_id = f"{entry.entry_id}_t{match.group(2)}_{match.group(3)}"
        _LOG.debug("Migrerer unique_id %s → %s", registry_entry.unique_id, new_id)
        return {"new_unique_id": new_id}

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Sæt en config entry op."""
    await _async_migrate_unique_ids(hass, entry)
    session = async_get_clientsession(hass)
    client = DbuClient(
        session=session,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )
    coordinator = KampklarCoordinator(hass, client, entry.entry_id)
    await coordinator.async_load_known_children()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Bed entiteterne opdatere når indstillingerne ændres.

    Kalenderen læser indstillingerne direkte, så der er ingen grund til at
    hente alt forfra hos DBU — vi skubber bare til entiteterne.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator:
        coordinator.async_update_listeners()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
