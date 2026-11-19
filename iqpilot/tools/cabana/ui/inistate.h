#pragma once
#include <string>

struct GLFWwindow;

namespace inistate {

struct MainWindowState {
  int pos[2] = {0, 0};
  int size[2] = {0, 0};
  bool maximized = false;
  bool has_geometry = false;
  float video_splitter_ratio = -1.0f;
  bool messages_visible = true;
  bool video_visible = true;
  bool charts_visible = true;
};

extern MainWindowState main_window;

void addSettingsHandler();
void load();
void applyWindowGeometry(GLFWwindow *window);
std::string save();

}
