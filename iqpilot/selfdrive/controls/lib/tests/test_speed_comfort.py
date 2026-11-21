from iqpilot.selfdrive.controls.lib.speed_comfort import BEND_SHAPE, RETURN_SHAPE, cruise_shape


def test_shapes_are_gentler_than_stock_and_only_for_the_right_targets():
  assert cruise_shape(False, "none", False) is RETURN_SHAPE
  assert cruise_shape(True, "vision", False) is BEND_SHAPE
  for provider in ("none", "route", "mapbox", "offlineOsm", "camera"):
    assert cruise_shape(True, provider, False) is None        # a turn on a route must still be reached in time
  assert cruise_shape(False, "none", True) is None            # forced deceleration keeps the stock braking
  assert cruise_shape(True, "vision", True) is None
  for shape in (RETURN_SHAPE, BEND_SHAPE):
    assert -1.2 < shape.min_accel < 0.0 and 0.0 < shape.gain_above < 1.0 and 0.0 < shape.gain_below <= 1.0 and 0.0 < shape.jerk_brake < 0.8
