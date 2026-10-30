#pragma once

#include <algorithm>
#include <atomic>
#include <cmath>
#include <filesystem>
#include <functional>
#include <memory>
#include <string>
#include <thread>
#include <vector>
#include <utility>

#include "tools/cabana/core/color.h"

class SegmentTree {
public:
  SegmentTree() = default;
  void build(int n, const std::function<double(int)> &y);
  inline std::pair<double, double> minmax(int left, int right) const { return get_minmax(1, 0, size - 1, left, right); }

private:
  std::pair<double, double> get_minmax(int n, int left, int right, int range_left, int range_right) const;
  void build_tree(const std::function<double(int)> &y, int n, int left, int right);
  std::vector<std::pair<double, double>> tree;
  int size = 0;
};


class LogScale {
public:
  LogScale(double factor) : factor(factor) {}
  void setRange(double min, double max) {
    log_min = factor * std::log10(min);
    log_max = factor * std::log10(max);
  }
  int value(int pos, int pos_min, int pos_max) const {
    double v = log_min + (log_max - log_min) * ((pos - pos_min) / double(pos_max - pos_min));
    return std::lround(std::pow(10, v / factor));
  }
  int position(int v, int pos_min, int pos_max) const {
    double log_v = std::clamp(factor * std::log10(v), log_min, log_max);
    return pos_min + (pos_max - pos_min) * ((log_v - log_min) / (log_max - log_min));
  }

private:
  double factor, log_min = 0, log_max = 1;
};

enum class ValidState { Invalid, Intermediate, Acceptable };


ValidState validateName(std::string &input);

ValidState validateNodes(const std::string &input);


ValidState validateIpAddress(const std::string &input);

ValidState validateDouble(const std::string &input);



namespace utils {

bool isMainThread();

void runOnMainThread(std::function<void()> fn);
void drainMainThreadQueue();
std::string homePath();
std::filesystem::path configPath();
bool getClipboardText(std::string *text);
bool setClipboardText(const std::string &text);




template <typename F>
auto guarded(const std::shared_ptr<bool> &alive, F fn) {
  return [alive = std::weak_ptr<bool>(alive), fn = std::move(fn)](auto &&...args) {
    if (!alive.expired()) fn(std::forward<decltype(args)>(args)...);
  };
}

}



class UnixSignalHandler {
public:
  UnixSignalHandler(std::function<void()> on_signal);
  ~UnixSignalHandler();
  static void signalHandler(int s);

private:
  inline static int sig_fd[2] = {};
  std::atomic<bool> shutting_down{false};
  std::thread waiter;
};

std::filesystem::path executableDir();
