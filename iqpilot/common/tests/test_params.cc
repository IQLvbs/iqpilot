#include "catch2/catch.hpp"
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#define private public
#include "common/params.h"
#include "common/util.h"

TEST_CASE("params_nonblocking_put") {
  char tmp_path[] = "/tmp/asyncWriter_XXXXXX";
  const std::string param_path = mkdtemp(tmp_path);
  auto param_names = {"CarParams", "IsMetric"};
  {
    Params params(param_path);
    const int lock_fd = open((param_path + "/.lock").c_str(), O_CREAT | O_RDWR, 0775);
    REQUIRE(lock_fd >= 0);
    REQUIRE(flock(lock_fd, LOCK_EX) == 0);
    for (const auto &name : param_names) {
      params.putNonBlocking(name, "1");
    }

    const bool future_valid = params.future.valid();
    const auto future_status = future_valid ? params.future.wait_for(std::chrono::milliseconds(0)) : std::future_status::deferred;
    REQUIRE(flock(lock_fd, LOCK_UN) == 0);
    REQUIRE(close(lock_fd) == 0);
    REQUIRE(future_valid);
    REQUIRE(future_status == std::future_status::timeout);
  }
  Params p(param_path);
  for (const auto &name : param_names) {
    REQUIRE(p.get(name) == "1");
  }
}
