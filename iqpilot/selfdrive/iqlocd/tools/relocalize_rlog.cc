/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
*/
#include <cstdio>
#include <fcntl.h>
#include <unistd.h>

#include <capnp/serialize.h>
#include <kj/io.h>

#include "iqpilot/cereal/messaging/messaging.h"
#include "iqpilot/selfdrive/iqlocd/atlas_loc_core.h"

static bool feeds_locator(cereal::Event::Which which) {
  return which == cereal::Event::GPS_LOCATION || which == cereal::Event::GPS_LOCATION_EXTERNAL ||
         which == cereal::Event::CAMERA_ODOMETRY || which == cereal::Event::EXTRINSICS_CALIBRATION ||
         which == cereal::Event::CAR_STATE || which == cereal::Event::ACCELEROMETER || which == cereal::Event::GYROSCOPE;
}

int main(int argc, char **argv) {
  if (argc != 4 || (std::string(argv[3]) != "qcom" && std::string(argv[3]) != "ublox")) {
    fprintf(stderr, "usage: relocalize_rlog <raw rlog in> <raw rlog out> qcom|ublox\n");
    return 2;
  }
  int input = open(argv[1], O_RDONLY);
  int output = open(argv[2], O_WRONLY | O_CREAT | O_TRUNC, 0644);
  if (input < 0 || output < 0) {
    fprintf(stderr, "cannot open input or output\n");
    return 2;
  }
  kj::FdInputStream raw(input);
  kj::BufferedInputStreamWrapper stream(raw);
  kj::FdOutputStream sink(output);
  AtlasLocator locator(std::string(argv[3]) == "qcom" ? AtlasGnssMode::QCOM : AtlasGnssMode::UBLOX);
  locator.reset_kalman();
  size_t replaced = 0, booting = 0;
  while (stream.tryGetReadBuffer().size() > 0) {
    capnp::InputStreamMessageReader reader(stream, capnp::ReaderOptions{.traversalLimitInWords = 1 << 30});
    cereal::Event::Reader event = reader.getRoot<cereal::Event>();
    const auto which = event.which();
    if (which == cereal::Event::IQ_LIVE_LOCATION) {
      continue;
    }
    capnp::MallocMessageBuilder copy;
    copy.setRoot(event);
    capnp::writeMessage(sink, copy);
    if (!feeds_locator(which)) {
      continue;
    }
    if (event.getValid()) {
      locator.consume_event(event);
    }
    if (which == cereal::Event::CAMERA_ODOMETRY) {
      MessageBuilder msg;
      cereal::Event::Builder out = msg.initEvent(true);
      out.setLogMonoTime(event.getLogMonoTime() + 1);
      cereal::IQLiveLocation::Builder fix = out.initIqLiveLocation();
      locator.populate_location_packet(fix);
      fix.setSensorsHealthy(true);
      fix.setGpsHealthy(locator.gps_ready());
      fix.setInputsHealthy(locator.inputs_are_ready());
      booting += fix.getSolutionState() == cereal::IQLiveLocation::SolutionState::BOOTING;
      capnp::writeMessage(sink, msg);
      replaced++;
    }
  }
  fprintf(stderr, "iqLiveLocation messages written: %zu, booting: %zu\n", replaced, booting);
  close(output);
  return 0;
}
