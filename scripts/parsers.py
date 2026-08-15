"""HTML-parsere til mit.dbu.dk.

Hver parser tager rå HTML-streng og returnerer en liste/dict af dataklasser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

DK_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "maj": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12,
}

# Tilmeldingsstatusser som mit.dbu.dk bruger: nøgle -> (label, emoji).
# Til kampe udtager træneren en trup, så der er flere trin end ved træning.
# Rækkefølgen er den de vises i i indstillingerne.
SIGNUP_STATUSES: dict[str, tuple[str, str]] = {
    "tilmeldt": ("Tilmeldt", "✅"),
    "udtaget_bekraeftet": ("Udtaget (bekræftet)", "⭐"),
    "udtaget": ("Udtaget", "📋"),
    "udtaget_ikke_bekraeftet": ("Udtaget (ikke bekræftet)", "⏳"),
    "til_raadighed": ("Til rådighed", "🟠"),
    "ikke_svaret": ("Ikke svaret", "❓"),
    "frameldt": ("Frameldt", "❌"),
    "andet": ("Andet", "▫️"),
}


@dataclass
class Child:
    """Et barn/hold-tilknytning — én pr. række i KampKlar-vælgeren.

    Hold-ID'et er det stabile holdepunkt: vælger-siden oplyser hverken
    person-ID eller hold-ID, så team_id læses af holdsiden og person_id
    hentes (når det er muligt) fra forsidens links.

    `stored_key` er den nøgle barnet fik første gang vi så det. Den gemmes og
    genbruges for evigt, så entiteternes unique_id aldrig skifter — heller
    ikke hvis vi senere lærer barnets person_id at kende.
    """
    team_id: int | None
    team_name: str | None = None    # fx "U12 Drenge Vestby (årgang 2014) 25/26"
    name: str | None = None         # barnets navn ("Kontaktperson for: ...")
    club_name: str | None = None
    club_id: str | None = None
    person_id: int | None = None
    stored_key: str | None = None
    # Postback-målet der vælger dette hold. Kun gyldigt i den aktuelle
    # opdatering — gemmes ikke.
    postback_target: str | None = None
    # Unikt visningsnavn — sættes af assign_display_names() når hele listen
    # af børn kendes, så to søskende ikke ender med samme entity-id.
    display_name: str | None = None

    @property
    def key(self) -> str:
        """Stabil identifikator — bliver til entiteternes unique_id.

        Hold-ID'et er det eneste der er både unikt og stabilt hen over
        sæsoner: DBU genbruger holdet og skifter bare navnet. Kender vi
        undtagelsesvis ikke holdet, falder vi tilbage på barnets navn.
        """
        if self.stored_key:
            return self.stored_key
        if self.team_id is not None:
            return f"t{self.team_id}"
        if self.name:
            return "n" + re.sub(r"\W+", "_", self.name.strip().lower())
        return "ukendt"

    @property
    def first_name(self) -> str:
        if self.name:
            return self.name.split(" ", 1)[0]
        if self.person_id:
            return str(self.person_id)
        return f"hold {self.team_id}" if self.team_id else "barn"

    @property
    def short_name(self) -> str:
        """Kort, slug-venligt navn — fornavn hvis muligt, ellers holdet."""
        return self.display_name or self.first_name

    def as_dict(self) -> dict:
        """Serialisering til HA's storage (så nøgler overlever genstart)."""
        return {
            "key": self.key,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "name": self.name,
            "club_name": self.club_name,
            "club_id": self.club_id,
            "person_id": self.person_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Child":
        team_id = data.get("team_id")
        person_id = data.get("person_id")
        return cls(
            team_id=int(team_id) if team_id is not None else None,
            team_name=data.get("team_name"),
            name=data.get("name"),
            club_name=data.get("club_name"),
            club_id=data.get("club_id"),
            person_id=int(person_id) if person_id is not None else None,
            # Ældre versioner gemte ingen nøgle. Den udledes så på ny af
            # hold-ID'et — det matcher de unique_id'er __init__.py migrerer
            # de gamle entiteter over til.
            stored_key=data.get("key"),
        )


@dataclass
class TeamContext:
    """Hvem/hvilket hold en holdside (PlayerTeam.aspx) viser."""
    child_name: str | None
    team_name: str | None
    club_name: str | None
    team_id: int | None = None
    club_id: str | None = None

    @property
    def is_team_page(self) -> bool:
        return self.team_name is not None


@dataclass
class ChooserRow:
    """Én række i KampKlar-vælgeren ("Som forælder/kontaktperson")."""
    postback_target: str
    team_name: str | None
    club_name: str | None
    child_name: str | None


@dataclass
class DashboardEvent:
    title: str
    date: date | None
    weekday_short: str | None
    team: str | None
    contact_person: str | None
    event_type: str | None
    activity_id: int | None
    team_id: int | None
    club_id: str | None
    contact_for_person_id: int | None
    url: str | None


@dataclass
class InboxMessage:
    message_id: int
    subject: str
    category: str | None
    unread: bool
    preview: str
    sender: str | None
    received: datetime | None


@dataclass
class MessageDetails:
    message_id: int
    subject: str | None
    sender: str | None
    category: str | None
    received: datetime | None
    body: str            # plaintext med \n som linjeskift


@dataclass
class TeamActivity:
    activity_id: int | None
    activity_type: str | None
    title: str
    weekday: str | None
    time_range: str | None
    location: str | None
    signup_status: str | None
    signup_locked: bool
    date: date | None
    counts: dict[str, int] = field(default_factory=dict)
    url: str | None = None
    meeting_time: str | None = None   # "Mødetid: 09:00" ved kampe
    pool: str | None = None           # række/pulje ved turneringskampe


def _qs_int(url: str, key: str) -> int | None:
    try:
        v = parse_qs(urlparse(url).query).get(key, [None])[0]
        return int(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _qs_str(url: str, key: str) -> str | None:
    return parse_qs(urlparse(url).query).get(key, [None])[0]


def parse_dashboard(html: str) -> list[DashboardEvent]:
    """Parse /default.aspx — viser brugerens kommende begivenheder."""
    soup = BeautifulSoup(html, "html.parser")
    events: list[DashboardEvent] = []

    for art in soup.find_all("article", class_="list__item"):
        if "list__personal" in (art.get("class") or []):
            continue
        a = art.find("h3")
        a = a.find("a") if a else None
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")

        time_el = art.find("time")
        weekday_short: str | None = None
        d: date | None = None
        if time_el:
            ws = time_el.find("span", class_="day_short")
            if ws:
                weekday_short = ws.get_text(strip=True)
            m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", time_el.get_text(" ", strip=True))
            if m:
                d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))

        team = contact = None
        p = art.find("p")
        if p:
            txt = p.get_text("\n", strip=True)
            for line in txt.split("\n"):
                if line.lower().startswith("hold:"):
                    team = line.split(":", 1)[1].strip()
                elif line.lower().startswith("kontaktperson:"):
                    contact = line.split(":", 1)[1].strip()

        tag_el = art.find("span", class_="event_tag")
        event_type = tag_el.get_text(strip=True) if tag_el else None

        events.append(
            DashboardEvent(
                title=title,
                date=d,
                weekday_short=weekday_short,
                team=team,
                contact_person=contact,
                event_type=event_type,
                activity_id=_qs_int(href, "activityid"),
                team_id=_qs_int(href, "teamid"),
                club_id=_qs_str(href, "clubid"),
                contact_for_person_id=_qs_int(href, "contactforpersonid"),
                url=href or None,
            )
        )
    return events


