#!/usr/bin/env python3
import io
import os
from collections.abc import Iterator

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware.hw import Paths
from openpilot.system.loggerd.config import SEGMENT_LENGTH
from openpilot.system.loggerd.xattr_cache import setxattr

UPLOAD_ATTR_NAME = 'user.upload'
UPLOAD_ATTR_VALUE = b'1'

MIN_UPLOAD_DURATION_S = float(os.getenv("UPLOAD_MIN_DURATION_S", "120"))  # 2 minutes


def is_zero_km(distance_m: float) -> bool:
  # ponytail: match connect UI rounding (0.1 km); sub-50 m displays as 0 km
  return round(distance_m * 0.001, 1) <= 0.0


def get_directory_sort(d: str) -> list[str]:
  o = ["0", ] if d.startswith("2024-") else ["1", ]
  return o + [s.rjust(10, '0') for s in d.rsplit('--', 1)]


def get_route_base(logdir: str) -> str | None:
  if logdir in ("crash", "boot") or "--" not in logdir:
    return None
  return logdir.rpartition("--")[0]


def get_route_base_from_path(path: str) -> str | None:
  norm_path = os.path.normpath(path)
  for root in (Paths.log_root(), Paths.log_root_external()):
    root = os.path.normpath(str(root))
    try:
      rel = os.path.relpath(norm_path, root)
    except ValueError:
      continue
    if rel.startswith(".."):
      continue
    segment = rel.split(os.sep, 1)[0]
    if not segment:
      return None
    return get_route_base(segment)
  return None


def get_route_base_from_fn(fn: str) -> str | None:
  segment = fn.split("/", 1)[0]
  return get_route_base(segment)


def get_route_segments(root: str, route_base: str) -> list[str]:
  prefix = route_base + "--"
  try:
    return sorted(d for d in os.listdir(root) if d.startswith(prefix) and os.path.isdir(os.path.join(root, d)))
  except OSError:
    return []


def segment_has_lock(root: str, segment: str) -> bool:
  path = os.path.join(root, segment)
  try:
    return any(name.endswith(".lock") for name in os.listdir(path))
  except OSError:
    return True


def _decompress_zst_bytes(data: bytes) -> bytes | None:
  import zstandard as zstd

  dctx = zstd.ZstdDecompressor()
  try:
    return dctx.decompress(data)
  except zstd.ZstdError:
    try:
      out = io.BytesIO()
      with dctx.stream_reader(io.BytesIO(data)) as reader:
        while True:
          chunk = reader.read(65536)
          if not chunk:
            break
          out.write(chunk)
      return out.getvalue()
    except zstd.ZstdError:
      return None


def qlog_segment_stats(qlog_path: str) -> tuple[float, float]:
  try:
    from cereal import log as capnp_log
  except ImportError:
    return 0.0, 0.0

  try:
    with open(qlog_path, "rb") as f:
      data = f.read()
  except OSError:
    return 0.0, 0.0

  if qlog_path.endswith(".zst") or data.startswith(b"\x28\xB5\x2F\xFD"):
    decompressed = _decompress_zst_bytes(data)
    if decompressed is None:
      return 0.0, 0.0
    data = decompressed

  first_t = last_t = None
  last_t_cs = None
  distance_m = 0.0
  try:
    for evt in capnp_log.Event.read_multiple_bytes(data):
      t = evt.logMonoTime
      if first_t is None:
        first_t = t
      last_t = t
      if evt.which() == "carState":
        v = max(float(evt.carState.vEgo), 0.0)
        if last_t_cs is not None and t > last_t_cs:
          distance_m += v * ((t - last_t_cs) / 1e9)
        last_t_cs = t
  except Exception:
    return 0.0, 0.0

  if first_t is None or last_t is None or last_t <= first_t:
    return 0.0, distance_m
  return (last_t - first_t) / 1e9, distance_m


