#!/usr/bin/env python3
"""
konn3kt_canproxy — view a remote device's live CAN in Cabana, through konn3kt.

Run this on your laptop. It connects to the konn3kt CAN stream for a device you have
access to and re-publishes the raw capnp frames onto a LOCAL ZMQ "can" socket. Then you
just open Cabana → Live → Device, pick ZMQ, and enter 127.0.0.1 — exactly the local
workflow, but the frames are coming from a device across the internet.

Flow:
    device canlived ──ws──> konn3kt relay ──ws──> THIS PROXY ──zmq──> Cabana (127.0.0.1)

The proxy never parses the CAN bytes; it forwards the exact capnp Event frames the device
produced, so Cabana decodes them identically to a local ZMQ bridge.

Auth: you authenticate as yourself (a konn3kt user JWT), not as the device. Get your JWT
from the konn3kt app/web session and pass it via --token or the KONN3KT_JWT env var.
Access is enforced server-side (owner-only, or a superuser with an explicit owner grant).

Usage:
    export KONN3KT_JWT="<your konn3kt jwt>"
    ./konn3kt_canproxy.py <dongle_id>
    # then in Cabana: Live → Device → ZMQ → 127.0.0.1

Requires the iqpilot/openpilot Python env (for cereal.messaging) and websocket-client.
"""
import argparse
import os
import sys
import time

from websocket import create_connection, ABNF, WebSocketException

# Force cereal messaging onto ZMQ so the local "can" publisher binds a TCP port that
# Cabana's ZMQ Device stream connects to. Must be set before importing messaging.
os.environ["ZMQ"] = "1"
import iqpilot.cereal.messaging as messaging  # noqa: E402

DEFAULT_HOST = os.getenv("KONN3KT_HOST", "wss://api-iqlabs.konn3kt.com")
RECONNECT_MIN = 1.0
RECONNECT_MAX = 10.0


def _ws_host(host: str) -> str:
  host = host.rstrip("/")
  if host.startswith("https://"):
    return "wss://" + host[len("https://"):]
  if host.startswith("http://"):
    return "ws://" + host[len("http://"):]
  if host.startswith(("ws://", "wss://")):
    return host
  return "wss://" + host


def run(dongle_id: str, host: str, token: str) -> None:
  ws_uri = f"{_ws_host(host)}/v1/devices/{dongle_id}/can-stream?sig={token}"
  # Local ZMQ publisher for "can"; Cabana subscribes to this on 127.0.0.1.
  pub = messaging.pub_sock("can")

  backoff = RECONNECT_MIN
  while True:
    try:
      print(f"[canproxy] connecting to konn3kt for {dongle_id} ...", file=sys.stderr)
      ws = create_connection(ws_uri, enable_multithread=True, timeout=30.0)
      print("[canproxy] connected. Open Cabana → Live → Device → ZMQ → 127.0.0.1", file=sys.stderr)
      backoff = RECONNECT_MIN
      n = 0
      while True:
        opcode, data = ws.recv_data(control_frame=True)
        if opcode == ABNF.OPCODE_BINARY:
          # Republish the exact capnp Event bytes locally.
          pub.send(data)
          n += 1
          if n % 1000 == 0:
            print(f"[canproxy] forwarded {n} frames", file=sys.stderr)
        elif opcode == ABNF.OPCODE_CLOSE:
          print("[canproxy] server closed the stream", file=sys.stderr)
          break
        elif opcode == ABNF.OPCODE_PING:
          ws.pong(data)
    except (WebSocketException, OSError) as e:
      print(f"[canproxy] disconnected: {e}; reconnecting in {backoff:.0f}s", file=sys.stderr)
      time.sleep(backoff)
      backoff = min(backoff * 2, RECONNECT_MAX)
    finally:
      try:
        ws.close()
      except Exception:
        pass


def main() -> None:
  ap = argparse.ArgumentParser(description="Bridge a konn3kt remote CAN stream into local ZMQ for Cabana.")
  ap.add_argument("dongle_id", help="dongle id of the device to stream")
  ap.add_argument("--host", default=DEFAULT_HOST, help=f"konn3kt host (default: {DEFAULT_HOST})")
  ap.add_argument("--token", default=os.getenv("KONN3KT_JWT"),
                  help="konn3kt user JWT (or set KONN3KT_JWT)")
  args = ap.parse_args()

  if not args.token:
    ap.error("no token: pass --token or set KONN3KT_JWT")

  try:
    run(args.dongle_id, args.host, args.token)
  except KeyboardInterrupt:
    print("\n[canproxy] bye", file=sys.stderr)


if __name__ == "__main__":
  main()
