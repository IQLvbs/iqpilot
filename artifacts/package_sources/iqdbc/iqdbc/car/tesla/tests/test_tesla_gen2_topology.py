"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import pytest

from iqdbc.can import CANPacker, CANParser
from iqdbc.car import Bus, gen_empty_fingerprint, structs
from iqdbc.car.tesla.carstate import CarState
from iqdbc.car.tesla.interface import CarInterface
from iqdbc.car.tesla.message_source import QUIET_NANOS, MessageSource
from iqdbc.car.tesla.values import CANBUS, CAR
from iqdbc.lvbs.car.tesla.values import TeslaFlagsIQ, TeslaSafetyFlagsIQ

STEP_NANOS = 20_000_000
START_NANOS = 1_000_000_000
SPEED_MS = 10.0


def gen2_fingerprint(vehicle_bus: bool = True):
  fingerprint = gen_empty_fingerprint()
  fingerprint[CANBUS.autopilot_party][0x399] = 8
  if vehicle_bus:
    fingerprint[CANBUS.vehicle][0x3F5] = 8
  return fingerprint


class Bench:
  def __init__(self, vehicle_bus: bool = True):
    fingerprint = gen2_fingerprint(vehicle_bus)
    self.CP = CarInterface.get_params(CAR.TESLA_MODEL_Y, fingerprint, [], False, False, False)
    self.CP_IQ = structs.IQCarParams()
    self.car_state = CarState(self.CP, self.CP_IQ)
    self.parsers = CarState.get_can_parsers(self.CP, self.CP_IQ)
    self.party = CANPacker("tesla_model3_party")
    self.vehicle = CANPacker("tesla_model3_vehicle")
    self.step_count = 0
    self.ret = None
    self.can_valid = False

  def mirrored(self, name, values, buses):
    address, dat, _ = self.party.make_can_msg(name, 0, values)
    return [(address, dat, bus) for bus in buses]

  def frames(self, speed_buses, state_buses, settings_buses):
    party = self.party
    frames = [
      party.make_can_msg("DI_systemStatus", CANBUS.party, {}),
      party.make_can_msg("ESP_status", CANBUS.party, {"ESP_driverBrakeApply": 1}),
      party.make_can_msg("ESP_B", CANBUS.party, {"ESP_vehicleSpeed": SPEED_MS * 3.6}),
      party.make_can_msg("EPAS3S_sysStatus", CANBUS.party, {}),
      party.make_can_msg("VehicleStatus", CANBUS.party, {"allDoorsClosed": 1}),
      party.make_can_msg("SCCM_steeringAngleSensor", CANBUS.autopilot_party, {}),
      party.make_can_msg("DAS_control", CANBUS.autopilot_party, {}),
      party.make_can_msg("DAS_steeringControl", CANBUS.autopilot_party, {}),
      party.make_can_msg("DAS_statusGen2", CANBUS.autopilot_party, {}),
      self.vehicle.make_can_msg("VCFRONT_lighting", CANBUS.vehicle, {}),
      self.vehicle.make_can_msg("VCFRONT_vehicleStatus", CANBUS.vehicle, {"VCFRONT_driverBuckleStatus": 1}),
      *self.mirrored("DI_speed", {"DI_vehicleSpeed": SPEED_MS * 3.6}, speed_buses),
    ]
    if self.step_count % 5 == 0:
      frames += self.mirrored("DI_state", {}, state_buses)
    if self.step_count % 25 == 0:
      frames += self.mirrored("DAS_settings", {"DAS_autosteerEnabled": 0}, settings_buses)
    return frames

  def run(self, steps, speed_buses, state_buses, settings_buses):
    for _ in range(steps):
      t = START_NANOS + self.step_count * STEP_NANOS
      entry = [t, self.frames(speed_buses, state_buses, settings_buses)]
      for parser in self.parsers.values():
        parser.update(entry)
      self.ret, _ = self.car_state.update(self.parsers)
      self.can_valid = all(parser.can_valid for parser in self.parsers.values())
      self.step_count += 1

  @property
  def active_buses(self):
    return tuple(source.active.bus for source in self.car_state.sources.values())


