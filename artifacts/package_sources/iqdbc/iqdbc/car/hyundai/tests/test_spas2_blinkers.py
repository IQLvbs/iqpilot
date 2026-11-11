import pytest

from iqdbc.can import CANPacker
from iqdbc.car import gen_empty_fingerprint, structs
from iqdbc.car.hyundai.interface import CarInterface
from iqdbc.car.hyundai.spas2 import BLINKERS_TIMEOUT, LEFT, NEUTRAL, RELEASE_FRAMES, RIGHT, SEND_EVERY
from iqdbc.car.hyundai.tests.test_spas2 import check_spas2
from iqdbc.car.hyundai.values import CAR, HyundaiFlags, HyundaiSafetyFlags
from iqdbc.car.structs import CarParams
from iqdbc.safety.tests.libsafety import libsafety_py
from iqpilot.common.params import Params

# Car-side bus of the 2024 Tucson SE (gas, HDA1, camera SCC) this was tried on: alt gear and button
# messages, BLINKERS, and no SPAS1/SPAS2. It fingerprints with flags 8206 and safety param 44.
TUCSON_ECAN = {0x40: 32, 0xA0: 24, 0x175: 24, 0x1AA: 16, 0x413: 8}
TUCSON_FLAGS = 8206
TUCSON_SAFETY_PARAM = 44

RELEASE_MESSAGES = RELEASE_FRAMES // SEND_EVERY
LAMP_HOLD_FRAMES = 50  # CarState keeps a blinker on this long after its lamp was last lit


def tucson_params(opt_in: bool, ecan: dict[int, int] = TUCSON_ECAN, cam: dict[int, int] | None = None, candidate=CAR.HYUNDAI_TUCSON_4TH_GEN):
  fingerprint = gen_empty_fingerprint()
  fingerprint[0] = dict(ecan)
  fingerprint[2] = dict(cam or {})
  Params().put("FingerPrints", str(fingerprint))
  Params().put_bool("HyundaiSpas2Blinkers", opt_in)
  return CarInterface.get_params(candidate, fingerprint, [], True, False, False)


@pytest.fixture(autouse=True)
def params_dir(tmp_path, monkeypatch):
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path / "params"))
  Params().put_bool("ControlsReady", True)


class Car:
  """The real Hyundai interface, parsers, CarState and CarController, one 100 Hz control frame at a time."""

  def __init__(self, CP, ready: bool = True):
    self.CI = CarInterface(CP, structs.IQCarParams())
    self.packer = CANPacker("hyundai_canfd_generated")
    self.CC = structs.CarControl.new_message()
    self.now = 0
    self.sent = []
    if ready:
      # CarState picks up BLINKERS once controls are ready and it has seen the message
      for _ in range(130):
        assert self.step() == []
      assert self.CI.CS.blinkers is not None

  def step(self, left=False, right=False, enabled=True, stalk=(False, False), lamps=(False, False), blinkers=True):
    """Returns the BLINKER_CONTROL values sent on this frame: [] or one value."""
    self.now += 10_000_000
    frames = []
    for cp in self.CI.can_parsers.values():
      for address in sorted(cp.addresses - {0x413}):
        frames.append(self.packer.make_can_msg(cp.message_states[address].name, cp.bus, {}))
    if blinkers:
      values = dict(zip(("LEFT_STALK", "RIGHT_STALK", "LEFT_LAMP", "RIGHT_LAMP"), (*stalk, *lamps), strict=True))
      frames.append(self.packer.make_can_msg("BLINKERS", 0, values))
    self.CI.update([(self.now, frames)])

    self.CC.leftBlinker, self.CC.rightBlinker, self.CC.enabled = left, right, enabled
    _, can_sends = self.CI.apply(self.CC.as_reader(), structs.IQCarControl(), self.now)
    spas = [message for message in can_sends if message[0] in (0x165, 0x16A)]
    assert all(address == 0x16A and bus == 0 and len(data) == 32 for address, data, bus in spas)
    self.sent += spas
    return [(data[16] >> 5) & 7 for _, data, _ in spas]

  def run(self, frames: int, **kwargs):
    return [control for _ in range(frames) for control in self.step(**kwargs)]


