#include "catch2/catch.hpp"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <optional>

#include "tools/replay/api.h"

// These cover the konn3kt endpoints that replaced upstream's PyDownloader shell-outs.
// Cabana's remote-routes dialog and jotpluggler's route-file listing both route through
// here, so a silent change to a path or to the error envelope breaks konn3kt without
// breaking the build.

TEST_CASE("konn3kt api paths") {
  SECTION("route files") {
    REQUIRE(CommaApi2::routeFilesPath("a2a0ccea32023010|2023-07-27--13-01-19") ==
            "v1/route/a2a0ccea32023010|2023-07-27--13-01-19/files");
  }

  SECTION("devices") {
    REQUIRE(CommaApi2::devicesPath() == "v1/me/devices/");
  }

  SECTION("device routes over a time range") {
    REQUIRE(CommaApi2::deviceRoutesPath("dongle", 1000, 2000, false) ==
            "v1/devices/dongle/routes_segments?start=1000&end=2000");
  }

  SECTION("device routes with only one bound") {
    REQUIRE(CommaApi2::deviceRoutesPath("dongle", 1000, 0, false) ==
            "v1/devices/dongle/routes_segments?start=1000");
    REQUIRE(CommaApi2::deviceRoutesPath("dongle", 0, 2000, false) ==
            "v1/devices/dongle/routes_segments?end=2000");
  }

  SECTION("device routes with no bounds omits the query entirely") {
    REQUIRE(CommaApi2::deviceRoutesPath("dongle", 0, 0, false) ==
            "v1/devices/dongle/routes_segments");
  }

  SECTION("preserved routes ignore the time range") {
    REQUIRE(CommaApi2::deviceRoutesPath("dongle", 1000, 2000, true) ==
            "v1/devices/dongle/routes/preserved");
  }
}

TEST_CASE("konn3kt api error envelope") {
  // Cabana and jotpluggler both branch on these exact strings.
  SECTION("success passes the body through") {
    REQUIRE(CommaApi2::apiResponse("[{\"dongle_id\": \"abc\"}]", 200) == "[{\"dongle_id\": \"abc\"}]");
  }

  SECTION("401 and 403 both map to unauthorized") {
    REQUIRE(CommaApi2::apiResponse("", 401) == R"({"error": "unauthorized"})");
    REQUIRE(CommaApi2::apiResponse("nope", 403) == R"({"error": "unauthorized"})");
  }

  SECTION("404 maps to not_found") {
    REQUIRE(CommaApi2::apiResponse("", 404) == R"({"error": "not_found"})");
  }

  SECTION("transport failure and 5xx map to network") {
    REQUIRE(CommaApi2::apiResponse("", 0) == R"({"error": "network"})");
    REQUIRE(CommaApi2::apiResponse("boom", 500) == R"({"error": "network"})");
  }

  SECTION("a 200 with an empty body is still an error") {
    REQUIRE(CommaApi2::apiResponse("", 200) == R"({"error": "network"})");
  }
}

TEST_CASE("konn3kt base url") {
  // Everything is built off BASE_URL; an accidental revert to comma's host would
  // silently point every tool at api.comma.ai.
  REQUIRE(CommaApi2::BASE_URL.find("comma.ai") == std::string::npos);
}

TEST_CASE("tools token comes only from iq home") {
  struct TemporaryHome {
    std::optional<std::string> previous;
    std::filesystem::path path;
    ~TemporaryHome() {
      if (previous) setenv("HOME", previous->c_str(), 1);
      else unsetenv("HOME");
      std::error_code error;
      std::filesystem::remove_all(path, error);
    }
  };
  std::string name = (std::filesystem::temp_directory_path() / "iqpilot-tools-auth-XXXXXX").string();
  const char *directory = mkdtemp(name.data());
  REQUIRE(directory != nullptr);
  const char *home = getenv("HOME");
  TemporaryHome temporary{home ? std::optional<std::string>(home) : std::nullopt, directory};
  REQUIRE(setenv("HOME", directory, 1) == 0);
  std::filesystem::create_directory(temporary.path / ".comma");
  std::ofstream(temporary.path / ".comma/auth.json") << R"({"access_token":"legacy-token"})";
  REQUIRE(CommaApi2::create_token(false).empty());
  REQUIRE(CommaApi2::getDevices() == R"({"error": "unauthorized"})");
  std::filesystem::create_directory(temporary.path / ".iq");
  std::ofstream(temporary.path / ".iq/auth.json") << R"({"access_token":"konn3kt-test-token"})";
  REQUIRE(CommaApi2::create_token(false) == "konn3kt-test-token");
  std::ofstream(temporary.path / ".iq/auth.json") << "invalid";
  REQUIRE(CommaApi2::create_token(false).empty());
}

TEST_CASE("tools verifies the user before browsing", "[.tools_session]") {
  REQUIRE(CommaApi2::getDevices() == util::getenv("TEST_DEVICES_RESPONSE"));
  REQUIRE(CommaApi2::getDeviceRoutes("test-device", 1000, 2000, false) == util::getenv("TEST_ROUTES_RESPONSE"));
}
