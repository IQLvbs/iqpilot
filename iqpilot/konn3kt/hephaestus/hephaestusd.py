#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import json

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.iqpilot._proprietary_loader import load_private_module
from openpilot.system.loggerd.route_upload import filter_upload_files_data, prune_short_routes_from_upload_queue


def _patch_upload_handlers(private_module) -> None:
  if hasattr(private_module, "uploadFilesToUrls"):
    original = private_module.uploadFilesToUrls

    def uploadFilesToUrls(files_data, *args, _original=original, **kwargs):
      filtered, skipped = filter_upload_files_data(files_data)
      for route_base in skipped:
        cloudlog.event("hephaestus_route_upload_skipped", route=route_base)
      return _original(filtered, *args, **kwargs)

    private_module.uploadFilesToUrls = uploadFilesToUrls

  if hasattr(private_module, "uploadFileToUrl"):
    original = private_module.uploadFileToUrl

    def uploadFileToUrl(fn, url, headers, *args, _original=original, **kwargs):
      filtered, skipped = filter_upload_files_data([{"fn": fn, "url": url, "headers": headers}])
      for route_base in skipped:
        cloudlog.event("hephaestus_route_upload_skipped", route=route_base)
      if not filtered:
        return {"enqueued": 0, "items": []}
      return _original(fn, url, headers, *args, **kwargs)

    private_module.uploadFileToUrl = uploadFileToUrl


def _sanitize_cached_upload_queue() -> None:
  params = Params()
  raw = params.get("AthenadUploadQueue")
  if raw is None:
    return
  try:
    items = json.loads(raw)
  except (TypeError, json.JSONDecodeError):
    return
  if not isinstance(items, list):
    return

  pruned = prune_short_routes_from_upload_queue(items)
  if len(pruned) != len(items):
    params.put("AthenadUploadQueue", json.dumps(pruned))


_private = load_private_module(__name__, "iqpilot_private.konn3kt.hephaestus.hephaestusd")
_patch_upload_handlers(_private)
_sanitize_cached_upload_queue()

if __name__ == "__main__":
  main()
