"""Turn signals through SPAS2 on a car without a parking ECU. Off unless HyundaiSpas2Blinkers is set (docs/hyundai_tucson_blinkers.md)."""
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
  """Follows CC.leftBlinker / CC.rightBlinker while cruise or always-on lateral is engaged: the direction while it is
  asked for, then neutral for RELEASE_FRAMES, then nothing. The driver comes first: a request does not start while the
  other side or the hazards are on, ends as soon as the other side shows activity, and stays off after such an override
  until the request drops. The requested side already blinking is the driver asking for the same thing."""

  def __init__(self, CP):
    self.enabled = bool(CP.flags & HyundaiFlags.CANFD_SPAS2_BLINKERS)
    self.frame = 0
    self.active = NEUTRAL
    self.last_active = NEUTRAL
    self.release_frames = 0
    self.overridden = False
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

  def update(self, CC, CC_IQ, CS) -> int | None:
    """The BLINKER_CONTROL value to send on this control frame, or None to send nothing."""
    if not self.enabled:
      return None
    self.frame += 1

    left, right, known = self.car_blinkers(CS)
    request = LEFT if CC.leftBlinker and not CC.rightBlinker else RIGHT if CC.rightBlinker and not CC.leftBlinker else NEUTRAL
    aol = CC_IQ.aol
    engaged = CC.enabled or (aol.available and aol.enabled and aol.active)
    allowed = engaged and known

    if not CC.leftBlinker and not CC.rightBlinker:
      self.overridden = False

    if self.active != NEUTRAL:
      other_side = right if self.active == LEFT else left
      if other_side:
        self.overridden = True
      if request != self.active or not allowed or other_side:
        self.active = NEUTRAL
        self.release_frames = RELEASE_FRAMES
    elif request != NEUTRAL and allowed and not self.overridden and not (right if request == LEFT else left):
      # the other side waits for the release to finish, so the car always sees neutral in between
      if request == self.last_active or self.release_frames == 0:
        self.active = self.last_active = request

    if self.active != NEUTRAL:
      control = self.active
    elif self.release_frames > 0:
      self.release_frames -= 1
      control = NEUTRAL
    else:
      return None
    return control if self.frame % SEND_EVERY == 0 else None