class TestTeslaHW4Gen2DriveInverterTopology:
  def test_party_bus_topology(self):
    bench = Bench()
    bench.run(100, [CANBUS.party], [CANBUS.party], [CANBUS.party])
    assert bench.can_valid
    assert bench.active_buses == (CANBUS.party, CANBUS.party, CANBUS.party)

  def test_drive_inverter_behind_the_autopilot_and_vehicle_buses(self):
    bench = Bench()
    bench.run(100, [CANBUS.autopilot_party], [CANBUS.vehicle], [CANBUS.autopilot_party])
    assert bench.can_valid
    assert bench.active_buses == (CANBUS.autopilot_party, CANBUS.vehicle, CANBUS.autopilot_party)
    assert bench.ret.vEgoRaw == pytest.approx(SPEED_MS, abs=0.05)

  def test_follows_the_drive_inverter_when_the_relay_splits_the_buses(self):
    bench = Bench()
    bridged = [CANBUS.party, CANBUS.autopilot_party]
    bench.run(60, bridged, bridged, bridged)
    assert bench.can_valid

    bench.run(200, [CANBUS.autopilot_party], [CANBUS.vehicle], [CANBUS.autopilot_party])
    assert bench.can_valid
    assert bench.active_buses == (CANBUS.autopilot_party, CANBUS.vehicle, CANBUS.autopilot_party)

  def test_follows_the_drive_inverter_back_to_the_party_bus(self):
    bench = Bench()
    bench.run(60, [CANBUS.autopilot_party], [CANBUS.vehicle], [CANBUS.autopilot_party])
    bench.run(200, [CANBUS.party], [CANBUS.party], [CANBUS.party])
    assert bench.can_valid
    assert bench.active_buses == (CANBUS.party, CANBUS.party, CANBUS.party)

  def test_no_vehicle_bus_tap_keeps_the_party_bus_parsers_only(self):
    bench = Bench(vehicle_bus=False)
    assert Bus.party_vehicle not in bench.parsers
    bench.run(100, [CANBUS.party], [CANBUS.party], [CANBUS.party])
    assert bench.can_valid

  def test_invalid_while_a_drive_inverter_message_is_nowhere(self):
    bench = Bench()
    bench.run(100, [CANBUS.autopilot_party], [], [CANBUS.autopilot_party])
    assert not bench.can_valid

  def test_invalid_after_the_active_source_goes_silent(self):
    bench = Bench()
    bench.run(100, [CANBUS.autopilot_party], [CANBUS.vehicle], [CANBUS.autopilot_party])
    assert bench.can_valid
    bench.run(100, [], [CANBUS.vehicle], [CANBUS.autopilot_party])
    assert not bench.can_valid


class TestMessageSource:
  @staticmethod
  def _sources():
    parsers = [CANParser("tesla_model3_party", [], bus) for bus in (0, 2)]
    return MessageSource("DI_speed", parsers), parsers

  @staticmethod
  def _feed(parser, t, bus):
    address, dat, _ = CANPacker("tesla_model3_party").make_can_msg("DI_speed", bus, {})
    parser.update([t, [(address, dat, bus)]])

  def test_first_parser_is_active_before_anything_arrives(self):
    source, parsers = self._sources()
    assert source.resolve() is parsers[0]

  def test_only_the_active_parser_is_held_to_a_deadline(self):
    source, parsers = self._sources()
    states = [parser.message_states[source.address] for parser in parsers]
    assert [state.ignore_alive for state in states] == [False, True]

  def test_moves_to_the_parser_that_carries_the_message(self):
    source, parsers = self._sources()
    self._feed(parsers[1], START_NANOS, 2)
    assert source.resolve() is parsers[1]
    states = [parser.message_states[source.address] for parser in parsers]
    assert [state.ignore_alive for state in states] == [True, False]

  def test_stays_put_while_both_parsers_deliver(self):
    source, parsers = self._sources()
    for step in range(20):
      t = START_NANOS + step * STEP_NANOS
      self._feed(parsers[0], t, 0)
      self._feed(parsers[1], t + QUIET_NANOS // 2, 2)
      assert source.resolve() is parsers[0]

  def test_moves_once_the_active_parser_has_been_quiet_long_enough(self):
    source, parsers = self._sources()
    self._feed(parsers[0], START_NANOS, 0)
    self._feed(parsers[1], START_NANOS + QUIET_NANOS + 1, 2)
    assert source.resolve() is parsers[1]


class TestTeslaHW4Gen2VehicleBusMarker:
  @staticmethod
  def _params(markers):
    fingerprint = gen2_fingerprint()
    for address in markers:
      fingerprint[CANBUS.vehicle][address] = 8
    CP = CarInterface.get_params(CAR.TESLA_MODEL_Y, fingerprint, [], False, False, False)
    return CarInterface.get_params_iq(CP, CAR.TESLA_MODEL_Y, fingerprint, [], False, False, False)

  def test_odometer_alone_is_not_a_vehicle_bus_addon_on_gen2(self):
    CP_IQ = self._params([0x3B6])
    assert not CP_IQ.flags & TeslaFlagsIQ.HAS_VEHICLE_BUS
    assert not CP_IQ.iqSafetyFlags & TeslaSafetyFlagsIQ.HAS_VEHICLE_BUS

  def test_ui_status2_marks_the_vehicle_bus_addon_on_gen2(self):
    CP_IQ = self._params([0x3DF])
    assert CP_IQ.flags & TeslaFlagsIQ.HAS_VEHICLE_BUS
    assert CP_IQ.iqSafetyFlags & TeslaSafetyFlagsIQ.HAS_VEHICLE_BUS
