"""Små unit tests af ASP.NET-postbacken uden en Home Assistant-installation."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
from pathlib import Path
import sys
import types

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
