// Copyright (c) 2026 IQ.Lvbs LLC. All Rights Reserved.
#include "tools/jotpluggler/internal.h"

#include <chrono>
#include <fstream>
#include <map>
#include <thread>

#include "json11/json11.hpp"
#include "tools/cabana/ui/auth.h"

namespace {

const char *PERIOD_NAMES[] = {"Last week", "Last 2 weeks", "Last month", "Last 6 months", "Preserved"};
const int PERIOD_DAYS[] = {7, 14, 30, 180, -1};

std::filesystem::path history_path() {
  const char *home = std::getenv("HOME");
  if (!home || !*home) throw std::runtime_error("HOME is not set");
  return std::filesystem::path(home) / ".iq" / "jotpluggler" / "recent_routes.json";
}

void initialize_picker(RoutePicker &picker) {
  if (picker.initialized) return;
  picker.initialized = true;
  picker.directory = std::getenv("HOME") ? std::getenv("HOME") : ".";
  try {
    std::ifstream input(history_path());
    if (!input) return;
    std::string error;
    const auto json = json11::Json::parse(std::string(std::istreambuf_iterator<char>(input), {}), error);
    for (const auto &item : json.array_items()) {
      if (!item["route"].string_value().empty()) {
        picker.recent.push_back({item["route"].string_value(), item["data_dir"].string_value()});
        if (picker.recent.size() == 20) break;
      }
    }
  } catch (const std::exception &e) {
    picker.history_error = e.what();
  }
}

void save_history(RoutePicker &picker) {
  try {
    const auto path = history_path();
    std::filesystem::create_directories(path.parent_path());
    json11::Json::array items;
    for (const auto &item : picker.recent) items.push_back(json11::Json::object{{"route", item.route}, {"data_dir", item.data_dir}});
    auto temporary = path;
    temporary += ".tmp";
    std::ofstream output(temporary);
    output << json11::Json(items).dump();
    output.close();
    if (!output) throw std::runtime_error("Could not save recent routes");
    std::filesystem::rename(temporary, path);
    picker.history_error.clear();
  } catch (const std::exception &e) {
    picker.history_error = e.what();
  }
}

void fetch_devices(RoutePicker &picker) {
  auto promise = std::make_shared<std::promise<RoutePickerResult>>();
  picker.request = promise->get_future();
  picker.fetching_devices = true;
  picker.error.clear();
  routes::fetchDevices([promise](auto devices, bool success, int error) {
    promise->set_value({.devices = std::move(devices), .success = success, .error = error});
  });
}

void fetch_routes(RoutePicker &picker) {
  picker.routes.clear();
  if (picker.devices.empty()) return;
  auto promise = std::make_shared<std::promise<RoutePickerResult>>();
  picker.request = promise->get_future();
  picker.fetching_devices = false;
  picker.error.clear();
  routes::fetchRoutes(picker.devices[picker.device_index].dongle_id, PERIOD_DAYS[picker.period_index],
                     [promise](auto routes, bool success, int error) {
    promise->set_value({.routes = std::move(routes), .success = success, .error = error});
  });
}

void poll_picker(RoutePicker &picker) {
  if (picker.auth.valid() && picker.auth.wait_for(std::chrono::seconds(0)) == std::future_status::ready) {
    std::string error;
    const auto result = json11::Json::parse(picker.auth.get(), error);
    const bool canceled = picker.auth_abort && *picker.auth_abort;
    picker.auth_abort.reset();
    if (!canceled && result["success"].bool_value()) {
      picker.login = false;
      fetch_devices(picker);
    } else if (!canceled) {
      picker.error = result["error"].string_value();
      if (picker.error.empty()) picker.error = "Could not start sign-in. Please try again.";
    }
  }
  if (!picker.request.valid() || picker.request.wait_for(std::chrono::seconds(0)) != std::future_status::ready) return;
  auto result = picker.request.get();
  if (!result.success) {
    picker.login = result.error == 401;
    picker.error = picker.login ? "Your login is missing, invalid, or expired. Please sign in again." : "Could not load routes. Check your connection and retry.";
  } else if (picker.fetching_devices) {
    picker.devices = std::move(result.devices);
    picker.device_index = 0;
    picker.devices_loaded = true;
    fetch_routes(picker);
  } else {
    picker.routes = std::move(result.routes);
  }
}

void select_route(UiState *state, const std::string &route, const std::string &directory) {
  state->route_buffer = route;
  state->data_dir_buffer = directory;
}

void draw_local_routes(UiState *state) {
  auto &picker = state->route_picker;
  ImGui::TextWrapped("Browse to the folder containing your route segments, or enter a route and data directory below.");
  ImGui::SetNextItemWidth(-1);
  input_text_string("##directory", &picker.directory);
  if (ImGui::Button("Up")) picker.directory = std::filesystem::path(picker.directory).parent_path().string();
  ImGui::SameLine();
  if (ImGui::Button("Home")) picker.directory = std::getenv("HOME") ? std::getenv("HOME") : ".";
  std::error_code error;
  std::vector<std::filesystem::path> directories;
  std::map<std::string, std::string> local_routes;
  auto entries = std::filesystem::directory_iterator(picker.directory, std::filesystem::directory_options::skip_permission_denied, error);
  for (auto it = entries; !error && it != std::filesystem::directory_iterator(); it.increment(error)) {
    if (!it->is_directory(error)) continue;
    auto path = it->path();
    const auto name = path.filename().string();
    if (name.empty() || name[0] == '.') continue;
    directories.push_back(path);
    const auto marker = name.rfind("--");
    if (marker == std::string::npos || marker + 2 == name.size()) continue;
    const auto segment = name.substr(marker + 2);
    if (segment.find_first_not_of("0123456789") != std::string::npos) continue;
    bool has_log = false;
    for (const char *log : {"rlog", "rlog.zst", "rlog.bz2", "qlog", "qlog.zst", "qlog.bz2"}) {
      std::error_code ec;
      has_log |= std::filesystem::is_regular_file(path / log, ec);
    }
    if (has_log) local_routes.emplace(name.substr(0, marker), picker.directory);
  }
  if (error) ImGui::TextWrapped("Cannot read this folder: %s", error.message().c_str());
  ImGui::BeginChild("local_entries", ImVec2(0, 210), ImGuiChildFlags_Borders);
  for (const auto &[route, directory] : local_routes) {
    if (ImGui::Selectable(("Route: " + route).c_str(), state->route_buffer == route)) select_route(state, route, directory);
  }
  std::sort(directories.begin(), directories.end());
  for (const auto &directory : directories) {
    if (ImGui::Selectable((directory.filename().string() + "/").c_str())) picker.directory = directory.string();
  }
  if (directories.empty()) ImGui::TextUnformatted("No route folders here.");
  ImGui::EndChild();
}

void draw_konn3kt_routes(UiState *state) {
  auto &picker = state->route_picker;
  if (!picker.devices_loaded && !picker.login && !picker.request.valid() && picker.error.empty()) fetch_devices(picker);
  if (picker.login) {
    ImGui::TextWrapped("Sign in with your Konn3kt account in your browser, then return here to choose a route.");
    if (picker.auth.valid()) {
      ImGui::TextUnformatted("Waiting for browser sign-in...");
      if (ImGui::Button("Cancel sign-in")) *picker.auth_abort = true;
    } else {
      for (const auto &[name, method] : std::vector<std::pair<std::string, std::string>>{
             {"Google", "google"}, {"GitHub", "github"}, {"Apple", "apple"}, {"Microsoft", "microsoft"}}) {
        if (ImGui::Button(("Sign in with " + name).c_str(), ImVec2(250, 36))) {
          picker.error.clear();
          picker.auth_abort = std::make_shared<std::atomic<bool>>(false);
          auto promise = std::make_shared<std::promise<std::string>>();
          picker.auth = promise->get_future();
          std::thread([promise, provider = std::string(method), abort = picker.auth_abort]() {
            promise->set_value(authenticateKonn3kt(provider, abort.get()));
          }).detach();
          break;
        }
      }
    }
  } else {
    ImGui::BeginDisabled(picker.request.valid());
    if (ImGui::Button("Refresh devices")) fetch_devices(picker);
    ImGui::SameLine();
    if (ImGui::Button("Sign in again")) {
      picker.login = true;
      picker.error.clear();
      picker.routes.clear();
      select_route(state, "", "");
    }
    if (!picker.devices.empty()) {
      if (ImGui::BeginCombo("Device", picker.devices[picker.device_index].dongle_id.c_str())) {
        for (int i = 0; i < static_cast<int>(picker.devices.size()); ++i) {
          if (ImGui::Selectable(picker.devices[i].dongle_id.c_str(), picker.device_index == i)) {
            picker.device_index = i;
            fetch_routes(picker);
          }
        }
        ImGui::EndCombo();
      }
      if (ImGui::Combo("Period", &picker.period_index, PERIOD_NAMES, IM_ARRAYSIZE(PERIOD_NAMES))) fetch_routes(picker);
    }
    ImGui::EndDisabled();
    input_text_string("Filter", &picker.filter);
    ImGui::BeginChild("remote_routes", ImVec2(0, 210), ImGuiChildFlags_Borders);
    if (picker.request.valid()) ImGui::TextUnformatted("Loading...");
    else if (picker.devices_loaded && picker.devices.empty()) ImGui::TextUnformatted("No devices are linked to this account.");
    else if (picker.routes.empty()) ImGui::TextUnformatted("No routes in this period.");
    for (const auto &route : picker.routes) {
      const auto label = routes::formatUnixMs(route.start_ms) + "   " + std::to_string((route.end_ms - route.start_ms) / 60000) + " min   " + route.name;
      if (!picker.filter.empty() && label.find(picker.filter) == std::string::npos) continue;
      if (ImGui::Selectable(label.c_str(), state->route_buffer == route.name)) select_route(state, route.name, "");
    }
    ImGui::EndChild();
  }
  if (!picker.error.empty()) {
    ImGui::TextWrapped("%s", picker.error.c_str());
    if (!picker.auth.valid() && !picker.request.valid() && ImGui::Button("Retry")) fetch_devices(picker);
  }
}

}

