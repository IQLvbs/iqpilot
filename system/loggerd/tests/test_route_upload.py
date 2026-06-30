from unittest.mock import patch

from openpilot.common.params import Params
from openpilot.system.hardware.hw import Paths
from openpilot.system.loggerd.route_upload import (
  MIN_UPLOAD_DURATION_S,
  filter_upload_files_data,
  get_route_base_from_fn,
  is_zero_km,
  mark_route_uploaded,
  prune_short_routes_from_upload_queue,
  should_skip_route_upload,
)
from openpilot.system.loggerd.tests.loggerd_tests_common import UploaderTestCase
from openpilot.system.loggerd.xattr_cache import getxattr
from openpilot.system.loggerd.uploader import UPLOAD_ATTR_NAME, UPLOAD_ATTR_VALUE


class TestRouteUpload(UploaderTestCase):
  def test_is_zero_km(self):
    assert is_zero_km(0.0) is True
    assert is_zero_km(49.0) is True
    assert is_zero_km(50.0) is False

  def test_get_route_base_from_fn(self):
    assert get_route_base_from_fn("00000029--abc--0/qlog.zst") == "00000029--abc"
    assert get_route_base_from_fn("boot/00000029--abc--0") is None

  def test_get_route_base_from_path(self):
    seg_dir = self.seg_format.format(self.seg_num)
    path = self.make_file_with_data(seg_dir, "qlog.zst", size_mb=0.01)
    from openpilot.system.loggerd.route_upload import get_route_base_from_path
    route_base = seg_dir.rpartition("--")[0]
    assert get_route_base_from_path(str(path)) == route_base

  def test_skip_short_route_when_offroad(self):
    seg_dir = self.seg_format.format(self.seg_num)
    route_base = seg_dir.rpartition("--")[0]
    self.make_file_with_data(seg_dir, "qlog.zst", size_mb=0.01)

    with patch("openpilot.system.loggerd.route_upload.get_route_stats", return_value=(30.0, 0.0)):
      assert should_skip_route_upload(route_base, True, str(Paths.log_root())) is True

  def test_skip_zero_km_route_when_offroad(self):
    seg_dir = self.seg_format.format(self.seg_num)
    route_base = seg_dir.rpartition("--")[0]

    with patch("openpilot.system.loggerd.route_upload.get_route_stats", return_value=(MIN_UPLOAD_DURATION_S + 60, 10.0)):
      assert should_skip_route_upload(route_base, True, str(Paths.log_root())) is True

  def test_keep_long_route_when_offroad(self):
    seg_dir = self.seg_format.format(self.seg_num)
    route_base = seg_dir.rpartition("--")[0]

    with patch("openpilot.system.loggerd.route_upload.get_route_stats", return_value=(MIN_UPLOAD_DURATION_S + 1, 1000.0)):
      assert should_skip_route_upload(route_base, True, str(Paths.log_root())) is False

  def test_filter_upload_files_data_skips_short_route(self):
    seg_dir = self.seg_format.format(self.seg_num)
    route_base = seg_dir.rpartition("--")[0]
    self.make_file_with_data(seg_dir, "qlog.zst", size_mb=0.01)

    files = [{
      "fn": f"{seg_dir}/qlog.zst",
      "url": "https://example.com/upload",
      "headers": {},
    }]

    with patch("openpilot.system.loggerd.route_upload.get_route_stats", return_value=(30.0, 0.0)):
      Params().put_bool("IsOffroad", True)
      filtered, skipped = filter_upload_files_data(files)

    assert filtered == []
    assert skipped == [route_base]

  def test_mark_route_uploaded_sets_xattr(self):
    seg_dir = self.seg_format.format(self.seg_num)
    route_base = seg_dir.rpartition("--")[0]
    path = self.make_file_with_data(seg_dir, "qlog.zst", size_mb=0.01)

    mark_route_uploaded(route_base, str(Paths.log_root()))
    assert getxattr(path, UPLOAD_ATTR_NAME) == UPLOAD_ATTR_VALUE

  def test_prune_short_routes_from_upload_queue(self):
    seg_dir = self.seg_format.format(self.seg_num)
    route_base = seg_dir.rpartition("--")[0]
    path = self.make_file_with_data(seg_dir, "qlog.zst", size_mb=0.01)

    queue = [{
      "path": str(path),
      "url": "https://example.com/upload",
      "headers": {},
    }]

    with patch("openpilot.system.loggerd.route_upload.get_route_stats", return_value=(30.0, 0.0)):
      Params().put_bool("IsOffroad", True)
      pruned = prune_short_routes_from_upload_queue(queue)

    assert pruned == []
    assert getxattr(path, UPLOAD_ATTR_NAME) == UPLOAD_ATTR_VALUE

  def test_prune_keeps_boot_entries(self):
    boot_path = self.make_file_with_data("boot", f"{self.seg_format.format(self.seg_num)}", size_mb=0.01)
    queue = [{
      "path": str(boot_path),
      "url": "https://example.com/upload",
      "headers": {},
    }]
    Params().put_bool("IsOffroad", True)
    assert prune_short_routes_from_upload_queue(queue) == queue
