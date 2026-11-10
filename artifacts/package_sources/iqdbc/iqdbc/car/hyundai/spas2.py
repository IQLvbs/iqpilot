"""Default-off SPAS2 integration for a separately qualified Tucson receiver.

The qualification record is engineering evidence, not vehicle discovery. Nothing
in this module establishes receiver timeout, lamp release or hazard priority.
"""
import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from iqdbc.car import structs
from iqdbc.car.hyundai.hyundaicanfd import CanBus
from iqdbc.car.hyundai.values import CAR, HyundaiFlags, HyundaiSafetyFlags

QUALIFICATION_PATH = Path("/data/experimental/tucson_spas2.json")
QUALIFICATION_SCHEMA = "tucson-spas2-qualification-v1"
ICU_PART_NUMBER = "91951CW133"
PERIOD_NS = 20_000_000
SOURCE_LEASE_NS = 100_000_000
DIRECTION_MAX_NS = 10_000_000_000
NEUTRAL_DRAIN_NS = 3_000_000_000
NEUTRAL_MARGIN_NS = 100_000_000  # Bound scheduling jitter while completing a real three-second receipt span.
DIRECTION_START_GAP_NS = 30_000_000  # Separate first direction from the final neutral admission under modest transport jitter.
VEHICLE_LEASE_NS = 100_000_000
STALK_LEASE_NS = 400_000_000  # 0x413 is slower than the drivetrain frames.
REQUIRED_FRAMES = {0x40: 32, 0xA0: 24, 0x175: 24, 0x413: 8}
QUALIFICATION_KEYS = frozenset({
  "schema", "opt_in", "vin_sha256", "icu_part_number", "driver_input_source",
  "neutral_release_verified", "self_timeout_verified", "receiver_timeout_ms",
  "driver_priority_verified", "hazard_priority_verified", "stalk_fields_verified", "evidence_sha256",
  "left_activation_verified", "right_activation_verified", "counter_gap_acceptance_verified",
  "moving_acceptance_verified", "navigation_trigger_cancel_verified",
})
VERIFIED_FIELDS = (
  "opt_in", "neutral_release_verified", "self_timeout_verified", "driver_priority_verified",
  "hazard_priority_verified", "stalk_fields_verified",
  "left_activation_verified", "right_activation_verified", "counter_gap_acceptance_verified",
  "moving_acceptance_verified", "navigation_trigger_cancel_verified",
)


@dataclass(frozen=True)
class Spas2Qualification:
  receiver_timeout_ms: int
  evidence_sha256: str


def is_spas2_platform(CP) -> bool:
  required = HyundaiFlags.CANFD | HyundaiFlags.CANFD_CAMERA_SCC | HyundaiFlags.CANFD_ALT_GEARS | HyundaiFlags.CANFD_ALT_BUTTONS
  excluded = HyundaiFlags.CANFD_HDA2 | HyundaiFlags.EV | HyundaiFlags.HYBRID | HyundaiFlags.FCEV | HyundaiFlags.RADAR_SCC | HyundaiFlags.ENABLE_BLINKERS
  return (CP.carFingerprint == CAR.HYUNDAI_TUCSON_4TH_GEN and CP.flags & required == required
          and not CP.flags & excluded and CanBus(CP).ECAN == 0
          and bool(CP.safetyConfigs) and CP.safetyConfigs[-1].safetyModel == structs.CarParams.SafetyModel.hyundaiCanfd)


