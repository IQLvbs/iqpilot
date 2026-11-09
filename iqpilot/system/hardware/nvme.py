"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import os

NVME_DEVICE = "/dev/nvme0n1"
MEDIA_MOUNT = "/data/media"
MOUNTS_FILE = "/proc/mounts"


def nvme_installed(device: str = NVME_DEVICE) -> bool:
  return os.path.exists(device)


def nvme_media_mounted(mounts_file: str = MOUNTS_FILE, mount_point: str = MEDIA_MOUNT) -> bool:
  try:
    with open(mounts_file) as f:
      rows = [line.split() for line in f]
  except OSError:
    return False
  return any(len(row) >= 2 and row[1] == mount_point and row[0].startswith("/dev/nvme") for row in rows)


def storage_missing(device_type: str, device: str = NVME_DEVICE, mounts_file: str = MOUNTS_FILE,
                    mount_point: str = MEDIA_MOUNT) -> bool:
  if device_type != "tici":
    return False
  return nvme_installed(device) and not nvme_media_mounted(mounts_file, mount_point)
