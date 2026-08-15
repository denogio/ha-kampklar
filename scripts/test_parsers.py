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
    merge_children,
    parse_dashboard,
    parse_inbox,
    parse_message_details,
    parse_myteams,
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


# ── holdaktiviteter ─────────────────────────────────────────────────────────


def test_myteams_parses_activities():
    acts = parse_myteams(_load("myteams_emil"), today=date(2026, 5, 15))
    assert len(acts) == 3
    a = acts[0]
    assert a.title == "Træning på bane 2"
    assert a.activity_type == "Træning"
    assert a.date == date(2026, 5, 18)
    assert a.weekday == "Mandag"
    assert a.time_range == "17:00 - 18:30"
    assert a.location == "Bane 2"


def test_myteams_signup_status_values():
    acts = parse_myteams(_load("myteams_emil"), today=date(2026, 5, 15))
    statuses = {a.signup_status for a in acts}
    assert statuses == {"Ikke svaret", "Frameldt", "Tilmeldt"}


def test_myteams_detects_locked_signup():
    acts = parse_myteams(_load("myteams_emil"), today=date(2026, 5, 15))
    assert [a.signup_locked for a in acts] == [False, True, False]


def test_myteams_counts_have_expected_keys():
    acts = parse_myteams(_load("myteams_emil"), today=date(2026, 5, 15))
    counted = [a for a in acts if a.counts]
    assert counted, "ingen aktivitet havde counts"
    for a in counted:
        assert set(a.counts) == {"ikke_svaret", "tilmeldt", "frameldt", "traenere"}


def test_myteams_context_identifies_child_and_team():
    ctx = parse_myteams_context(_load("myteams_emil"))
    assert ctx.child_name == "Emil Jensen"
    assert ctx.team_name == "U12 Drenge Vestby (årgang 2014) 25/26"
    assert ctx.club_name == "Vestby IF"


def test_myteams_context_for_second_child():
    ctx = parse_myteams_context(_load("myteams_ida"))
    assert ctx.child_name == "Ida Jensen"
    assert ctx.team_name.startswith("U9 Piger")


# ── børn på tværs af sider ──────────────────────────────────────────────────


def _child(person_id: int, team_id: int, name: str, team: str = "U12 Drenge") -> Child:
    return Child(
        person_id=person_id,
        team_id=team_id,
        club_id=None,
        team_name=team,
        name=name,
    )


def test_dashboard_alone_finds_only_the_busiest_child():
    """Forsiden viser kun ~4 begivenheder — barn nr. 2 er ikke med.

    Det er hele grunden til at børn også gemmes på disk og verificeres via
    deres egen KampKlar-side.
    """
    children = discover_children(parse_dashboard(_load("dashboard")))
    assert [c.key for c in children] == ["1000000001_11"]


def test_merge_keeps_known_child_missing_from_dashboard():
    known = [_child(1000000001, 11, "Emil Jensen"), _child(1000000002, 12, "Ida Jensen")]
    discovered = discover_children(parse_dashboard(_load("dashboard")))
    merged = merge_children(known, discovered)
    assert {c.key for c in merged} == {"1000000001_11", "1000000002_12"}
    # forsidens (bekræftede) barn kommer først
    assert merged[0].key == "1000000001_11"


def test_merge_adds_newly_discovered_child():
    merged = merge_children(
        [_child(1000000001, 11, "Emil Jensen")], [_child(1000000002, 12, "Ida Jensen")]
    )
    assert {c.key for c in merged} == {"1000000001_11", "1000000002_12"}


def test_display_names_are_unique():
    children = [
        _child(1000000001, 11, "Emil Jensen", "U12 Drenge Vestby"),
        _child(1000000002, 12, "Ida Jensen", "U9 Piger Vestby"),
    ]
    assign_display_names(children)
    assert [c.short_name for c in children] == ["Emil", "Ida"]

    # samme fornavn (eller ét barn på to hold) må ikke give samme entity-id
    same_name = [
        _child(1000000003, 13, "Emil Sørensen", "U12 Drenge"),
        _child(1000000001, 11, "Emil Jensen", "U11 Drenge"),
    ]
    assign_display_names(same_name)
    assert len({c.short_name for c in same_name}) == 2


def test_child_roundtrips_through_storage_dict():
    c = _child(1000000002, 12, "Ida Jensen", "U9 Piger Vestby (årgang 2017) 25/26")
    c.club_name = "Vestby IF"
    assert Child.from_dict(c.as_dict()) == c
