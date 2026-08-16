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
    CONF_CALENDAR_TITLE_STATUSES,
    CONF_CALENDAR_TITLE_TYPE,
    CONF_CALENDAR_TYPES,
    CONF_LEGACY_CALENDAR_STATUSES,
    DEFAULT_CALENDAR_TITLE_STATUSES,
    DEFAULT_CALENDAR_TITLE_TYPE,
    DOMAIN,
    statuses_option_key,
)
from .parsers import SIGNUP_STATUSES, default_statuses_for_type

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

        Listen bygges af de hentede data, så indstillingerne passer til
        klubbens egne typer i stedet for en hardcodet liste.
        """
        types: set[str] = set(self._entry.options.get(CONF_CALENDAR_TYPES) or [])
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if coordinator and coordinator.data:
            for activities in coordinator.data.activities_by_child.values():
                types.update(a.activity_type for a in activities if a.activity_type)
        return sorted(types)

    def _status_default(self, activity_type: str) -> list[str]:
        """Hvad statusfeltet for en type skal stå på når formularen åbnes."""
        options = self._entry.options
        key = statuses_option_key(activity_type)
        if key in options:
            return list(options[key])
        # v0.4.0 havde ét fælles valg — brug det, så det ikke går tabt
        if CONF_LEGACY_CALENDAR_STATUSES in options:
            return list(options[CONF_LEGACY_CALENDAR_STATUSES])
        return default_statuses_for_type(activity_type)

    def _status_selector(self) -> SelectSelector:
        return SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=key, label=label)
                    for key, label in SIGNUP_STATUSES.items()
                ],
                multiple=True,
                mode=SelectSelectorMode.LIST,
            )
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        activity_types = self._known_activity_types()

        if user_input is not None:
            # Fravælger man alt, udelader HA nøglen helt. Vi skriver den
            # eksplicit, så "ingen statusser" ikke bliver læst som "standard".
            data: dict[str, Any] = {
                CONF_CALENDAR_TYPES: user_input.get(CONF_CALENDAR_TYPES, []),
                CONF_CALENDAR_TITLE_TYPE: user_input.get(
                    CONF_CALENDAR_TITLE_TYPE, DEFAULT_CALENDAR_TITLE_TYPE
                ),
                CONF_CALENDAR_TITLE_STATUSES: user_input.get(
                    CONF_CALENDAR_TITLE_STATUSES, []
                ),
            }
            for activity_type in activity_types:
                key = statuses_option_key(activity_type)
                data[key] = user_input.get(key, [])
            # Det fælles valg fra v0.4.0 er nu fordelt ud på typerne
            data.pop(CONF_LEGACY_CALENDAR_STATUSES, None)
            return self.async_create_entry(title="", data=data)

        options = self._entry.options
        fields: dict[Any, Any] = {}

        # Ét statusvalg pr. aktivitetstype — ved træning er status kun
        # interessant hvis man har meldt fra, ved kamp er der flere trin.
        for activity_type in activity_types:
            fields[
                vol.Optional(
                    statuses_option_key(activity_type),
                    description={"suggested_value": self._status_default(activity_type)},
                    default=self._status_default(activity_type),
                )
            ] = self._status_selector()

        fields[
            vol.Optional(
                CONF_CALENDAR_TYPES,
                default=list(options.get(CONF_CALENDAR_TYPES, [])),
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=[SelectOptionDict(value=t, label=t) for t in activity_types],
                multiple=True,
                custom_value=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
        fields[
            vol.Optional(
                CONF_CALENDAR_TITLE_TYPE,
                default=options.get(
                    CONF_CALENDAR_TITLE_TYPE, DEFAULT_CALENDAR_TITLE_TYPE
                ),
            )
        ] = bool
        fields[
            vol.Optional(
                CONF_CALENDAR_TITLE_STATUSES,
                default=list(
                    options.get(
                        CONF_CALENDAR_TITLE_STATUSES, DEFAULT_CALENDAR_TITLE_STATUSES
                    )
                ),
            )
        ] = self._status_selector()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(fields),
            description_placeholders={
                "types": ", ".join(activity_types) or "ingen fundet endnu"
            },
        )
