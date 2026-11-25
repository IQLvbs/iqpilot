import pytest

from iqpilot.cereal import log
from iqpilot.selfdrive.selfdrived.selfdrived import rx_checks_failed_while_powered


def panda_state(rx_invalid, ignition_line, ignition_can=False):
  ps = log.PandaState.new_message()
  ps.safetyRxChecksInvalid = rx_invalid
  ps.ignitionLine = ignition_line
  ps.ignitionCan = ignition_can
  return ps


@pytest.mark.parametrize("rx_invalid,line,can,expected", [
  (True, True, False, True),
  (True, False, True, True),
  (True, False, False, False),
  (False, True, False, False),
  (False, False, False, False),
])
def test_rx_check_failure_only_counts_while_the_car_is_powered(rx_invalid, line, can, expected):
  assert rx_checks_failed_while_powered(panda_state(rx_invalid, line, can)) is expected


@pytest.mark.parametrize("exception", [
  None, "powered", "moving", "drive", "invalid_can", "enabled", "lat", "long", "control_enabled",
  "ignition_line", "ignition_can", "second_panda_powered", "controls_allowed", "wrong_mode", "stale",
])
def test_expected_shutdown_mode(exception):
  from types import SimpleNamespace
  from iqpilot.cereal import car
  from iqpilot.selfdrive.selfdrived.selfdrived import expected_shutdown_mode

  ps = panda_state(False, exception == "ignition_line", exception == "ignition_can")
  ps.safetyModel = "silent" if exception == "wrong_mode" else "noOutput"
  ps.controlsAllowed = exception == "controls_allowed"
  cs = car.CarState.new_message(canValid=exception != "invalid_can", standstill=exception != "moving",
                                gearShifter="drive" if exception == "drive" else "park")
  class Signals(dict):
    def all_checks(self, services):
      return exception != "stale"

  sm = Signals(deviceState=SimpleNamespace(started=exception == "powered"),
               carControl=car.CarControl.new_message(enabled=exception == "control_enabled",
                                                     latActive=exception == "lat", longActive=exception == "long"),
               pandaStates=[ps, panda_state(False, exception == "second_panda_powered")])
  assert expected_shutdown_mode(ps, cs, sm, exception == "enabled") is (exception is None)