void remember_route(const AppSession &session, UiState *state) {
  if (session.route_name.empty()) return;
  auto &picker = state->route_picker;
  initialize_picker(picker);
  picker.recent.erase(std::remove_if(picker.recent.begin(), picker.recent.end(), [&](const auto &item) {
    return item.route == session.route_name && item.data_dir == session.data_dir;
  }), picker.recent.end());
  picker.recent.insert(picker.recent.begin(), {session.route_name, session.data_dir});
  if (picker.recent.size() > 20) picker.recent.resize(20);
  save_history(picker);
}

void draw_open_route_popup(AppSession *session, UiState *state) {
  const auto *viewport = ImGui::GetMainViewport();
  ImGui::SetNextWindowSize(ImVec2(std::min(820.0f, viewport->WorkSize.x - 30), std::min(670.0f, viewport->WorkSize.y - 30)), ImGuiCond_Appearing);
  ImGui::SetNextWindowPos(viewport->GetWorkCenter(), ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
  if (!app_begin_popup_modal("Open Route")) return;
  auto &picker = state->route_picker;
  initialize_picker(picker);
  poll_picker(picker);
  ImGui::TextUnformatted("Open a route in Jotpluggler");
  ImGui::SameLine();
  bool dark = jot_dark_mode();
  if (ImGui::Checkbox("Dark mode", &dark)) set_jot_dark_mode(dark);
  if (!jot_theme_error().empty()) ImGui::TextWrapped("%s", jot_theme_error().c_str());
  ImGui::TextWrapped("Choose a recorded drive. Your plots and layout stay in place when switching routes.");
  ImGui::Spacing();
  if (ImGui::BeginTabBar("route_sources")) {
    if (ImGui::BeginTabItem("Recent")) {
      ImGui::BeginChild("recent_routes", ImVec2(0, 285), ImGuiChildFlags_Borders);
      if (picker.recent.empty()) ImGui::TextWrapped("No recent routes yet. Browse local routes or sign in to Konn3kt to get started.");
      for (size_t i = 0; i < picker.recent.size(); ++i) {
        ImGui::PushID(static_cast<int>(i));
        const auto &item = picker.recent[i];
        if (ImGui::SmallButton("Remove")) {
          picker.recent.erase(picker.recent.begin() + i);
          save_history(picker);
          ImGui::PopID();
          break;
        }
        ImGui::SameLine();
        if (ImGui::Selectable((item.route + "  " + (item.data_dir.empty() ? "Konn3kt" : item.data_dir)).c_str(), state->route_buffer == item.route && state->data_dir_buffer == item.data_dir)) select_route(state, item.route, item.data_dir);
        ImGui::PopID();
      }
      ImGui::EndChild();
      ImGui::EndTabItem();
    }
    if (ImGui::BeginTabItem("Local Routes")) {
      draw_local_routes(state);
      ImGui::EndTabItem();
    }
    if (ImGui::BeginTabItem("Konn3kt")) {
      draw_konn3kt_routes(state);
      ImGui::EndTabItem();
    }
    ImGui::EndTabBar();
  }
  ImGui::Separator();
  ImGui::SetNextItemWidth(-125);
  input_text_string("Route", &state->route_buffer);
  ImGui::SetNextItemWidth(-125);
  input_text_string("Data directory", &state->data_dir_buffer);
  ImGui::TextDisabled("Leave the data directory empty for Konn3kt routes.");
  if (!picker.history_error.empty()) ImGui::TextWrapped("Recent routes: %s", picker.history_error.c_str());
  ImGui::Spacing();
  ImGui::BeginDisabled(util::strip(state->route_buffer).empty());
  bool close = false;
  if (ImGui::Button("Open Route", ImVec2(140, 32))) close = reload_session(session, state, util::strip(state->route_buffer), util::strip(state->data_dir_buffer));
  ImGui::EndDisabled();
  ImGui::SameLine();
  if (ImGui::Button("Live Stream...", ImVec2(140, 32))) {
    state->open_stream = true;
    close = true;
  }
  ImGui::SameLine();
  if (ImGui::Button("Cancel", ImVec2(100, 32))) close = true;
  if (close) {
    if (picker.auth_abort) *picker.auth_abort = true;
    ImGui::CloseCurrentPopup();
  }
  ImGui::EndPopup();
}
