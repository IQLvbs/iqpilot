#pragma once

#include <array>
#include <string>
#include <vector>

#include "imgui.h"
#include "imgui_internal.h"


struct TipLine {
  bool has_marker = false;
  ImU32 marker = 0;
  std::string name;
  std::string value, min, max;
};

class TipLabel {
public:
  void showText(const ImVec2 &pt, const std::vector<TipLine> &text, const ImRect &rect);
  void hide() { visible_ = false; }
  bool isVisible() const { return visible_; }
  void draw(const ImRect &rect);

private:

  ImVec2 layoutLines(ImDrawList *p, const ImVec2 &origin, ImU32 fg) const;
  ImVec2 sizeHint() const;
  void updateLayout();

  static constexpr float MARGIN = 6.0f;
  std::vector<TipLine> text_;
  std::array<float, 4> column_widths_{};
  ImVec2 anchor_;
  ImRect area_;
  ImVec2 pos_;
  ImVec2 size_;
  bool compact_ = false;
  bool visible_ = false;
};
