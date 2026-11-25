"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""

import pytest

from iqdbc.car.hyundai.values import HyundaiSafetyFlags
from iqdbc.car.structs import CarParams
from iqdbc.safety.tests.common import CANPackerSafety
from iqdbc.safety.tests.hyundai_common import classic_steer, packet
from iqdbc.safety.tests.libsafety import libsafety_py


@pytest.fixture
def safety():
  return libsafety_py.libsafety


HAS_LDA_BUTTON = 64
CLU11_SET = 2
CLU11_MAIN = 8
LFA_PRESSED = 0x10

SAFETY_MODES = (CarParams.SafetyModel.hyundai, CarParams.SafetyModel.hyundaiLegacy)
CAMERA_SCC_MODES = (CarParams.SafetyModel.hyundai,)
LFA_CONFIGURATIONS = (
  HyundaiSafetyFlags.EV_GAS | HyundaiSafetyFlags.CAMERA_SCC | HyundaiSafetyFlags.ALT_LIMITS,
  HyundaiSafetyFlags.EV_GAS | HyundaiSafetyFlags.CAMERA_SCC | HyundaiSafetyFlags.ALT_LIMITS | HyundaiSafetyFlags.LONG,
  HyundaiSafetyFlags.EV_GAS | HyundaiSafetyFlags.LONG,
  HyundaiSafetyFlags.EV_GAS,
)


@pytest.fixture
def aol_safety(safety):
  yield safety
  safety.set_aol_button_press(-1)
  safety.set_controls_allowed_lat(False)
  safety.set_controls_requested_lat(False)
  safety.set_acc_main_on(False)
  safety.set_aol_params(False, False, False)
  safety.set_heartbeat_engaged_aol(True)
  safety.set_current_safety_param_iq(0)


def start_aol(safety, mode, param, param_iq=0):
  safety.set_current_safety_param_iq(param_iq)
  assert safety.set_safety_hooks(mode, param) == 0
  safety.init_tests()
  safety.set_aol_params(True, False, False)


class Clu11:
  def __init__(self):
    self.counter = 0

  def message(self, button=0, main=False):
    self.counter = (self.counter + 1) % 16
    return packet(0x4F1, 0, 4, {0: button | (CLU11_MAIN if main else 0), 3: self.counter << 4})


@pytest.mark.parametrize("mode", CAMERA_SCC_MODES)
def test_camera_scc_longitudinal_cluster_buttons_reach_safety(aol_safety, mode):
  safety = aol_safety
  param = (HyundaiSafetyFlags.EV_GAS | HyundaiSafetyFlags.CAMERA_SCC | HyundaiSafetyFlags.ALT_LIMITS |
           HyundaiSafetyFlags.LONG)
  start_aol(safety, mode, param)
  cluster = Clu11()

  safety.safety_rx_hook(cluster.message())
  assert not safety.get_acc_main_on()
  assert not safety.get_controls_allowed_lat()

  safety.safety_rx_hook(cluster.message(main=True))
  safety.safety_rx_hook(cluster.message())
  assert safety.get_acc_main_on()
  assert safety.get_controls_allowed_lat()

  assert not safety.get_controls_allowed()
  safety.safety_rx_hook(cluster.message(button=CLU11_SET))
  safety.safety_rx_hook(cluster.message())
  assert safety.get_controls_allowed()


@pytest.mark.parametrize("mode", CAMERA_SCC_MODES)
def test_camera_scc_without_longitudinal_does_not_track_cluster_buttons(aol_safety, mode):
  safety = aol_safety
  param = HyundaiSafetyFlags.EV_GAS | HyundaiSafetyFlags.CAMERA_SCC | HyundaiSafetyFlags.ALT_LIMITS
  start_aol(safety, mode, param)
  cluster = Clu11()

  safety.safety_rx_hook(cluster.message(main=True))
  safety.safety_rx_hook(cluster.message())
  assert not safety.get_acc_main_on()
  assert not safety.get_controls_allowed_lat()


@pytest.mark.parametrize("mode", SAFETY_MODES)
@pytest.mark.parametrize("param", LFA_CONFIGURATIONS)
def test_lfa_button_requests_always_on_lateral(aol_safety, mode, param):
  safety = aol_safety
  start_aol(safety, mode, param, HAS_LDA_BUTTON)

  assert not safety.get_controls_allowed_lat()
  safety.safety_rx_hook(packet(0x391, 0, 8, {0: LFA_PRESSED}))
  safety.safety_rx_hook(packet(0x391, 0, 8))
  assert safety.get_controls_allowed_lat()


