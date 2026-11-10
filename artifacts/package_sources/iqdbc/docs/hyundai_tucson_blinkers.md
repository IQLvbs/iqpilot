# Tucson navigation blinkers

This development integration connects the existing `CarControl.leftBlinker` and
`rightBlinker` requests to SPAS2 on the tested 2024 Tucson SE gas, HDA1 CAN-FD,
camera SCC, ICU `91951CW133`. It is disabled by default and is not validated for
driving.

## Vehicle evidence

| Request | BLINKER_CONTROL | Byte 16 | Physical evidence |
| --- | ---: | ---: | --- |
| Right | 4 | `0x80` | Exterior lamps observed in Park and stationary Drive |
| Left | 3 | `0x60` | Protocol encoding only; not physically tested |
| Neutral | 0 | `0x00` | Transmitted; neutral-only release not isolated |

The observed right request used CAN-FD `0x16A`, 32 bytes, logical bus 0 at 50 Hz,
with the normal Hyundai CRC and rolling counter. The stationary Drive test used
a held service brake. No SPAS1, diagnostic lamp command or parking ECU disable
was needed. Ignition-off lamp release does not prove neutral-only release.

## Implementation contract

Use a separate Hyundai capability and normal safety parameter; leave the existing
HDA2 `ENABLE_BLINKERS` path intact. That older capability also disables parking
ECU `0x7B1` and must not be enabled as a shortcut.

The host controller receives the original CarControl publisher timestamp and
validity, checks actual CAN receive timestamps, limits direction duration, and sends
a finite neutral sequence on cancellation. A held request cannot continuously
restart itself after its duration limit. One CANPacker owns the packet counter.
The filtered CarState lamp status does not establish independent driver intent.
After idle, a new request first sends a bounded neutral preamble lasting about
3.1 seconds, plus scheduling and transport. It activates only if that same request remains fresh and all
gates still hold. This latency requires actual navigation lead-time validation.

Panda admission constrains address, bus, length, reserved bits, control,
CRC, counter, rate and request lifetime without weakening normal steering, SCC,
relay, heartbeat or SILENT protections. A separate feature buffer and final
hardware-transmission check are used: TX-hook admission alone cannot expire
a frame already queued in the CAN controller. Cleanup must affect only feature
traffic.

The MCU lease measures time since packet admission. SPAS2 contains no original
CarControl timestamp, so this does not prove end-to-end command age. A
replace-latest buffer can also create gaps in the wire counter sequence.

This version generates no MCU neutral packets. Dropping or aborting stale output
does not establish that the receiver released a lamp request. Host loss, reset,
SILENT, bus faults and ignition transitions may prevent any neutral transmission.

## Navigation integration

The private navigation producer is unchanged. Its next build needs to admit this
Tucson and publish the existing `CarControl` fields; a vehicle allowlist change
alone does not activate or qualify the lamp controller.

- Use the separate `HyundaiFlags.CANFD_SPAS2_BLINKERS` capability for this path.
  Do not set the existing HDA2 `ENABLE_BLINKERS` flag or disable a parking ECU.
- Publish exactly one of `leftBlinker` or `rightBlinker` while requesting that
  direction, with `enabled` and `latActive` true. Continuously refresh valid
  `carControl` messages; the controller rejects source age above 100 ms. Card
  supplies the original publisher timestamp, so no navigation timestamp API is
  needed.
- Publish both directions false to cancel and to rearm before another request.
  The controller must first observe a fresh neutral request. A held direction
  cannot restart itself after the ten-second direction limit.
- Allow about 3.1 seconds of neutral preparation, plus scheduling/transport,
  before directional output. Keep the requested direction valid throughout
  that interval; a brief pulse does not activate the lamps. Validate navigation
  lead time against the actual maneuver.
- Review how the private producer interprets `CarState.leftBlinker` and
  `rightBlinker`: these are lamp feedback, not independent proof of stalk input.
  Its response to lamps activated by its own request still needs verification.

A combined stable-release build has been installed and boot-checked with the
expected controller imports and Panda firmware signature. Lamp output remains
disabled; no positive qualification record was installed. This startup check
does not qualify navigation operation or add to the physical lamp evidence above.

## Activation remains unqualified

No positive qualification file is distributed. Activation requires a private,
explicit opt-in bound to the vehicle VIN hash and the tested ICU part, supported
by recorded physical checks. A platform match or a syntactically valid file is
not evidence of those checks.

Before activation, verify both directions, neutral-only release, receiver
self-timeout, independent stalk decoding, driver and hazard priority, counter-gap
acceptance, actual navigation triggering/cancellation, and operation while moving
in a controlled setting. Also review the feature-specific CAN mailbox layout and
its transitions on the actual board. Offline tests and a successful firmware
build do not establish these vehicle properties.

## Board behavior requiring bench validation

The Cuatro H7 path reserves one dedicated TX mailbox while retaining the normal
46 RX elements and one TX FIFO element per controller. When allocation changes,
all three cores enter INIT and configuration-change enable before any shared RAM
address changes; all ranges are programmed before any core is restarted. A
partial configuration keeps the cores stopped. The feature stays inhibited until
MCU restart after a harness mapping change. Other hardware does not emit feature
packets.

The final gate checks physical context and effective CAN-FD mode. It uses a local
generation ticket in addition to the wrapping wire counter and cancels only the
owned mailbox. A cancellation request cannot retract a frame already on the
wire. Firmware polling latency, cancellation acknowledgement and recovery from
layout/initialization failures still need actual-board measurements.

The one-element normal TX FIFO also satisfies the dedicated-buffer/FIFO ordering
workaround in ST ES0491 section 2.22.2:
https://www.st.com/resource/en/errata_sheet/es0491-stm32h72xx73xx-device-errata-stmicroelectronics.pdf

The configuration-change reset boundary follows Bosch M_CAN User Manual 3.3.1,
section 3.1.1, printed page 58. This is design evidence, not a board test:
https://www.bosch-semiconductors.com/media/ip_modules/pdf_2/m_can/mcan_users_manual_v331.pdf
