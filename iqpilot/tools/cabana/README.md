# Cabana

Cabana is IQ.Pilot's desktop CAN analysis tool. It uses ImGui and GLFW on macOS and Linux without Qt.

Run it through the project command:

```bash
iq cabana
```

Cabana can open a local route, a Konn3kt route, a Panda, SocketCAN on Linux, local msgq, or a remote ZMQ stream.

```bash
iq cabana "dongle_id|2026-09-02--12-00-00"
iq cabana --panda
iq cabana --msgq
iq cabana --zmq 192.168.1.10
iq cabana --bridge 192.168.1.10
```

The executable is built on demand by `iqpilot/tools/cabana/cabana`. IQ.Pilot prebuilt device checkouts intentionally omit desktop analysis tools.

## Konn3kt authentication

Choose **Browse Konn3kt routes** to sign in with Google, GitHub, Apple, or Microsoft. Cabana opens Konn3kt's provider endpoint in your browser and returns to the route picker after authentication. The tools helper and replay share `~/.iq/auth.json`.

Browser sign-in requires Konn3kt's localhost tools callback support. The matching backend change is in `src/controllers/oauth.rs` in the Konn3kt repository. The callback is restricted to localhost, an explicit port, `/auth`, and a per-login state value; the token arrives in a URL fragment and is validated with `/v1/me` before saving.

## Manual upstream port

Reviewed upstream master at `5f50bda7ba1a78862d0886c75f03125446bc6f1b` against the previous port baseline `06d76bdb24b9f5f3e69120782e8e3eb54a2f4f7e`.

Ported chart downsampling and range fixes, strict message ID parsing, recorded-message selection, replay/thread shutdown fixes, frame pacing, video crop and startup fixes, native dock panels, dropdowns, signal layout, theme improvements, and the FPS indicator.

IQ.Pilot retains its launch workspace, IQDBC package integration, C++ Konn3kt route downloads, live CAN proxy and stream modes, and road/driver/wide-road camera mapping. Upstream's Python downloader, Qt migration, binary-wrapper removal, and comma OAuth configuration were excluded.

The route browser verifies your session before listing devices or drives. Missing, invalid, expired, or revoked logins return to the provider chooser. Use **Sign in again** to replace a saved login; network failures offer a retry without discarding your token.
