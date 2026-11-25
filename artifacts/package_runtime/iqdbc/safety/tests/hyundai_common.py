from collections.abc import Callable

import iqdbc.safety.tests.common as common
from iqdbc.safety.tests.libsafety import libsafety_py
from iqdbc.safety.tests.common import make_msg


class Buttons:
  NONE = 0
  RESUME = 1
  SET = 2
  CANCEL = 4


PREV_BUTTON_SAMPLES = 8
ENABLE_BUTTONS = (Buttons.RESUME, Buttons.SET, Buttons.CANCEL)


class HyundaiButtonBase(common.CarSafetyTest):
  DBC: str
  SAFETY_MODEL: int
  SAFETY_PARAM = 0
  SAFETY_PARAM_IQ = 0

  BUTTONS_TX_BUS = 0  # tx on this bus, rx on 0
  SCC_BUS = 0  # rx on this bus

  _button_msg: Callable[..., libsafety_py.CANPacket]

  def setUp(self):
    self.packer = common.CANPackerSafety(self.DBC)
    self.safety = libsafety_py.libsafety
    self.safety.set_current_safety_param_iq(self.SAFETY_PARAM_IQ)
    self.assertEqual(0, self.safety.set_safety_hooks(self.SAFETY_MODEL, self.SAFETY_PARAM))
    self.safety.init_tests()

  HAS_AOL_BUTTON = False

  @property
  def aol_main_supported(self):
    param = int(self.SAFETY_PARAM)
    return not (param & 8 and not param & 4)

  def _lkas_button_msg(self, enabled):
    return self.packer.make_can_msg_safety("BCM_PO_11", self.PT_BUS, {"LDA_BTN": enabled})

  def _acc_state_msg(self, enabled):
    # the main button toggles ACC main, so a state change needs a released-then-pressed edge
    if bool(self.safety.get_acc_main_on()) == bool(enabled):
      return self._button_msg(0, main_button=0)
    self._rx(self._button_msg(0, main_button=0))
    return self._button_msg(0, main_button=1)

  def test_enable_control_allowed_with_aol_button(self):
    if self.HAS_AOL_BUTTON:
      super().test_enable_control_allowed_with_aol_button()

  def test_enable_control_allowed_with_aol_button_and_disable_with_main_cruise(self):
    if self.HAS_AOL_BUTTON and self.aol_main_supported:
      super().test_enable_control_allowed_with_aol_button_and_disable_with_main_cruise()

  def test_engage_with_brake_pressed_0_aol_button(self):
    if self.HAS_AOL_BUTTON:
      super().test_engage_with_brake_pressed_0_aol_button()

  def test_engage_with_brake_pressed_1_acc_main_on(self):
    if self.aol_main_supported:
      super().test_engage_with_brake_pressed_1_acc_main_on()

  def test_enable_control_allowed_with_manual_acc_main_on_state(self):
    if self.aol_main_supported:
      super().test_enable_control_allowed_with_manual_acc_main_on_state()

  def test_button_sends(self):
    """
      Only RES and CANCEL buttons are allowed
      - RES allowed while controls allowed
      - CANCEL allowed while cruise is enabled
    """
    self.safety.set_controls_allowed(0)
    self.assertFalse(self._tx(self._button_msg(Buttons.RESUME, bus=self.BUTTONS_TX_BUS)))
    self.assertFalse(self._tx(self._button_msg(Buttons.SET, bus=self.BUTTONS_TX_BUS)))

    self.safety.set_controls_allowed(1)
    self.assertTrue(self._tx(self._button_msg(Buttons.RESUME, bus=self.BUTTONS_TX_BUS)))
    self.assertFalse(self._tx(self._button_msg(Buttons.SET, bus=self.BUTTONS_TX_BUS)))

    for enabled in (True, False):
      self._rx(self._pcm_status_msg(enabled))
      self.assertEqual(enabled, self._tx(self._button_msg(Buttons.CANCEL, bus=self.BUTTONS_TX_BUS)))

  def test_enable_control_allowed_from_cruise(self):
    """
      Hyundai non-longitudinal only enables on PCM rising edge and recent button press. Tests PCM enabling with:
      - disallowed: No buttons
      - disallowed: Buttons that don't enable cruise
      - allowed: Buttons that do enable cruise
      - allowed: Main button with all above combinations
    """
    for main_button in (0, 1):
      for btn in range(8):
        for _ in range(PREV_BUTTON_SAMPLES):  # reset
          self._rx(self._button_msg(Buttons.NONE))

        self._rx(self._pcm_status_msg(False))
        self.assertFalse(self.safety.get_controls_allowed())
        self._rx(self._button_msg(btn, main_button=main_button))
        self._rx(self._pcm_status_msg(True))
        controls_allowed = btn in ENABLE_BUTTONS or main_button
        self.assertEqual(controls_allowed, self.safety.get_controls_allowed())
        self.safety.set_controls_allowed(False)
        self._rx(self._pcm_status_msg(True))
        self.assertFalse(self.safety.get_controls_allowed())

  def test_sampling_cruise_buttons(self):
    """
      Test that we allow controls on recent button press, but not as button leaves sliding window
    """
    self._rx(self._button_msg(Buttons.SET))
    for i in range(2 * PREV_BUTTON_SAMPLES):
      self._rx(self._pcm_status_msg(False))
      self.assertFalse(self.safety.get_controls_allowed())
      self._rx(self._pcm_status_msg(True))
      controls_allowed = i < PREV_BUTTON_SAMPLES
      self.assertEqual(controls_allowed, self.safety.get_controls_allowed())
      self._rx(self._button_msg(Buttons.NONE))


