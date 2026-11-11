"""Turn signals through SPAS2 on a Tucson that has no parking ECU.

Off unless the HyundaiSpas2Blinkers param is set. docs/hyundai_tucson_blinkers.md lists what
has and has not been checked on a car.
"""
from iqdbc.car.hyundai.values import CAR, HyundaiFlags

# SPAS2 BLINKER_CONTROL values
NEUTRAL = 0
LEFT = 3
RIGHT = 4

SEND_EVERY = 2          # control frames per message: 50 Hz, the rate used in the car tests
RELEASE_FRAMES = 300    # after a request ends, send neutral for 3 s, then stop sending
BLINKERS_TIMEOUT = 100  # control frames without a new BLINKERS message before its state counts as unknown

BLINKERS_ADDR = 0x413
SPAS_ADDRS = (0x165, 0x16A)  # SPAS1, SPAS2: a car that sends these has its own parking ECU


def spas2_blinkers_supported(candidate, flags: int, ecan: int, fingerprint: dict[int, int]) -> bool:
  """Only the layout it was tried on: gas Tucson, HDA1, camera SCC, BLINKERS on the bus and no parking ECU."""
  required = HyundaiFlags.CANFD | HyundaiFlags.CANFD_CAMERA_SCC | HyundaiFlags.CANFD_ALT_BUTTONS | HyundaiFlags.CANFD_ALT_GEARS
  excluded = HyundaiFlags.CANFD_HDA2 | HyundaiFlags.HYBRID | HyundaiFlags.EV | HyundaiFlags.FCEV | HyundaiFlags.ENABLE_BLINKERS
  return (candidate == CAR.HYUNDAI_TUCSON_4TH_GEN and (flags & required) == required and not (flags & excluded) and ecan == 0
          and fingerprint.get(BLINKERS_ADDR) == 8 and not any(addr in fingerprint for addr in SPAS_ADDRS))


class Spas2Blinkers:
  """Follows CC.leftBlinker / CC.rightBlinker while engaged.

  Sends nothing when idle. A request sends that direction until it ends, then neutral for
  RELEASE_FRAMES, then nothing again.

  The driver comes first. A request does not start while a turn signal or the hazards are
  already on, and it ends as soon as the other side shows activity. Activity on the requested
  side does not end it: the BLINKERS stalk bits stay set for a whole one-touch blink after the
  lever is released, so they follow the blink and not the lever, and our own request may set
  them too. A request that has ended must be dropped before it can start again, so one that is
  still held after the driver overrode it does not come back.
  """

  def __init__(self, CP):
    self.enabled = bool(CP.flags & HyundaiFlags.CANFD_SPAS2_BLINKERS)
    self.frame = 0
    self.active = NEUTRAL
    self.release_frames = 0
    self.armed = False
    self.blinkers_stamp = 0
    self.blinkers_age = BLINKERS_TIMEOUT

  def car_blinkers(self, CS) -> tuple[bool, bool, bool]:
    """(left, right, known): is that side signalling, by stalk bits or lamps, and is BLINKERS still arriving."""
    if CS.cp is None or CS.blinkers is None:
      return False, False, False

    stamp = CS.cp.ts_nanos["BLINKERS"]["LEFT_STALK"]
    if stamp != self.blinkers_stamp:
      self.blinkers_stamp, self.blinkers_age = stamp, 0
    else:
      self.blinkers_age = min(self.blinkers_age + 1, BLINKERS_TIMEOUT)

    left = bool(CS.blinkers["LEFT_STALK"]) or CS.out.leftBlinker
    right = bool(CS.blinkers["RIGHT_STALK"]) or CS.out.rightBlinker
    return left, right, self.blinkers_age < BLINKERS_TIMEOUT

  def update(self, CC, CS) -> int | None:
    """The BLINKER_CONTROL value to send on this control frame, or None to send nothing."""
    if not self.enabled:
      return None
    self.frame += 1

    left, right, known = self.car_blinkers(CS)
    request = LEFT if CC.leftBlinker and not CC.rightBlinker else RIGHT if CC.rightBlinker and not CC.leftBlinker else NEUTRAL
    allowed = CC.enabled and known

    if self.active != NEUTRAL:
      other_side = right if self.active == LEFT else left
      if request != self.active or not allowed or other_side:
        self.active = NEUTRAL
        self.release_frames = RELEASE_FRAMES
    elif request != NEUTRAL and self.armed and allowed and not left and not right:
      self.active = request
      self.armed = False

    if not CC.leftBlinker and not CC.rightBlinker:
      self.armed = True

    if self.active != NEUTRAL:
      control = self.active
    elif self.release_frames > 0:
      self.release_frames -= 1
      control = NEUTRAL
    else:
      return None
    return control if self.frame % SEND_EVERY == 0 else None
