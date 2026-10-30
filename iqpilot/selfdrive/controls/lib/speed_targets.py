"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from datetime import datetime


from iqpilot.cereal import messaging, custom
from iqdbc.car import structs
from iqpilot.common.constants import CV
from iqpilot.common.realtime import DT_MDL
from iqpilot.selfdrive.car.cruise import V_CRUISE_MAX
from iqpilot.selfdrive.controls.lib.custom_stop_distance import CustomStopDistance
from iqpilot.selfdrive.controls.lib.force_stop import ForceStopDetector
from iqpilot.selfdrive.controls.lib.helpers.e2e_alerts import EndToEndAlertEngine
from iqpilot.selfdrive.controls.lib.slc_vcruise import SLCVCruise
from iqpilot.selfdrive.selfdrived.iq_events import IQEvents
from iqpilot.selfdrive.iqmodeld.models.helpers import get_active_bundle

IQDynamicState = custom.IQPlan.IQDynamicControl.IQDynamicControlState
LongitudinalPlanSource = custom.IQPlan.LongitudinalPlanSource
SpeedLimitAssistState = custom.IQPlan.SpeedLimit.AssistState
SpeedLimitSource = custom.IQPlan.SpeedLimit.Source
NavProvider = custom.IQNavState.LongitudinalProvider
NavLongitudinalState = custom.IQNavState.LongitudinalState

