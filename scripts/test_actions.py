"""Små unit tests af ASP.NET-postbacken uden en Home Assistant-installation."""

from __future__ import annotations

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
