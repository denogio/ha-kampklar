"""Små unit tests af ASP.NET-postbacken uden en Home Assistant-installation."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import AsyncMock

import pytest


_ROOT = Path(__file__).parents[1] / "custom_components" / "kampklar"
_PACKAGE = types.ModuleType("kampklar_test")
_PACKAGE.__path__ = [str(_ROOT)]
sys.modules[_PACKAGE.__name__] = _PACKAGE

for _name in ("parsers", "api"):
    _spec = importlib.util.spec_from_file_location(
        f"{_PACKAGE.__name__}.{_name}", _ROOT / f"{_name}.py"
    )
    assert _spec and _spec.loader
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _module
    _spec.loader.exec_module(_module)

_api = sys.modules[f"{_PACKAGE.__name__}.api"]

_FORM = """
<form method="post" action="./PlayerActivity.aspx?activityid=42">
  <input type="hidden" name="__VIEWSTATE" value="viewstate-token" />
  <input type="hidden" name="__EVENTVALIDATION" value="validation-token" />
  <textarea name="ctl00$cphMain$rtbComment">Evt. kommentar</textarea>
  <button type="button"
    onclick="__doPostBack('ctl00$cphMain$rptStatusButton$ctl00$btn','')">
    Frameld
  </button>
</form>
"""


def test_signup_postback_preserves_tokens_and_adds_comment():
    action, data = _api._signup_postback_data(_FORM, "Frameld", "Er syg")

    assert action == "./PlayerActivity.aspx?activityid=42"
    assert data["__VIEWSTATE"] == "viewstate-token"
    assert data["__EVENTVALIDATION"] == "validation-token"
    assert data["__EVENTTARGET"] == "ctl00$cphMain$rptStatusButton$ctl00$btn"
    assert data["ctl00$cphMain$rtbComment"] == "Er syg"


def test_signup_postback_rejects_unavailable_action():
    with pytest.raises(_api.DbuActionError, match="ikke tilgængelig"):
        _api._signup_postback_data(_FORM, "Tilmeld")


def test_decline_confirmed_without_signup_button_on_closed_activity():
    html = '<span id="cphMain_lblStatusInfo">Er frameldt kampen</span>'
    assert _api._signup_confirmed(html, attending=False)
    assert not _api._signup_confirmed(html, attending=True)


def test_status_field_takes_precedence_over_opposite_button():
    html = _FORM + '<span id="cphMain_lblStatusInfo">Ikke svaret</span>'
    assert not _api._signup_confirmed(html, attending=True)
    assert not _api._signup_confirmed(html, attending=False)


def test_signup_confirmed_from_personal_status():
    html = '<span id="cphMain_lblStatusInfo">Er tilmeldt aktiviteten</span>'
    assert _api._signup_confirmed(html, attending=True)
    assert not _api._signup_confirmed(html, attending=False)


def test_signup_confirmation_falls_back_for_older_markup():
    assert _api._signup_confirmed(_FORM, attending=True)
    assert not _api._signup_confirmed(_FORM, attending=False)


@pytest.mark.parametrize("entities, allowed", [([], True), ([object()], False)])
def test_device_removal_only_allowed_without_entities(entities, allowed):
    # Test den faktiske hook uden at installere hele Home Assistant.
    tree = ast.parse((_ROOT / "__init__.py").read_text())
    hook = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "async_remove_config_entry_device"
    )
    module = ast.parse("from __future__ import annotations")
    module.body.append(hook)
    registry = {"device": entities}
    namespace = {
        "er": types.SimpleNamespace(
            async_get=lambda hass: registry,
            async_entries_for_device=lambda reg, device_id: reg[device_id],
        )
    }
    exec(compile(module, str(_ROOT / "__init__.py"), "exec"), namespace)
    result = asyncio.run(namespace[hook.name](None, None, types.SimpleNamespace(id="device")))
    assert result is allowed


def test_select_child_uses_fresh_chooser_instead_of_stale_postback():
    chooser = (_ROOT.parents[1] / "scripts/fixtures/myteams_chooser.html").read_text()
    page = (_ROOT.parents[1] / "scripts/fixtures/playerteam_emil.html").read_text()
    child = _api._child_from_context(_api.parse_myteams_context(page))
    child.postback_target = "stale-target"
    client = _api.DbuClient(None, "user", "pass")
    client._get_html = AsyncMock(return_value=chooser)
    client.fetch_team_page = AsyncMock(return_value=page)
    asyncio.run(client._select_child(child))
    expected = next(row for row in _api.parse_myteams_chooser(chooser) if row.child_name == child.name)
    assert client.fetch_team_page.await_args.args[0] == expected.postback_target
    assert client.fetch_team_page.await_args.args[0] != child.postback_target


def test_select_child_rejects_wrong_team_before_any_signup_post():
    fixtures = _ROOT.parents[1] / "scripts/fixtures"
    chooser = (fixtures / "myteams_chooser.html").read_text()
    expected_page = (fixtures / "playerteam_emil.html").read_text()
    wrong_page = (fixtures / "playerteam_ida.html").read_text()
    child = _api._child_from_context(_api.parse_myteams_context(expected_page))
    client = _api.DbuClient(None, "user", "pass")
    client._get_html = AsyncMock(return_value=chooser)
    client.fetch_team_page = AsyncMock(return_value=wrong_page)
    with pytest.raises(_api.DbuActionError, match="forventede barn"):
        asyncio.run(client._select_child(child))


def _mock_coordinator():
    tree = ast.parse((_ROOT / "coordinator.py").read_text())
    klass = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "KampklarCoordinator")
    methods = [node for node in klass.body if isinstance(node, ast.AsyncFunctionDef)
               and node.name in {"async_set_signup", "_async_update_data"}]
    module = ast.parse("from __future__ import annotations")
    module.body.extend(methods)
    namespace = {"DbuActionError": _api.DbuActionError}
    exec(compile(module, str(_ROOT / "coordinator.py"), "exec"), namespace)
    klass = type("TestCoordinator", (), {node.name: namespace[node.name] for node in methods})
    coordinator = klass()
    coordinator._dbu_lock = asyncio.Lock()
    coordinator.client = types.SimpleNamespace(set_signup=AsyncMock())
    child = _api.Child(team_id=11, name="Emil Jensen", team_name="U12")
    coordinator.data = types.SimpleNamespace(
        children=[child], activities_by_child={child.key: [types.SimpleNamespace(activity_id=42)]}
    )
    return coordinator, child


def test_coordinator_resolves_child_from_activity():
    coordinator, child = _mock_coordinator()
    asyncio.run(coordinator.async_set_signup(42, attending=False, comment="Er syg"))
    coordinator.client.set_signup.assert_awaited_once_with(42, child=child, attending=False, comment="Er syg")


def test_shared_activity_requires_explicit_child_key():
    coordinator, child = _mock_coordinator()
    other = _api.Child(team_id=12, name="Ida Jensen", team_name="U9")
    coordinator.data.children.append(other)
    coordinator.data.activities_by_child[other.key] = [types.SimpleNamespace(activity_id=42)]
    with pytest.raises(_api.DbuActionError, match="entydigt"):
        asyncio.run(coordinator.async_set_signup(42, attending=False))
    coordinator.client.set_signup.assert_not_awaited()
    asyncio.run(coordinator.async_set_signup(42, attending=False, child_key=other.key))
    assert coordinator.client.set_signup.await_args.kwargs["child"] is other


def test_fetch_does_not_switch_child_during_signup():
    async def run():
        coordinator, _ = _mock_coordinator()
        started, finish = asyncio.Event(), asyncio.Event()
        async def write(*args, **kwargs):
            started.set()
            await finish.wait()
        coordinator.client.set_signup = AsyncMock(side_effect=write)
        coordinator._async_fetch_data = AsyncMock(return_value=coordinator.data)
        writing = asyncio.create_task(coordinator.async_set_signup(42, attending=False))
        await started.wait()
        fetching = asyncio.create_task(coordinator._async_update_data())
        await asyncio.sleep(0)
        coordinator._async_fetch_data.assert_not_awaited()
        finish.set()
        await writing
        await fetching
        coordinator._async_fetch_data.assert_awaited_once()
    asyncio.run(run())