def parse_inbox(html: str) -> list[InboxMessage]:
    """Parse /Message/Inbox.aspx — Telerik RadGrid."""
    soup = BeautifulSoup(html, "html.parser")
    messages: list[InboxMessage] = []

    rows = soup.find_all("tr", class_=lambda c: c in ("rgRow", "rgAltRow"))
    for row in rows:
        subject_a = row.find("a", id=re.compile(r"_hlType$"))
        if not subject_a:
            continue
        msg_id = _qs_int(subject_a.get("href", ""), "id") or 0

        # category-tag: lblType. unread-tag: Label1 ("Ny besked")
        category = None
        unread = False
        for tag in row.find_all("span", class_="tag"):
            tid = tag.get("id", "")
            text = tag.get_text(strip=True)
            if tid.endswith("_lblType"):
                category = text
            elif "Ny besked" in text:
                unread = True

        preview_el = row.find("span", class_="MessageText")
        preview = preview_el.get_text(" ", strip=True) if preview_el else ""

        from_el = row.find("span", id=re.compile(r"_lblFrom$"))
        sender = from_el.get_text(strip=True) if from_el else None

        created_el = row.find("span", id=re.compile(r"_lblCreated$"))
        received: datetime | None = None
        if created_el:
            txt = created_el.get_text(strip=True)
            try:
                received = datetime.strptime(txt, "%d-%m-%Y %H:%M")
            except ValueError:
                pass

        messages.append(
            InboxMessage(
                message_id=msg_id,
                subject=subject_a.get_text(strip=True),
                category=category,
                unread=unread,
                preview=preview,
                sender=sender,
                received=received,
            )
        )
    return messages


