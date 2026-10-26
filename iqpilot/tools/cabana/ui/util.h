#pragma once

#include <functional>
#include <string>
#include <vector>

#include "tools/cabana/ui/dropdown.h"
#include "tools/cabana/utils/util.h"

struct GLFWwindow;


constexpr const char *MESSAGES_PANEL_ID = "###MessagesPanel";

struct InputContext {
  std::string *str;
  ImGuiInputTextCallback validator;
  ValidState (*validate)(const std::string &) = nullptr;
  const std::string *last_valid = nullptr;
};

int inputCallback(ImGuiInputTextCallbackData *data);


bool validatedInput(const char *label, std::string *s, ImGuiInputTextCallback validator, const char *hint = "",
                    ImGuiInputTextFlags flags = 0);

inline bool inputText(const char *label, std::string *s, const char *hint = "", ImGuiInputTextFlags flags = 0) {
  return validatedInput(label, s, nullptr, hint, flags);
}

bool inputTextMultiline(const char *label, std::string *s, const ImVec2 &size, ImGuiInputTextFlags flags = 0);

constexpr float CONTROL_OUTLINE_PADDING = 1.0f;

bool beginControlChild(const char *id, const ImVec2 &size, ImGuiWindowFlags flags = 0);


bool clearableInput(const char *label, std::string *s, const char *hint = "", ImGuiInputTextCallback validator = nullptr);

bool selectable(const char *label, bool selected, ImGuiSelectableFlags flags = 0, const ImVec2 &size = ImVec2(0, 0));

bool comboBox(const char *label, int *index, const std::vector<std::string> &items);


template <typename T>
inline bool comboBox(const char *label, int *index, const T *values, int count) {
  bool changed = false;
  const std::string preview = *index >= 0 && *index < count ? std::to_string(values[*index]) : "";
  if (dropdown::BeginCombo(label, preview.c_str())) {
    for (int i = 0; i < count; ++i) {
      ImGui::PushID(i);
      if (dropdown::Item(std::to_string(values[i]).c_str(), nullptr, i == *index) && *index != i) {
        *index = i;
        changed = true;
      }
      if (i == *index) ImGui::SetItemDefaultFocus();
      ImGui::PopID();
    }
    dropdown::EndCombo();
  }
  return changed;
}


bool validatedText(const char *label, std::string *s, ValidState (*validate)(const std::string &),
                   const char *hint = "", ImGuiInputTextCallback filter = nullptr);


int nameValidator(ImGuiInputTextCallbackData *data);
int nodeValidator(ImGuiInputTextCallbackData *data);
int doubleValidator(ImGuiInputTextCallbackData *data);
int ipValidator(ImGuiInputTextCallbackData *data);
int nonWhitespaceValidator(ImGuiInputTextCallbackData *data);

#ifdef __APPLE__
constexpr const char *MOD_KEY = "Cmd";
#else
constexpr const char *MOD_KEY = "Ctrl";
#endif
inline std::string shortcut(const char *keys) { return std::string(MOD_KEY) + "+" + keys; }


bool iconButton(const char *id, const char *icon, const char *tooltip = nullptr);
float iconButtonWidth();
bool stepButton(const char *id, bool increment, const char *tooltip = nullptr);
struct IconTextButtonOptions {
  float height = 0.0f;
  float rounding = -1.0f;
  float icon_gap = -1.0f;
  bool center_content = false;
  float label_width = 0.0f;
};
bool iconTextButton(const char *id, const char *icon, const std::string &text, float width = 0.0f,
                    const IconTextButtonOptions &options = {});
float iconTextButtonWidth(const char *icon, const std::string &text, const IconTextButtonOptions &options = {});


void disabledItemTooltip(const char *text);




struct PopupOwner {
  ImGuiID popup_id = 0, owner_id = 0;


  bool begin(const char *id);

  void reset() { popup_id = owner_id = 0; }
};


bool dialogEscapePressed();


ImGuiWindow *topPopupWindow();


bool dialogButtons(const char *accept_label, bool *accepted, bool *rejected, bool accept_enabled = true,
                   const char *reject_label = "Cancel");



float inputIntWidth(int digits);
bool inputInt(const char *label, int *value, int step = 1, int step_fast = 100,
              ImGuiInputTextFlags flags = ImGuiInputTextFlags_None);


int tableHeadersRow();




bool viewSelectable(const char *label, bool selected, ImGuiSelectableFlags flags, const ImVec2 &size);



bool checkBox(const char *label, bool *v);
constexpr float CHECKBOX_SIZE = 16.0f;


void alignRight(float width);


void drawText(ImDrawList *dl, const ImRect &rect, const char *text, ImU32 col, ImFont *font = nullptr,
              float font_size = 0.0f, const ImVec2 &align = ImVec2(0.5f, 0.5f));

void drawElidedText(ImDrawList *dl, const ImRect &rect, const std::string &text, ImU32 col, bool align_right = false);

float markerSize();
void drawColorMarker(ImDrawList *dl, const ImVec2 &pos, ImU32 col);


void setNextWindowFloatsOut();
#ifdef __APPLE__


void setMacAppName(const char *name);

bool isNativeFullScreen(GLFWwindow *window);
void toggleNativeFullScreen(GLFWwindow *window);
#endif


void setNextDialogWindow(const ImVec2 &size);

bool beginDialog(const char *id, PopupOwner *owner, const ImVec2 &size, ImGuiWindowFlags flags = ImGuiWindowFlags_NoResize);

const float SLIDER_LENGTH = 13.0f;
const float SLIDER_THICKNESS = 13.0f;



struct ToolbarItem {
  float width;
  std::function<void()> draw;
  std::string menu_label;
  std::function<void()> trigger;
  bool enabled = true;
  bool in_menu = true;
  std::function<void()> submenu;
};
ToolbarItem toolbarAction(const char *id, const char *icon, const char *label, std::function<void()> trigger,
                          bool enabled = true);


ToolbarItem toolbarMenu(const char *id, const std::string &text, const char *label, std::function<void()> items,
                        bool bold = false, float width = 0.0f);
float toolbarButtonWidth(const std::string &label);

float toolbarWidth(const std::vector<ToolbarItem> &items, size_t spacer_index);


void drawToolbar(const std::vector<ToolbarItem> &items, size_t spacer_index, float width = -1.0f);



float menuButtonWidth(const std::string &text, bool bold = false);
bool menuButton(const char *id, const std::string &text, const char *popup_id, bool bold = false, float width = 0.0f);

void drawSliderHandle(ImDrawList *p, const ImRect &r);

bool fusionSliderInt(const char *label, int *v, int min, int max, float width);
