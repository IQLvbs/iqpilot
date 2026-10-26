// Copyright (c) 2026 comma.ai. MIT License.
#pragma once

#include "imgui.h"
#include "imgui_internal.h"

#include "tools/cabana/core/color.h"

struct Palette {
  ImVec4 text, text_disabled, text_selected;
  ImVec4 window;
  ImVec4 surface;
  ImVec4 frame, frame_hovered, frame_active;
  ImVec4 button, button_hovered, button_active;
  ImVec4 header, header_hovered, header_active;
  ImVec4 accent;
  ImVec4 border, separator, scrollbar_grab;
  ImVec4 slider_track;
  ImVec4 tab, tab_hovered, table_header;
  ImVec4 grid;
  ImVec4 badge;
  ImVec4 bit_background;
  double heatmap_signal_alpha, heatmap_bit_alpha, heatmap_gamma;
  float sparkline_saturation, sparkline_value;
};

constexpr ImVec4 rgb(unsigned hex, float alpha = 1.0f) {
  return ImVec4(((hex >> 16) & 255) / 255.0f, ((hex >> 8) & 255) / 255.0f, (hex & 255) / 255.0f, alpha);
}
inline ImVec4 colorRgb(int r, int g, int b, float alpha = 1.0f) {
  return ImVec4(r / 255.0f, g / 255.0f, b / 255.0f, alpha);
}
inline ImU32 toImU32(const CabanaColor &c) { return IM_COL32(c.r, c.g, c.b, c.a); }
inline ImVec4 toImVec4(const CabanaColor &c) { return ImVec4(c.r / 255.0f, c.g / 255.0f, c.b / 255.0f, c.a / 255.0f); }
inline ImU32 withAlpha(ImU32 c, int alpha) { return (c & ~IM_COL32_A_MASK) | ((ImU32)alpha << IM_COL32_A_SHIFT); }



namespace spacing {
constexpr float CONTROL = 8.0f;
constexpr float INNER = 4.0f;
constexpr float DIALOG_BUTTON_MIN_WIDTH = 80.0f;
}

constexpr float UI_FONT_SIZE = 16.0f;

void loadFonts();
void applyTheme(int theme);
const Palette &palette();
CabanaColor sparklineColor(const CabanaColor &color);

ImFont *boldFont();
void pushMonoFont(float size = 0.0f);
void popMonoFont();
void pushBoldFont();
void popBoldFont();
void pushLargeFont();
void popLargeFont();
