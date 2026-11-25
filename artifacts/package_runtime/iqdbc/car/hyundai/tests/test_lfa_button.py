"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""

from iqdbc.can import CANPacker
from iqdbc.car import Bus, gen_empty_fingerprint, structs
from iqdbc.car.hyundai.hyundaicanfd import CanBus
from iqdbc.car.hyundai.interface import CarInterface
from iqdbc.car.hyundai.values import CAR, DBC, HyundaiFlags, HyundaiFlagsIQ, HyundaiSafetyFlagsIQ

LDA_BUTTON_ADDR = 0x391
ButtonType = structs.CarState.ButtonEvent.Type


def build(candidate, fingerprint):
  cp = CarInterface.get_params(candidate, fingerprint, [], False, False, False)
  cp_iq = CarInterface.get_params_iq(cp, candidate, fingerprint, [], False, False, False)
  return cp, cp_iq


def test_classic_car_with_the_lfa_button_sets_the_iq_capability_and_safety_flag():
  fingerprint = gen_empty_fingerprint()
  fingerprint[0][LDA_BUTTON_ADDR] = 8
  cp, cp_iq = build(CAR.HYUNDAI_ELANTRA_2021, fingerprint)
  assert cp.flags & HyundaiFlags.HAS_LDA_BUTTON
  assert cp_iq.flags & HyundaiFlagsIQ.HAS_LFA_BUTTON
  assert cp_iq.iqSafetyFlags & HyundaiSafetyFlagsIQ.HAS_LDA_BUTTON


def test_non_camera_scc_car_keeps_iq_button_detection_on_the_second_panda():
  fingerprint = gen_empty_fingerprint()
  fingerprint[4][LDA_BUTTON_ADDR] = 8
  _, cp_iq = build(CAR.HYUNDAI_ELANTRA_2021, fingerprint)
  assert cp_iq.flags & HyundaiFlagsIQ.HAS_LFA_BUTTON
  assert cp_iq.iqSafetyFlags & HyundaiSafetyFlagsIQ.HAS_LDA_BUTTON


def test_classic_car_without_the_lfa_button_has_neither():
  cp, cp_iq = build(CAR.HYUNDAI_ELANTRA_2021, gen_empty_fingerprint())
  assert not cp.flags & HyundaiFlags.HAS_LDA_BUTTON
  assert not cp_iq.flags & HyundaiFlagsIQ.HAS_LFA_BUTTON
  assert not cp_iq.iqSafetyFlags & HyundaiSafetyFlagsIQ.HAS_LDA_BUTTON


def test_can_canfd_hybrid_reads_the_lfa_button_from_the_e_can_bus():
  fingerprint = gen_empty_fingerprint()
  fingerprint[2][0x50] = 16
  fingerprint[CanBus(None, fingerprint, True).ECAN][LDA_BUTTON_ADDR] = 8
  _, cp_iq = build(CAR.HYUNDAI_PALISADE_2023, fingerprint)
  assert cp_iq.flags & HyundaiFlagsIQ.HAS_LFA_BUTTON


def test_lfa_button_press_is_reported_as_a_lkas_button_event():
  fingerprint = gen_empty_fingerprint()
  fingerprint[0][LDA_BUTTON_ADDR] = 8
  cp, cp_iq = build(CAR.HYUNDAI_ELANTRA_2021, fingerprint)
  car = CarInterface(cp, cp_iq)
  packer = CANPacker(DBC[CAR.HYUNDAI_ELANTRA_2021][Bus.pt])

  events = []
  t = 0
  for pressed in (0, 0, 1, 1, 0):
    t += 10_000_000
    frame = packer.make_can_msg("BCM_PO_11", 0, {"LDA_BTN": pressed})
    car_state, _ = car.update([(t, [frame])])
    events += [(e.type, e.pressed) for e in car_state.buttonEvents if e.type == ButtonType.lkas]
  assert events == [(ButtonType.lkas, True), (ButtonType.lkas, False)]
