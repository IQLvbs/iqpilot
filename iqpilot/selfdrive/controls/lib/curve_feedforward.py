import math

ENTER_LAT_ACCEL = 0.6  # m/s^2: a curve starts at or above this
LEAVE_LAT_ACCEL = 0.3  # m/s^2: and ends once the request has settled at or below this
LEAVE_RATE = 0.15      # m/s^3: "settled"
LEAVE_HOLD_S = 0.5
ENTER_TAU_S = 0.25
LEAVE_TAU_S = 1.0
RATE_TAU_S = 0.3
WEIGHT_FLOOR = 1e-3


class CurveWeight:
  """0 on straights, 1 in a curve, moving between the two without a step. An S-bend is one curve."""

  def __init__(self, dt: float):
    self.dt = dt
    self.reset()

  def reset(self) -> None:
    self.in_curve = False
    self.weight = 0.0
    self._last_request: float | None = None
    self._rate = 0.0
    self._steady_s = 0.0

  def update(self, request: float) -> float:
    if not math.isfinite(request):
      return self.weight
    change = 0.0 if self._last_request is None else request - self._last_request
    self._last_request = request
    self._rate += (change / self.dt - self._rate) * self.dt / RATE_TAU_S

    if abs(request) >= ENTER_LAT_ACCEL:
      self.in_curve = True
      self._steady_s = 0.0
    elif self.in_curve:
      steady = abs(request) <= LEAVE_LAT_ACCEL and abs(self._rate) <= LEAVE_RATE
      self._steady_s = self._steady_s + self.dt if steady else 0.0
      self.in_curve = self._steady_s < LEAVE_HOLD_S

    target, tau = (1.0, ENTER_TAU_S) if self.in_curve else (0.0, LEAVE_TAU_S)
    self.weight += (target - self.weight) * self.dt / tau
    if not self.in_curve and self.weight < WEIGHT_FLOOR:
      self.weight = 0.0
    return self.weight
