import re

from iqdbc.can import CANPacker, CANParser
from iqdbc.car import Bus, DT_CTRL, gen_empty_fingerprint, structs
from iqdbc.car.honda import hondacan
from iqdbc.car.honda.carcontroller import CarControllerParams
from iqdbc.car.honda.fingerprints import FW_VERSIONS
from iqdbc.car.honda.hondacan import CanBus
from iqdbc.car.honda.interface import CarInterface
from iqdbc.car.honda.values import CAR, DBC, FW_QUERY_CONFIG, HONDA_BOSCH, HONDA_BOSCH_ALT_RADAR, HONDA_BOSCH_CANFD, \
                                   HONDA_BOSCH_RADARLESS, HONDA_BOSCH_TJA_CONTROL, HONDA_RADAR_SCAN_CAPABLE, HondaFlags
from iqdbc.car.interfaces import get_torque_params

Ecu = structs.CarParams.Ecu
TransmissionType = structs.CarParams.TransmissionType
GearShifter = structs.CarState.GearShifter

PORTED_PLATFORM_STEER_MAX = {
  CAR.ACURA_ADX: 3840,
  CAR.ACURA_MDX_4G: 3840,
  CAR.ACURA_RDX_3G_MMR: 2560,
  CAR.HONDA_E_ADVANCE: 4096,
  CAR.HONDA_PILOT_4G_MMR: 3628,
  CAR.HONDA_PRELUDE_6G: 4096,
}


BUSY_BUS = tuple(range(0x300, 0x30C))


def build_car(candidate, pt_addrs=(), alpha_long=False):
  fingerprint = gen_empty_fingerprint()
  for addr in pt_addrs:
    fingerprint[0][addr] = 8
    fingerprint[1][addr] = 8
  CP = CarInterface.get_params(candidate, fingerprint, [], alpha_long, False, False)
  CP_IQ = CarInterface.get_params_iq(CP, candidate, fingerprint, [], alpha_long, False, False)
  return CarInterface(CP, CP_IQ)


class CanFeed:
  def __init__(self, ci):
    self.ci = ci
    self.packer = CANPacker(DBC[ci.CP.carFingerprint][Bus.pt])
    self.pt = CanBus(ci.CP).pt
    self.nanos = 0
    self.step()
    self.ci.CS.update(self.ci.can_parsers)

  def step(self, msgs=()):
    self.nanos += int(DT_CTRL * 1e9)
    packed = [self.packer.make_can_msg(name, self.pt, values) for name, values in msgs]
    for parser in self.ci.can_parsers.values():
      parser.update([self.nanos, packed])

  def update(self, msgs=()):
    self.step(msgs)
    return self.ci.CS.update(self.ci.can_parsers)[0]

HONDA_FW_VERSION_RE = br"[A-Z0-9]{5}(-|,)[A-Z0-9]{3}(-|,)[A-Z0-9]{4}(\x00){2}$"


class TestHondaFingerprint:
  def test_fw_version_format(self):
    # Asserts all FW versions follow an expected format
    for fw_by_ecu in FW_VERSIONS.values():
      for fws in fw_by_ecu.values():
        for fw in fws:
          assert re.match(HONDA_FW_VERSION_RE, fw) is not None, fw

  def test_tja_bosch_only(self):
    assert set(HONDA_BOSCH_TJA_CONTROL).issubset(set(HONDA_BOSCH)), "Nidec car found in TJA control list"


