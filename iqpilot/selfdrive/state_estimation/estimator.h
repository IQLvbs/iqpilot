/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
*/
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <optional>
#include <stdexcept>
#include <unordered_map>
#include <vector>

#include <eigen3/Eigen/Dense>

namespace iqpilot::state_estimation {

using Matrix = Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor>;
using Vector = Eigen::VectorXd;

struct Estimate {
  double time;
  Vector state;
  Matrix covariance;
  std::vector<Vector> innovations;
};

struct ModelDefinition {
  int state_size;
  int error_size;
  std::function<Vector(const Vector &, double)> transition;
  std::unordered_map<int, std::function<Vector(const Vector &)>> measurements;
  Matrix process_noise;
  std::unordered_map<int, Matrix> observation_noise;
  std::function<Vector(const Vector &, const Vector &)> inject_error;
  std::function<Matrix(const Vector &)> error_projection;
  std::function<Vector(const Vector &)> normalize;
  std::function<Matrix(const Vector &, double)> error_transition;
  std::unordered_map<int, std::function<Matrix(const Vector &)>> observation_jacobians;
};

class StateEstimator {
public:
  StateEstimator(ModelDefinition model, Vector state, Matrix covariance, double max_rewind_age = 0.0)
    : model_(std::move(model)), max_rewind_age_(max_rewind_age) {
    init_state(state, covariance, NAN);
  }

  void init_state(const Vector &state, const Matrix &covariance, double time) {
    if (state.size() != model_.state_size || covariance.rows() != model_.error_size || covariance.cols() != model_.error_size) {
      throw std::invalid_argument("estimator initialization dimension mismatch");
    }
    state_ = normalize(state);
    covariance_ = stabilize(covariance);
    time_ = time;
    events_.clear();
    snapshots_.assign(1, Snapshot{time_, state_, covariance_});
  }

  void predict(double time) {
    if (std::isnan(time_)) {
      time_ = time;
      return;
    }
    if (time < time_) {
      throw std::invalid_argument("prediction time precedes estimator time");
    }
    const double dt = time - time_;
    if (dt == 0.0) return;
    const Vector previous = state_;
    const Vector predicted = model_.transition(previous, dt);
    Matrix error_transition;
    if (model_.error_transition) {
      error_transition = model_.error_transition(previous, dt);
    } else {
      const Matrix state_jacobian = jacobian([this, dt](const Vector &value) { return model_.transition(value, dt); }, previous);
      error_transition = error_projection(predicted).completeOrthogonalDecomposition().pseudoInverse() * state_jacobian * error_projection(previous);
    }
    state_ = normalize(predicted);
    covariance_ = error_transition * covariance_ * error_transition.transpose() + dt * model_.process_noise;
    time_ = time;
  }

  std::optional<Estimate> predict_and_observe(double time, int kind, const std::vector<Vector> &measurements,
                                               const std::vector<Matrix> &noise = {}) {
    if (model_.measurements.find(kind) == model_.measurements.end()) throw std::invalid_argument("unknown observation kind");
    std::vector<Matrix> resolved;
    resolved.reserve(measurements.size());
    for (size_t index = 0; index < measurements.size(); ++index) {
      resolved.push_back(noise.empty() ? model_.observation_noise.at(kind) : noise.at(index));
    }
    Event event{time, kind, measurements, std::move(resolved), next_order_++};
    if (!std::isnan(time_) && time < time_) {
      if (max_rewind_age_ <= 0.0 || time_ - time > max_rewind_age_) return std::nullopt;
      return rewind(event);
    }
    Estimate result = apply(event);
    events_.push_back(std::move(event));
    snapshots_.push_back(Snapshot{time_, state_, covariance_});
    trim_history();
    return result;
  }

  const Vector &state() const { return state_; }
  const Matrix &covariance() const { return covariance_; }
  double time() const { return time_; }

private:
  struct Event {
    double time;
    int kind;
    std::vector<Vector> measurements;
    std::vector<Matrix> noise;
    uint64_t order;
  };

  struct Snapshot {
    double time;
    Vector state;
    Matrix covariance;
  };

