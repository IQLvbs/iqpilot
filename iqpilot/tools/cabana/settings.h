#pragma once

#include <string>

#include "tools/cabana/core/observable.h"
#include "tools/cabana/core/settings.h"

class Settings : public CabanaSettingsState {
public:
  Settings();
  void save();

  std::string ui_state;

  Observable<> changed;
};

extern Settings settings;
