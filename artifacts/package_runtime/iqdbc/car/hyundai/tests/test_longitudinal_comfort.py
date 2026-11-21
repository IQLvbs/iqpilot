from dataclasses import replace

import pytest

from iqdbc.can import CANParser
from iqdbc.car import Bus, gen_empty_fingerprint, structs
from iqdbc.car.hyundai.interface import CarInterface
from iqdbc.car.hyundai.values import CAR, DBC, HyundaiFlags

PATHS = ('radar', 'camera', 'canfd', 'canfd_camera', 'canfd_lka')


def make_car(path):
  canfd = path.startswith('canfd')
  candidate = CAR.KIA_EV6 if canfd else CAR.HYUNDAI_SONATA
  fingerprint = gen_empty_fingerprint()
  cp = CarInterface.get_params(candidate, fingerprint, [], True, False, False)
  if path == 'camera':
    cp.flags |= HyundaiFlags.CAMERA_SCC.value
  if path == 'canfd':
    cp.flags &= ~HyundaiFlags.CANFD_CAMERA_SCC.value
  if path == 'canfd_camera':
    cp.flags |= HyundaiFlags.CANFD_CAMERA_SCC.value
  if path == 'canfd_lka':
    cp.flags &= ~HyundaiFlags.CANFD_CAMERA_SCC.value
    cp.flags |= HyundaiFlags.CANFD_LKA_STEER_MSG.value
  cp_iq = CarInterface.get_params_iq(cp, candidate, fingerprint, [], True, False, False)
  car = CarInterface(cp, cp_iq)
  car.update([(0, [])])
  car.CS.out = structs.CarState(vEgo=20.0, vEgoRaw=20.0)
  car.CS.out.cruiseState.available = True
  car.CS.out.gearShifter = structs.CarState.GearShifter.drive
  return car


def policy(**kwargs):
  values = dict(valid=True, comfortEnabled=True, jerkUp=0.89, jerkDown=3.19,
                accelDeviationAbove=0.18, accelDeviationBelow=0.06)
  values.update(kwargs)
  return structs.IQCarControl.LongitudinalComfort(**values)


def apply(car, data=None, *, gate=True, gas=False, fcw=False, active=True, stopping=False, accel=0.6):
  cc = structs.CarControl()
  cc.enabled = active
  cc.longActive = active and not gas
  cc.longComfortMode = gate
  cc.cruiseControl.override = gas
  cc.actuators.accel = accel
  cc.actuators.jerk = 0.3
  cc.actuators.longControlState = 'off' if not active else 'stopping' if stopping else 'pid'
  if fcw:
    cc.hudControl.visualAlert = structs.CarControl.HUDControl.VisualAlert.fcw
  cc.hudControl.setSpeed = 25.0
  car.CS.out.gasPressed = gas
  iq = structs.IQCarControl()
  if data is not None:
    iq.longitudinalComfort = data
  car.CC.frame += -car.CC.frame % 2
  now = (car.CC.frame + 1) * 10_000_000
  _, messages = car.apply(cc.as_reader(), iq, now)
  canfd = car.CP.flags & HyundaiFlags.CANFD
  name, bus = ('SCC_CONTROL', car.CC.CAN.ECAN) if canfd else ('SCC14', 0)
  parser = CANParser(DBC[car.CP.carFingerprint][Bus.pt], [(name, 0)], bus)
  assert any(addr == parser.dbc.name_to_msg[name].address and src == bus for addr, _, src in messages)
  parser.update([(now, messages)])
  return messages, dict(parser.vl[name])


@pytest.mark.parametrize('candidate', list(CAR))
@pytest.mark.parametrize('openpilot_long', [False, True])
def test_all_hyundai_platforms_use_native_jerk_and_only_classic_scc14_senders_advertise_bands(candidate, openpilot_long):
  fingerprint = gen_empty_fingerprint()
  cp = CarInterface.get_params(candidate, fingerprint, [], openpilot_long, False, False)
  cp_iq = CarInterface.get_params_iq(cp, candidate, fingerprint, [], openpilot_long, False, False)
  capability = cp_iq.longitudinalActuation
  assert capability.jerkControl == 'nativeAsymmetric'
  assert capability.maxJerkUp == capability.maxJerkDown == 5.0
  has_band = cp.openpilotLongitudinalControl and not cp.flags & HyundaiFlags.CANFD
  assert capability.comfortBand == ('asymmetric' if has_band else 'none')


def stock_limits(car, accel_state='pid'):
  if car.CP.flags & HyundaiFlags.CANFD:
    return {'JerkUpperLimit': 3.0, 'JerkLowerLimit': 5.0}
  return {'JerkUpperLimit': 3.0 if accel_state == 'pid' else 1.0, 'JerkLowerLimit': 5.0,
          'ComfortBandUpper': 0.0, 'ComfortBandLower': 0.0}


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('state', [{}, {'gas': True}, {'fcw': True}, {'active': False}, {'stopping': True}])
def test_gate_off_can_is_byte_identical_even_when_policy_requests_different_limits(path, state):
  legacy, gated = make_car(path), make_car(path)
  for accel in (0.0, 0.8, -0.7, -3.3):
    assert apply(legacy, gate=False, accel=accel, **state)[0] == apply(gated, policy(), gate=False, accel=accel, **state)[0]


