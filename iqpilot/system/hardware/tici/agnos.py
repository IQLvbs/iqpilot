#!/usr/bin/env python3
import base64
import hashlib
import json
import lzma
import os
import shlex
import struct
import subprocess
import time
from collections.abc import Generator

import sys
_VENV_PY = "/usr/local/venv/bin/python3"
if sys.executable != _VENV_PY and os.path.exists(_VENV_PY):
  try:
    import Crypto  # noqa: F401
  except ImportError:
    os.execv(_VENV_PY, [_VENV_PY, os.path.abspath(__file__), *sys.argv[1:]])

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
if _REPO_ROOT not in sys.path:
  sys.path.insert(0, _REPO_ROOT)

import requests

try:
  from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except Exception as exc:
  Ed25519PublicKey = None
  _CRYPTO_IMPORT_ERROR = exc
else:
  _CRYPTO_IMPORT_ERROR = None

SPARSE_CHUNK_FMT = struct.Struct('H2xI4x')
IQPILOT_MANIFEST_PUBLIC_KEY = bytes.fromhex("40ae3f81b77506ecc4982a1ca37ba1d6f8765d2ae510eae9039577206c3e5732")

AGNOS_MANIFEST_FILE = "system/hardware/tici/agnos.json"

LFS_POINTER_MAGIC = b"version https://git-lfs"
# Cloudflare cuts a proxied response off after ~100 s, so a part slower than ~900 KB/s only completes through range resumes.
PART_RESUME_LIMIT = 50
PART_RESUME_DELAY = 2

def _image_auth_module():
  try:
    from iqpilot.system.proprietary_runtime.bundle_modes import import_verified_module
    return import_verified_module("iqpilot_updater_private", "iqpilot_private.updater.git_remote")
  except Exception:
    pass
  try:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    bundle_python = os.path.join(root, "artifacts", "iqpilot_updater_private", "python")
    if os.path.isdir(bundle_python):
      if bundle_python not in sys.path:
        sys.path.insert(0, bundle_python)
      import importlib
      return importlib.import_module("iqpilot_private.updater.git_remote")
  except Exception:
    pass
  return None

# The updater UIs read stdout as "<text>:<percent>" progress, so diagnostics must stay off stdout.
def _diag(msg: str) -> None:
  print(msg, file=sys.stderr, flush=True)

def _is_private_os_image(url: str) -> bool:
  return "/iq.lvbs/iqos/" in url.lower()

def _read_dongle_id() -> str | None:
  import re
  for path in (os.path.join(PERSIST_COMMA, "dongle_id"), "/data/params/d/DongleId"):
    try:
      with open(path) as f:
        v = f.read().strip()
      if re.fullmatch(r"[a-fA-F0-9]{16}", v):
        return v.lower()
    except Exception:
      pass
  return None

PERSIST_COMMA = "/persist/comma"

def _load_device_key(key_path: str):
  from cryptography.hazmat.primitives import serialization
  from cryptography.hazmat.primitives.asymmetric import ec
  with open(key_path, "rb") as f:
    pem = f.read()
  key = serialization.load_pem_private_key(pem, password=None)
  alg = "ES256" if isinstance(key, ec.EllipticCurvePrivateKey) else "RS256"
  public_pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo).decode()
  return key, alg, public_pem

def _custodian_signer():
  try:
    from iqpilot.common.api.base import _custodian_available, _custodian_sign_jwt
    return _custodian_sign_jwt if _custodian_available() else None
  except Exception:
    return None

_clock_offset: list[int] = []

def _local_now() -> int:
  from datetime import UTC, datetime
  return int(datetime.now(UTC).timestamp())

# A freshly flashed device can boot with its clock behind real time, which makes every token it signs look expired to konn3kt.
def _trusted_now() -> int:
  local = _local_now()
  if not _clock_offset:
    offset = 0
    try:
      from email.utils import parsedate_to_datetime
      date = requests.head(_api_host(), timeout=10).headers.get("Date")
      if date:
        offset = max(0, int(parsedate_to_datetime(date).timestamp()) - local)
    except Exception as e:
      _diag(f"IQ.OS proxy: could not read konn3kt time ({type(e).__name__}: {e})")
    _clock_offset.append(offset if offset > 60 else 0)
  return local + _clock_offset[0]