  Estimate rewind(const Event &late) {
    size_t base = 0;
    for (size_t index = 0; index < snapshots_.size(); ++index) {
      if (std::isnan(snapshots_[index].time) || snapshots_[index].time <= late.time) base = index;
    }
    std::vector<Event> replay(events_.begin() + base, events_.end());
    replay.push_back(late);
    std::stable_sort(replay.begin(), replay.end(), [](const Event &a, const Event &b) {
      return a.time < b.time || (a.time == b.time && a.order < b.order);
    });
    state_ = snapshots_[base].state;
    covariance_ = snapshots_[base].covariance;
    time_ = snapshots_[base].time;
    events_.resize(base);
    snapshots_.resize(base + 1);
    std::optional<Estimate> result;
    for (Event &event : replay) {
      Estimate current = apply(event);
      if (event.order == late.order) result = current;
      events_.push_back(std::move(event));
      snapshots_.push_back(Snapshot{time_, state_, covariance_});
    }
    trim_history();
    return *result;
  }

  void trim_history() {
    if (max_rewind_age_ <= 0.0 || std::isnan(time_)) {
      events_.clear();
      snapshots_.assign(1, Snapshot{time_, state_, covariance_});
      return;
    }
    const double cutoff = time_ - max_rewind_age_;
    size_t remove = 0;
    while (remove < events_.size() && events_[remove].time < cutoff) ++remove;
    if (remove > 0) {
      events_.erase(events_.begin(), events_.begin() + remove);
      snapshots_.erase(snapshots_.begin(), snapshots_.begin() + remove);
    }
  }

  Estimate apply(const Event &event) {
    predict(event.time);
    const int kind = event.kind;
    const std::vector<Vector> &measurements = event.measurements;
    auto measurement_function = model_.measurements.find(kind);
    std::vector<Vector> innovations;
    for (size_t index = 0; index < measurements.size(); ++index) {
      const Matrix &measurement_noise = event.noise.at(index);
      const Vector expected = measurement_function->second(state_);
      if (measurements[index].size() != expected.size() || measurement_noise.rows() != expected.size() || measurement_noise.cols() != expected.size()) {
        throw std::invalid_argument("observation dimension mismatch");
      }
      const Vector innovation = measurements[index] - expected;
      Matrix observation_jacobian;
      auto analytic_jacobian = model_.observation_jacobians.find(kind);
      if (analytic_jacobian != model_.observation_jacobians.end()) {
        observation_jacobian = analytic_jacobian->second(state_);
      } else {
        const Matrix state_jacobian = jacobian(measurement_function->second, state_);
        observation_jacobian = state_jacobian * error_projection(state_);
      }
      const Matrix innovation_covariance = observation_jacobian * covariance_ * observation_jacobian.transpose() + measurement_noise;
      const Matrix gain = innovation_covariance.ldlt().solve(observation_jacobian * covariance_).transpose();
      state_ = normalize(inject(state_, gain * innovation));
      const Matrix identity = Matrix::Identity(model_.error_size, model_.error_size);
      const Matrix residual = identity - gain * observation_jacobian;
      covariance_ = residual * covariance_ * residual.transpose() + gain * measurement_noise * gain.transpose();
      if (!state_.allFinite() || !covariance_.allFinite()) throw std::runtime_error("estimator produced non-finite values");
      innovations.push_back(innovation);
    }
    return Estimate{time_, state_, covariance_, innovations};
  }

  Matrix jacobian(const std::function<Vector(const Vector &)> &function, const Vector &value) const {
    const Vector output = function(value);
    Matrix result(output.size(), value.size());
    for (int index = 0; index < value.size(); ++index) {
      const double step = std::cbrt(Eigen::NumTraits<double>::epsilon()) * std::max(1.0, std::abs(value(index)));
      Vector upper = value;
      Vector lower = value;
      upper(index) += step;
      lower(index) -= step;
      result.col(index) = (function(upper) - function(lower)) / (2.0 * step);
    }
    return result;
  }

  Vector inject(const Vector &state, const Vector &delta) const {
    return model_.inject_error ? model_.inject_error(state, delta) : state + delta;
  }

  Matrix error_projection(const Vector &state) const {
    return model_.error_projection ? model_.error_projection(state) : Matrix::Identity(model_.state_size, model_.error_size);
  }

  Vector normalize(const Vector &state) const {
    return model_.normalize ? model_.normalize(state) : state;
  }

  Matrix stabilize(const Matrix &covariance) const {
    Matrix symmetric = (covariance + covariance.transpose()) * 0.5;
    if (!symmetric.allFinite()) throw std::runtime_error("invalid covariance");
    return symmetric;
  }

  ModelDefinition model_;
  double max_rewind_age_ = 0.0;
  Vector state_;
  Matrix covariance_;
  double time_ = NAN;
  std::vector<Event> events_;
  std::vector<Snapshot> snapshots_;
  uint64_t next_order_ = 0;
};

}
