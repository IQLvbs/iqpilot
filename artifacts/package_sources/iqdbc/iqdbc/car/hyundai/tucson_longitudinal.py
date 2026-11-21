import numpy as np

# 4th-gen Tucson (gas, camera SCC). The car lets go about 1.25 s after the request turns positive, then gives about
# 1.6x aReqValue in 1st gear and 0.95-1.15x in 2nd; the gearbox shifts 1-2 at about 6.8 mph.
RELEASE_JERK = 2.5   # m/s^3 while aReqValue is still braking: lets go of the hold without a step
LAUNCH_JERK = 1.1    # m/s^3 up to the 1st-gear cap
EASE_JERK = 1.0      # m/s^3 from EASE_SPEED on
CAP_SPEED = [1.3, 2.7]  # m/s (3, 6 mph)
CAP_ACCEL = [1.2, 1.7]  # m/s^2: 1st-gear cap on aReqValue
EASE_SPEED = 2.45    # m/s (5.5 mph): from here the 2nd-gear cap applies, ahead of the 1-2 shift
CAP_2ND = 1.7        # m/s^2 at EASE_SPEED and through the shift
FULL_SPEED = 6.25    # m/s (14 mph): the cap has risen to the full request
START_SPEED = 0.3    # m/s: a launch starts at rest
END_SPEED = 6.7      # m/s (15 mph)
MAX_TIME = 8.0       # s
CAUGHT_UP = 0.05     # m/s^2
LAUNCH_DT = 0.02     # the SCC message is sent at 50 Hz

BUILD_SPEED = [0.0, 2.0, 5.0]  # m/s
BUILD_JERK = [0.8, 1.2, 2.5]   # m/s^3: how fast acceleration may build, opening with speed
CROSS_JERK = 1.5     # m/s^3 at most while the request is positive and the command is still braking
BRAKE_JERK = 2.0     # m/s^3: floor of the braking limit, opening by 2 per m/s^2 the command trails the request beyond TRAIL
TRAIL = 0.5          # m/s^2
ONSET_JERK = 1.3     # m/s^3: floor while the command keeps close to the request, so braking starts gently
ONSET_MIN_SPEED = 4.5   # m/s (10 mph): below this stops keep their firm finish
ONSET_MIN_ACCEL = -2.5  # m/s^2: a request this deep or deeper is urgent
JERK_MAX = 5.0


def jerk_limits(jerk: float, accel: float, accel_value_last: float, v_ego: float, fcw: bool, override: bool) -> tuple[float, float]:
  """(upper, lower) jerk limits for the SCC message, from the planner's jerk, the request and the last aReqValue sent."""
  if fcw or override:
    limit = JERK_MAX if fcw else 0.5
    return limit, limit
  build = float(np.interp(v_ego, BUILD_SPEED, BUILD_JERK))
  if accel < 0.0:
    jerk_u_min = CROSS_JERK
  elif accel_value_last < 0.0:
    jerk_u_min = min(build, CROSS_JERK)
  else:
    jerk_u_min = build
  jerk_u = min(max(jerk_u_min, jerk * 2.0), JERK_MAX)

  catch_up = BRAKE_JERK + 2.0 * (accel_value_last - accel - TRAIL)
  if v_ego >= ONSET_MIN_SPEED and ONSET_MIN_ACCEL < accel < 0.0:
    return jerk_u, float(np.clip(catch_up, ONSET_JERK, JERK_MAX))
  jerk_l_raw = np.clip(BRAKE_JERK + 2.0 * max(0.0, -accel - 2.8), BRAKE_JERK, JERK_MAX)
  jerk_l_mpc = np.clip(-jerk * 4.0, BRAKE_JERK, JERK_MAX)
  return jerk_u, max(jerk_l_raw, jerk_l_mpc, float(np.clip(catch_up, BRAKE_JERK, JERK_MAX)))


def first_gear_cap(v_ego: float) -> float:
  return float(np.interp(v_ego, CAP_SPEED, CAP_ACCEL))


def second_gear_cap(v_ego: float, accel: float) -> float:
  return float(np.interp(v_ego, [EASE_SPEED, FULL_SPEED], [min(accel, CAP_2ND), accel]))


class TucsonLaunch:
  """Shapes aReqValue from rest to END_SPEED so the push builds once, about as a driver's foot does.
  Never asks for more than the request and never touches braking."""

  def __init__(self):
    self.reset()

  def reset(self) -> None:
    self.active = False
    self.easing = False
    self.time = 0.0

  def update(self, accel: float, accel_value_last: float, v_ego: float, blocked: bool) -> tuple[float | None, float | None]:
    """One SCC frame: (upper jerk limit, cap on aReqValue) while a launch is shaped, else (None, None)."""
    if blocked or not accel > 0.0:
      self.reset()
      return None, None

    if not self.active:
      if not (accel_value_last < 0.0 and v_ego < START_SPEED):
        return None, None
      self.active = True
    else:
      self.time += LAUNCH_DT
      if v_ego > END_SPEED or self.time > MAX_TIME or (self.easing and accel_value_last >= accel - CAUGHT_UP):
        self.reset()
        return None, None

    if accel_value_last < 0.0:
      return RELEASE_JERK, first_gear_cap(v_ego)
    self.easing = self.easing or v_ego >= EASE_SPEED
    if self.easing:
      # the cap limits how far aReqValue rises, it never pulls it down
      return EASE_JERK, max(second_gear_cap(v_ego, accel), min(accel_value_last, accel))
    return LAUNCH_JERK, first_gear_cap(v_ego)

  def apply(self, hyundai_jerk, accel: float, accel_value_last: float, CS, CC, CC_IQ, stopping: bool) -> None:
    fcw = str(CC.hudControl.visualAlert) == 'fcw' or CC_IQ.longitudinalComfort.bypassJerkLimit
    engaged = CC.enabled and CS.out.cruiseState.available
    blocked = (not engaged or stopping or CC.cruiseControl.override or fcw or hyundai_jerk.comfort_active or CS.softHoldActive > 0
               or hyundai_jerk.carrot_cruise != 0)
    jerk_u, hyundai_jerk.launch_cap = self.update(accel, accel_value_last, CS.out.vEgo, bool(blocked))
    if jerk_u is not None:
      hyundai_jerk.jerk_u = jerk_u
