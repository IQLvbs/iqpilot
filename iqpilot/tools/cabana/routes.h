#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <utility>
#include <vector>

namespace routes {

struct DeviceInfo {
  std::string dongle_id;
};

struct RouteInfo {
  std::string name;
  int64_t start_ms = 0;
  int64_t end_ms = 0;
};

using DevicesCallback = std::function<void(std::vector<DeviceInfo> devices, bool success, int error_code)>;
using RoutesCallback = std::function<void(std::vector<RouteInfo> routes, bool success, int error_code)>;

std::pair<bool, int> checkApiResponse(const std::string &result);

int64_t nowUnixMs();
int64_t parseIsoToUnixMs(const std::string &s);
std::string formatUnixMs(int64_t ms);

std::vector<DeviceInfo> parseDevices(const std::string &json);
std::vector<RouteInfo> parseRoutes(const std::string &json, bool preserved);

void fetchDevices(DevicesCallback callback);
void fetchRoutes(const std::string &dongle_id, int period_days, RoutesCallback callback);

}
