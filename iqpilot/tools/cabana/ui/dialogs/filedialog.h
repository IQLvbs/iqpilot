#pragma once

#include <filesystem>
#include <functional>
#include <string>
#include <vector>


namespace FileDialog {

using Callback = std::function<void(const std::string &path)>;

void getOpenFileName(const std::string &title, const std::string &dir, const std::string &extension, Callback cb);
void getSaveFileName(const std::string &title, const std::string &default_path, const std::string &extension, Callback cb);
void getExistingDirectory(const std::string &title, const std::string &dir, Callback cb);

void draw();

}
