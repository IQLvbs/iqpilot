"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""

import pytest

from iqdbc.car.hyundai.values import HyundaiSafetyFlags
from iqdbc.car.structs import CarParams
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
