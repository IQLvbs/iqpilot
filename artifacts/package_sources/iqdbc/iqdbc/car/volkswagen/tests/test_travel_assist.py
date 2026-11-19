# Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
from types import SimpleNamespace

import pytest

from iqdbc.can import CANPacker, CANParser
from iqdbc.car import Bus, structs
from iqdbc.car.volkswagen import mebcan
from iqdbc.car.volkswagen.carstate import CarState
from iqdbc.car.volkswagen.interface import CarInterface
from iqdbc.car.volkswagen.values import CAR, DBC, CarControllerParams, VolkswagenFlags

ButtonType = structs.CarState.ButtonEvent.Type

PLATFORMS = (CAR.VOLKSWAGEN_ID4_MK1, CAR.VOLKSWAGEN_ID4_MK2, CAR.VOLKSWAGEN_GOLF_MK8)
STOCK_TA = {"Travel_Assist_Press_Ack": 1, "Travel_Assist_Request": 4}


def car_params(platform):
  fingerprint = {bus: {} for bus in range(7)}
  return CarInterface.get_params(platform, fingerprint, [], alpha_long=False, is_release=False, docs=False)


def ta_frame(platform, ta_stock_values, enabled=True):
  packer = CANPacker(DBC[platform][Bus.pt])
  parser = CANParser(DBC[platform][Bus.pt], [("TA_01", 50)], 0)
  messages = mebcan.create_acc_accel_control(
    packer, 0, SimpleNamespace(flags=VolkswagenFlags.MEB), 1, enabled, 4.0, 4.0, 0.0, 0.0,
    0.5, mebcan.ACC_CTRL_ACTIVE, mebcan.ACC_HMS_NO_REQUEST, False, False, False, 20.0, False, True,
    ta_stock_values,
  )
  parser.update([0, messages])
  return parser.vl["TA_01"]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_travel_assist_is_a_button(platform):
  buttons = {button.event_type: button for button in CarControllerParams(car_params(platform)).BUTTONS}
  assert buttons[ButtonType.travelAssist].can_addr == "GRA_ACC_01"
  assert buttons[ButtonType.travelAssist].can_msg == "GRA_TravelAssist"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_travel_assist_release_enables_openpilot(platform):
  carstate = CarState.__new__(CarState)
  carstate.CP = SimpleNamespace(pcmCruise=False)
  carstate.cruise_fault_lateral_active = False
  carstate.cruise_faulted = False
  for button_type, pressed, expected in (
    (ButtonType.travelAssist, False, True),
    (ButtonType.travelAssist, True, False),
    (ButtonType.setCruise, False, True),
    (ButtonType.gapAdjustCruise, False, False),
  ):
    event = structs.CarState.ButtonEvent(type=button_type, pressed=pressed)
    assert carstate.update_button_enable([event]) is expected


@pytest.mark.parametrize("platform", PLATFORMS)
def test_camera_answer_is_forwarded_to_the_cluster(platform):
  values = ta_frame(platform, STOCK_TA)
  assert values["Travel_Assist_Press_Ack"] == 1
  assert values["Travel_Assist_Request"] == 4
  assert values["Travel_Assist_Status"] == 4
  assert values["Travel_Assist_Available"] == 1


@pytest.mark.parametrize("platform", PLATFORMS)
def test_only_the_enable_request_is_forwarded(platform):
  values = ta_frame(platform, {"Travel_Assist_Press_Ack": 0, "Travel_Assist_Request": 3})
  assert values["Travel_Assist_Press_Ack"] == 0
  assert values["Travel_Assist_Request"] == 0


@pytest.mark.parametrize("platform", PLATFORMS)
def test_nothing_is_forwarded_outside_the_engage_window(platform):
  values = ta_frame(platform, None)
  assert values["Travel_Assist_Press_Ack"] == 0
  assert values["Travel_Assist_Request"] == 0


def test_engage_window_is_one_and_a_half_seconds():
  assert CarControllerParams(car_params(CAR.VOLKSWAGEN_ID4_MK2)).TRAVEL_ASSIST_TEXT_FRAMES == 150


@pytest.mark.parametrize("platform", PLATFORMS)
def test_camera_travel_assist_is_read_from_the_camera_bus(platform):
  cp = car_params(platform)
  parsers = CarState.get_can_parsers(cp, structs.IQCarParams())
  assert "TA_01" in parsers[Bus.cam].vl