def _sign_device_token(dongle_id: str, claims: dict, install_key: bool = False) -> tuple[str, str]:
  import jwt
  now = _trusted_now()
  payload = {"identity": dongle_id, "nbf": now, "iat": now, "exp": now + 3600, **claims}
  if install_key:
    payload["serial"] = _device_serial()
  errors = []
  for name in ("id_rsa", "id_ecdsa"):
    key_path = os.path.join(PERSIST_COMMA, name)
    if not os.path.exists(key_path):
      continue
    try:
      key, alg, public_pem = _load_device_key(key_path)
      if install_key:
        payload["install_key"] = public_pem
      return jwt.encode(payload, key, algorithm=alg), public_pem
    except PermissionError:
      signer = _custodian_signer()
      try:
        with open(key_path + ".pub") as f:
          public_pem = f.read()
      except OSError as e:
        errors.append(f"{name}.pub: {e}")
        continue
      if signer is None:
        errors.append(f"{name}: unreadable and no custodian signer")
        continue
      if install_key:
        payload["install_key"] = public_pem
      return signer(dongle_id, payload, "ES256" if name == "id_ecdsa" else "RS256"), public_pem
    except Exception as e:
      errors.append(f"{name}: {type(e).__name__}: {e}")
  raise RuntimeError(f"no usable device key in {PERSIST_COMMA} (" + "; ".join(errors or ["no key files"]) + ")")

def _sign_device_jwt(dongle_id: str) -> str | None:
  try:
    return _sign_device_token(dongle_id, {})[0]
  except Exception as e:
    _diag(f"IQ.OS proxy: device token signing failed ({e})")
    return None

def _extract_image_path(url: str) -> str:
  if "/raw/branch/" in url:
    after_branch = url.split("/raw/branch/", 1)[1]
    return after_branch.split("/", 1)[1] if "/" in after_branch else after_branch
  if "/raw/" in url:
    return url.rsplit("/raw/", 1)[1]
  return url.rsplit("/", 1)[-1]

_k3_identity: dict[str, str] = {}

def _api_host() -> str:
  # Konik's setup image exports API_HOST=https://api.konik.ai into /data/continue.sh on every boot; that host has no konn3kt /assets/iqos route, so the IQ.OS endpoints must ignore the generic API_HOST and use konn3kt's own host.
  return os.environ.get("KONN3KT_API_HOST", "https://api-iqlabs.konn3kt.com").rstrip("/")

def _device_serial() -> str:
  try:
    with open("/proc/cmdline") as f:
      for arg in f.read().split():
        if arg.startswith("androidboot.serialno="):
          return arg.split("=", 1)[1]
  except OSError:
    pass
  try:
    from iqpilot.system.hardware import HARDWARE
    return HARDWARE.get_serial() or ""
  except Exception:
    return ""

def _device_imeis() -> tuple[str, str]:
  try:
    from iqpilot.system.hardware import HARDWARE
    return HARDWARE.get_imei(0) or "", HARDWARE.get_imei(1) or ""
  except Exception:
    return "", ""

# The IQ.OS update runs under the stock OS's /usr/local/venv, where IQ.Pilot's own modules may not import, so registration uses only requests, jwt and /persist.
def _ensure_k3_registered(dongle_id: str | None) -> str:
  cache_key = dongle_id or ""
  if cache_key in _k3_identity:
    return _k3_identity[cache_key]
  serial = _device_serial()
  imei1, imei2 = _device_imeis()
  last_error = "no attempt"
  for attempt in range(3):
    if attempt:
      time.sleep(2 * attempt)
    try:
      register_token, public_pem = _sign_device_token(dongle_id or "register", {"register": True})
      resp = requests.post(f"{_api_host()}/v2/pilotauth", timeout=15, params={
        "imei": imei1, "imei2": imei2, "serial": serial, "public_key": public_pem, "register_token": register_token})
    except Exception as e:
      last_error = f"{type(e).__name__}: {e}"
      continue
    if resp.ok:
      registered_id = (resp.json().get("dongle_id") or "").lower()
      if len(registered_id) == 16:
        if dongle_id and registered_id != dongle_id:
          _diag(f"IQ.OS proxy: konn3kt kept {registered_id} instead of {dongle_id}")
        _diag(f"IQ.OS proxy: registered with konn3kt as {registered_id}")
        _k3_identity[cache_key] = registered_id
        return registered_id
      last_error = f"HTTP {resp.status_code} without a dongle_id"
    else:
      last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
      if resp.status_code in (400, 401, 403):
        break
  raise RuntimeError(f"konn3kt registration failed for {dongle_id or 'a device without a dongle id'}: {last_error}")

