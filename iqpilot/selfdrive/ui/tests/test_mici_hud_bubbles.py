from types import SimpleNamespace

import pytest
import raylib_nb as rl

from iqpilot.selfdrive.ui.mici.onroad import hud_renderer
from iqpilot.selfdrive.ui.mici.onroad.hud_renderer import BOTTOM_DISPLAY_PARAM, BottomDisplay, read_bottom_display
from iqpilot.ui.mici.onroad import lead_stats


class FakeParams:
  def __init__(self, value):
    self.value = value

  def get(self, key, return_default=False):
    assert key == BOTTOM_DISPLAY_PARAM
    return self.value


@pytest.mark.parametrize('raw, expected', [
  (0, BottomDisplay.OFF), (1, BottomDisplay.TORQUE_BAR), (2, BottomDisplay.LEAD_STATS),
  (None, BottomDisplay.TORQUE_BAR), (7, BottomDisplay.TORQUE_BAR), ('bad', BottomDisplay.TORQUE_BAR),
])
def test_bottom_display_param_parsing(raw, expected):
  assert read_bottom_display(FakeParams(raw)) == expected


@pytest.mark.parametrize('mode, torque_calls, lead_calls', [
  (BottomDisplay.OFF, 0, 0), (BottomDisplay.TORQUE_BAR, 1, 0), (BottomDisplay.LEAD_STATS, 0, 1),
])
def test_bottom_display_draws_exactly_one_element(mocker, mode, torque_calls, lead_calls):
  hud = SimpleNamespace(_bottom_display=mode, _torque_bar=mocker.Mock(), _lead_stats=mocker.Mock(), is_cruise_set=False)
  hud_renderer.HudRenderer._render(hud, rl.Rectangle(0, 0, 536, 240))
  assert hud._torque_bar.render.call_count == torque_calls
  assert hud._lead_stats.render.call_count == lead_calls


def test_lead_stats_split_big_labels_into_value_and_unit(monkeypatch):
  monkeypatch.setattr(lead_stats, '_gap_label', lambda d, v: f"{d:.0f} ft")
  monkeypatch.setattr(lead_stats, '_pace_label', lambda d, v: f"{v:.0f} mph")
  monkeypatch.setattr(lead_stats, '_ttc_label', lambda d, v, ve: "---")
  assert lead_stats.lead_stats_parts(30.0, -2.0, 20.0) == [("30", "ft"), ("18", "mph"), ("---", "")]


def lead_state(monkeypatch, status, valid=True):
  lead = SimpleNamespace(status=status, dRel=30.0, vRel=0.0)

  class Messages(dict):
    pass
  sm = Messages(radarState=SimpleNamespace(leadOne=lead), carState=SimpleNamespace(vEgo=20.0))
  sm.valid = {'radarState': valid}
  monkeypatch.setattr(lead_stats, 'ui_state', SimpleNamespace(sm=sm, is_metric=True))
  monkeypatch.setattr(lead_stats, 'lead_stats_parts', lambda d, v, ve: [("30", "m")])


@pytest.mark.parametrize('status, valid, shown', [(True, True, True), (False, True, False), (True, False, False)])
def test_lead_stats_bubble_fades_with_the_lead(monkeypatch, status, valid, shown):
  lead_state(monkeypatch, status, valid)
  bubble = object.__new__(lead_stats.LeadStatsBubble)
  bubble._alpha = SimpleNamespace(x=0.0, update=lambda v: setattr(bubble._alpha, 'x', v))
  bubble._parts = []
  bubble._update_state()
  assert (bubble._alpha.x == 1.0) == shown
  assert (bubble._parts == [("30", "m")]) == shown
