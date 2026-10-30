#pragma once

#include <curl/curl.h>
#include <cstdint>
#include <string>

#include "common/util.h"
#include "third_party/json11/json11.hpp"

namespace CommaApi2 {

const std::string BASE_URL = util::getenv("API_HOST", "https://api-iqlabs.konn3kt.com").c_str();
std::string create_token(bool use_jwt, const json11::Json& payloads = {}, int expiry = 3600);
std::string httpGet(const std::string &url, long *response_code = nullptr);

// konn3kt equivalents of upstream's PyDownloader API helpers. Same endpoints and
// same response shapes, but served over the C++/libcurl path instead of shelling
// into tools/lib. On failure they return {"error": "<code>"} so callers can tell
// unauthorized from a transport error without a second out-param.
std::string getRouteFiles(const std::string &route);
std::string getUser();
std::string getDevices();
std::string getDeviceRoutes(const std::string &dongle_id, int64_t start_ms = 0, int64_t end_ms = 0, bool preserved = false);

// Endpoint paths, relative to BASE_URL. Split out from the fetchers so the konn3kt
// routing can be asserted without network access.
std::string routeFilesPath(const std::string &route);
std::string devicesPath();
std::string deviceRoutesPath(const std::string &dongle_id, int64_t start_ms, int64_t end_ms, bool preserved);

// Maps an HTTP status + body to either the body or an {"error": ...} envelope.
std::string apiResponse(const std::string &body, long response_code);

}  // namespace CommaApi2