_k3_download_identity: dict[str, str] = {}
_k3_registration_error: dict[str, str] = {}

def _download_identity(persist_id: str | None) -> str:
  cache_key = persist_id or ""
  if cache_key not in _k3_download_identity:
    try:
      _k3_download_identity[cache_key] = _ensure_k3_registered(persist_id)
    except RuntimeError as e:
      _diag(f"IQ.OS proxy: {e}; downloading with the device's own key instead")
      _k3_registration_error[cache_key] = str(e)
      _k3_download_identity[cache_key] = persist_id or "register"
  return _k3_download_identity[cache_key]

def _k3_proxy_url(url: str) -> tuple[str, dict] | None:
  dongle_id = _download_identity(_read_dongle_id())
  token, _ = _sign_device_token(dongle_id, {}, install_key=True)
  api_host = _api_host()
  mod = _image_auth_module()
  if mod is not None and hasattr(mod, 'os_image_proxy'):
    try:
      return mod.os_image_proxy(url, dongle_id, token, api_host)
    except Exception as e:
      _diag(f"IQ.OS proxy: private image proxy failed ({type(e).__name__}: {e}), using the konn3kt device proxy")
  return f"{api_host}/v1/devices/{dongle_id}/assets/iqos/{_extract_image_path(url)}", {"Authorization": f"JWT {token}"}

def _download_headers(url: str) -> dict:
  mod = _image_auth_module()
  if mod is not None:
    try:
      headers = mod.os_image_headers(url)
      if headers:
        return headers
    except Exception:
      pass
  return {}

class RangeNotSupported(requests.exceptions.RequestException):
  pass

def _ranged_get(url: str, headers: dict, offset: int) -> requests.Response:
  if offset:
    headers = {**headers, 'Range': f"bytes={offset}-"}
  req = requests.get(url, stream=True, headers=headers, timeout=60)
  req.raise_for_status()
  if offset and req.status_code != 206:
    req.close()
    raise RangeNotSupported(f"server ignored range resume at {offset} for {url}")
  return req

def _os_auth_error(url: str) -> str:
  return (
    "cannot install IQ.OS: device could not authenticate to konn3kt. The image is served only "
    "through the konn3kt device proxy, which needs a device-signed JWT; that token is unavailable "
    "when the custodian signer is unreachable — typically because the running software tree is not "
    "SELinux-labeled code_t, so iqkeeperd refuses the signing socket. Re-label the tree "
    f"(run iq-selabel, or chcon -R -t code_t on it) and retry. url={url}")

