# Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
import pytest

from iqdbc.can import CANPacker
from iqdbc.car import Bus, structs
from iqdbc.car.volkswagen.carstate import CarState
from iqdbc.car.volkswagen.interface import CarInterface
from iqdbc.car.volkswagen.values import CAR, DBC

KOMBI_03 = 0x6B8
SECOND = 1_000_000_000

GOLF_7_73_PERCENT = bytes.fromhex("a627247937610000")
GOLF_7_26_PERCENT = bytes.fromhex("a607682814610000")


def parsers(platform):
  fingerprint = {bus: {} for bus in range(7)}
  cp = CarInterface.get_params(platform, fingerprint, [], alpha_long=False, is_release=False, docs=False)
  return CarState.get_can_parsers(cp, structs.IQCarParams())[Bus.pt]


def kombi_03(platform, percent):
  packer = CANPacker(DBC[platform][Bus.pt])
  return packer.make_can_msg("Kombi_03", 0, {"KBI_Tankfuellstand_Prozent": percent})


def feed(parser, frames, start=SECOND):
  for i, frame in enumerate(frames):
    parser.update([start + i * SECOND, [(frame[0], frame[1], 0)]])


@pytest.mark.parametrize("platform", (CAR.VOLKSWAGEN_GOLF_MK7, CAR.VOLKSWAGEN_TIGUAN_MK2, CAR.VOLKSWAGEN_GOLF_MK8))
def test_kombi_03_never_gates_can_validity(platform):
  parser = parsers(platform)
  state = parser.message_states[KOMBI_03]
  assert state.ignore_alive
  parser.update([10 * SECOND, []])
  assert KOMBI_03 not in {int(m["address"], 16) for m in parser.invalid_messages()}


@pytest.mark.parametrize("platform", (CAR.VOLKSWAGEN_ID4_MK1, CAR.VOLKSWAGEN_ID4_MK2))
def test_battery_platforms_do_not_subscribe_to_kombi_03(platform):
  assert KOMBI_03 not in parsers(platform).message_states


@pytest.mark.parametrize("platform", (CAR.VOLKSWAGEN_GOLF_MK7, CAR.VOLKSWAGEN_GOLF_MK8))
def test_no_cluster_fuel_before_the_message_arrives(platform):
  assert CarState.cluster_fuel_fraction(parsers(platform)) is None


@pytest.mark.parametrize("platform", (CAR.VOLKSWAGEN_GOLF_MK7, CAR.VOLKSWAGEN_GOLF_MK8))
@pytest.mark.parametrize("percent,expected", [(0, 0.0), (26, 0.26), (73, 0.73), (100, 1.0)])
def test_cluster_fuel_follows_the_cluster_percentage(platform, percent, expected):
  parser = parsers(platform)
  feed(parser, [kombi_03(platform, percent)])
  assert CarState.cluster_fuel_fraction(parser) == pytest.approx(expected)


@pytest.mark.parametrize("platform", (CAR.VOLKSWAGEN_GOLF_MK7, CAR.VOLKSWAGEN_GOLF_MK8))
@pytest.mark.parametrize("sentinel", (126, 127))
def test_init_and_error_values_are_not_a_fuel_level(platform, sentinel):
  parser = parsers(platform)
  feed(parser, [kombi_03(platform, sentinel)])
  assert CarState.cluster_fuel_fraction(parser) is None


@pytest.mark.parametrize("frame,expected", [(GOLF_7_73_PERCENT, 0.73), (GOLF_7_26_PERCENT, 0.26)])
def test_logged_golf_7_frames_decode_to_the_cluster_gauge(frame, expected):
  parser = parsers(CAR.VOLKSWAGEN_GOLF_MK7)
  feed(parser, [(KOMBI_03, frame)])
  assert CarState.cluster_fuel_fraction(parser) == pytest.approx(expected)
