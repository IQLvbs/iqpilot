#pragma once

#include "tools/cabana/ui/tools/tooldialog.h"

class Replay;

class RouteInfoDlg : public ToolDialog {
public:
  RouteInfoDlg();
  bool draw() override;

private:
  Replay *replay_ = nullptr;
};
