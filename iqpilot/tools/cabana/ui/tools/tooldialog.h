#pragma once

#include <cstdio>
#include <string>

#include "imgui.h"
#include "tools/cabana/core/observable.h"
#include "tools/cabana/ui/util.h"


class ToolDialog {
public:
  virtual ~ToolDialog() = default;
  virtual bool draw() = 0;

  Connections connections_;

protected:
  void setTitle(const std::string &name) {
    char buf[32];
    snprintf(buf, sizeof(buf), "###tooldialog%p", (void *)this);
    title_ = name + buf;
  }


  bool begin(const ImVec2 &size) {
    if (!open_) return false;
    ImGui::SetNextWindowSize(size, ImGuiCond_Appearing);
    setNextWindowFloatsOut();
    began_ = true;
    return visible_ = ImGui::Begin(title_.c_str(), &open_, ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoCollapse);
  }

  bool end() {
    if (!began_) return false;

    if (visible_ && ImGui::IsWindowFocused(ImGuiFocusedFlags_RootAndChildWindows) &&
        ImGui::IsKeyPressed(ImGuiKey_Escape, false) &&
        !ImGui::IsPopupOpen(nullptr, ImGuiPopupFlags_AnyPopupId | ImGuiPopupFlags_AnyPopupLevel)) {
      open_ = false;
    }
    ImGui::End();
    began_ = false;
    return open_;
  }

  std::string title_;
  bool open_ = true;

private:
  bool began_ = false, visible_ = false;
};
