from typing import NamedTuple

SPEED_COMFORT_FINGERPRINTS = frozenset({"HYUNDAI_TUCSON_4TH_GEN"})


class CruiseShape(NamedTuple):
  gain_above: float  # 1/s: acceleration asked per m/s above the target (stock 1.0)
  gain_below: float  # 1/s: per m/s below it (stock 1.0)
  min_accel: float   # m/s^2
  jerk_brake: float  # m/s^3: how fast braking may build


RETURN_SHAPE = CruiseShape(gain_above=0.3, gain_below=0.5, min_accel=-0.8, jerk_brake=0.5)  # back down to the set speed
BEND_SHAPE = CruiseShape(gain_above=0.5, gain_below=0.5, min_accel=-0.8, jerk_brake=0.6)    # down to the camera's bend target


def uses_speed_comfort(cp) -> bool:
  return str(cp.carFingerprint) in SPEED_COMFORT_FINGERPRINTS


def cruise_shape(source_is_nav: bool, nav_provider, forced: bool) -> CruiseShape | None:
  if forced:
    return None
  if source_is_nav:
    return BEND_SHAPE if str(nav_provider) == "vision" else None
  return RETURN_SHAPE
