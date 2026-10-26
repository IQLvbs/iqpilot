#pragma once

#include "tools/cabana/streams/livestream.h"

#include <string>
#include <sys/types.h>

class DeviceStream : public LiveStream {
public:
  enum class Mode { Msgq, Zmq, Bridge };

  DeviceStream(Mode mode = Mode::Msgq, std::string address = {});
  ~DeviceStream();
  inline std::string routeName() const override {
    return "Live Streaming From " + address_;
  }

protected:
  void start() override;
  void streamThread() override;
  void stopBridge();
  pid_t bridge_pid = -1;
  const Mode mode_;
  const std::string address_;
};
