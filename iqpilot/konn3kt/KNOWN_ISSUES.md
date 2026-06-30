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
| IQ.Pilot Longitudinal Control | `AlphaLongitudinalEnabled` | OK |
| Steering Mode on Brake Pedal | `AolSteeringMode` (INT) | OK |
| Enable WebSSH | `SshEnabled` | OK (REST, not bool RPC) |

Bool wire format is now on-disk `0`/`1` via `param_to_bytes` / `param_from_base64`.

## Frontend / hephaestusd — still broken

### 1. Cellular Uploads → wrong param

- **Web UI:** "Cellular Uploads" toggle
- **Actual RPC:** `setBoolParam("GsmMetered", !value)` and read via `!GsmMetered`
- **Should be:** `OnroadUploads` (no inversion)
- **Evidence:** toggling web ON sets `GsmMetered=False` while `OnroadUploads` stays unchanged; initial `OnroadUploads=True` shows as web OFF
- **Fix:** konn3kt frontend bundle — replace `GsmMetered` with `OnroadUploads`, remove negation

### 2. `OnroadUploads` not in hephaestusd RPC whitelist

- `getBoolParams` / `setBoolParam` return `invalid param` for `OnroadUploads`
- **Fix:** add `OnroadUploads` to hephaestusd allowed bool keys (proprietary `.so`)

### 3. `LongitudinalControlMode` stale after web bool toggle

- Web `setBoolParam("AlphaLongitudinalEnabled", false)` updates the bool but not `LongitudinalControlMode`
- Device UI path calls `sync_longitudinal_control_mode`; web RPC bypasses `iqpilot/konn3kt/common/params.py`
- **Fix:** hephaestusd should route bool writes through `param_from_base64` or call sync for `LONGITUDINAL_BACKING_KEYS`

### 4. `ParamsVersion` not bumped on web RPC

- Local UI and `param_from_base64` increment `ParamsVersion`; web `setBoolParam` does not
- **Fix:** hephaestusd should call `bump_params_version` after remote param writes
