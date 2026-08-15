"""DbuClient: high-level API til mit.dbu.dk.

Håndterer login, auto-relogin ved session-udløb, og henter rå HTML som
parsers.py kan behandle.
"""

from __future__ import annotations

import logging
import re

import aiohttp
from bs4 import BeautifulSoup

from .parsers import (
    Child,
    DashboardEvent,
    InboxMessage,
    MessageDetails,
    TeamActivity,
    TeamContext,
    discover_children,
    parse_dashboard,
    parse_inbox,
    parse_message_details,
    parse_myteams,
    parse_myteams_context,
)

_LOG = logging.getLogger(__name__)

WWW = "https://www.dbu.dk"
MIT = "https://mit.dbu.dk"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class DbuAuthError(Exception):
    """Login afvist eller credentials forkerte."""


class DbuConnectionError(Exception):
    """Netværksfejl mod dbu.dk / mit.dbu.dk."""


class DbuClient:
    """Asynkron klient til mit.dbu.dk."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._logged_in = False

    async def login(self) -> None:
        """Kør hele login-flowet. Raiser DbuAuthError eller DbuConnectionError."""
        try:
            async with self._session.get(f"{WWW}/", headers=self._base_headers()) as r:
                html = await r.text()
        except aiohttp.ClientError as err:
            raise DbuConnectionError(f"Kunne ikke nå {WWW}: {err}") from err

        token = self._extract_antiforgery(html)
        if not token:
            raise DbuAuthError("Fandt ikke __RequestVerificationToken på dbu.dk forside")

        headers = self._base_headers()
        headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": WWW,
                "Referer": f"{WWW}/",
                "RequestVerificationToken": token,
            }
        )
        data = {
            "username": self._username,
            "password": self._password,
            "remember": "false",
        }
        try:
            async with self._session.post(
                f"{WWW}/login/PerformLogin", data=data, headers=headers
            ) as r:
                if r.status != 200:
                    raise DbuAuthError(f"PerformLogin status {r.status}")
                payload = await r.json(content_type=None)
        except aiohttp.ClientError as err:
            raise DbuConnectionError(f"PerformLogin fejlede: {err}") from err

        if payload.get("result") != 1 or not payload.get("url"):
            raise DbuAuthError(f"Login afvist: {payload!r}")

        try:
            async with self._session.get(
                payload["url"], headers=self._base_headers(), allow_redirects=True
            ) as r:
                if "login" in r.url.path.lower():
                    raise DbuAuthError("Blev sendt tilbage til login efter token-redirect")
                await r.read()
        except aiohttp.ClientError as err:
            raise DbuConnectionError(f"Token-redirect fejlede: {err}") from err

        self._logged_in = True
        _LOG.info("Logget ind på mit.dbu.dk som %s", self._username)

    async def fetch_dashboard(self) -> list[DashboardEvent]:
        html = await self._get_html(f"{MIT}/default.aspx")
        return parse_dashboard(html)

    async def fetch_inbox(self) -> list[InboxMessage]:
        html = await self._get_html(f"{MIT}/Message/Inbox.aspx")
        return parse_inbox(html)

    async def fetch_message_details(self, message_id: int) -> MessageDetails:
        html = await self._get_html(
            f"{MIT}/Message/MessageDetails.aspx?id={message_id}"
        )
        return parse_message_details(html, message_id)

    async def fetch_myteams(
        self, team_id: int | None = None, person_id: int | None = None
    ) -> list[TeamActivity]:
        activities, _ = await self.fetch_myteams_page(team_id, person_id)
        return activities

    async def fetch_myteams_page(
        self, team_id: int | None = None, person_id: int | None = None
    ) -> tuple[list[TeamActivity], TeamContext]:
        """Hent KampKlar-siden for ét barn/hold — aktiviteter *og* hvem siden viser.

        Konteksten bruges til at verificere at vi rent faktisk fik det barn vi
        bad om (og til at få barnets navn selvom det ikke står på forsiden).
        """
        url = f"{MIT}/MyTeam/MyTeams.aspx"
        if team_id is not None and person_id is not None:
            url = f"{url}?teamid={team_id}&contactforpersonid={person_id}"
        html = await self._get_html(url)
        return parse_myteams(html), parse_myteams_context(html)

    async def fetch_children(self) -> list[Child]:
        events = await self.fetch_dashboard()
        return discover_children(events)

    async def fetch_all_activities(self) -> dict[str, list[TeamActivity]]:
        """Hent myteams pr. barn. Returnerer dict keyed by Child.key."""
        children = await self.fetch_children()
        results: dict[str, list[TeamActivity]] = {}
        for child in children:
            results[child.key] = await self.fetch_myteams(
                team_id=child.team_id, person_id=child.person_id
            )
        return results

    async def _ensure_authed(self) -> None:
        if not self._logged_in:
            await self.login()

    async def _get_html(self, url: str) -> str:
        await self._ensure_authed()
        try:
            async with self._session.get(url, headers=self._base_headers()) as r:
                text = await r.text()
                if r.status != 200 or "login" in r.url.path.lower():
                    _LOG.info("Session udløbet (final_url=%s), logger ind igen", r.url)
                    self._logged_in = False
                    await self.login()
                    async with self._session.get(url, headers=self._base_headers()) as r2:
                        if r2.status != 200 or "login" in r2.url.path.lower():
                            raise DbuAuthError(
                                f"Stadig redirected til login efter relogin: {r2.url}"
                            )
                        return await r2.text()
                return text
        except aiohttp.ClientError as err:
            raise DbuConnectionError(f"GET {url}: {err}") from err

    def _base_headers(self) -> dict[str, str]:
        return {"User-Agent": UA, "Accept-Language": "da-DK,da;q=0.9,en;q=0.7"}

    @staticmethod
    def _extract_antiforgery(html: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        el = soup.find("input", {"name": "__RequestVerificationToken"})
        if el and el.get("value"):
            return el["value"]
        m = re.search(
            r'name=["\']__RequestVerificationToken["\']\s+[^>]*value=["\']([^"\']+)',
            html,
        )
        return m.group(1) if m else None
