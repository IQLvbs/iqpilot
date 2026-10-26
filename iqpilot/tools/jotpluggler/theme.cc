// Copyright (c) 2026 IQ.Lvbs LLC. All Rights Reserved.
#include "tools/jotpluggler/theme.h"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <unistd.h>

#include "implot.h"
#include "json11/json11.hpp"

namespace {

bool dark_mode = false;
std::array<ImVec4, ImGuiCol_COUNT> light_colors;
std::array<ImVec4, ImPlotCol_COUNT> light_plot_colors;
std::string save_error;

std::filesystem::path settings_path() {
  const char *home = std::getenv("HOME");
  if (!home || !*home) throw std::runtime_error("HOME is not set");
  return std::filesystem::path(home) / ".iq" / "jotpluggler" / "settings.json";
}

ImVec4 themed_color(ImVec4 color) {
  if (!dark_mode || color.w < 0) return color;
  const float range = std::max({color.x, color.y, color.z}) - std::min({color.x, color.y, color.z});
  if (range > 0.2f) {
    return ImVec4(0.18f + 0.82f * color.x, 0.18f + 0.82f * color.y, 0.18f + 0.82f * color.z, color.w);
  }
  const float lightness = 0.2126f * color.x + 0.7152f * color.y + 0.0722f * color.z;
  const float value = 0.95f - 0.85f * lightness;
  return ImVec4(value * 0.91f, value * 0.96f, value, color.w);
}

void apply_theme() {
  auto &style = ImGui::GetStyle();
  for (int i = 0; i < ImGuiCol_COUNT; ++i) style.Colors[i] = themed_color(light_colors[i]);
  auto &plot = ImPlot::GetStyle();
  for (int i = 0; i < ImPlotCol_COUNT; ++i) plot.Colors[i] = themed_color(light_plot_colors[i]);
}

}

void apply_jot_theme() { apply_theme(); }
bool jot_dark_mode() { return dark_mode; }
const std::string &jot_theme_error() { return save_error; }

ImVec4 ui_color(int r, int g, int b, float alpha) {
  return themed_color(ImVec4(r / 255.0f, g / 255.0f, b / 255.0f, alpha));
}

void initialize_jot_theme() {
  std::copy_n(ImGui::GetStyle().Colors, ImGuiCol_COUNT, light_colors.begin());
  std::copy_n(ImPlot::GetStyle().Colors, ImPlotCol_COUNT, light_plot_colors.begin());
  dark_mode = true;
  try {
    std::ifstream input(settings_path());
    if (input) {
      std::string error;
      const auto settings = json11::Json::parse(std::string(std::istreambuf_iterator<char>(input), {}), error);
      if (settings["dark_mode"].is_bool()) dark_mode = settings["dark_mode"].bool_value();
    }
  } catch (const std::exception &e) {
    save_error = e.what();
  }
  apply_theme();
}

void set_jot_dark_mode(bool dark) {
  dark_mode = dark;
  apply_theme();
  try {
    const auto path = settings_path();
    std::filesystem::create_directories(path.parent_path());
    auto temporary = path;
    temporary += "." + std::to_string(getpid()) + ".tmp";
    std::ofstream output(temporary);
    output << json11::Json(json11::Json::object{{"dark_mode", dark}}).dump();
    output.close();
    if (!output) throw std::runtime_error("Could not save appearance settings");
    std::filesystem::rename(temporary, path);
    save_error.clear();
  } catch (const std::exception &e) {
    save_error = e.what();
  }
}
