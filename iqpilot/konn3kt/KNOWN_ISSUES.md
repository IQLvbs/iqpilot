# Konn3kt cloud console — known issues (app.konn3kt.com)

Device-side param wire encoding and local UI sync are fixed in this repo.
The items below require changes in the **Konn3kt web frontend** and/or **hephaestusd** (proprietary).

Verified on device `510fb287097868b1` (richard_di), 2026-07-01.

## Fixed here (device / openpilot)

| Web setting | Device param | Status |
|-------------|--------------|--------|
| Always On Lateral | `AolEnabled` | OK |
| Toggle With Cruise Main | `AolMainCruiseAllowed` | OK |
| Lane Line Planner | `IQLanePlanner` | OK |
| IQ.Pilot Longitudinal Control | `AlphaLongitudinalEnabled` | OK (+ `LongitudinalControlMode` sync via hephaestusd patch) |
| Steering Mode on Brake Pedal | `AolSteeringMode` (INT) | OK |
| Enable WebSSH | `SshEnabled` | OK (REST, not bool RPC) |
| Cellular Uploads | `OnroadUploads` | OK (device-side `GsmMetered` alias in `hephaestusd.py`) |

Bool wire format is on-disk `0`/`1` via `param_to_bytes` / `param_from_base64`.
Web RPC writes bump `ParamsVersion` and sync longitudinal backing keys via `iqpilot/konn3kt/hephaestus/hephaestusd.py`.

## Frontend — still uses wrong RPC key (device workaround in place)

### 1. Cellular Uploads → wrong param name in app bundle

- **App UI:** "Cellular Uploads" toggle
- **App RPC:** `setBoolParam("GsmMetered", !value)` and read via `!GsmMetered`
- **Device param:** `OnroadUploads` (no inversion)
- **Workaround (2026-07-01):** `hephaestusd.py` maps `GsmMetered` ↔ `OnroadUploads` and serves `OnroadUploads` on RPC
- **Proper fix:** konn3kt app bundle — replace `GsmMetered` with `OnroadUploads`, remove negation

## Fixed here (hephaestusd wrapper)

### ~~2. `OnroadUploads` not in hephaestusd RPC whitelist~~

Handled in open-source `hephaestusd.py` wrapper (direct read/write + `GsmMetered` alias).

### ~~3. `LongitudinalControlMode` stale after web bool toggle~~

`setBoolParam` wrapper calls `sync_longitudinal_control_mode` for `LONGITUDINAL_BACKING_KEYS`.

### ~~4. `ParamsVersion` not bumped on web RPC~~

`setBoolParam` wrapper calls `bump_params_version` after remote bool writes.

Verify on device: `PYTHONPATH=/data/openpilot python3 iqpilot/konn3kt/tests/verify_bool_toggle_rpc.py`
