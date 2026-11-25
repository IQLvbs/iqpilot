"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from iqpilot.system.hardware.nvme import nvme_media_mounted, storage_missing

MOUNTED = "/dev/sda12 /data ext4 rw 0 0\n/dev/nvme0n1 /data/media ext4 rw,noatime 0 0\n"
UNMOUNTED = "/dev/sda12 /data ext4 rw 0 0\n/dev/sda11 /cache ext4 rw 0 0\n"
WRONG_SOURCE = "/dev/sda12 /data ext4 rw 0 0\n/dev/sda13 /data/media ext4 rw 0 0\n"


def _mounts(tmp_path, text):
  path = tmp_path / "mounts"
  path.write_text(text)
  return str(path)


def _device(tmp_path, present):
  path = tmp_path / "nvme0n1"
  if present:
    path.write_text("")
  return str(path)


def test_media_mounted_only_when_nvme_backs_data_media(tmp_path):
  assert nvme_media_mounted(_mounts(tmp_path, MOUNTED))
  assert not nvme_media_mounted(_mounts(tmp_path, UNMOUNTED))
  assert not nvme_media_mounted(_mounts(tmp_path, WRONG_SOURCE))
  assert not nvme_media_mounted(str(tmp_path / "missing"))


def test_storage_missing_when_nvme_present_but_unmounted(tmp_path):
  assert storage_missing("tici", _device(tmp_path, True), _mounts(tmp_path, UNMOUNTED))


def test_storage_not_missing_when_mounted(tmp_path):
  assert not storage_missing("tici", _device(tmp_path, True), _mounts(tmp_path, MOUNTED))


def test_storage_not_missing_without_nvme(tmp_path):
  assert not storage_missing("tici", _device(tmp_path, False), _mounts(tmp_path, UNMOUNTED))


def test_storage_not_missing_on_other_hardware(tmp_path):
  assert not storage_missing("mici", _device(tmp_path, True), _mounts(tmp_path, UNMOUNTED))
  assert not storage_missing("tizi", _device(tmp_path, True), _mounts(tmp_path, UNMOUNTED))