def _open_image_response(url: str, offset: int = 0) -> requests.Response:
  proxy = _k3_proxy_url(url)
  if proxy is not None:
    proxy_url, proxy_headers = proxy
    try:
      if offset:
        resp = _ranged_get(proxy_url, {'Accept-Encoding': None, **proxy_headers}, offset)
      else:
        resp = requests.get(proxy_url, stream=True, headers={'Accept-Encoding': None, **proxy_headers}, timeout=120)
      resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
      status = e.response.status_code if e.response is not None else 0
      registration_error = _k3_registration_error.get(_read_dongle_id() or "")
      if status in (401, 403) and registration_error:
        raise RuntimeError(f"konn3kt refused the IQ.OS download (HTTP {status}) after {registration_error}") from e
      raise
    return resp
  auth = _download_headers(url)
  if _is_private_os_image(url) and not auth:
    raise RuntimeError(_os_auth_error(url))

  req = requests.get(url, stream=True, headers={'Accept-Encoding': None, **auth}, timeout=60)
  req.raise_for_status()
  if int(req.headers.get('content-length') or 0) >= 1024:
    if not offset:
      return req
    req.close()
    return _ranged_get(url, {'Accept-Encoding': None, **auth}, offset)

  body = req.content
  if not body.startswith(LFS_POINTER_MAGIC):
    raise requests.exceptions.InvalidURL(f"unexpected tiny response ({len(body)} bytes) for {url}")
  meta = dict(line.split(" ", 1) for line in body.decode().strip().splitlines() if " " in line)
  oid = meta["oid"].split(":", 1)[1]
  size = int(meta["size"])
  lfs_base = url.split("/raw/", 1)[0] + ".git/info/lfs"

  try:
    return _ranged_get(f"{lfs_base}/objects/{oid}", {'Accept-Encoding': None, 'Accept': 'application/vnd.git-lfs', **auth}, offset)
  except (requests.exceptions.HTTPError, RangeNotSupported):
    pass

  batch = requests.post(f"{lfs_base}/objects/batch",
                        data=json.dumps({"operation": "download", "transfers": ["basic"],
                                         "objects": [{"oid": oid, "size": size}]}),
                        headers={"Content-Type": "application/vnd.git-lfs+json",
                                 "Accept": "application/vnd.git-lfs+json", **auth},
                        timeout=60)
  batch.raise_for_status()
  action = batch.json()["objects"][0]["actions"]["download"]
  return _ranged_get(action["href"], {'Accept-Encoding': None, **action.get("header", {})}, offset)


def verify_manifest_signature(manifest_path: str) -> None:
  sig_path = f"{manifest_path}.sig"
  if not os.path.exists(sig_path):
    raise RuntimeError(f"missing AGNOS manifest signature: {sig_path}")
  if Ed25519PublicKey is None:
    raise RuntimeError(f"cryptography import failed: {_CRYPTO_IMPORT_ERROR}")

  manifest_bytes = open(manifest_path, "rb").read()
  signature = base64.b64decode(open(sig_path, "rb").read().strip())
  digest = hashlib.sha256(manifest_bytes).digest()
  public_key = Ed25519PublicKey.from_public_bytes(IQPILOT_MANIFEST_PUBLIC_KEY)
  public_key.verify(signature, digest)

class _ChainedParts:
  def __init__(self, urls: list[str]) -> None:
    self.urls = urls
    self.req: requests.Response | None = None

  def raise_for_status(self) -> None:
    if self.req is not None:
      self.req.raise_for_status()

  def iter_content(self, chunk_size: int) -> Generator[bytes, None, None]:
    for u in self.urls:
      received = 0
      resumes = 0
      while True:
        try:
          self.req = _open_image_response(u, received)
          for chunk in self.req.iter_content(chunk_size=chunk_size):
            received += len(chunk)
            yield chunk
          break
        except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError):
          resumes += 1
          if resumes > PART_RESUME_LIMIT:
            raise
          print(f"Resuming {u} at {received} bytes ({resumes})", flush=True)
          time.sleep(PART_RESUME_DELAY)

class StreamingDecompressor:
  def __init__(self, url: str, parts: int = 0) -> None:
    self.buf = b""

    if parts > 1:
      self.req = _ChainedParts([f"{url}.p{i:02d}" for i in range(parts)])
    else:
      self.req = _ChainedParts([url])
    self.it = self.req.iter_content(chunk_size=1024 * 1024)
    self.decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_AUTO)
    self.eof = False
    self.sha256 = hashlib.sha256()

  def read(self, length: int) -> bytes:
    while len(self.buf) < length and not self.eof:
      if self.decompressor.needs_input:
        self.req.raise_for_status()

        try:
          compressed = next(self.it)
        except StopIteration:
          self.eof = True
          break
      else:
        compressed = b''

      self.buf += self.decompressor.decompress(compressed, max_length=length)

      if self.decompressor.eof:
        self.eof = True
        break

    result = self.buf[:length]
    self.buf = self.buf[length:]

    self.sha256.update(result)
    return result

