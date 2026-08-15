"""Tests af parserne mod anonymiserede fixtures i scripts/fixtures/.

Fixtures er udklip af den rigtige markup fra mit.dbu.dk med opdigtede navne,
hold og id'er — ingen private data i repoet.

Kør: scripts/.venv/bin/python -m pytest scripts/test_parsers.py -v
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from parsers import (
    Child,
    assign_display_names,
    discover_children,
    parse_aspnet_form,
    parse_dashboard,
    parse_inbox,
    parse_message_details,
    parse_myteams,
    parse_myteams_chooser,
    parse_myteams_context,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text()


# ── forsiden ────────────────────────────────────────────────────────────────


def test_dashboard_parses_events():
    events = parse_dashboard(_load("dashboard"))
    assert len(events) >= 4
    e = events[0]
    assert e.title == "TRÆNING PÅ BANE 2"
    assert e.activity_id == 7100001
    assert e.team_id == 11
    assert e.club_id
    assert e.date == date(2026, 5, 18)
    assert e.event_type == "Kampklar"


def test_dashboard_has_team_and_contact():
    events = parse_dashboard(_load("dashboard"))
    assert any(e.team for e in events)
    assert any(e.contact_person == "Emil Jensen" for e in events)


def test_dashboard_shortcut_cards_never_become_children():
    """Genvejskortene (Beskedcenter osv.) har hverken barn eller hold."""
    events = parse_dashboard(_load("dashboard"))
    shortcuts = [e for e in events if e.activity_id is None]
    assert shortcuts, "fixture bør indeholde mindst ét genvejskort"
    assert all(e.contact_for_person_id is None for e in shortcuts)


# ── indbakke ────────────────────────────────────────────────────────────────


def test_inbox_parses_messages():
    msgs = parse_inbox(_load("inbox"))
    assert len(msgs) == 2
    m = msgs[0]
    assert m.message_id == 700000001
    assert m.subject == "Kamp mod Vestby B på mandag"
    assert m.sender == "Mette Træner"
    assert m.category == "KampKlar"
    assert m.received is not None
    assert m.preview


def test_inbox_detects_unread():
    msgs = parse_inbox(_load("inbox"))
    assert all(isinstance(m.unread, bool) for m in msgs)


def test_message_details_body_keeps_linebreaks():
    details = parse_message_details(_load("message"), 700000001)
    assert details.subject == "Kamp mod Vestby B på mandag"
    assert details.category == "KampKlar"
    assert details.received is not None
    assert "Vestby Stadion" in details.body
    assert "\n" in details.body


# ── KampKlar-vælgeren (flere børn) ──────────────────────────────────────────


def test_chooser_lists_every_child():
    """Vælgeren er den eneste komplette liste over børn på mit.dbu.dk."""
    rows = parse_myteams_chooser(_load("myteams_chooser"))
    assert [r.child_name for r in rows] == ["Ida Jensen", "Emil Jensen"]
    assert all(r.postback_target.startswith("ctl00$cphMain$rgPlayerContact") for r in rows)
    assert rows[0].team_name.startswith("U9 Piger")
    assert rows[0].club_name == "Vestby IF"


def test_chooser_page_is_not_a_team_page():
    ctx = parse_myteams_context(_load("myteams_chooser"))
    assert ctx.is_team_page is False
    assert ctx.team_name is None


def test_aspnet_form_has_the_fields_postbacken_kraever():
    form = parse_aspnet_form(_load("myteams_chooser"))
    assert "__VIEWSTATE" in form
    assert "__EVENTVALIDATION" in form
    assert "__VIEWSTATEGENERATOR" in form


def test_single_child_page_needs_no_chooser():
    """Med ét barn springer DBU vælgeren over og viser holdsiden direkte."""
    assert parse_myteams_chooser(_load("myteams_emil")) == []
    assert parse_myteams_context(_load("myteams_emil")).is_team_page is True


# ── holdsiden (PlayerTeam.aspx) ─────────────────────────────────────────────


def test_team_page_identifies_child_team_and_ids():
    ctx = parse_myteams_context(_load("playerteam_emil"))
    assert ctx.is_team_page is True
    assert ctx.child_name == "Emil Jensen"
    assert ctx.team_name.startswith("U12 Drenge Vestby")
    assert ctx.club_name == "Vestby IF"
    # hold- og klub-ID står kun i iCal-linket
    assert ctx.team_id == 11
    assert ctx.club_id == "11111111-2222-3333-4444-555555555555"


def test_team_page_for_second_child():
    ctx = parse_myteams_context(_load("playerteam_ida"))
    assert ctx.child_name == "Ida Jensen"
    assert ctx.team_id == 12


def test_team_page_parses_activities():
    acts = parse_myteams(_load("playerteam_emil"), today=date(2026, 8, 14))
    assert len(acts) == 3
    kamp = acts[0]
    assert kamp.activity_type == "Kamp"
    assert kamp.date == date(2026, 8, 15)
    assert kamp.time_range == "10:00 - 11:10"
    assert kamp.signup_locked is True


def test_meeting_time_is_not_mistaken_for_a_location():
    """Feltet bruges til sted ved træning og mødetid ved kamp."""
    acts = parse_myteams(_load("playerteam_emil"), today=date(2026, 8, 14))
    kamp = acts[0]
    assert kamp.meeting_time == "09:00"
    assert kamp.location is None
    assert all(
        not (a.location or "").lower().startswith("mødetid") for a in acts
    )
    # ... og et rigtigt sted lander stadig i location
    traening = parse_myteams(_load("myteams_emil"), today=date(2026, 5, 15))[0]
    assert traening.location == "Bane 2"


def test_match_counts_split_selected_players():
    """Ved kampe står de udtagne som "10/0" = bekræftet/ikke bekræftet."""
    kamp = parse_myteams(_load("playerteam_emil"), today=date(2026, 8, 14))[0]
    assert kamp.counts["udtaget"] == 10
    assert kamp.counts["udtaget_ikke_bekraeftet"] == 0
    assert kamp.counts["ikke_svaret"] == 12
    assert "til_raadighed" in kamp.counts


def test_signup_status_values():
    acts = parse_myteams(_load("playerteam_emil"), today=date(2026, 8, 14))
    assert {a.signup_status for a in acts} >= {"Udtaget (bekræftet)", "Tilmeldt"}


# ── børn og nøgler ──────────────────────────────────────────────────────────


def _child(team_id: int, name: str, person_id: int | None = None) -> Child:
    return Child(team_id=team_id, team_name="U12 Drenge", name=name, person_id=person_id)


def test_key_is_team_based_and_stable():
    """Nøglen bliver til entiteternes unique_id og må aldrig skifte."""
    child = _child(11, "Emil Jensen")
    assert child.key == "t11"
    # person-ID må ikke kunne rykke nøglen — det står kun på forsiden
    child.person_id = 1000000001
    assert child.key == "t11"
    # og en gemt nøgle vinder altid, fx hvis DBU giver barnet et nyt hold
    child.stored_key = "t9"
    assert child.key == "t9"


def test_key_falls_back_to_the_name_without_a_team():
    assert Child(team_id=None, name="Emil Jensen").key == "nemil_jensen"


def test_child_roundtrips_through_storage_dict():
    c = _child(12, "Ida Jensen", person_id=1000000002)
    c.club_name = "Vestby IF"
    restored = Child.from_dict(c.as_dict())
    assert restored.key == c.key
    assert restored.name == c.name
    assert restored.club_name == c.club_name


def test_children_stored_before_keys_existed_get_the_team_key():
    """v0.2.0 gemte person+hold uden nøglefelt.

    De skal lande på holdnøglen — den samme som __init__.py migrerer de
    gamle entiteters unique_id over til.
    """
    restored = Child.from_dict({"person_id": 1000000001, "team_id": 11})
    assert restored.key == "t11"


def test_display_names_are_unique():
    children = [_child(11, "Emil Jensen"), _child(12, "Ida Jensen")]
    assign_display_names(children)
    assert [c.short_name for c in children] == ["Emil", "Ida"]

    same_name = [
        Child(team_id=11, team_name="U12 Drenge", name="Emil Jensen"),
        Child(team_id=13, team_name="U9 Piger", name="Emil Sørensen"),
    ]
    assign_display_names(same_name)
    assert len({c.short_name for c in same_name}) == 2


def test_child_without_name_still_gets_a_slug():
    assert Child(team_id=12).short_name == "hold 12"


def test_dashboard_supplies_person_ids_for_the_children():
    """Vælgeren oplyser ikke person-ID — det kommer fra forsidens links."""
    children = discover_children(parse_dashboard(_load("dashboard")))
    assert [(c.person_id, c.team_id) for c in children] == [(1000000001, 11)]