@pytest.mark.parametrize("mode", SAFETY_MODES)
@pytest.mark.parametrize("param", LFA_CONFIGURATIONS)
def test_lfa_button_is_ignored_without_the_lda_flag(aol_safety, mode, param):
  safety = aol_safety
  start_aol(safety, mode, param)

  safety.safety_rx_hook(packet(0x391, 0, 8, {0: LFA_PRESSED}))
  safety.safety_rx_hook(packet(0x391, 0, 8))
  assert not safety.get_controls_allowed_lat()


@pytest.mark.parametrize("mode", SAFETY_MODES)
def test_lfa_latched_lateral_allows_steering_without_controls(aol_safety, mode):
  safety = aol_safety
  param = HyundaiSafetyFlags.EV_GAS | HyundaiSafetyFlags.CAMERA_SCC | HyundaiSafetyFlags.ALT_LIMITS
  start_aol(safety, mode, param, HAS_LDA_BUTTON)

  assert not safety.safety_tx_hook(classic_steer(2))
  safety.safety_rx_hook(packet(0x391, 0, 8, {0: LFA_PRESSED}))
  safety.safety_rx_hook(packet(0x391, 0, 8))
  assert not safety.get_controls_allowed()
  assert safety.safety_tx_hook(classic_steer(2))


def test_ev6_lane_button_controls_lateral_independently_of_main(aol_safety):
  safety = aol_safety
  param = HyundaiSafetyFlags.EV_GAS | HyundaiSafetyFlags.CANFD_LKA_STEER_MSG | HyundaiSafetyFlags.LONG
  start_aol(safety, CarParams.SafetyModel.hyundaiCanfd, param, HAS_LDA_BUTTON)
  safety.set_heartbeat_engaged_aol(False)
  packer = CANPackerSafety("hyundai_canfd_generated")

  def buttons(lda=False, main=False, cruise=0):
    values = {"LDA_BTN": int(lda), "ADAPTIVE_CRUISE_MAIN_BTN": int(main), "CRUISE_BUTTONS": cruise}
    assert safety.safety_rx_hook(packer.make_can_msg_safety("CRUISE_BUTTONS", 1, values))

  def torque_allowed():
    return safety.safety_tx_hook(packer.make_can_msg_safety("LFA", 1, {"StrTqReqVal": 2, "ActToiSta": 1}))

  buttons(lda=True)
  assert not torque_allowed()
  buttons()
  buttons(main=True)
  assert not torque_allowed()
  buttons()
  buttons(lda=True)
  buttons(lda=True)
  assert torque_allowed()
  buttons()
  buttons(main=True)
  assert torque_allowed()
  assert not safety.get_controls_allowed()
  buttons()
  buttons(lda=True)
  buttons(lda=True)
  assert not torque_allowed()
  buttons()
  buttons(cruise=2)
  buttons()
  assert safety.get_controls_allowed()
  assert torque_allowed()
  buttons(lda=True)
  assert not safety.get_controls_allowed()
  assert not torque_allowed()
  buttons()
  buttons(lda=True)
  assert torque_allowed()
  safety.set_heartbeat_engaged_aol(False)
  for _ in range(3):
    safety.aol_heartbeat_engaged_check()
  assert not torque_allowed()


@pytest.mark.parametrize('param,pt_bus,scc_bus', [(0, 0, 0), (HyundaiSafetyFlags.CAMERA_SCC, 0, 2),
                                                (HyundaiSafetyFlags.CANFD_LKA_STEER_MSG, 1, 1)])
def test_factory_canfd_main_follows_scc(aol_safety, param, pt_bus, scc_bus):
  start_aol(aol_safety, CarParams.SafetyModel.hyundaiCanfd, param)
  packer = CANPackerSafety("hyundai_canfd_generated")

  for enabled in (False, True, False):
    aol_safety.safety_rx_hook(packer.make_can_msg_safety("SCC_CONTROL", scc_bus, {"MainMode_ACC": int(enabled)}))
    for pressed in (True, False):
      aol_safety.safety_rx_hook(packer.make_can_msg_safety("CRUISE_BUTTONS", pt_bus, {"ADAPTIVE_CRUISE_MAIN_BTN": int(pressed)}))
      assert bool(aol_safety.get_acc_main_on()) == enabled
      assert bool(aol_safety.get_controls_allowed_lat()) == enabled
