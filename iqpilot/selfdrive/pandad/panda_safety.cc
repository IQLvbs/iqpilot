#include "selfdrive/pandad/pandad.h"
#include "cereal/messaging/messaging.h"
#include "common/swaglog.h"

namespace {
class ConfigurationReadErrors : public kj::ExceptionCallback {
public:
  bool failed = false;
  void onRecoverableException(kj::Exception &&) override { failed = true; }
};

bool completeMessage(const std::string &payload) {
  if (payload.empty() || payload.size() % sizeof(capnp::word) != 0) return false;
  auto read32 = [&](size_t offset) {
    uint32_t value = 0;
    for (size_t byte = 0; byte < 4; ++byte) {
      value |= static_cast<uint32_t>(static_cast<unsigned char>(payload[offset + byte])) << (8 * byte);
    }
    return value;
  };
  const uint64_t segments = static_cast<uint64_t>(read32(0)) + 1;
  const uint64_t header_words = (segments + 2) / 2;
  const uint64_t total_words = payload.size() / sizeof(capnp::word);
  if (header_words >= total_words) return false;
  uint64_t remaining = total_words - header_words;
  for (uint64_t index = 0; index < segments; ++index) {
    const uint32_t words = read32(4 * (index + 1));
    if (words > remaining || (index == 0 && words == 0)) return false;
    remaining -= words;
  }
  return remaining == 0;
}
}

void PandaSafety::configureSafetyMode(bool is_onroad) {
  if (is_onroad && !safety_configured_) {
    updateMultiplexingMode();

    if (auto configuration = readSafetyConfiguration()) {
      applySafetyConfiguration(*configuration);
      safety_configured_ = true;
    }
  } else if (!is_onroad) {
    initialized_ = false;
    safety_configured_ = false;
    log_once_ = false;
  }
}

void PandaSafety::updateMultiplexingMode() {
  // Initialize to ELM327 without OBD multiplexing for initial fingerprinting
  if (!initialized_) {
    prev_obd_multiplexing_ = false;
    for (int i = 0; i < pandas_.size(); ++i) {
      pandas_[i]->set_safety_model(cereal::CarParams::SafetyModel::ELM327, 1U);
    }
    initialized_ = true;
  }

  // Switch between multiplexing modes based on the OBD multiplexing request
  bool obd_multiplexing_requested = params_.getBool("ObdMultiplexingEnabled");
  if (obd_multiplexing_requested != prev_obd_multiplexing_) {
    for (int i = 0; i < pandas_.size(); ++i) {
      const uint16_t safety_param = (i > 0 || !obd_multiplexing_requested) ? 1U : 0U;
      pandas_[i]->set_safety_model(cereal::CarParams::SafetyModel::ELM327, safety_param);
    }
    prev_obd_multiplexing_ = obd_multiplexing_requested;
    params_.putBool("ObdMultiplexingChanged", true);
  }
}

std::optional<PandaSafety::SafetyConfiguration> PandaSafety::readSafetyConfiguration() {
  if (!params_.getBool("FirmwareQueryDone")) {
    return std::nullopt;
  }
  if (!log_once_) {
    LOGW("Finished FW query, waiting for complete safety configuration");
    log_once_ = true;
  }
  if (!params_.getBool("ControlsReady")) {
    return std::nullopt;
  }

  const std::string vehicle_payload = params_.get("CarParams");
  const std::string iq_payload = params_.get("IQCarParams");
  if (!completeMessage(vehicle_payload) || !completeMessage(iq_payload)) {
    return std::nullopt;
  }

  ConfigurationReadErrors errors;
  try {
    AlignedBuffer vehicle_buffer;
    AlignedBuffer iq_buffer;
    capnp::FlatArrayMessageReader vehicle_reader(vehicle_buffer.align(vehicle_payload.data(), vehicle_payload.size())
                                                  .slice(0, vehicle_payload.size() / sizeof(capnp::word)));
    capnp::FlatArrayMessageReader iq_reader(iq_buffer.align(iq_payload.data(), iq_payload.size())
                                             .slice(0, iq_payload.size() / sizeof(capnp::word)));
    const auto vehicle = vehicle_reader.getRoot<cereal::CarParams>();
    const auto iq = iq_reader.getRoot<cereal::IQCarParams>();
    const auto settings = vehicle.getSafetyConfigs();

    SafetyConfiguration configuration{static_cast<uint16_t>(vehicle.getAlternativeExperience()),
                                      static_cast<uint16_t>(iq.getIqSafetyFlags()), {}};
    configuration.devices.resize(pandas_.size());
    for (size_t index = 0; index < configuration.devices.size() && index < settings.size(); ++index) {
      configuration.devices[index] = {settings[index].getSafetyModel(), settings[index].getSafetyParam()};
    }
    if (!errors.failed) return configuration;
  } catch (const kj::Exception &) {
    return std::nullopt;
  }
  return std::nullopt;
}

void PandaSafety::applySafetyConfiguration(const SafetyConfiguration &configuration) {
  for (size_t index = 0; index < configuration.devices.size(); ++index) {
    const auto &setting = configuration.devices[index];
    LOGW("Panda %zu: safety model %d, parameter %u, alternative experience %u, IQ flags %u",
         index, static_cast<int>(setting.model), setting.parameter, configuration.alternative_experience, configuration.iq_flags);
    pandas_[index]->set_alternative_experience(configuration.alternative_experience, configuration.iq_flags);
    pandas_[index]->set_safety_model(setting.model, setting.parameter);
  }
}

bool PandaSafety::getOffroadMode() {
  auto offroad_mode = params_.getBool("IQAlwaysOffroad");
  return offroad_mode;
}
