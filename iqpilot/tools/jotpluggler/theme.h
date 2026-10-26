// Copyright (c) 2026 IQ.Lvbs LLC. All Rights Reserved.
#pragma once

#include <string>

#include "imgui.h"

bool jot_dark_mode();
void initialize_jot_theme();
void apply_jot_theme();
void set_jot_dark_mode(bool dark);
const std::string &jot_theme_error();
ImVec4 ui_color(int r, int g, int b, float alpha = 1.0f);
