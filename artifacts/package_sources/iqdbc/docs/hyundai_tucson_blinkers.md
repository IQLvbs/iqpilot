# Tucson turn signals through SPAS2

An opt-in output path that lets `CarControl.leftBlinker` / `rightBlinker` flash the real turn
signals on a 4th-generation Tucson with HDA1, camera SCC and no parking ECU, and a small helper
that uses it to keep a tapped signal on through a lane change. Off by default. Tried on one car.

## What was seen on the car

2024 Tucson SE, gas, HDA1 CAN-FD, camera SCC, body unit (ICU) part `91951CW133`. The car does
not send SPAS1 (`0x165`) or SPAS2 (`0x16A`) itself.

| Request | BLINKER_CONTROL | Byte 16 | Seen |
| --- | ---: | ---: | --- |
| Left | 3 | `0x60` | Left lamps flash for as long as it is sent |
| Right | 4 | `0x80` | Right lamps flash for as long as it is sent |
| Neutral | 0 | `0x00` | Sent for 3 s after each request; the lamps are off about 0.7 s after the request ends |

The request is SPAS2 alone: `0x16A`, 32 bytes, car-side bus 0, 50 Hz, with the usual Hyundai
CAN-FD checksum and counter. No SPAS1, no diagnostic session, no ECU disable.

On the road (November 2026): 102 holds, 83 lane changes with the car steering, the signal on
for the whole lane change in 82 of them and off as it ended. No frame was sent outside a hold
and the panda raised no fault.

Three things about this car worth knowing:

- `BLINKERS` (`0x413`) `LEFT_STALK` / `RIGHT_STALK` turn on with the first flash and stay set for
  a whole one-touch blink after the lever is back in the middle. They follow the blink, not the
  lever, and our own request sets them too.
- The car answers SPAS2 with a message of its own, `0x1C0` (bus 0, 24 bytes, 50 Hz, not in the
  DBC). It starts about 3 s after the first SPAS2 frame of a drive and runs until switch-off.
  Its meaning is not known.
- Once, 0.4 s after a hold that had run out its 10 s wait let go, both lamps gave a single flash
  with the car's hazard flag set. The comma was sending only neutral. Cause unknown; it did not
  happen after four later holds that also ran out.

## How it works

**Opt-in.** `HyundaiSpas2Blinkers` has to be set, and the car has to match the layout it was
tried on: `HYUNDAI_TUCSON_4TH_GEN`, HDA1, camera SCC, not hybrid or EV, the same button and gear
messages, `BLINKERS` on the car-side bus, and no SPAS1 or SPAS2 in the fingerprint. That sets
`HyundaiFlags.CANFD_SPAS2_BLINKERS` and the matching safety param bit. It is separate from
`ENABLE_BLINKERS`, which also sends SPAS1 and disables the parking ECU.

**Controller** (`car/hyundai/spas2.py`). Idle sends nothing. A request sends that direction for
as long as it is held, then neutral for 3 s, then nothing.

- Only while engaged in the sense steering uses: `CC.enabled`, or always-on lateral active. Not
  `CC.latActive`: braking for a turn drops cruise and leaves lateral on, and at a standstill
  `CC.latActive` is false on this platform. The signal has to survive both.
- Only while `BLINKERS` is arriving, so the driver's side is always visible.
- The driver comes first. A request does not start while the other side or the hazards are on,
  ends as soon as the other side shows activity, and then stays off until the request drops.
  The requested side already blinking is the driver asking for the same thing.
- The other side only starts after the 3 s of neutral.

**Panda** (`safety/modes/hyundai_canfd.h`). With the safety param bit set on HDA1 camera SCC,
`0x16A` on bus 0 joins the allowed messages. The payload may only be neutral, left or right with
everything else empty. A direction needs `is_lat_active()`, the permission steering uses; neutral
is always allowed so a request can be released. The message uses `check_relay`.

## A tapped signal held through the lane change

`iqpilot/selfdrive/controls/lib/lane_change_signal.py`, called from `controlsd.py` next to the
navigation controller and only with this opt-in.

A tap gives the car's own three flashes, about 2 s. A lane change takes about 5 s after the
nudge, so the lamps go out about 2.8 s before the car has finished. Pushing the stalk home keeps
the signal on, but it then has to be cancelled by hand.

- Starts when a turn signal's lamps come on at 20 mph or more with lateral control active, the
  other side and the hazards off, and navigation not asking for a signal.
- Holds while `modelV2.meta.laneChangeState` waits for the nudge or changes lanes in that
  direction. It must see that within 2 s.
- Lets go when the state turns to `laneChangeFinishing`: the car is in its new lane, and the
  lamps are out before the logic could take a push on the wheel as a new nudge.
- Also lets go when the logic goes back to off, after 10 s of waiting with no nudge, after 1 s of
  steering the other way while it waits, at any signal on the other side or the hazards, when
  lateral control drops, when navigation asks for the other side, or after 20 s in all.
- A stalk pushed home keeps its own signal on regardless: the car follows the lever.

## What navigation needs

The navigation turn-signal code does not produce requests for this car today. To use this path
it has to admit a car with `HyundaiFlags.CANFD_SPAS2_BLINKERS`, hold exactly one of
`leftBlinker` / `rightBlinker` for as long as the signal is wanted (the lamps follow the level),
not tie the request to `CC.latActive` (false at every stop on Hyundai), and drop and raise the
request again after a driver override.

## Not checked

- Requests from navigation: none has been made on this car.
- What the lamps do if the frames just stop with no neutral (a process restart).
- Other Tucson years and trims, and other Hyundai or Kia cars. The layout check only knows that
  they look the same on the bus; each needs a parked test first.