def get_route_stats(root: str, route_base: str) -> tuple[float, float] | None:
  segments = get_route_segments(root, route_base)
  if not segments or any(segment_has_lock(root, s) for s in segments):
    return None

  total_duration = 0.0
  total_distance_m = 0.0
  for segment in segments:
    qlog_path = os.path.join(root, segment, "qlog")
    if not os.path.isfile(qlog_path):
      qlog_path = os.path.join(root, segment, "qlog.zst")
    if not os.path.isfile(qlog_path):
      return None
    duration, distance_m = qlog_segment_stats(qlog_path)
    total_duration += duration if duration > 0 else SEGMENT_LENGTH
    total_distance_m += distance_m

  return total_duration, total_distance_m


def should_defer_route_upload(route_base: str, offroad: bool, root: str | None = None) -> bool:
  if offroad:
    return False
  stats = get_route_stats(root or str(Paths.log_root()), route_base)
  if stats is None:
    return True
  duration, distance_m = stats
  return duration < MIN_UPLOAD_DURATION_S or is_zero_km(distance_m)


def should_skip_route_upload(route_base: str, offroad: bool, root: str | None = None) -> bool:
  if not offroad:
    return False
  stats = get_route_stats(root or str(Paths.log_root()), route_base)
  if stats is None:
    return False
  duration, distance_m = stats
  return duration < MIN_UPLOAD_DURATION_S or is_zero_km(distance_m)


def mark_route_uploaded(route_base: str, root: str | None = None) -> None:
  log_root = root or str(Paths.log_root())
  for segment in get_route_segments(log_root, route_base):
    path = os.path.join(log_root, segment)
    try:
      for name in os.listdir(path):
        fn = os.path.join(path, name)
        if os.path.isfile(fn) and not name.endswith(".lock"):
          try:
            setxattr(fn, UPLOAD_ATTR_NAME, UPLOAD_ATTR_VALUE)
          except OSError:
            cloudlog.event("route_upload_setxattr_failed", key=os.path.join(segment, name), fn=fn)
    except OSError:
      continue


def should_enqueue_upload_path(path: str, offroad: bool | None = None) -> bool:
  if offroad is None:
    offroad = Params().get_bool("IsOffroad")

  route_base = get_route_base_from_path(path)
  if route_base is None:
    return True

  return should_enqueue_route_upload(route_base, offroad)


def should_enqueue_route_upload(route_base: str, offroad: bool) -> bool:
  if should_skip_route_upload(route_base, offroad):
    cloudlog.event("route_upload_skipped", route=route_base, source="athenad")
    mark_route_uploaded(route_base)
    return False

  if should_defer_route_upload(route_base, offroad):
    return False

  return True


def filter_upload_files_data(files_data: list[dict]) -> tuple[list[dict], list[str]]:
  offroad = Params().get_bool("IsOffroad")
  allowed: list[dict] = []
  skipped_routes: list[str] = []
  skipped_bases: set[str] = set()

  for file_data in files_data:
    fn = file_data.get("fn", "")
    if not fn:
      allowed.append(file_data)
      continue

    route_base = get_route_base_from_fn(fn)
    if route_base is None:
      allowed.append(file_data)
      continue

    if route_base in skipped_bases:
      continue

    if not should_enqueue_route_upload(route_base, offroad):
      if should_skip_route_upload(route_base, offroad):
        skipped_bases.add(route_base)
        skipped_routes.append(route_base)
      continue

    allowed.append(file_data)

  return allowed, skipped_routes


def prune_short_routes_from_upload_queue(queue_items: list[dict]) -> list[dict]:
  offroad = Params().get_bool("IsOffroad")
  kept: list[dict] = []
  skipped_bases: set[str] = set()

  for item in queue_items:
    path = item.get("path", "")
    route_base = get_route_base_from_path(path)
    if route_base is None:
      kept.append(item)
      continue

    if route_base in skipped_bases:
      continue

    if not should_enqueue_upload_path(path, offroad):
      if should_skip_route_upload(route_base, offroad):
        skipped_bases.add(route_base)
        cloudlog.event("route_upload_skipped", route=route_base, source="upload_queue")
        mark_route_uploaded(route_base)
      continue

    kept.append(item)

  return kept
