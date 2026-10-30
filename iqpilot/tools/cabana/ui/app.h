#pragma once

#include <functional>
#include <memory>
#include <string>
#include <vector>

#include "tools/cabana/streams/abstractstream.h"


using StreamLoader = std::function<std::unique_ptr<AbstractStream>()>;



int run(std::unique_ptr<AbstractStream> stream, StreamLoader stream_loader, const std::string &dbc_file);



struct KeyEvent {
  int key;
  int mods;
};
std::vector<KeyEvent> takeKeyEvents();
