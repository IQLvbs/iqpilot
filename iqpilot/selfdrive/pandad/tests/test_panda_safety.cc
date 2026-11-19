// Copyright (c) 2026 IQ.Lvbs. All rights reserved.
#define CATCH_CONFIG_MAIN

#include <cstdlib>
#include <filesystem>
#include <tuple>

#include "catch2/catch.hpp"
#include "cereal/messaging/messaging.h"
#include "selfdrive/pandad/pandad.h"

using SafetyModel = cereal::CarParams::SafetyModel;
using Command = std::tuple<uint32_t, bool, uint16_t, uint16_t>;
static std::vector<Command> commands;

void Panda::set_safety_model(SafetyModel model, uint16_t parameter) {
  commands.emplace_back(bus_offset, false, static_cast<uint16_t>(model), parameter);
}

void Panda::set_alternative_experience(uint16_t alternative_experience, uint16_t iq_flags) {
  commands.emplace_back(bus_offset, true, alternative_experience, iq_flags);
}

class RecordingPanda : public Panda {
public:
  explicit RecordingPanda(uint32_t offset) : Panda(offset) {}
};

struct SafetyFixture {
  std::string path;
  RecordingPanda primary{0};
  RecordingPanda secondary{4};

  SafetyFixture() {
    char pattern[] = "/tmp/iq-panda-safety-XXXXXX";
    auto directory = mkdtemp(pattern);
    REQUIRE(directory != nullptr);
    path = directory;
    commands.clear();
  }

  ~SafetyFixture() {
    std::filesystem::remove_all(path);
  }

  static std::string serialize(capnp::MallocMessageBuilder &message) {
    auto words = capnp::messageToFlatArray(message);
    auto bytes = words.asBytes();
    return std::string(reinterpret_cast<const char *>(bytes.begin()), bytes.size());
  }

  void write_configuration(size_t count = 1, unsigned segment_words = 1024) {
    capnp::MallocMessageBuilder vehicle(segment_words, capnp::AllocationStrategy::FIXED_SIZE);
    auto cp = vehicle.initRoot<cereal::CarParams>();
    cp.setAlternativeExperience(19);
    auto settings = cp.initSafetyConfigs(count);
    for (size_t index = 0; index < count; ++index) {
      settings[index].setSafetyModel(SafetyModel::HONDA_NIDEC);
      settings[index].setSafetyParam(7 + index);
    }
    capnp::MallocMessageBuilder iq(segment_words, capnp::AllocationStrategy::FIXED_SIZE);
    iq.initRoot<cereal::IQCarParams>().setIqSafetyFlags(23);
    Params params(path);
    params.put("CarParams", serialize(vehicle));
    params.put("IQCarParams", serialize(iq));
    params.putBool("FirmwareQueryDone", true);
    params.putBool("ControlsReady", true);
  }
};

TEST_CASE_METHOD(SafetyFixture, "configuration applies IQ flags before per-device safety") {
  write_configuration();
  PandaSafety safety({&primary, &secondary}, path);
  safety.configureSafetyMode(true);
  const std::vector<Command> expected = {
    {0, false, static_cast<uint16_t>(SafetyModel::ELM327), 1},
    {4, false, static_cast<uint16_t>(SafetyModel::ELM327), 1},
    {0, true, 19, 23},
    {0, false, static_cast<uint16_t>(SafetyModel::HONDA_NIDEC), 7},
    {4, true, 19, 23},
    {4, false, static_cast<uint16_t>(SafetyModel::SILENT), 0},
  };
  REQUIRE(commands == expected);
  safety.configureSafetyMode(true);
  REQUIRE(commands == expected);
  safety.configureSafetyMode(false);
  commands.clear();
  safety.configureSafetyMode(true);
  REQUIRE(commands == expected);
}

TEST_CASE_METHOD(SafetyFixture, "every Panda uses its own configured parameter") {
  write_configuration(2);
  PandaSafety safety({&primary, &secondary}, path);
  safety.configureSafetyMode(true);
  REQUIRE(commands.back() == Command{4, false, static_cast<uint16_t>(SafetyModel::HONDA_NIDEC), 8});
}

