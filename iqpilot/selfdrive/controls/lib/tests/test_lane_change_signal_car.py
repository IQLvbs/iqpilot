"""A tapped signal held through a lane change, end to end: LaneChangeSignal (as controlsd runs it) -> CarControl -> the
real Hyundai interface, CarState and CarController (Spas2Blinkers) -> SPAS2 frames -> the panda safety.

The car is emulated only where it has to be: its lamps blink for the driver's tap (three flashes), and keep blinking
while SPAS2 asks for that side; the lane change logic's states are given as they appear in the owner's logs.
"""
import pytest

from iqpilot.cereal import log
from iqpilot.selfdrive.controls.lib.lane_change_signal import WAIT_MAX, LaneChangeSignal
from iqdbc.car.hyundai.spas2 import LEFT, NEUTRAL, RELEASE_FRAMES, RIGHT, SEND_EVERY
from iqdbc.car.hyundai.tests.test_spas2_blinkers import Car, params_dir, tucson_params  # noqa: F401  (params_dir is autouse)
from iqdbc.car.hyundai.values import HyundaiSafetyFlags
from iqdbc.car.structs import CarParams
from iqdbc.safety.tests.libsafety import libsafety_py

S = log.LaneChangeState
D = log.LaneChangeDirection
HALF = 35                 # frames: the lamps' half period, 0.35 s
TAP = 6 * HALF            # the car's own one-touch blink: three flashes, 2.1 s
RELEASE_MESSAGES = RELEASE_FRAMES // SEND_EVERY
SPEED = 12.0              # m/s, 27 mph


class Road:
  def __init__(self):
    self.car = Car(tucson_params(opt_in=True))
    self.lcs = LaneChangeSignal(True)
    self.req = (False, False)
    self.frame = 0
    self.tap_side, self.tap_until = None, -1
    self.spas_side = None
    self.blink_start = None
    self.controls = []           # (frame, BLINKER_CONTROL) for every SPAS2 frame sent

  def tap(self, side):
    self.tap_side, self.tap_until = side, self.frame + TAP

  def step(self, state=S.off, direction=D.none, pressed=False, torque=0.0):
    side = self.tap_side if self.frame < self.tap_until else self.spas_side
    if side is None:
      self.blink_start = None
    elif self.blink_start is None:
      self.blink_start = self.frame
    lit = side is not None and ((self.frame - self.blink_start) // HALF) % 2 == 0
    lamps = (lit and side == "left", lit and side == "right")
    stalk = (side == "left", side == "right")        # on this car the stalk bits follow the blink
    sent = self.car.step(left=self.req[0], right=self.req[1], lamps=lamps, stalk=stalk)
    for control in sent:
      self.controls.append((self.frame, control))
      self.spas_side = {LEFT: "left", RIGHT: "right"}.get(control)
    cs = self.car.CI.CS.out
    self.req = self.lcs.update(state, direction, cs.leftBlinker, cs.rightBlinker, SPEED, True, pressed, torque, False, False)
    self.frame += 1

  def run(self, frames, **kw):
    for _ in range(frames):
      self.step(**kw)


@pytest.mark.parametrize("side", ("left", "right"))
def test_a_tap_is_held_through_a_late_nudge_and_the_lane_change_then_released(side):
  road = Road()
  road.run(50)
  assert road.controls == []
  want = LEFT if side == "left" else RIGHT
  direction = D.left if side == "left" else D.right

  t_tap = road.frame
  road.tap(side)
  road.run(6)                                           # the lane change logic notices in about 0.06 s
  road.run(260 - 6, state=S.preLaneChange, direction=direction)          # nudge at 2.6 s: after the tap's own flashes
  road.run(390, state=S.laneChangeStarting, direction=direction)
  t_finish = road.frame
  road.run(100, state=S.laneChangeFinishing, direction=direction)
  road.run(RELEASE_FRAMES + 200)

  sent = road.controls
  frames_dir = [f for f, c in sent if c == want]
  assert frames_dir[0] - t_tap <= 3                     # held from the start of the tap
  assert t_finish - 3 <= frames_dir[-1] <= t_finish + 3  # until the car is in its new lane (finishing starts)
  # every message while held is that side, at 50 Hz, with no gap
  held = [c for f, c in sent if f <= frames_dir[-1]]
  assert held == [want] * len(held) and len(held) >= (t_finish - t_tap) // SEND_EVERY - 2
  # then neutral for the release, then silence
  after = [c for f, c in sent if f > frames_dir[-1]]
  assert after == [NEUTRAL] * RELEASE_MESSAGES
  assert sent[-1][0] < road.frame - 100

  # every frame passes the panda safety with steering engaged
  safety = libsafety_py.libsafety
  safety_param = road.car.CI.CP.safetyConfigs[-1].safetyParam
  assert safety_param & HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS
  assert safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, safety_param) == 0
  safety.init_tests()
  try:
    safety.set_controls_allowed(True)
    assert all(safety.safety_tx_hook(libsafety_py.make_CANPacket(address, bus, data)) for address, data, bus in road.car.sent)
  finally:
    safety.set_controls_allowed(False)


def test_a_tap_that_is_not_a_lane_change_is_released_after_the_wait():
  road = Road()
  road.run(50)
  road.tap("right")
  road.run(6)
  road.run(int(WAIT_MAX * 100) + 150, state=S.preLaneChange, direction=D.right)   # no nudge
  frames_right = [f for f, c in road.controls if c == RIGHT]
  assert frames_right and (frames_right[-1] - frames_right[0]) * 0.01 == pytest.approx(WAIT_MAX, abs=0.2)


def test_the_driver_signalling_the_other_way_ends_it_and_keeps_their_own_signal():
  road = Road()
  road.run(50)
  road.tap("right")
  road.run(150, state=S.preLaneChange, direction=D.right)
  assert road.controls[-1][1] == RIGHT
  road.tap("left")                                       # the driver taps the other way
  road.run(400, state=S.preLaneChange, direction=D.left)
  after = [c for f, c in road.controls if f >= road.frame - 400]
  assert LEFT not in after and RIGHT not in after[3:]    # the right hold ends; the left tap stays the car's own blink