@pytest.fixture
def car():
  return Car(tucson_params(opt_in=True))


def test_off_unless_opted_in():
  CP = tucson_params(opt_in=False)
  assert CP.flags == TUCSON_FLAGS
  assert CP.safetyConfigs[-1].safetyParam == TUCSON_SAFETY_PARAM

  car = Car(CP)
  assert car.run(200, right=True) == []
  assert car.run(200, left=True) == []


def test_opt_in_on_the_tested_layout():
  CP = tucson_params(opt_in=True)
  assert CP.flags == TUCSON_FLAGS | HyundaiFlags.CANFD_SPAS2_BLINKERS
  assert CP.safetyConfigs[-1].safetyParam == TUCSON_SAFETY_PARAM | HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS


@pytest.mark.parametrize("layout", (
  dict(ecan=TUCSON_ECAN | {0x165: 24}),                             # has a parking ECU (SPAS1)
  dict(ecan=TUCSON_ECAN | {0x16A: 32}),                             # has a parking ECU (SPAS2)
  dict(ecan={a: n for a, n in TUCSON_ECAN.items() if a != 0x413}),  # no BLINKERS, so no way to see the driver
  dict(ecan=TUCSON_ECAN | {0x413: 16}),
  dict(ecan=TUCSON_ECAN | {0x105: 32}),                             # hybrid
  dict(ecan=TUCSON_ECAN | {0x1CF: 8}),                              # standard cruise buttons
  dict(ecan={a: n for a, n in TUCSON_ECAN.items() if a != 0x40}),   # other gear message
  dict(cam={0x50: 16}),                                             # HDA2
  dict(candidate=CAR.HYUNDAI_SANTA_CRUZ_1ST_GEN),
  dict(candidate=CAR.KIA_EV6),
), ids=("spas1", "spas2", "no-blinkers", "blinkers-size", "hybrid", "std-buttons", "other-gears", "hda2", "santa-cruz", "ev6"))
def test_opt_in_refused_on_other_layouts(layout):
  CP = tucson_params(opt_in=True, **layout)
  assert not CP.flags & HyundaiFlags.CANFD_SPAS2_BLINKERS
  assert not CP.safetyConfigs[-1].safetyParam & HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS


@pytest.mark.parametrize(("asked", "control"), ((dict(left=True), LEFT), (dict(right=True), RIGHT)))
def test_follows_the_request_then_releases_and_goes_silent(car, asked, control):
  # starts straight away, at 50 Hz, for as long as it is asked
  assert car.run(20, **asked) == [control] * 10
  assert car.run(3000, **asked) == [control] * 1500

  # request dropped: neutral for three seconds, then nothing
  assert car.run(RELEASE_FRAMES) == [NEUTRAL] * RELEASE_MESSAGES
  assert car.run(500) == []


def test_wire_format_rate_and_counter(car):
  sent_on = [frame for frame in range(40) if car.step(right=frame < 20)]
  assert sent_on == list(range(sent_on[0], 40, SEND_EVERY))
  assert len(car.sent) == 20
  for counter, message in enumerate(car.sent):
    check_spas2(message, counter, RIGHT if counter < 10 else NEUTRAL)


def test_own_blink_feedback_does_not_cancel(car):
  assert car.run(10, right=True) == [RIGHT] * 5
  # the car now reports the requested side as active: stalk bit set and the lamp flashing
  for _ in range(10):
    assert car.run(35, right=True, stalk=(False, True), lamps=(False, True)) + \
           car.run(35, right=True, stalk=(False, True), lamps=(False, False)) == [RIGHT] * 35
  # and the request still ends normally
  assert car.run(RELEASE_FRAMES, stalk=(False, True), lamps=(False, True)) == [NEUTRAL] * RELEASE_MESSAGES
  assert car.run(200) == []


@pytest.mark.parametrize("driver", (
  dict(stalk=(True, False)),                       # other side, stalk bit
  dict(lamps=(True, False)),                       # other side, lamp
  dict(stalk=(True, True), lamps=(True, True)),    # hazards
), ids=("stalk", "lamp", "hazards"))
def test_driver_on_the_other_side_wins_and_a_held_request_stays_off(car, driver):
  assert car.run(10, right=True) == [RIGHT] * 5
  assert car.run(RELEASE_FRAMES, right=True, **driver) == [NEUTRAL] * RELEASE_MESSAGES

  # still held after the driver is done: stays off
  assert car.run(500, right=True) == []

  # dropped and asked again: a new request
  assert car.run(2) == []
  assert car.run(10, right=True) == [RIGHT] * 5