def _unique_keys(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      raise ValueError("duplicate qualification field")
    result[key] = value
  return result


def load_qualification(CP, path: Path | None = None) -> Spas2Qualification | None:
  """Read a private regular file; all missing, ambiguous and unsupported records fail closed."""
  if not is_spas2_platform(CP) or not re.fullmatch(r"5NM[A-HJ-NPR-Z0-9]{6}R[A-HJ-NPR-Z0-9]{7}", CP.carVin):
    return None
  try:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    with os.fdopen(os.open(path if path is not None else QUALIFICATION_PATH, flags), "r", encoding="utf-8") as record:
      metadata = os.fstat(record.fileno())
      if (not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077
          or metadata.st_uid not in (0, os.geteuid()) or metadata.st_size > 16_384):
        return None
      data = json.loads(record.read(16_385), object_pairs_hook=_unique_keys)
    if not isinstance(data, dict) or data.keys() != QUALIFICATION_KEYS:
      return None
    if (data["schema"] != QUALIFICATION_SCHEMA or data["icu_part_number"] != ICU_PART_NUMBER
        or data["driver_input_source"] != "BLINKERS_0x413_STALK" or any(data[field] is not True for field in VERIFIED_FIELDS)):
      return None
    if any(not isinstance(data[field], str) or re.fullmatch(r"[0-9a-f]{64}", data[field]) is None
           for field in ("vin_sha256", "evidence_sha256")):
      return None
    if data["vin_sha256"] != hashlib.sha256(CP.carVin.encode("ascii")).hexdigest():
      return None
    timeout = data["receiver_timeout_ms"]
    if type(timeout) is not int or not 1 <= timeout <= 1000:
      return None
    return Spas2Qualification(timeout, data["evidence_sha256"])
  except (OSError, ValueError, TypeError, UnicodeError):
    return None


def configure_spas2(CP, fingerprint, path: Path | None = None) -> None:
  """Run after real VIN assignment. Cached flags never substitute for qualification."""
  CP.flags = int(CP.flags) & ~int(HyundaiFlags.CANFD_SPAS2_BLINKERS)
  for config in CP.safetyConfigs:
    config.safetyParam = int(config.safetyParam) & ~int(HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS)
  if (load_qualification(CP, path) is not None and all(fingerprint[0].get(addr) == size for addr, size in REQUIRED_FRAMES.items())
      and not any(addr in fingerprint[0] for addr in (0x165, 0x16A))):
    CP.flags = int(CP.flags) | int(HyundaiFlags.CANFD_SPAS2_BLINKERS)
    CP.safetyConfigs[-1].safetyParam = int(CP.safetyConfigs[-1].safetyParam) | int(HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS)


def _fresh(cp, address: int, signal: str, size: int, now_nanos: int, lease_nanos: int) -> bool:
  timestamp = cp.ts_nanos.get(address, {}).get(signal, 0)
  return (timestamp > 0 and 0 <= now_nanos - timestamp <= lease_nanos
          and len(cp.dat.get(address, b"")) == size)


def vehicle_inputs_ready(CS, now_nanos: int) -> tuple[bool, bool]:
  """Use accepted parser timestamps and independent stalk candidates, never lamp feedback."""
  cp = CS.cp
  if cp is None or cp.bus != 0:
    return False, True
  fresh = all(_fresh(cp, addr, signal, size, now_nanos, lease) for addr, signal, size, lease in (
    (0x40, "GEAR", 32, VEHICLE_LEASE_NS),
    (0xA0, "WHEEL_SPEED_1", 24, VEHICLE_LEASE_NS),
    (0x175, "DriverBraking", 24, VEHICLE_LEASE_NS),
    (0x413, "LEFT_STALK", 8, STALK_LEASE_NS),
  ))
  if not fresh:
    return False, True
  stalk = cp.vl[0x413]
  manual_override = bool(stalk["LEFT_STALK"] or stalk["RIGHT_STALK"])
  ready = (CS.out.canValid and not CS.out.canTimeout and CS.out.gearShifter == structs.CarState.GearShifter.drive
           and math.isfinite(CS.out.vEgo) and 0 <= CS.out.vEgo <= 100)
  return bool(ready), manual_override


class Spas2Controller:
  """One finite neutral preamble, one direction epoch, then one release drain.

  A fresh navigation request needs at least three seconds of neutral preamble.
  No CAN is sent while idle. The source must keep that same direction valid
  throughout the preamble; cancellation cannot become a delayed activation.
  """
  def __init__(self, CP, path: Path | None = None):
    self.qualified = bool(CP.flags & HyundaiFlags.CANFD_SPAS2_BLINKERS and CP.safetyConfigs
                          and CP.safetyConfigs[-1].safetyParam & HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS
                          and load_qualification(CP, path) is not None)
    self.source_nanos = 0
    self.source_valid = False
    self.last_now_nanos = 0
    self.last_send_nanos = 0
    self.active_control = 0
    self.pending_control = 0
    self.direction_start_nanos = 0
    self.preamble_until_nanos = 0
    self.drain_until_nanos = 0
    self.neutral_start_nanos = 0
    self.last_neutral_nanos = 0
    self.primed = False
    self.armed = False
    self.native_sender_seen = False

  def set_car_control_context(self, publisher_nanos: int, valid: bool) -> None:
    self.source_nanos = publisher_nanos
    self.source_valid = valid

  def _reset_neutral_span(self) -> None:
    self.neutral_start_nanos = self.last_neutral_nanos = 0
    self.primed = False

  def update(self, CC, CS, now_nanos: int) -> int | None:
    if not self.qualified:
      return None
    # Sharing ownership with an existing sender is not a supported release path.
    self.native_sender_seen |= CS.spas2_native_sender_seen
    if self.native_sender_seen:
      self.active_control = self.pending_control = 0
      self.armed = False
      self.drain_until_nanos = 0
      self._reset_neutral_span()
      return None
    monotonic = now_nanos > 0 and now_nanos >= self.last_now_nanos
    loop_fresh = not self.last_now_nanos or now_nanos - self.last_now_nanos <= SOURCE_LEASE_NS
    self.last_now_nanos = max(now_nanos, self.last_now_nanos)
    source_fresh = (self.source_valid and self.source_nanos > 0
                    and 0 <= now_nanos - self.source_nanos <= SOURCE_LEASE_NS)
    inputs_ready, manual_override = vehicle_inputs_ready(CS, now_nanos)
    valid = monotonic and loop_fresh and source_fresh and inputs_ready and not manual_override
    requested = 3 if CC.leftBlinker and not CC.rightBlinker else 4 if CC.rightBlinker and not CC.leftBlinker else 0
    neutral_requested = not CC.leftBlinker and not CC.rightBlinker
    directional_allowed = valid and CC.enabled and CC.latActive
    if not valid:
      self.armed = False

    if self.pending_control and (not directional_allowed or requested != self.pending_control
                                 or now_nanos > self.preamble_until_nanos + SOURCE_LEASE_NS
                                 or (now_nanos > self.preamble_until_nanos and not self.primed)):
      # Only neutral has been sent. Abort immediately, with no delayed direction
      # and no new preamble for a continuously asserted/reversed request.
      self.pending_control = 0
      self.armed = False
      self._reset_neutral_span()

    if self.active_control and (not directional_allowed or requested != self.active_control
                                or now_nanos - self.direction_start_nanos >= DIRECTION_MAX_NS):
      self.active_control = 0
      self.drain_until_nanos = self.last_now_nanos + NEUTRAL_DRAIN_NS + NEUTRAL_MARGIN_NS
      self.armed = False
      self._reset_neutral_span()

    draining = self.drain_until_nanos > 0 and self.drain_until_nanos >= now_nanos and not self.primed
    if valid and neutral_requested:
      self.armed = True
    elif not self.active_control and not self.pending_control:
      if directional_allowed and requested and self.armed and not draining:
        self.pending_control = requested
        self.preamble_until_nanos = now_nanos + NEUTRAL_DRAIN_NS + NEUTRAL_MARGIN_NS
        self._reset_neutral_span()
      self.armed = False

    if self.active_control:
      control = self.active_control
    elif self.pending_control:
      if now_nanos <= self.preamble_until_nanos:
        control = 0
      else:
        control = self.pending_control if now_nanos - self.last_send_nanos >= DIRECTION_START_GAP_NS else None
    else:
      control = 0 if draining else None
    # Clock regressions cannot cause a burst; the monotonic watermark must catch up.
    if control is None or not monotonic or (self.last_send_nanos and now_nanos - self.last_send_nanos < PERIOD_NS):
      return None
    self.last_send_nanos = now_nanos
    if control == 0:
      if not self.neutral_start_nanos or now_nanos - self.last_neutral_nanos > SOURCE_LEASE_NS:
        self.neutral_start_nanos = now_nanos
      self.last_neutral_nanos = now_nanos
      self.primed = now_nanos - self.neutral_start_nanos >= NEUTRAL_DRAIN_NS
    elif not self.active_control:
      # The direction cap begins with the first actual directional packet.
      self.active_control = control
      self.pending_control = 0
      self.direction_start_nanos = now_nanos
      self.primed = False
    return control