def parse_message_details(html: str, message_id: int) -> MessageDetails:
    """Parse /Message/MessageDetails.aspx?id=X.

    Body ligger i <span id="cphMain_lblMsg"> med <br/> som linjeskift —
    vi erstatter dem med newlines så vi får ren tekst.
    """
    soup = BeautifulSoup(html, "html.parser")

    def _text(el_id: str) -> str | None:
        el = soup.find(id=el_id)
        return el.get_text(" ", strip=True) if el else None

    body_el = soup.find(id="cphMain_lblMsg")
    if body_el:
        for br in body_el.find_all("br"):
            br.replace_with("\n")
        body = body_el.get_text().strip()
        # Fjern overflødige whitespace-runs, men bevar newlines
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n{3,}", "\n\n", body)
    else:
        body = ""

    received: datetime | None = None
    date_txt = _text("cphMain_lblDate")
    if date_txt:
        try:
            received = datetime.strptime(date_txt, "%d-%m-%Y %H:%M")
        except ValueError:
            pass

    return MessageDetails(
        message_id=message_id,
        subject=_text("cphMain_lblSubject"),
        sender=None,  # sender er i <h3> ikke som id'd span; vi parser separat
        category=_text("cphMain_lblCategory"),
        received=received,
        body=body,
    )


def discover_children(events: list[DashboardEvent]) -> list[Child]:
    """Udled liste af børn/hold fra dashboard-events.

    Grupperer efter (contact_for_person_id, team_id) — første event vinder
    for team_name/club_id. Events uden person_id+team_id ignoreres.

    BEMÆRK: forsiden viser kun de førstkommende ~4 begivenheder på tværs af
    alle børn. Har ét barn fire aktiviteter før det andet barns første, er
    barn nr. 2 helt fraværende her. Derfor er det her kun en *opdagelses*-
    kilde — den samlede liste vedligeholdes via merge_children().
    """
    seen: dict[tuple[int, int], Child] = {}
    for e in events:
        if e.contact_for_person_id is None or e.team_id is None:
            continue
        key = (e.contact_for_person_id, e.team_id)
        if key in seen:
            continue
        seen[key] = Child(
            person_id=e.contact_for_person_id,
            team_id=e.team_id,
            club_id=e.club_id,
            team_name=e.team,
            name=e.contact_person,
        )
    return list(seen.values())


def assign_display_names(children: list[Child]) -> None:
    """Giv hvert barn et unikt, kort visningsnavn (bruges i entity-id'er).

    Normalt bare fornavnet. Er der sammenfald (søskende med samme fornavn,
    eller ét barn på to hold) tilføjes holdets første ord — og i sidste ende
    person/hold-id, så vi aldrig får to devices med samme navn.
    """
    by_first: dict[str, list[Child]] = {}
    for child in children:
        by_first.setdefault(child.first_name.lower(), []).append(child)

    for group in by_first.values():
        if len(group) == 1:
            group[0].display_name = group[0].first_name
            continue
        used: set[str] = set()
        for child in group:
            suffix = (child.team_name or "").split(" ", 1)[0].strip()
            candidate = f"{child.first_name} {suffix}".strip() if suffix else ""
            if not candidate or candidate.lower() in used:
                candidate = f"{child.first_name} {child.team_id}"
            used.add(candidate.lower())
            child.display_name = candidate


def parse_myteams_context(html: str) -> TeamContext:
    """Hvem viser denne holdside (PlayerTeam.aspx)?

    Siden fortæller det selv i toppen — klubnavn, hold og "Kontaktperson for:
    <barnets navn>". Hold- og klub-ID hentes fra iCal-linket
    (TeamActivities.ashx?...&clubkey=<uuid>&teamid=<n>), som er det eneste
    sted de optræder nu.

    Er der intet holdnavn, er det ikke en holdside — så er det vælgeren.
    ASP.NET skifter mellem "cphMain_" og "ctl00_cphMain_" som id-præfiks
    afhængigt af siden, så vi matcher på endelsen.
    """
    soup = BeautifulSoup(html, "html.parser")

    def _by_suffix(suffix: str) -> str | None:
        el = soup.find(id=re.compile(re.escape(suffix) + r"$"))
        return el.get_text(" ", strip=True) if el else None

    child_name = None
    role = _by_suffix("lblRole")
    if role and ":" in role:
        child_name = role.split(":", 1)[1].strip() or None

    team_id = club_id = None
    m = re.search(r"TeamActivities\.ashx\?[^\"']*", html)
    if m:
        team_id = _qs_int(m.group(0), "teamid")
        club_id = _qs_str(m.group(0), "clubkey")

    return TeamContext(
        child_name=child_name,
        team_name=_by_suffix("lblTeam"),
        club_name=_by_suffix("lblClubName"),
        team_id=team_id,
        club_id=club_id,
    )


