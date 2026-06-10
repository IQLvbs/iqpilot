import os
import re

import zstandard as zstd
from cereal import log as capnp_log

MIN_UPLOAD_DURATION_S = 120.0
MIN_UPLOAD_DISTANCE_M = 50.0  # treat as 0 mi on connect

ROUTE_ID_RE = re.compile(r"^(?P<route_id>.+)--(\d+)$")


def route_id_from_segment(segment_dir: str) -> str | None:
  m = ROUTE_ID_RE.match(segment_dir)
  return m.group("route_id") if m else None


def _read_qlog_bytes(path: str) -> bytes | None:
  try:
    with open(path, "rb") as f:
      data = f.read()
  except OSError:
    return None
  if not data:
    return None
  if data.startswith(b"\x28\xB5\x2F\xFD"):
    try:
      dctx = zstd.ZstdDecompressor()
      with dctx.stream_reader(data) as reader:
        data = reader.read()
    except Exception:
      return None
  return data


def _compute_segment_stats(qlog_path: str) -> tuple[float, float] | None:
  data = _read_qlog_bytes(qlog_path)
  if data is None:
    return None

  try:
    events = capnp_log.Event.read_multiple_bytes(data)
  except Exception:
    return None

  first_mono = None
  last_mono = None
  distance_m = 0.0
  prev_mono = None
  prev_v = 0.0

  for evt in events:
    try:
      if evt.which() != "carState":
        continue
    except Exception:
      continue

    mono = evt.logMonoTime
    if first_mono is None:
      first_mono = mono
    last_mono = mono

    v = evt.carState.vEgo
    if prev_mono is not None and mono > prev_mono:
      dt = (mono - prev_mono) / 1e9
      distance_m += (prev_v + v) * 0.5 * dt
    prev_mono = mono
    prev_v = v

  if first_mono is None or last_mono is None:
    return None
  return (last_mono - first_mono) / 1e9, distance_m


def _segment_dirs(root: str, route_id: str) -> list[str]:
  prefix = route_id + "--"
  try:
    names = os.listdir(root)
  except OSError:
    return []
  return sorted(n for n in names if n.startswith(prefix) and os.path.isdir(os.path.join(root, n)))


def compute_route_stats(root: str, route_id: str) -> tuple[float, float] | None:
  total_duration = 0.0
  total_distance = 0.0
  found_any = False

  for segment_dir in _segment_dirs(root, route_id):
    seg_path = os.path.join(root, segment_dir)
    if any(name.endswith(".lock") for name in os.listdir(seg_path)):
      return None

    qlog_path = os.path.join(seg_path, "qlog")
    if not os.path.isfile(qlog_path):
      continue

    stats = _compute_segment_stats(qlog_path)
    if stats is None:
      continue
    found_any = True
    total_duration += stats[0]
    total_distance += stats[1]

  if not found_any:
    return None
  return total_duration, total_distance


def should_skip_route_upload(root: str, route_id: str) -> bool | None:
  stats = compute_route_stats(root, route_id)
  if stats is None:
    return None
  duration_s, distance_m = stats
  return duration_s < MIN_UPLOAD_DURATION_S or distance_m < MIN_UPLOAD_DISTANCE_M
