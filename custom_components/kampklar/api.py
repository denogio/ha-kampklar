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
    ChooserRow,
    DashboardEvent,
    InboxMessage,
    MessageDetails,
    TeamActivity,
    TeamContext,
    parse_aspnet_form,
    parse_dashboard,
    parse_inbox,
    parse_message_details,
    parse_myteams,
    parse_myteams_chooser,
    parse_myteams_context,
)

_LOG = logging.getLogger(__name__)

WWW = "https://www.dbu.dk"
MIT = "https://mit.dbu.dk"

MYTEAMS_URL = f"{MIT}/MyTeam/MyTeams.aspx"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _child_from_context(ctx: TeamContext) -> Child:
    return Child(
        team_id=ctx.team_id,
        team_name=ctx.team_name,
        name=ctx.child_name,
        club_name=ctx.club_name,
        club_id=ctx.club_id,
    )


def _child_from_row(row: ChooserRow) -> Child:
    return Child(
        team_id=None,
        team_name=row.team_name,
        name=row.child_name,
        club_name=row.club_name,
        postback_target=row.postback_target,
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

    async def fetch_team_page(self, target: str, form: dict[str, str]) -> str:
        """Vælg et hold i KampKlar-vælgeren via ASP.NET-postback.

        DBU holder valget i server-session og sender os videre til
        PlayerTeam.aspx. Der findes ingen GET-variant: kalder man
        PlayerTeam.aspx direkte, ryger man tilbage til vælgeren.
        """
        data = dict(form)
        data["__EVENTTARGET"] = target
        data["__EVENTARGUMENT"] = ""
        await self._ensure_authed()
        headers = self._base_headers()
        headers["Referer"] = MYTEAMS_URL
        try:
            async with self._session.post(
                MYTEAMS_URL, data=data, headers=headers
            ) as r:
                if r.status != 200:
                    raise DbuConnectionError(f"Holdvalg gav status {r.status}")
                return await r.text()
        except aiohttp.ClientError as err:
            raise DbuConnectionError(f"Holdvalg fejlede: {err}") from err

    async def fetch_children_with_activities(
        self,
    ) -> list[tuple[Child, list[TeamActivity]]]:
        """Hent alle børn og deres aktiviteter.

        KampKlar-forsiden er en vælger med én række pr. barn/hold — den er den
        eneste komplette liste over børn på mit.dbu.dk, og den viser også børn
        uden aktiviteter. Har du kun ét barn, springer DBU vælgeren over og
        viser holdsiden med det samme.
        """
        html = await self._get_html(MYTEAMS_URL)
        context = parse_myteams_context(html)

        if context.is_team_page:
            return [(_child_from_context(context), parse_myteams(html))]

        rows = parse_myteams_chooser(html)
        if not rows:
            _LOG.warning(
                "KampKlar-siden havde hverken hold eller vælger — "
                "har mit.dbu.dk ændret sig igen?"
            )
            return []

        form = parse_aspnet_form(html)
        out: list[tuple[Child, list[TeamActivity]]] = []
        for row in rows:
            page = await self.fetch_team_page(row.postback_target, form)
            ctx = parse_myteams_context(page)
            if not ctx.is_team_page:
                # Holdvalget slog fejl — behold barnet med det vælgeren ved,
                # så det ikke forsvinder ud af Home Assistant.
                _LOG.warning(
                    "Kunne ikke åbne holdsiden for %s (%s)",
                    row.child_name,
                    row.team_name,
                )
                out.append((_child_from_row(row), []))
                continue
            child = _child_from_context(ctx)
            child.postback_target = row.postback_target
            child.name = child.name or row.child_name
            child.team_name = child.team_name or row.team_name
            out.append((child, parse_myteams(page)))
        return out

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