@pytest.mark.parametrize('path', PATHS)
def test_gate_off_keeps_the_stock_limits(path):
  car = make_car(path)
  _, fields = apply(car, gate=False)
  for name, value in stock_limits(car).items():
    assert fields[name] == pytest.approx(value, abs=0.05)


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('data', [None, policy(valid=False)] + [
  policy(**{field: value}) for field in ('jerkUp', 'jerkDown', 'accelDeviationAbove', 'accelDeviationBelow')
  for value in (float('nan'), float('inf'), -0.1)
] + [policy(jerkUp=0.0), policy(jerkDown=0.0)])
def test_missing_invalid_or_nonfinite_data_restores_stock_can_after_a_valid_tick(path, data):
  legacy, gated = make_car(path), make_car(path)
  apply(legacy, policy())
  apply(gated, policy())
  assert apply(gated, data)[0] == apply(legacy, gate=False)[0]


@pytest.mark.parametrize('path', PATHS)
def test_native_can_uses_independent_jerk_limits_without_rounding_above_the_policy(path):
  data = policy()
  _, fields = apply(make_car(path), data)
  for name, maximum in [('JerkUpperLimit', data.jerkUp), ('JerkLowerLimit', data.jerkDown)]:
    assert 0 < fields[name] <= maximum < fields[name] + 0.1
  assert fields['JerkUpperLimit'] < fields['JerkLowerLimit']


@pytest.mark.parametrize('path', PATHS)
def test_native_jerk_stays_within_the_ports_five_meter_per_second_cubed_ceiling(path):
  _, fields = apply(make_car(path), policy(jerkUp=8.0, jerkDown=9.0, comfortEnabled=False))
  assert fields['JerkUpperLimit'] == fields['JerkLowerLimit'] == 5.0


@pytest.mark.parametrize('path', PATHS)
def test_comfort_mode_stops_exactly_like_comfort_mode_off(path):
  legacy, gated = make_car(path), make_car(path)
  for accel in (-0.2, -0.6, -1.2):
    data = policy(jerkUp=5.0, jerkDown=5.0, comfortEnabled=False)
    assert apply(legacy, gate=False, accel=accel, stopping=True)[0] == apply(gated, data, accel=accel, stopping=True)[0]


@pytest.mark.parametrize('path', ['radar', 'camera'])
def test_scc14_upper_is_physical_above_and_lower_is_physical_below_with_conservative_steps(path):
  data = policy()
  _, fields = apply(make_car(path), data)
  for name, maximum in [('ComfortBandUpper', data.accelDeviationAbove), ('ComfortBandLower', data.accelDeviationBelow)]:
    assert 0 < fields[name] <= maximum < fields[name] + 0.02
  assert fields['ComfortBandUpper'] > fields['ComfortBandLower']


@pytest.mark.parametrize('path', ['radar', 'camera'])
def test_classic_steady_band_reaches_at_least_point_two_two_within_the_active_stock_envelope(path):
  _, fields = apply(make_car(path), policy(accelDeviationAbove=0.375, accelDeviationBelow=0.375))
  assert 0.22 <= fields['ComfortBandUpper'] <= 0.24
  assert 0.22 <= fields['ComfortBandLower'] <= 0.24


@pytest.mark.parametrize('path', ['radar', 'camera'])
def test_a_band_just_below_a_dbc_step_never_rounds_up(path):
  data = policy(accelDeviationAbove=0.18 - 1e-9, accelDeviationBelow=0.06 - 1e-9)
  _, fields = apply(make_car(path), data)
  assert fields['ComfortBandUpper'] <= data.accelDeviationAbove
  assert fields['ComfortBandLower'] <= data.accelDeviationBelow


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('bypass', ['hud_fcw', 'policy_fcw', 'lead_braking'])
def test_emergencies_restore_downward_authority_and_zero_bands(path, bypass):
  data = policy(bypassJerkLimit=bypass == 'policy_fcw', bypassJerkDownLimit=bypass == 'lead_braking')
  _, fields = apply(make_car(path), data, fcw=bypass == 'hud_fcw')
  assert fields['JerkLowerLimit'] == 5.0
  assert fields['JerkUpperLimit'] == (pytest.approx(0.8) if bypass == 'lead_braking' else 5.0)
  if not path.startswith('canfd'):
    assert fields['ComfortBandUpper'] == fields['ComfortBandLower'] == 0.0


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('stopping', [False, True])
def test_gas_override_uses_published_soft_jerk_even_with_a_pending_stop(path, stopping):
  data = policy(jerkUp=0.5, jerkDown=0.5, comfortEnabled=False)
  _, fields = apply(make_car(path), data, gas=True, stopping=stopping)
  assert fields['JerkUpperLimit'] == fields['JerkLowerLimit'] == 0.5
  if not path.startswith('canfd'):
    assert fields['ComfortBandUpper'] == fields['ComfortBandLower'] == 0.0


@pytest.mark.parametrize('path', PATHS)
def test_disabling_the_band_keeps_native_jerk(path):
  _, fields = apply(make_car(path), replace(policy(), comfortEnabled=False))
  assert fields['JerkUpperLimit'] <= 0.89
  assert fields['JerkLowerLimit'] <= 3.19
  if not path.startswith('canfd'):
    assert fields['ComfortBandUpper'] == fields['ComfortBandLower'] == 0.0
