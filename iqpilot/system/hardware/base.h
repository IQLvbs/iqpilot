#pragma once

#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "cereal/gen/cpp/log.capnp.h"

// no-op base hw class
class HardwareNone {
public:
  struct UfsHealth {
    uint8_t pre_eol_info;
    uint8_t life_time_estimate_a;
    uint8_t life_time_estimate_b;
    std::vector<uint8_t> vendor_health_report;
  };

  static std::string get_name() { return ""; }
  static cereal::InitData::DeviceType get_device_type() { return cereal::InitData::DeviceType::UNKNOWN; }
  static int get_voltage() { return 0; }
  static int get_current() { return 0; }

  static std::string get_serial() { return "cccccc"; }

  static std::map<std::string, std::string> get_init_logs(bool route_log = false) {
    return {};
  }

  static std::optional<UfsHealth> get_ufs_health() { return std::nullopt; }

  static void set_ir_power(int percentage) {}

  static bool PC() { return false; }
  static bool TICI() { return false; }
  static bool AGNOS() { return false; }
};
