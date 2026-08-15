"""Config flow til Kampklar."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import DbuAuthError, DbuClient, DbuConnectionError
from .const import (
    CONF_CALENDAR_PREFIX,
    CONF_CALENDAR_STATUSES,
    CONF_CALENDAR_TYPES,
    DEFAULT_CALENDAR_PREFIX,
    DEFAULT_CALENDAR_STATUSES,
    DOMAIN,
    PREFIX_MODES,
)
from .parsers import SIGNUP_STATUSES

_LOG = logging.getLogger(__name__)

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class KampklarConfigFlow(ConfigFlow, domain=DOMAIN):
    """UI-flow til at oprette en Kampklar config entry."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return KampklarOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = DbuClient(
                session=session,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
            )
            try:
                await client.login()
            except DbuAuthError:
                errors["base"] = "invalid_auth"
            except DbuConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOG.exception("Uventet fejl ved login-validering")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"mit.dbu.dk ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user", data_schema=SCHEMA, errors=errors
        )


class KampklarOptionsFlow(OptionsFlow):
    """Indstillinger: hvad kalenderen skal indeholde, og hvordan status vises."""

    def __init__(self, entry: ConfigEntry) -> None:
        # Gemmes under et privat navn — self.config_entry sættes af HA selv.
        self._entry = entry

    def _known_activity_types(self) -> list[str]:
        """Aktivitetstyper vi rent faktisk har set (Træning, Kamp, Stævne …).

        Listen bygges af de hentede data, så den passer til klubbens egne
        typer i stedet for en hardcodet liste. Allerede valgte typer bliver
        stående, også hvis de ikke er i data lige nu.
        """
        types: set[str] = set(self._entry.options.get(CONF_CALENDAR_TYPES) or [])
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if coordinator and coordinator.data:
            for activities in coordinator.data.activities_by_child.values():
                types.update(a.activity_type for a in activities if a.activity_type)
        return sorted(types)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            # Fravælger man alt, udelader HA nøglen helt. Vi skriver den
            # eksplicit, så "ingen statusser" ikke bliver læst som "standard".
            return self.async_create_entry(
                title="",
                data={
                    CONF_CALENDAR_STATUSES: user_input.get(CONF_CALENDAR_STATUSES, []),
                    CONF_CALENDAR_TYPES: user_input.get(CONF_CALENDAR_TYPES, []),
                    CONF_CALENDAR_PREFIX: user_input.get(
                        CONF_CALENDAR_PREFIX, DEFAULT_CALENDAR_PREFIX
                    ),
                },
            )

        options = self._entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CALENDAR_STATUSES,
                    default=list(
                        options.get(CONF_CALENDAR_STATUSES, DEFAULT_CALENDAR_STATUSES)
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=key, label=label)
                            for key, (label, _) in SIGNUP_STATUSES.items()
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_CALENDAR_TYPES,
                    default=list(options.get(CONF_CALENDAR_TYPES, [])),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=t, label=t)
                            for t in self._known_activity_types()
                        ],
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_CALENDAR_PREFIX,
                    default=options.get(CONF_CALENDAR_PREFIX, DEFAULT_CALENDAR_PREFIX),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=key, label=label)
                            for key, label in PREFIX_MODES.items()
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
