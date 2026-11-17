"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from types import SimpleNamespace

import pytest

from iqpilot.cereal import custom
from iqpilot.common.atlas_alerts import Tags as ET
from iqpilot.selfdrive.selfdrived.iq_events import EVENTS_IQ
from iqpilot.selfdrive.selfdrived.selfdrived import SelfdriveD

NAMES = custom.IQOnroadEvent.EventName
TYPES = custom.IQNavState.ManeuverType


def events_for(maneuver_type, direction):
  nav = SimpleNamespace(active=True, shouldSendLaneChangeDesire=True, navLaneChangeDesireDirection=direction,
                        nextManeuverType=maneuver_type, nextManeuverValid=False, cameraValid=False)
  stub = SimpleNamespace(nav_exit_lane_change=True)
  stub.sm = type("SM", (), {"updated": {'iqNavState': True}, "__getitem__": lambda self, k: nav})()
  SelfdriveD._refresh_cached_nav_events(stub)
  return stub._cached_nav_event_names


@pytest.mark.parametrize("maneuver_type,direction,expected", [
  (TYPES.exit, 2, NAMES.navExitRight),
  (TYPES.exit, 1, NAMES.navExitLeft),
  (TYPES.fork, 2, NAMES.navExitRight),
  (TYPES.turn, 2, NAMES.navKeepRight),
  (TYPES.turn, 1, NAMES.navKeepLeft),
  (TYPES.roundabout, 2, NAMES.navKeepRight),
])
def test_lane_request_alert_matches_the_maneuver(maneuver_type, direction, expected):
  assert events_for(maneuver_type, direction) == (expected,)


def test_move_alerts_exist_and_do_not_claim_an_exit():
  for name in (NAMES.navKeepLeft, NAMES.navKeepRight):
    alert = EVENTS_IQ[name][ET.WARNING]
    assert "Exit" not in alert.alert_text_1
