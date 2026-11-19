#pragma once

#include <functional>
#include <string>



namespace MessageBox {


void information(const std::string &title, const std::string &text, std::function<void()> on_close = nullptr);
void warning(const std::string &title, const std::string &text, const std::string &detailed_text = "",
             std::function<void()> on_close = nullptr);

void question(const std::string &title, const std::string &text, std::function<void(bool ok)> on_result);

void draw();

}
