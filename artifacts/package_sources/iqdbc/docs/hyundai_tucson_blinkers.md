# Tucson navigation blinkers through SPAS2

The goal is to connect IQ navigation's turn-signal requests to the exterior lamps
on the tested 2024 Tucson SE gas: HDA1 CAN-FD, camera SCC, ICU `91951CW133`.
This is an integration proposal supported by a vehicle experiment and executable
packet tests. The helper extraction alone does not enable navigation blinkers.

## Message verified on the vehicle

Send **SPAS2 only**, CAN-FD `0x16A`, 32 bytes, on car-side logical bus 0 at
**50 Hz**. Use the DBC packer for the rolling byte-2 counter and Hyundai CRC.

| Request | `BLINKER_CONTROL` | Byte 16 | Evidence |
| --- | ---: | ---: | --- |
| Right | 4 | `0x80` | Exterior lamps observed in Park and stationary Drive |
| Left | 3 | `0x60` | Existing protocol encoding; physical response not tested |
| Neutral | 0 | `0x00` | Packets transmitted; neutral-only physical release not isolated |

The stationary Drive test used a held service brake. A temporary native-panda
fixture sent the right request followed by three seconds of neutral. No SPAS1,
UDS lamp command or parking-ECU disable was used. Earlier lamp-stop confirmation
followed ignition OFF, so it does not establish neutral-only release timing.

## Navigation-to-lamps implementation

1. **Keep the existing navigation interface.**
   `iqpilot/selfdrive/controls/controlsd.py` already assigns
   `CC.leftBlinker` and `CC.rightBlinker` from `NavTurnSignalController.update()`.
   That controller is private; maintainers need to confirm Hyundai eligibility,
   request lifetime and cancellation inside it.
2. **Select this receiver narrowly.**
   Add a separate SPAS2-only capability, such as a new
   `CANFD_SPAS2_BLINKERS` flag, for the validated variant. The Tucson platform
   enum also includes hybrid and plug-in variants. The current firmware query
   does not automatically identify this ICU part number in CarParams.
3. **Connect the Hyundai output.**
   In `car/hyundai/carcontroller.py`, pass the existing CC blinker requests to
   `hyundaicanfd.create_spas2_message()` on `CAN.ECAN` (tested as bus 0).
   Schedule at 50 Hz: every second frame of the existing 100 Hz loop. Keep the
   existing HDA2 SPAS1/SPAS2 path intact. Specify and validate a finite neutral
   release sequence with continuous counters on request cancellation or timeout.
4. **Keep this separate from `ENABLE_BLINKERS`.**
   That existing flag disables parking ECU `0x7B1` in `interface.py`; its
   controller code also contains parking-ECU tester-present, while the HDA2
   sender bundles SPAS1 with SPAS2. Those actions were not needed for this
   receiver. Simply setting that flag does not add the missing HDA1 output.
5. **Add normal Hyundai panda admission.**
   `safety/modes/hyundai_canfd.h` currently lacks `0x16A` in its HDA1 TX lists.
   Add a dedicated capability-specific bus/length/payload/CRC/counter/rate policy,
   with reviewed request expiry and sender-conflict handling. Preserve the normal
   steering, SCC and relay protections. The experimental firmware is not a
   replacement for the production safety policy.
6. **Handle driver intent independently of lamp feedback.**
   Hyundai `carstate.py` derives blinkers from `BLINKERS` lamp status and holds
   that feedback for 50 frames. These are lamp-status fields, not a verified
   independent stalk-intent signal. Verify whether SPAS2-driven lamps feed those
   fields, and handle that feedback without treating it as a new driver request.
   Confirm driver/hazard arbitration and closed-loop navigation/ALC behavior.

## Evidence and remaining validation

The right-side CAN path works on this receiver while stationary. Left activation,
neutral-only release in both directions, stalk/hazard priority, moving acceptance
and actual navigation triggering/cancellation remain to be validated. These gaps
need not delay review of the proposed implementation, but the current result
should not be labeled navigation-ready.

`car/hyundai/tests/test_spas2.py` checks real CANPacker output against independent
CRC/golden vectors, counter wrap, both-direction encoding, and unchanged legacy
SPAS1/SPAS2 ordering and counters on ECAN 0/1. Packet tests do not substitute for
exterior-lamp or driver-override observations.