TEST_CASE_METHOD(SafetyFixture, "configuration readiness gates command application") {
  write_configuration();
  Params params(path);
  const std::string gate = GENERATE("FirmwareQueryDone", "ControlsReady");
  params.putBool(gate, false);
  PandaSafety safety({&primary}, path);
  safety.configureSafetyMode(true);
  REQUIRE(commands.size() == 1);
  params.putBool(gate, true);
  safety.configureSafetyMode(true);
  REQUIRE(commands.size() == 3);
}

TEST_CASE_METHOD(SafetyFixture, "incomplete or malformed messages never apply safety settings") {
  write_configuration();
  Params params(path);
  const std::string key = GENERATE("CarParams", "IQCarParams");
  const std::string invalid = GENERATE(std::string{}, std::string{"bad"}, std::string(16, '\xff'));
  params.put(key, invalid);
  PandaSafety safety({&primary}, path);
  safety.configureSafetyMode(true);
  REQUIRE(commands.size() == 1);
  write_configuration();
  safety.configureSafetyMode(true);
  REQUIRE(commands.size() == 3);
}

TEST_CASE_METHOD(SafetyFixture, "only the first Panda enables OBD multiplexing") {
  Params params(path);
  params.putBool("ObdMultiplexingEnabled", true);
  PandaSafety safety({&primary, &secondary}, path);
  safety.configureSafetyMode(true);
  REQUIRE(commands.size() == 4);
  REQUIRE(commands[2] == Command{0, false, static_cast<uint16_t>(SafetyModel::ELM327), 0});
  REQUIRE(commands[3] == Command{4, false, static_cast<uint16_t>(SafetyModel::ELM327), 1});
  REQUIRE(params.getBool("ObdMultiplexingChanged"));
}

TEST_CASE_METHOD(SafetyFixture, "word-aligned truncation cannot use padded bytes") {
  write_configuration();
  Params params(path);
  const std::string key = GENERATE("CarParams", "IQCarParams");
  auto payload = params.get(key);
  payload.resize(payload.size() - sizeof(capnp::word));
  params.put(key, payload);
  PandaSafety safety({&primary}, path);
  safety.configureSafetyMode(true);
  REQUIRE(commands.size() == 1);
}

TEST_CASE_METHOD(SafetyFixture, "absent device settings select silent mode") {
  write_configuration(0);
  PandaSafety safety({&primary}, path);
  safety.configureSafetyMode(true);
  REQUIRE(commands.back() == Command{0, false, static_cast<uint16_t>(SafetyModel::SILENT), 0});
}

TEST_CASE_METHOD(SafetyFixture, "invalid root pointers cannot produce default configurations") {
  write_configuration();
  Params params(path);
  const std::string key = GENERATE("CarParams", "IQCarParams");
  std::string payload(16, '\0');
  payload[4] = 1;
  for (size_t index = 8; index < payload.size(); ++index) payload[index] = '\xff';
  params.put(key, payload);
  PandaSafety safety({&primary}, path);
  safety.configureSafetyMode(true);
  REQUIRE(commands.size() == 1);
}

TEST_CASE_METHOD(SafetyFixture, "multi-segment configuration retains all device settings") {
  write_configuration(2, 1);
  Params params(path);
  REQUIRE(static_cast<unsigned char>(params.get("CarParams")[0]) > 0);
  REQUIRE(static_cast<unsigned char>(params.get("IQCarParams")[0]) > 0);
  PandaSafety safety({&primary, &secondary}, path);
  safety.configureSafetyMode(true);
  REQUIRE(commands.size() == 6);
  REQUIRE(commands[4] == Command{4, true, 19, 23});
  REQUIRE(commands[5] == Command{4, false, static_cast<uint16_t>(SafetyModel::HONDA_NIDEC), 8});
}
