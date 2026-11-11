# Tucson turn signals through SPAS2

An opt-in output path that lets `CarControl.leftBlinker` / `rightBlinker` flash the real turn
signals on a 4th-generation Tucson with HDA1, camera SCC and no parking ECU. It is off by
default and has only been tried on one car, standing still.

## What was seen on the car

2024 Tucson SE, gas, HDA1 CAN-FD, camera SCC, body unit (ICU) part `91951CW133`. The car does
not send SPAS1 (`0x165`) or SPAS2 (`0x16A`) itself.

| Request | BLINKER_CONTROL | Byte 16 | Seen |
| --- | ---: | ---: | --- |
| Right | 4 | `0x80` | Right lamps flashed, in Park and in Drive at a standstill |
| Left | 3 | `0x60` | Not tried |
| Neutral | 0 | `0x00` | Sent after each right request. Not shown to be what stops the lamps |

The request was SPAS2 alone: `0x16A`, 32 bytes, car-side bus 0, 50 Hz, with the usual Hyundai
CAN-FD checksum and counter. Each test sent the right request first and neutral for 3 s after
it, with no neutral beforehand. No SPAS1, no diagnostic session and no ECU disable were
involved. The frames came from a temporary test build of the panda firmware, not from this code.

The lamps were watched by eye. In Park, a one-second request was not seen the first time and
was seen on an identical repeat. In Drive, a ten-second request was seen. In Park the lamps
were confirmed off only after the car had been switched off.

## How it works

**Opt-in.** `HyundaiSpas2Blinkers` has to be set, and the car has to match the layout it was
tried on: `HYUNDAI_TUCSON_4TH_GEN`, HDA1, camera SCC, not hybrid or EV, the same button and
gear messages, `BLINKERS` (`0x413`) on the car-side bus, and no SPAS1 or SPAS2 in the
fingerprint. That sets `HyundaiFlags.CANFD_SPAS2_BLINKERS` and the matching safety param bit.
It is separate from `ENABLE_BLINKERS`, which also sends SPAS1 and disables the parking ECU.

**Controller** (`car/hyundai/spas2.py`):

- Idle sends nothing. A request sends that direction at 50 Hz for as long as it is held, then
  neutral for 3 s, then nothing again. This is the sequence used on the car.
- Only while `CC.enabled`, and only while `BLINKERS` is arriving, so the driver's side is
  always visible.
- The driver comes first. A request does not start while a turn signal or the hazards are on.
  It ends as soon as the other side shows activity, from the stalk bits or the lamps.
- Activity on the requested side does not end it. `LEFT_STALK` / `RIGHT_STALK` stay set for a
  whole one-touch blink after the lever is back in the middle, so they follow the blink and not
  the lever. Our own request may set them as well, and it certainly lights the lamps.
- A request that has ended must drop before it can start again. One that is still held after
  the driver overrode it stays off.

**Panda** (`safety/modes/hyundai_canfd.h`): with the safety param bit set on HDA1 camera SCC,
`0x16A` on bus 0 is added to the allowed messages. The payload may only be neutral, left or
right with everything else empty. A direction needs `controls_allowed`; neutral is always
allowed so a request can be released after disengaging. The message uses `check_relay`: if
anything else sends `0x16A` on the car side, that is a relay malfunction. Nothing in the
firmware's CAN driver changes.

## What navigation needs

The navigation turn-signal code is private and currently does not produce requests for this
car. For this path to do anything it has to:

- treat `HyundaiFlags.CANFD_SPAS2_BLINKERS` as a car that supports turn-signal requests;
- hold exactly one of `leftBlinker` / `rightBlinker` for as long as the signal is wanted, and
  drop it to stop;
- drop and raise the request again after the driver overrode it;
- allow for `CarState.leftBlinker` / `rightBlinker` being lamp feedback on this car: they turn
  on because of the request, not only because of the driver.

## Not checked on a car yet

Nothing below has been tried. All of it should be, parked first, before this is used on the
road.

- Left.
- How quickly the lamps start on the first request after start-up.
- That the lamps stop on neutral, and how long that takes.
- What the lamps do if the frames just stop, with no neutral (process restart, ignition off).
- That the stalk and the hazards still work normally while neutral is being sent, and win
  over a request.
- What `0x413` reports while a request is active. The controller is written so that either
  answer is safe, but it decides whether the stalk bits can ever tell the driver apart.
- Any of it while moving, and any of it driven by the real navigation code.
- Other Tucson years and trims. The layout check only knows they look the same on the bus.
