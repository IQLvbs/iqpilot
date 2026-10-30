// Copyright (c) 2026 IQ.Lvbs LLC. All Rights Reserved.
#pragma once

#include <atomic>
#include <future>
#include <memory>
#include <string>
#include <vector>

#include "tools/cabana/routes.h"

struct RecentRoute {
  std::string route;
  std::string data_dir;
};

struct RoutePickerResult {
  std::vector<routes::DeviceInfo> devices;
  std::vector<routes::RouteInfo> routes;
  bool success = false;
  int error = 0;
};

struct RoutePicker {
  ~RoutePicker() { if (auth_abort) *auth_abort = true; }
  bool initialized = false;
  bool login = false;
  bool devices_loaded = false;
  bool fetching_devices = false;
  int device_index = 0;
  int period_index = 0;
  std::string directory;
  std::string filter;
  std::string error;
  std::string history_error;
  std::vector<RecentRoute> recent;
  std::vector<routes::DeviceInfo> devices;
  std::vector<routes::RouteInfo> routes;
  std::future<RoutePickerResult> request;
  std::future<std::string> auth;
  std::shared_ptr<std::atomic<bool>> auth_abort;
};