def parse_myteams_chooser(html: str) -> list[ChooserRow]:
    """Parse vælger-siden /MyTeam/MyTeams.aspx.

    Har du flere børn, viser DBU en tabel ("Som forælder/kontaktperson") med
    ét hold pr. række — den eneste komplette liste over dine børn der findes
    på mit.dbu.dk. Holdet vælges med en ASP.NET-postback, og rækkens
    __doPostBack-mål er nøglen til at hente holdsiden bagefter.

    Med kun ét barn springer DBU vælgeren over og viser holdsiden direkte —
    så giver den her en tom liste.
    """
    soup = BeautifulSoup(html, "html.parser")
    grid = soup.find(id=re.compile(r"rgPlayerContact$"))
    if grid is None:
        return []

    rows: list[ChooserRow] = []
    for tr in grid.find_all("tr", class_=lambda c: c in ("rgRow", "rgAltRow")):
        link = tr.find("a", href=re.compile(r"__doPostBack"))
        if not link:
            continue
        m = re.search(r"__doPostBack\('([^']+)'", link.get("href", ""))
        if not m:
            continue
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        rows.append(
            ChooserRow(
                postback_target=m.group(1),
                team_name=link.get_text(strip=True) or None,
                # Kolonner: Holdnavn, Afdeling, Sportsgren, Køn, Klub,
                # "Kontaktperson for". Vi tager de to sidste og lader resten
                # ligge — holdsiden har alligevel de præcise værdier.
                club_name=cells[-2] if len(cells) >= 2 else None,
                child_name=cells[-1] if cells else None,
            )
        )
    return rows


def normalize_signup_status(status: str | None) -> str:
    """Oversæt DBU's statustekst til en fast nøgle.

    Teksten varierer ("Udtaget", "Udtaget (bekræftet)", "Ikke svaret" …) og
    DBU har ændret den før, så alt matches løst. Ukendte værdier lander i
    "andet" — de skal stadig kunne slås til og fra i kalenderen.
    """
    text = (status or "").strip().lower()
    if not text:
        return "ikke_svaret"
    if "frameld" in text:
        return "frameldt"
    if "udtaget" in text:
        if "ikke bekræftet" in text:
            return "udtaget_ikke_bekraeftet"
        if "bekræftet" in text:
            return "udtaget_bekraeftet"
        return "udtaget"
    if "rådighed" in text:
        return "til_raadighed"
    if "tilmeldt" in text:
        return "tilmeldt"
    if "ikke svaret" in text:
        return "ikke_svaret"
    return "andet"


def parse_aspnet_form(html: str) -> dict[str, str]:
    """Træk ASP.NET's skjulte felter ud (__VIEWSTATE m.fl.).

    De skal med i postbacken, ellers afviser serveren den.
    """
    soup = BeautifulSoup(html, "html.parser")
    return {
        el["name"]: el.get("value") or ""
        for el in soup.find_all("input", type="hidden")
        if el.get("name")
    }


def _infer_year(month: int, today: date) -> int:
    """myteams viser månednavn+dag uden år. Antag samme år, eller næste år hvis
    måneden er mere end 6 måneder bagud — så ruller vi over årsskifte korrekt."""
    year = today.year
    candidate = date(year, month, 1)
    diff_months = (today.year - candidate.year) * 12 + (today.month - candidate.month)
    if diff_months > 6:
        return year + 1
    return year