def unsparsify(f: StreamingDecompressor) -> Generator[bytes, None, None]:
  magic = struct.unpack("I", f.read(4))[0]
  assert(magic == 0xed26ff3a)

  major = struct.unpack("H", f.read(2))[0]
  minor = struct.unpack("H", f.read(2))[0]
  assert(major == 1 and minor == 0)

  f.read(2)
  f.read(2)

  block_sz = struct.unpack("I", f.read(4))[0]
  f.read(4)
  num_chunks = struct.unpack("I", f.read(4))[0]
  f.read(4)

  for _ in range(num_chunks):
    chunk_type, out_blocks = SPARSE_CHUNK_FMT.unpack(f.read(12))

    if chunk_type == 0xcac1:
      yield f.read(out_blocks * block_sz)
    elif chunk_type == 0xcac2:
      filler = f.read(4) * (block_sz // 4)
      for _ in range(out_blocks):
        yield filler
    elif chunk_type == 0xcac3:
      yield b""
    else:
      raise Exception("Unhandled sparse chunk type")

def noop(f: StreamingDecompressor) -> Generator[bytes, None, None]:
  while len(chunk := f.read(1024 * 1024)) > 0:
    yield chunk

def get_target_slot_number() -> int:
  current_slot = subprocess.check_output(["abctl", "--boot_slot"], encoding='utf-8').strip()
  return 1 if current_slot == "_a" else 0

def slot_number_to_suffix(slot_number: int) -> str:
  assert slot_number in (0, 1)
  return '_a' if slot_number == 0 else '_b'

def get_partition_path(target_slot_number: int, partition: dict) -> str:
  path = f"/dev/disk/by-partlabel/{partition['name']}"

  if partition.get('has_ab', True):
    path += slot_number_to_suffix(target_slot_number)

  return path

# IQ.OS 4.9.9.4 workaround: udev gives the loader and system partitions to root:otaflash 0660, and only
# `iq` is listed in otaflash. iq.service runs as User=comma, the same uid 1000 under another name, so
# systemd's initgroups leaves otaflash out and opening a partition raises PermissionError. `sg otaflash`
# resolves uid 1000 to iq, a listed member, so it needs no password. The narrow sudo no longer allows
# dd; that route stays last for older images. Remove the sg route once the image gives the service otaflash.
OTAFLASH_GROUP = "otaflash"
PARTITION_ROUTES = ("direct", "sg", "sudo")
_partition_routes: dict[str, str] = {}


def _route_command(route: str, command: str) -> list[str]:
  if route == "sg":
    return ["sg", OTAFLASH_GROUP, "-c", command]
  return ["sudo", "-n", *shlex.split(command)]


def _route_works(route: str, path: str) -> bool:
  try:
    if route == "direct":
      with open(path, 'rb') as f:
        f.read(1)
      with open(path, 'r+b'):
        pass
      return True
    quoted = shlex.quote(path)
    # count=0 with conv=notrunc opens the partition for writing without writing anything
    for command in (f"dd if={quoted} of=/dev/null bs=4096 count=1 status=none",
                    f"dd if=/dev/null of={quoted} bs=4096 count=0 conv=notrunc status=none"):
      subprocess.run(_route_command(route, command), check=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    return True
  except (OSError, subprocess.SubprocessError):
    return False


def _find_route(path: str) -> str | None:
  return next((route for route in PARTITION_ROUTES if _route_works(route, path)), None)


def preflight_partition_io(paths: list[str], log) -> None:
  """Find a route that can read each path and open it for writing, and log it. Writes nothing."""
  refused = []
  for path in paths:
    route = _find_route(path)
    log.info(f"partition I/O preflight: {path} via {route or 'nothing'}")
    if route is None:
      refused.append(path)
    else:
      _partition_routes[path] = route
  if refused:
    raise PermissionError(f"no route can read and write {', '.join(refused)} (tried {', '.join(PARTITION_ROUTES)})")


def _route_for(path: str) -> str:
  if path not in _partition_routes:
    _partition_routes[path] = _find_route(path) or "direct"
  return _partition_routes[path]


def read_partition(path: str, offset: int, length: int) -> Generator[bytes, None, None]:
  chunk_size = 1024 * 1024
  if _route_for(path) == "direct":
    with open(path, 'rb') as f:
      f.seek(offset)
      while length > 0 and (chunk := f.read(min(chunk_size, length))):
        length -= len(chunk)
        yield chunk
    return
  command = (f"dd if={shlex.quote(path)} bs=1M skip={offset} count={length} "
             "iflag=skip_bytes,count_bytes status=none")
  proc = subprocess.Popen(_route_command(_partition_routes[path], command), stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
  try:
    while chunk := proc.stdout.read(chunk_size):
      yield chunk
  finally:
    proc.stdout.close()
    if proc.wait() != 0:
      raise PermissionError(f"reading {path} through {_partition_routes[path]} failed ({proc.returncode})")


def write_partition_at(path: str, offset: int, data: bytes) -> None:
  if _route_for(path) == "direct":
    with open(path, 'r+b') as f:
      f.seek(offset)
      f.write(data)
    return
  command = f"dd of={shlex.quote(path)} bs=1M seek={offset} oflag=seek_bytes conv=notrunc status=none"
  subprocess.run(_route_command(_partition_routes[path], command), input=data, check=True, stderr=subprocess.DEVNULL)


class _PipedWriter:
  """dd fed through a pipe; close() waits for dd so nothing is still in flight when the caller syncs and verifies."""
  def __init__(self, path: str, route: str) -> None:
    self.path, self.route = path, route
    command = f"dd of={shlex.quote(path)} bs=1M conv=notrunc iflag=fullblock status=none"
    self.proc = subprocess.Popen(_route_command(route, command), stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

  def write(self, data: bytes) -> None:
    self.proc.stdin.write(data)

  def close(self) -> None:
    self.proc.stdin.close()
    if self.proc.wait() != 0:
      raise OSError(f"writing {self.path} through {self.route} failed ({self.proc.returncode})")


def open_partition_writer(path: str):
  if _route_for(path) == "direct":
    return open(path, 'wb+')
  return _PipedWriter(path, _partition_routes[path])


def get_raw_hash(path: str, partition_size: int) -> str:
  raw_hash = hashlib.sha256()
  for chunk in read_partition(path, 0, partition_size):
    raw_hash.update(chunk)
  return raw_hash.hexdigest().lower()

def verify_partition(target_slot_number: int, partition: dict[str, str | int], force_full_check: bool = False) -> bool:
  full_check = partition['full_check'] or force_full_check
  path = get_partition_path(target_slot_number, partition)

  if not isinstance(partition['size'], int):
    return False

  partition_size: int = partition['size']

  if not isinstance(partition['hash_raw'], str):
    return False

  partition_hash: str = partition['hash_raw']

  if full_check:
    return get_raw_hash(path, partition_size) == partition_hash.lower()
  else:
    return b"".join(read_partition(path, partition_size, 64)) == partition_hash.lower().encode()

def clear_partition_hash(target_slot_number: int, partition: dict) -> None:
  path = get_partition_path(target_slot_number, partition)
  write_partition_at(path, partition['size'], b"\x00" * 64)
  os.sync()

def extract_compressed_image(target_slot_number: int, partition: dict, cloudlog):
  path = get_partition_path(target_slot_number, partition)
  downloader = StreamingDecompressor(partition['url'], parts=int(partition.get('url_parts', 0)))

  out = open_partition_writer(path)

  last_p = 0
  written = 0
  raw_hash = hashlib.sha256()
  f = unsparsify if partition['sparse'] else noop
  for chunk in f(downloader):
    raw_hash.update(chunk)
    out.write(chunk)
    written += len(chunk)
    p = int(written / partition['size'] * 100)
    if p != last_p:
      last_p = p
      print(f"Installing {partition['name']}: {p}", flush=True)

  out.close()

  if raw_hash.hexdigest().lower() != partition['hash_raw'].lower():
    raise Exception(f"Raw hash mismatch '{raw_hash.hexdigest().lower()}'")

  if downloader.sha256.hexdigest().lower() != partition['hash'].lower():
    raise Exception("Uncompressed hash mismatch")

  if written != partition['size']:
    raise Exception("Uncompressed size mismatch")

  os.sync()

def flash_partition(target_slot_number: int, partition: dict, cloudlog, standalone=False):
  cloudlog.info(f"Downloading and writing {partition['name']}")

  if verify_partition(target_slot_number, partition):
    cloudlog.info(f"Already flashed {partition['name']}")
    return

  full_check = partition['full_check']
  if not full_check:
    clear_partition_hash(target_slot_number, partition)

  path = get_partition_path(target_slot_number, partition)

  extract_compressed_image(target_slot_number, partition, cloudlog)

  if not full_check:
    write_partition_at(path, partition['size'], partition['hash_raw'].lower().encode())

def swap(manifest_path: str, target_slot_number: int, cloudlog) -> None:
  verify_manifest_signature(manifest_path)
  update = json.load(open(manifest_path))
  for partition in update:
    if not partition.get('full_check', False):
      clear_partition_hash(target_slot_number, partition)

  while True:
    out = subprocess.check_output(f"sudo -n abctl --set_active {target_slot_number}", shell=True, stderr=subprocess.STDOUT, encoding='utf8')
    if ("No such file or directory" not in out) and ("lun as boot lun" in out):
      cloudlog.info(f"Swap successful {out}")
      break
    else:
      cloudlog.error(f"Swap failed {out}")

def flash_agnos_update(manifest_path: str, target_slot_number: int, cloudlog, standalone=False) -> None:
  verify_manifest_signature(manifest_path)
  update = json.load(open(manifest_path))

  cloudlog.info(f"Target slot {target_slot_number}")

  os.system(f"sudo -n abctl --set_unbootable {target_slot_number}")

  for partition in update:
    success = False

    for retries in range(10):
      try:
        flash_partition(target_slot_number, partition, cloudlog, standalone)
        success = True
        break

      except requests.exceptions.RequestException:
        cloudlog.exception("Failed")
        cloudlog.info(f"Failed to download {partition['name']}, retrying ({retries})")
        time.sleep(10)

    if not success:
      cloudlog.info(f"Failed to flash {partition['name']}, aborting")
      raise Exception("Maximum retries exceeded")

  cloudlog.info(f"AGNOS ready on slot {target_slot_number}")

def board_name() -> str:
  try:
    with open("/sys/firmware/devicetree/base/model") as f:
      return f.read().strip("\x00").strip().split("comma ")[-1]
  except OSError:
    return ""


def select_for_board(update: list, device: str | None = None) -> list:
  """Keep the entries for this board, as IQ.OS 5's iqos.select_for_board does (xbl differs by board)."""
  boards = {p["board"] for p in update if isinstance(p, dict) and p.get("board")}
  if not boards:
    return list(update)
  device = board_name() if device is None else device
  if not device:
    raise RuntimeError("manifest declares boards but this device's model could not be read")
  chosen = [p for p in update if not p.get("board") or p["board"] == device]
  missing = {p["name"] for p in update} - {p["name"] for p in chosen}
  if missing:
    raise RuntimeError(f"manifest has no {'/'.join(sorted(missing))} for {device} (boards {'/'.join(sorted(boards))})")
  return chosen


# IQ.OS 4.9.9.9.5 leaves the shared splash partition root:disk, so the move keeps the current boot picture there
COSMETIC_PARTITIONS = frozenset(("splash",))


def drop_unwritable_cosmetic(update: list[dict], target_slot_number: int, cloudlog) -> list[dict]:
  kept = []
  for partition in update:
    if partition['name'] in COSMETIC_PARTITIONS and _find_route(get_partition_path(target_slot_number, partition)) is None:
      cloudlog.warning(f"IQ.OS 5 move: {partition['name']} is not writable on this OS, keeping the current one")
      continue
    kept.append(partition)
  return kept


def flash_iqos5_update(manifest_path: str, target_slot_number: int, cloudlog) -> None:
  """Flash IQ.OS 5 to the target slot from AGNOS with this build's flasher; the new tree's code never runs here."""
  verify_manifest_signature(manifest_path)
  update = drop_unwritable_cosmetic(select_for_board(json.load(open(manifest_path))), target_slot_number, cloudlog)
  cloudlog.info(f"IQ.OS 5 target slot {target_slot_number}: {', '.join(p['name'] for p in update)}")
  preflight_partition_io([get_partition_path(target_slot_number, p) for p in update], cloudlog)

  os.system(f"sudo -n /usr/sbin/abctl --set_unbootable {target_slot_number}")
  for partition in update:
    for retries in range(10):
      try:
        flash_partition(target_slot_number, partition, cloudlog, standalone=True)
        break
      except requests.exceptions.RequestException:
        cloudlog.exception("Failed")
        cloudlog.info(f"Failed to download {partition['name']}, retrying ({retries})")
        time.sleep(10)
    else:
      raise Exception(f"Maximum retries exceeded flashing {partition['name']}")

  bad = [p['name'] for p in update if not verify_partition(target_slot_number, p, force_full_check=p['full_check'])]
  if bad:
    raise Exception(f"IQ.OS 5 slot {target_slot_number} failed verification: {', '.join(bad)}")
  cloudlog.info(f"IQ.OS 5 ready on slot {target_slot_number}")


def switch_slot(target_slot_number: int, cloudlog, attempts: int = 3) -> None:
  """comma's stock abctl, the only switch IQ.OS 4.9.9.4's narrow sudo allows."""
  out = ""
  for _ in range(attempts):
    result = subprocess.run(["sudo", "-n", "/usr/sbin/abctl", "--set_active", str(target_slot_number)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf8')
    out = result.stdout
    if result.returncode == 0 and "No such file or directory" not in out and "lun as boot lun" in out:
      cloudlog.info(f"Swap successful {out}")
      return
    cloudlog.error(f"Swap failed {out}")
  raise Exception(f"switching to slot {target_slot_number} failed: {out.strip()}")


def verify_agnos_update(manifest_path: str, target_slot_number: int) -> bool:
  verify_manifest_signature(manifest_path)
  update = json.load(open(manifest_path))
  return all(verify_partition(target_slot_number, partition) for partition in update)

def preflight_image_auth(manifest_path: str) -> None:
  verify_manifest_signature(manifest_path)
  update = json.load(open(manifest_path))
  for partition in update:
    url = partition.get('url', '')
    if _is_private_os_image(url):
      if _k3_proxy_url(url) is None:
        raise RuntimeError(_os_auth_error(url))
      return

if __name__ == "__main__":
  import argparse
  import logging

  parser = argparse.ArgumentParser(description="Flash and verify AGNOS update",
                                   formatter_class=argparse.ArgumentDefaultsHelpFormatter)

  parser.add_argument("--verify", action="store_true", help="Verify and perform swap if update ready")
  parser.add_argument("--swap", action="store_true", help="Verify and perform swap, downloads if necessary")
  parser.add_argument("--check-auth", action="store_true", help="Preflight: confirm the device can authenticate to the image source, then exit")
  parser.add_argument("manifest", help="Manifest json")
  args = parser.parse_args()

  logging.basicConfig(level=logging.INFO)

  if args.check_auth:
    try:
      preflight_image_auth(args.manifest)
    except Exception as e:
      print(f"Error: {e}", flush=True)
      exit(1)
    exit(0)

  target_slot_number = get_target_slot_number()
  if args.verify:
    if verify_agnos_update(args.manifest, target_slot_number):
      swap(args.manifest, target_slot_number, logging)
      exit(0)
    exit(1)
  elif args.swap:
    while not verify_agnos_update(args.manifest, target_slot_number):
      logging.error("Verification failed. Flashing AGNOS")
      flash_agnos_update(args.manifest, target_slot_number, logging, standalone=True)

    logging.warning(f"Verification succeeded. Swapping to slot {target_slot_number}")
    swap(args.manifest, target_slot_number, logging)
  else:
    flash_agnos_update(args.manifest, target_slot_number, logging, standalone=True)
