"""Kampklar custom_component — mit.dbu.dk integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DbuClient
from .const import DOMAIN, PLATFORMS
from .coordinator import KampklarCoordinator

_LOG = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Sæt en config entry op."""
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
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
