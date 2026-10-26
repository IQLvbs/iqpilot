import numpy as np
from iqpilot.cereal import car
from iqpilot.common.realtime import DT_CTRL
from iqpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from iqpilot.common.filter_simple import FirstOrderFilter
from iqpilot.common.pid import PIDController
from iqpilot.selfdrive.iqmodeld.config import ModelConstants
from iqpilot.selfdrive.controls.lib.smooth_stops import SMOOTH_STOP_MAX_SPEED, SmoothStopController

CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]

LongCtrlState = car.CarControl.Actuators.LongControlState

# measured accel response: EV6 0.15 s dead time + 0.7 s lag, 2021 Elantra 0.4 s + 1.1 s, where a speed-error loop hunts
SPEED_ERROR_PID_CARS = {"KIA_EV6"}
FILTERED_A_EGO_CARS = {"HYUNDAI_ELANTRA_2021"}
A_EGO_FILTER_TS = 0.3
# closed-loop replay of 2021 Elantra drives: at gain 1 the accel-error loop cycles throttle and brake around a smooth plan
# (17.7 flips/min in the city), at 0.4 it halves that and actual accel tracking is unchanged
ACCEL_ERROR_KP = {"HYUNDAI_ELANTRA_2021": 0.4}


class LongControl:
  def __init__(self, CP, CP_IQ):
    self.CP = CP
    self.CP_IQ = CP_IQ
    self.long_control_state = LongCtrlState.off
    self.pid = PIDController((CP.longitudinalTuning.kpBP, CP.longitudinalTuning.kpV),
                             (CP.longitudinalTuning.kiBP, CP.longitudinalTuning.kiV),
                             rate=1 / DT_CTRL)
    self.last_output_accel = 0.0
    self.stopping_decel_rate = CP_IQ.stoppingDecelRateOverride or 1.0
    self.smooth = SmoothStopController()
    self.speed_error_pid = CP.carFingerprint in SPEED_ERROR_PID_CARS
    self.filter_a_ego = CP.carFingerprint in FILTERED_A_EGO_CARS
    self.a_ego_filter = FirstOrderFilter(0.0, A_EGO_FILTER_TS, DT_CTRL, initialized=False)
    if CP.carFingerprint in ACCEL_ERROR_KP:
      self.pid._k_p = ([0.0], [ACCEL_ERROR_KP[CP.carFingerprint]])

  def reset(self):
    self.pid.reset()

  def _update_state(self, active, car_state, stop_requested):
    if not active:
      self.long_control_state = LongCtrlState.off
      return

    holding = self.long_control_state == LongCtrlState.stopping
    hold_requested = stop_requested
    if self.smooth.enabled and not holding:
      hold_requested = self.smooth.want_hold(stop_requested, car_state.vEgo, car_state.standstill)

    if hold_requested:
      self.long_control_state = LongCtrlState.stopping
      return

    if self.long_control_state == LongCtrlState.pid:
      return

    release_blocked = car_state.brakePressed or (
      car_state.cruiseState.standstill and not self.CP_IQ.enableGasInterceptor
    )
    self.long_control_state = LongCtrlState.stopping if release_blocked else LongCtrlState.pid

  def update(self, active, CS, a_target, should_stop, accel_limits, lead_distance=0.0, has_lead=False, gas_override=False, *, v_target_now):
    self.pid.neg_limit = accel_limits[0]
    self.pid.pos_limit = accel_limits[1]
    self.smooth.update()
    a_ego = self.a_ego_filter.update(CS.aEgo) if self.filter_a_ego else CS.aEgo

    self._update_state(active, CS, should_stop)
    if self.long_control_state == LongCtrlState.off:
      self.reset()
      self.smooth.reset()
      output_accel = 0.

    elif self.long_control_state == LongCtrlState.stopping:
      output_accel = self.last_output_accel
      if output_accel > self.CP.stopAccel:
        output_accel = min(output_accel, 0.0)
        output_accel -= self.stopping_decel_rate * DT_CTRL
      self.reset()
      self.smooth.reset()

    else:
      if self.smooth.enabled and active and should_stop and CS.vEgo <= SMOOTH_STOP_MAX_SPEED:
        output_accel = self.smooth.settle(a_target, CS.vEgo, lead_distance, has_lead, self.last_output_accel)
        self.reset()
      else:
        error = v_target_now - CS.vEgo if self.speed_error_pid else a_target - a_ego
        output_accel = self.pid.update(error, speed=CS.vEgo,
                                       feedforward=a_target,
                                       freeze_integrator=gas_override)
        self.smooth.reset()

    self.last_output_accel = np.clip(output_accel, accel_limits[0], accel_limits[1])
    return self.last_output_accel