class TestHondaPortedPlatforms:
  def test_steer_max_matches_upstream(self):
    for car, steer_max in PORTED_PLATFORM_STEER_MAX.items():
      CP = build_car(car).CP
      assert list(CP.lateralParams.torqueBP) == [0, steer_max], car
      assert list(CP.lateralParams.torqueV) == [0, steer_max], car

  def test_platform_flags(self):
    assert CAR.ACURA_ADX in HONDA_BOSCH_RADARLESS
    assert CAR.HONDA_PRELUDE_6G in HONDA_BOSCH_RADARLESS
    assert CAR.ACURA_MDX_4G in HONDA_BOSCH_ALT_RADAR
    assert CAR.ACURA_RDX_3G_MMR in HONDA_BOSCH_ALT_RADAR
    assert CAR.HONDA_PILOT_4G_MMR in HONDA_BOSCH_CANFD
    assert CAR.HONDA_E_ADVANCE in HONDA_RADAR_SCAN_CAPABLE
    assert CAR.ACURA_RDX_3G_MMR.config.flags & HondaFlags.BOSCH_ALT_BRAKE

  def test_torque_data_registered(self):
    params = get_torque_params()
    assert params[CAR.ACURA_ADX]["FRICTION"] == 0.22
    assert params[CAR.ACURA_MDX_4G]["LAT_ACCEL_FACTOR"] == 1.4
    assert params[CAR.ACURA_RDX_3G_MMR]["FRICTION"] == 0.16
    assert params[CAR.HONDA_PILOT_4G_MMR]["LAT_ACCEL_FACTOR"] == 2.0
    assert params[CAR.HONDA_E_ADVANCE] == params[CAR.HONDA_CIVIC_BOSCH]
    assert params[CAR.HONDA_PRELUDE_6G] == params[CAR.HONDA_CIVIC_2022]

  def test_new_platform_ecus_are_queryable(self):
    non_essential = FW_QUERY_CONFIG.non_essential_ecus
    for car in (CAR.HONDA_E_ADVANCE, CAR.ACURA_MDX_4G, CAR.ACURA_RDX_3G_MMR, CAR.HONDA_PILOT_4G_MMR, CAR.ACURA_ADX, CAR.HONDA_PRELUDE_6G):
      assert car in non_essential[Ecu.eps]
      assert car in non_essential[Ecu.vsa]

  def test_manual_transmission_detected_from_missing_gearbox_messages(self):
    for car in (CAR.HONDA_FIT, CAR.HONDA_CIVIC_2022, CAR.ACURA_ADX):
      assert build_car(car, pt_addrs=BUSY_BUS).CP.transmissionType == TransmissionType.manual, car
      assert build_car(car, pt_addrs=BUSY_BUS + (0x1A3,)).CP.transmissionType == TransmissionType.automatic, car
      assert build_car(car, pt_addrs=BUSY_BUS + (0x191,)).CP.transmissionType == TransmissionType.cvt, car

  def test_sparse_fingerprint_is_never_manual(self):
    for car in (CAR.HONDA_FIT, CAR.HONDA_CIVIC_2022, CAR.ACURA_ADX, CAR.HONDA_ACCORD):
      assert build_car(car).CP.transmissionType == TransmissionType.automatic, car
      assert build_car(car, pt_addrs=BUSY_BUS[:9]).CP.transmissionType == TransmissionType.automatic, car

  def test_manual_reverse_light_on_scm_buttons(self):
    ci = build_car(CAR.HONDA_FIT, pt_addrs=BUSY_BUS)
    assert ci.CP.transmissionType == TransmissionType.manual
    feed = CanFeed(ci)
    assert feed.update([("SCM_BUTTONS", {"REVERSE_LIGHT": 1})]).gearShifter == GearShifter.reverse
    assert feed.update([("SCM_BUTTONS", {"REVERSE_LIGHT": 0})]).gearShifter == GearShifter.drive

  def test_regen_gear_decodes_as_brake(self):
    ci = build_car(CAR.HONDA_CIVIC_2022, pt_addrs=(0x1A3,))
    feed = CanFeed(ci)
    assert feed.update([("GEARBOX_AUTO", {"GEAR_SHIFTER": 11})]).gearShifter == GearShifter.brake

  def test_steer_status_one_stays_a_fault_off_mdx(self):
    for car in (CAR.HONDA_CIVIC_BOSCH, CAR.HONDA_ACCORD, CAR.ACURA_RDX_3G, CAR.HONDA_CRV_5G):
      cs = CanFeed(build_car(car)).update([("STEER_STATUS", {"STEER_STATUS": 1})])
      assert cs.steerFaultTemporary, car
      assert cs.steerFaultPermanent, car

  def test_mdx_tja_low_speed_lockout_is_not_a_fault(self):
    ci = build_car(CAR.ACURA_MDX_4G)
    feed = CanFeed(ci)
    cs = feed.update([("STEER_STATUS", {"STEER_STATUS": 1})])
    assert not cs.steerFaultTemporary
    assert not cs.steerFaultPermanent
    cs = feed.update([("STEER_STATUS", {"STEER_STATUS": 6})])
    assert cs.steerFaultTemporary

  def test_tja_low_speed_lockout_stays_a_fault_elsewhere(self):
    ci = build_car(CAR.ACURA_RDX_3G_MMR)
    feed = CanFeed(ci)
    assert feed.update([("STEER_STATUS", {"STEER_STATUS": 1})]).steerFaultPermanent

  def test_mdx_acc_fault_from_brake_module(self):
    ci = build_car(CAR.ACURA_MDX_4G, pt_addrs=(0x1BE,), alpha_long=True)
    assert ci.CP.flags & HondaFlags.BOSCH_ALT_BRAKE
    assert ci.CP.openpilotLongitudinalControl
    feed = CanFeed(ci)
    ci.CS.initial_accFault_cleared = True
    assert feed.update([("BRAKE_MODULE", {"CRUISE_FAULT": 1})]).accFaulted
    assert not feed.update([("BRAKE_MODULE", {"CRUISE_FAULT": 0})]).accFaulted

  def test_alt_radar_lkas_hud_does_not_abuse_lkas_problem(self):
    for car in (CAR.ACURA_MDX_4G, CAR.ACURA_RDX_3G_MMR, CAR.HONDA_ODYSSEY_5G_MMR, CAR.ACURA_TLX_2G):
      CP = build_car(car).CP
      dbc_name = DBC[car][Bus.pt]
      packer = CANPacker(dbc_name)
      hud_control = structs.CarControl.HUDControl()
      commands = hondacan.create_lkas_hud(packer, 0, CP, hud_control, True, True, False, {}, False)
      parser = CANParser(dbc_name, [("LKAS_HUD", 0)], 0)
      parser.update([1, commands])
      assert parser.vl["LKAS_HUD"]["SOLID_LANES"] == 1, car
      assert parser.vl["LKAS_HUD"]["LKAS_PROBLEM"] == 0, car

  def test_alt_radar_dashed_lanes_follow_global_min_steer_speed(self):
    for car in HONDA_BOSCH_ALT_RADAR:
      dbc_name = DBC[car][Bus.pt]
      min_speed = max(CarControllerParams.STEER_GLOBAL_MIN_SPEED, build_car(car).CP.minSteerSpeed)
      for v_ego, dashed in ((0.0, 0), (0.5, 0), (min_speed - 0.1, 0), (min_speed + 0.1, 1), (min_speed + 5.0, 1)):
        ci = build_car(car)
        ci.update([])
        ci.CS.out.vEgo = v_ego
        ci.CS.out.cruiseState.available = True
        CC = structs.CarControl()
        CC.enabled = True
        CC.latActive = True
        parser = CANParser(dbc_name, [("LKAS_HUD", 0)], 0)
        _, sends = ci.apply(CC.as_reader(), structs.IQCarControl(), int(DT_CTRL * 1e9), None)
        parser.update([1, sends])
        assert parser.vl["LKAS_HUD"]["SOLID_LANES"] == 1, (car, v_ego)
        assert parser.vl["LKAS_HUD"]["DASHED_LANES"] == dashed, (car, v_ego)
