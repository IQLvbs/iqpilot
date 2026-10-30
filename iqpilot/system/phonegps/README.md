# PhoneGPS

`IQPhoneGPSEnabled` is persistent and defaults to `0`. Changing it during a drive takes effect without restarting navigation or either hardware GPS producer. A phone must also opt in locally and grant precise background location permission.

On TICI-family devices, `phonegpsd` forwards the selected hardware GPS stream to its existing Cereal service. With PhoneGPS disabled or without a usable phone fix, hardware packets retain their original bytes, validity, source, and timestamps. Hardware acquisition continues while phone fixes are selected. Replay and non-device execution retain the original publisher endpoints.

The receiver accepts a recent, authenticated nearby session through Hephaestus BLE or LAN LocalAPI. Cloud submission is rejected. Its RPC methods are `getPhoneGPSStatus`, `beginPhoneGPS`, `sendPhoneGPS`, and `stopPhoneGPS`. The persistent switch is written through the existing boolean-param RPC.

The phone estimates the device's monotonic clock using a bounded round trip. Measurements retain their capture time. The receiver rejects expired sessions, duplicate or reordered samples, excessive clock uncertainty, stale measurements, invalid coordinates, poor accuracy, mock fixes, and implausible jumps. No queued historical fixes are replayed and no position is extrapolated through a tunnel. A selected fix expires after two seconds; hardware then resumes automatically. Fresh accepted phone fixes can take over again in the same drive.

The app sends WGS84 ellipsoidal altitude, including the explicit Core Location ellipsoidal field on iOS. Missing course is accepted only when stationary. Location samples are not persisted by the phone feature, but the selected GPS enters normal IQPilot drive logs.

The daemon uses the owner-only Unix datagram socket `/dev/shm/iq-phonegps/rpc.sock`. Requests and per-loop work are bounded. Only the latest pending mobile fix is kept. Permission or account/device changes stop submission; the device independently expires a missing feed.

## Validation

Run `pytest iqpilot/system/phonegps/test_phonegps.py` for packet passthrough, both canonical GPS services, immediate toggling, stale fallback, recovery, malformed inputs, session isolation, and live Unix-socket/Msgq transport. Private RPC tests are in `konn3kt_private/tests/test_phonegps_rpc.py`. Mobile protocol tests are in `ios-app/scripts/test-phone-gps.ts` in Konn3kt.

Source tests do not certify background delivery, transport timing under onroad CPU load, or source handoff on physical devices. Before deployment, rebuild the private Hephaestus bundle and both native apps, then verify iOS and Android with foreground/background permissions, BLE-only and LAN-only links, device GPS loss, phone GPS loss, network handover, disconnect/reconnect, and the feature disabled. Force-quitting the mobile app is not a supported guarantee of continued GPS delivery.