def parse_myteams(html: str, today: date | None = None) -> list[TeamActivity]:
    """Parse /MyTeam/MyTeams.aspx — listen af aktivitetItem-divs."""
    soup = BeautifulSoup(html, "html.parser")
    today = today or date.today()
    out: list[TeamActivity] = []

    for div in soup.find_all("div", class_="activityItem"):
        month_el = div.find("span", id=re.compile(r"_lblMonth_\d+$"))
        day_el = div.find("span", id=re.compile(r"_lblDate_\d+$"))
        d: date | None = None
        if month_el and day_el:
            try:
                m = DK_MONTHS.get(month_el.get_text(strip=True).lower()[:3])
                day = int(day_el.get_text(strip=True))
                if m:
                    d = date(_infer_year(m, today), m, day)
            except (ValueError, TypeError):
                pass

        name_el = div.find("span", id=re.compile(r"_lblActivityName_\d+$"))
        activity_type = name_el.get_text(strip=True) if name_el else None

        link = div.find("a", id=re.compile(r"_hlName_\d+$"))
        title = link.get_text(strip=True) if link else ""
        href = link.get("href") if link else None
        activity_id = _qs_int(href, "activityid") if href else None

        dt_el = div.find("span", id=re.compile(r"_lblDatetime_\d+$"))
        weekday = time_range = None
        if dt_el:
            txt = dt_el.get_text(" ", strip=True)
            m = re.match(r"(\S+)\s+kl\.\s+(.+)", txt)
            if m:
                weekday, time_range = m.group(1), m.group(2)
            else:
                weekday = txt

        # Samme felt bruges til to ting: sted ved træning ("(Bane 2 )") og
        # mødetid ved kampe ("Mødetid: 09:00").
        loc_el = div.find("span", id=re.compile(r"_lblMeetingDateTime_\d+$"))
        location = meeting_time = None
        if loc_el:
            txt = loc_el.get_text(" ", strip=True).strip("()").strip()
            if txt.lower().startswith("mødetid"):
                meeting_time = txt.split(":", 1)[1].strip() if ":" in txt else txt
            else:
                location = txt or None

        pool_el = div.find("span", id=re.compile(r"_lblRowAndPool_\d+$"))
        pool = pool_el.get_text(" ", strip=True) or None if pool_el else None

        status_el = div.find("span", id=re.compile(r"_lblSignUpStatus_\d+$"))
        signup_status = status_el.get_text(strip=True) if status_el else None

        locked_el = div.find("img", id=re.compile(r"_imgLocked_\d+$"))
        signup_locked = bool(
            locked_el and "ikke" not in (locked_el.get("title", "").lower())
            and "lukket" in (locked_el.get("title", "").lower())
        )

        counts: dict[str, int] = {}
        for sp in div.find_all("span", class_="status"):
            classes = sp.get("class", [])
            title_attr = sp.get("title", "").strip().lower()
            text = sp.get_text(strip=True)
            key = None
            if "green" in classes or "tilmeldt" == title_attr:
                key = "tilmeldt"
            elif "red" in classes:
                key = "frameldt"
            elif "gray" in classes:
                key = "ikke_svaret"
            elif "blue" in classes:
                key = "traenere"
            elif "orange" in classes:
                key = "til_raadighed"
            if not key:
                continue
            if "/" in text:
                # Ved kampe står de udtagne som "10/0" =
                # bekræftet/ikke bekræftet.
                bekraeftet, _, ikke = text.partition("/")
                try:
                    counts["udtaget"] = int(bekraeftet)
                    counts["udtaget_ikke_bekraeftet"] = int(ikke)
                except ValueError:
                    pass
                continue
            try:
                counts[key] = int(text)
            except ValueError:
                continue

        out.append(
            TeamActivity(
                activity_id=activity_id,
                activity_type=activity_type,
                title=title,
                weekday=weekday,
                time_range=time_range,
                location=location,
                signup_status=signup_status,
                signup_locked=signup_locked,
                date=d,
                counts=counts,
                url=href,
                meeting_time=meeting_time,
                pool=pool,
            )
        )
    return out


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    # Kør mod de anonymiserede fixtures — eller mod dine egne dumps fra
    # poc_login.py, som ligger i scripts/dumps/ (gitignored).
    base = Path(__file__).parent / "fixtures"
    name = sys.argv[1] if len(sys.argv) > 1 else "dashboard"
    fn = {
        "dashboard": parse_dashboard,
        "inbox": parse_inbox,
        "myteams_emil": parse_myteams,
        "myteams_ida": parse_myteams,
    }[name]
    html = (base / f"{name}.html").read_text()
    result = fn(html)

    def default(o):
        if hasattr(o, "__dict__"):
            return o.__dict__
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        raise TypeError

    print(json.dumps(result, default=default, indent=2, ensure_ascii=False))