@pytest.mark.parametrize("driver", (
  dict(stalk=(True, False)),
  dict(stalk=(False, True)),
  dict(lamps=(True, False)),
  dict(lamps=(False, True)),
  dict(stalk=(True, True), lamps=(True, True)),
), ids=("left-stalk", "right-stalk", "left-lamp", "right-lamp", "hazards"))
def test_does_not_start_while_the_driver_is_signalling(car, driver):
  assert car.run(200, right=True, **driver) == []

  # a lamp still counts as on until CarState's hold runs out
  if "lamps" in driver:
    assert car.run(LAMP_HOLD_FRAMES - 1, right=True) == []

  # the car is quiet and the request is still waiting: it starts
  assert car.run(20, right=True) == [RIGHT] * 10


def test_only_while_engaged(car):
  assert car.run(200, right=True, enabled=False) == []
  assert car.run(10, right=True) == [RIGHT] * 5

  # disengaging releases it, and it does not come back by itself
  assert car.run(RELEASE_FRAMES, right=True, enabled=False) == [NEUTRAL] * RELEASE_MESSAGES
  assert car.run(200, right=True, enabled=False) == []
  assert car.run(200, right=True) == []


def test_needs_to_see_the_blinkers_message(car):
  assert car.run(10, right=True) == [RIGHT] * 5

  # BLINKERS stops arriving: keep going until it counts as unknown, then release
  controls = car.run(BLINKERS_TIMEOUT + RELEASE_FRAMES, right=True, blinkers=False)
  assert controls == [RIGHT] * ((BLINKERS_TIMEOUT - 1) // SEND_EVERY) + [NEUTRAL] * (len(controls) - (BLINKERS_TIMEOUT - 1) // SEND_EVERY)
  assert abs(controls.count(NEUTRAL) - RELEASE_MESSAGES) <= 1

  # no new request while it is unknown
  assert car.run(2, blinkers=False) == []
  assert car.run(200, right=True, blinkers=False) == []

  # back again
  assert car.run(2) == []
  assert car.run(10, right=True) == [RIGHT] * 5


def test_never_starts_before_blinkers_is_registered():
  car = Car(tucson_params(opt_in=True), ready=False)
  Params().put_bool("ControlsReady", False)
  assert car.run(300, right=True) == []
  assert car.CI.CS.blinkers is None


def test_one_direction_at_a_time(car):
  # both together is not a request
  assert car.run(200, left=True, right=True) == []

  assert car.run(2) == []
  assert car.run(10, right=True) == [RIGHT] * 5
  # straight to the other side: release, and no start until the request has dropped
  assert car.run(100, left=True) == [NEUTRAL] * 50
  assert car.run(2) == [NEUTRAL]
  controls = car.run(20, left=True)
  assert controls == [LEFT] * 10

  # both together while active ends it too
  assert set(car.run(20, left=True, right=True)) == {NEUTRAL}


@pytest.mark.parametrize("asked", (dict(left=True), dict(right=True)))
def test_frames_pass_the_panda_safety(car, asked):
  safety = libsafety_py.libsafety
  safety_param = car.CI.CP.safetyConfigs[-1].safetyParam
  assert safety_param == TUCSON_SAFETY_PARAM | HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS
  assert safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, safety_param) == 0
  safety.init_tests()

  def allowed(messages):
    return [bool(safety.safety_tx_hook(libsafety_py.make_CANPacket(address, bus, data))) for address, data, bus in messages]

  # engaged: the request and its release
  car.run(50, **asked)
  car.run(RELEASE_FRAMES)
  safety.set_controls_allowed(True)
  assert len(car.sent) == 25 + RELEASE_MESSAGES
  assert all(allowed(car.sent))

  # disengaged mid-request: the direction frames are refused, the release is not
  safety.set_controls_allowed(False)
  assert allowed(car.sent) == [False] * 25 + [True] * RELEASE_MESSAGES
