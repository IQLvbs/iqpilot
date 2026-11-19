#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "imgui.h"
#include "imgui_internal.h"
#include "tools/cabana/core/color.h"




ImVec2 byteCellSize();
ImVec2 bytesCellSize(int n, bool multiple_lines);
ImU32 cellTextColor(bool selected, bool inactive);

void drawTextCell(ImDrawList *dl, const ImRect &rect, const std::string &text, bool selected, bool inactive);
void drawBytesCell(ImDrawList *dl, const ImRect &rect, const std::vector<uint8_t> &bytes, const std::vector<CabanaColor> *colors,
                   bool selected, bool inactive, bool multiple_lines);