class SpeedTargets:
  def __init__(self, CP: structs.CarParams, CP_IQ: structs.IQCarParams):
    self.events_iq = IQEvents()
    self.force_stop = ForceStopDetector()
    self.custom_stop_distance = CustomStopDistance()
    self.slimit = SLCVCruise()
    self.generation = int(model_bundle.generation) if (model_bundle := get_active_bundle()) else None
    self.source = LongitudinalPlanSource.cruise
    self.e2e_alerts = EndToEndAlertEngine()
    self.output_v_target = 0.
    self.output_a_target = 0.
    self.speed_limit_last = 0.
    self.speed_limit_final_last = 0.
    self.speed_limit_source = SpeedLimitSource.none
    self.nav_engaged = False
    self.nav_provider = NavProvider.none
    self.nav_state = NavLongitudinalState.disabled
    self.nav_speed_target = 0.
    self.nav_accel_target = 0.
    self.nav_valid = False
    self.force_stop_timer = 0.0
    self.forcing_stop = False
    self.override_force_stop = False
    self.override_force_stop_timer = 0.0
    self.tracked_model_length = 0.0

  def update_targets(self, sm: messaging.SubMaster, v_ego: float, v_cruise: float) -> float:
    CS = sm['carState']
    v_cruise_cluster_kph = min(CS.vCruiseCluster, V_CRUISE_MAX)
    v_cruise_cluster = v_cruise_cluster_kph * CV.KPH_TO_MS
    slc_apply_enabled = bool(getattr(sm['selfdriveState'], "enabled", False))

    nav_state = sm['iqNavState']
    self.nav_engaged = bool(getattr(nav_state, "longitudinalEngaged", False))
    self.nav_provider = getattr(nav_state, "longitudinalProvider", NavProvider.none)
    self.nav_state = getattr(nav_state, "longitudinalState", NavLongitudinalState.disabled)
    self.nav_speed_target = float(getattr(nav_state, "speedTarget", 0.0))
    self.nav_accel_target = float(getattr(nav_state, "accelTarget", 0.0))
    self.nav_valid = bool(getattr(nav_state, "valid", False) and self.nav_engaged)

    now = datetime.now()
    if hasattr(sm, "alive"):
      time_validated = sm.alive.get('clocks', False) and getattr(sm['clocks'], 'timeValid', False)
    else:
      clocks = sm.get('clocks', None) if isinstance(sm, dict) else None
      time_validated = bool(getattr(clocks, 'timeValid', False))
    slc_v_cruise = self.slimit.update(slc_apply_enabled, now, time_validated, v_cruise, v_ego, sm)
    self.force_stop.update(sm)
    display_speed_limit = self.slimit.slc_target if self.slimit.slc_target > 0 else self.slimit.slc_active_target
    display_source = self.slimit.slc_source if self.slimit.slc_source != "None" else self.slimit.slc_active_source

    if display_speed_limit > 0:
      self.speed_limit_last = display_speed_limit
      self.speed_limit_final_last = display_speed_limit + self.slimit.slc_offset
    elif display_source == "None":
      self.speed_limit_last = 0.0
      self.speed_limit_final_last = 0.0
    if v_cruise_cluster > 0 and self.speed_limit_final_last > 0:
      self.speed_limit_final_last = min(self.speed_limit_final_last, v_cruise_cluster)
    source_map = {
      "Dashboard": SpeedLimitSource.car,
      "Map Data": SpeedLimitSource.map,
      "Mapbox": SpeedLimitSource.map,
      "None": SpeedLimitSource.none,
    }
    self.speed_limit_source = source_map.get(display_source, SpeedLimitSource.none)

    targets = {
      LongitudinalPlanSource.cruise: v_cruise,
      LongitudinalPlanSource.speedLimitAssist: slc_v_cruise,
    }
    if self.nav_valid:
      targets[LongitudinalPlanSource.nav] = self.nav_speed_target

    self.source = min(targets, key=lambda k: targets[k])
    self.output_v_target = targets[self.source]
    self.output_v_target = self._apply_force_stop(self.output_v_target, v_ego, sm, slc_apply_enabled)
    return self.output_v_target

  def update(self, sm: messaging.SubMaster) -> None:
    self.events_iq.clear()
    for event_name in getattr(self.slimit, 'pending_events', []):
      self.events_iq.add(event_name)
    self.custom_stop_distance.update()
    self.e2e_alerts.update(sm, self.events_iq)
    if bool(getattr(sm["iqCarState"], "alcOverrideAlert", False)):
      self.events_iq.add(custom.IQOnroadEvent.EventName.steeringOverrideReengageAlc)

  def apply_e2e_stop_distance(self, sm: messaging.SubMaster, v_ego: float, a_target: float, should_stop: bool) -> tuple[float, bool]:
    return self.custom_stop_distance.adjust_e2e_stop(a_target, should_stop, v_ego, sm['modelV2'])

  def _apply_force_stop(self, v_target: float, v_ego: float, sm: messaging.SubMaster, apply_enabled: bool) -> float:
    force_stop = self.force_stop.requested() and apply_enabled and self.override_force_stop_timer <= 0.0
    self.force_stop_timer = self.force_stop_timer + DT_MDL if force_stop else 0.0
    force_stop_enabled = self.force_stop_timer >= 1.0
    force_stop_ramp_time = max(float(self.force_stop.model_stop_time), DT_MDL)

    accel_pressed = bool(getattr(sm["iqCarState"], "accelPressed", False))
    self.override_force_stop |= sm["carState"].gasPressed or accel_pressed
    self.override_force_stop &= force_stop_enabled

    if self.override_force_stop:
      self.override_force_stop_timer = 10.0
    elif self.override_force_stop_timer > 0.0:
      self.override_force_stop_timer = max(0.0, self.override_force_stop_timer - DT_MDL)
    else:
      self.override_force_stop = False

    if force_stop_enabled and not self.override_force_stop:
      self.forcing_stop = True
      self.tracked_model_length = max(self.tracked_model_length - (v_ego * DT_MDL), 0.0)
      if sm["carState"].standstill:
        return 0.0
      return min(self.tracked_model_length / force_stop_ramp_time, v_target)

    self.forcing_stop = False
    self.tracked_model_length = max(
      float(self.force_stop.model_length),
      float(self.force_stop.minimum_force_stop_length),
      0.0,
    )
    return v_target

  def publish_iq_plan(self, sm: messaging.SubMaster, pm: messaging.PubMaster) -> None:
    def fill_plan(plan_msg) -> None:
      plan_msg.longitudinalPlanSource = self.source
      plan_msg.vTarget = float(self.output_v_target)
      plan_msg.aTarget = float(self.output_a_target)
      plan_msg.events = self.events_iq.to_msg()
      if hasattr(self, 'distance_control'):
        self.distance_control.state.fill(plan_msg.distanceControl)
      if hasattr(self, 'accel_boost'):
        plan_msg.accelBoost = float(self.accel_boost.value)

      iq_dynamic = plan_msg.iqDynamic
      iq_dynamic.state = IQDynamicState.acc
      iq_dynamic.enabled = False
      iq_dynamic.active = False

      nav_summary = plan_msg.iqNavState.nav
      nav_summary.engaged = self.nav_engaged
      nav_summary.provider = self.nav_provider
      nav_summary.state = self.nav_state
      nav_summary.speedTarget = float(self.nav_speed_target)
      nav_summary.accelTarget = float(self.nav_accel_target)
      nav_summary.valid = self.nav_valid

      speedLimit = plan_msg.speedLimit
      resolver = speedLimit.resolver
      speed_limit = float(self.slimit.slc_target if self.slimit.slc_target > 0 else self.slimit.slc_active_target)
      speed_limit_offset = float(self.slimit.slc_offset)
      speed_limit_final = speed_limit + speed_limit_offset if speed_limit > 0 else 0.
      speed_limit_valid = speed_limit > 0.
      speed_limit_last_valid = self.speed_limit_last > 0.

      resolver.speedLimit = speed_limit
      resolver.speedLimitLast = float(self.speed_limit_last)
      resolver.speedLimitFinal = float(speed_limit_final)
      resolver.speedLimitFinalLast = float(self.speed_limit_final_last)
      resolver.speedLimitValid = speed_limit_valid
      resolver.speedLimitLastValid = speed_limit_last_valid
      resolver.speedLimitOffset = speed_limit_offset
      resolver.distToSpeedLimit = 0.
      resolver.source = self.speed_limit_source

      assist = speedLimit.assist
      slc_assist_state = self.slimit.assist_state
      assist.enabled = bool(self.slimit.slc_target > 0 or self.slimit.slc_unconfirmed > 0)
      assist.active = self.source == LongitudinalPlanSource.speedLimitAssist and self.slimit.slc_target > 0
      if slc_assist_state is not None:
        assist.state = slc_assist_state
      elif not assist.enabled:
        assist.state = SpeedLimitAssistState.disabled
      elif self.slimit.slc_unconfirmed > 0:
        assist.state = SpeedLimitAssistState.preActive
      elif assist.active:
        assist.state = SpeedLimitAssistState.active
      else:
        assist.state = SpeedLimitAssistState.inactive
      assist.vTarget = float(self.output_v_target if assist.active else 255.)
      assist.aTarget = float(self.slimit.slc_a_target if assist.active else 0.)

      e2eAlerts = plan_msg.e2eAlerts
      e2eAlerts.pathOpen = self.e2e_alerts.path_alert
      e2eAlerts.leadPullaway = self.e2e_alerts.lead_alert

    valid = sm.all_checks(service_list=['carState', 'controlsState'])

    plan_iq_send = messaging.new_message('iqPlan')
    plan_iq_send.valid = valid
    fill_plan(plan_iq_send.iqPlan)
    pm.send('iqPlan', plan_iq_send)
