#pragma once

#include <string>
#include <utility>
#include <vector>

#include "imgui_internal.h"




class HelpOverlay {
public:
  void toggle();
  bool visible() const { return visible_; }

  void add(const std::string &text, const ImRect &rect);
  void draw();

private:
  struct Entry {
    std::string text;
    ImRect rect;
    ImGuiViewport *viewport;
  };
  std::vector<Entry> texts_;
  bool visible_ = false;
  int opened_frame_ = -1;
};