class HyundaiLongitudinalBase(common.LongitudinalAccelSafetyTest):

  DISABLED_ECU_UDS_MSG: tuple[int, int]
  DISABLED_ECU_ACTUATION_MSG: tuple[int, int]

  _button_msg: Callable[..., libsafety_py.CANPacket]

  # override these tests from CarSafetyTest, hyundai longitudinal uses button enable
  def test_disable_control_allowed_from_cruise(self):
    pass

  def test_enable_control_allowed_from_cruise(self):
    pass

  def test_sampling_cruise_buttons(self):
    pass

  def test_cruise_engaged_prev(self):
    pass

  def test_button_sends(self):
    pass

  def _pcm_status_msg(self, enable):
    raise Exception

  def _accel_msg(self, accel, aeb_req=False, aeb_decel=0):
    raise NotImplementedError

  def test_set_resume_buttons(self):
    """
      SET and RESUME enter controls allowed on their falling edge.
    """
    for btn_prev in range(8):
      for btn_cur in range(8):
        self._rx(self._button_msg(Buttons.NONE))
        self.safety.set_controls_allowed(0)
        for _ in range(10):
          self._rx(self._button_msg(btn_prev))
          self.assertFalse(self.safety.get_controls_allowed())

        # should enter controls allowed on falling edge and not transitioning to cancel
        should_enable = btn_cur != btn_prev and \
                        btn_cur != Buttons.CANCEL and \
                        btn_prev in (Buttons.RESUME, Buttons.SET)

        self._rx(self._button_msg(btn_cur))
        self.assertEqual(should_enable, self.safety.get_controls_allowed())

  def test_cancel_button(self):
    self.safety.set_controls_allowed(1)
    self._rx(self._button_msg(Buttons.CANCEL))
    self.assertFalse(self.safety.get_controls_allowed())

  def test_tester_present_allowed(self, ecu_disable: bool = True):
    """
      Ensure tester present diagnostic message is allowed to keep ECU knocked out
      for longitudinal control.
    """

    addr, bus = self.DISABLED_ECU_UDS_MSG
    for should_tx, msg in ((True, b"\x02\x3E\x80\x00\x00\x00\x00\x00"),
                           (False, b"\x03\xAA\xAA\x00\x00\x00\x00\x00")):
      tester_present = libsafety_py.make_CANPacket(addr, bus, msg)
      self.assertEqual(should_tx and ecu_disable, self._tx(tester_present))

  def test_disabled_ecu_alive(self):
    """
      If the ECU knockout failed, make sure the relay malfunction is shown
    """

    addr, bus = self.DISABLED_ECU_ACTUATION_MSG
    self.assertFalse(self.safety.get_relay_malfunction())
    self._rx(make_msg(bus, addr, 8))
    self.assertTrue(self.safety.get_relay_malfunction())


def packet(addr: int, bus: int, length: int, updates: dict[int, int] | None = None):
  data = bytearray(length)
  for index, value in (updates or {}).items():
    data[index] = value
  return libsafety_py.make_CANPacket(addr, bus, data)


def classic_steer(torque: int, request: bool = True):
  value = torque + 1024
  word = (value << 16) | (int(request) << 27)
  return packet(0x340, 0, 8, {i: (word >> (8 * i)) & 0xFF for i in range(4)})


def canfd_steer(addr: int, length: int, torque: int, request: bool = True):
  value = torque + 1024
  return packet(addr, 0, length, {
    5: (value & 0x7F) << 1,
    6: ((value >> 7) & 0xF) | (int(request) << 4),
  })


def classic_accel(accel: int, *, aeb_decel: int = 0, aeb_request: bool = False, aeb_stop_request: bool = False):
  value = accel + 1023
  return packet(0x421, 0, 8, {
    2: aeb_decel,
    3: value & 0xFF,
    4: ((value >> 8) & 0x7) | ((value & 0x7) << 5),
    5: (value >> 3) & 0xFF,
    6: (int(aeb_request) << 6) | (int(aeb_stop_request) << 7),
  })


def canfd_accel(accel: int, *, acc_mode: int = 0, bus: int = 0):
  value = accel + 1023
  return packet(0x1A0, bus, 32, {
    8: (acc_mode & 0x7) << 4,
    16: value & 0xFF,
    17: ((value >> 8) & 0x7) | ((value & 0xF) << 4),
    18: (value >> 4) & 0xFF,
  })


TESTER_PRESENT = bytes.fromhex("023e800000000000")
