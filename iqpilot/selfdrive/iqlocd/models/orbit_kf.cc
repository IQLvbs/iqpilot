/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
*/
#include "iqpilot/selfdrive/iqlocd/models/orbit_kf.h"

#include <cmath>

using Eigen::Matrix3d;
using Eigen::Quaterniond;
using Eigen::Vector3d;
using Eigen::VectorXd;
using iqpilot::state_estimation::ModelDefinition;
using iqpilot::state_estimation::StateEstimator;

namespace {

constexpr double EARTH_GM = 3.986005e14;

Matrix3d rotation(const VectorXd &state) {
  return Quaterniond(state(3), state(4), state(5), state(6)).normalized().toRotationMatrix();
}

Matrix3d skew(const Vector3d &value) {
  Matrix3d result;
  result << 0.0, -value.z(), value.y(), value.z(), 0.0, -value.x(), -value.y(), value.x(), 0.0;
  return result;
}

VectorXd transition(const VectorXd &state, double dt) {
  VectorXd result = state;
  const Quaterniond orientation(state(3), state(4), state(5), state(6));
  const Vector3d omega = state.segment<3>(10);
  const Quaterniond derivative(0.0, omega.x(), omega.y(), omega.z());
  const Quaterniond rate = orientation * derivative;
  result.segment<3>(0) += dt * state.segment<3>(7);
  result.segment<4>(3) += 0.5 * dt * (VectorXd(4) << rate.w(), rate.x(), rate.y(), rate.z()).finished();
  result.segment<3>(7) += dt * rotation(state) * state.segment<3>(16);
  return result;
}

VectorXd normalize(const VectorXd &state) {
  VectorXd result = state;
  result.segment<4>(3) /= result.segment<4>(3).norm();
  return result;
}

VectorXd inject(const VectorXd &state, const VectorXd &delta) {
  VectorXd result = state;
  result.segment<3>(0) += delta.segment<3>(0);
  const Quaterniond orientation(state(3), state(4), state(5), state(6));
  Quaterniond error(1.0, 0.5 * delta(3), 0.5 * delta(4), 0.5 * delta(5));
  const Quaterniond updated = error * orientation;
  result.segment<4>(3) << updated.w(), updated.x(), updated.y(), updated.z();
  result.segment(7, 15) += delta.segment(6, 15);
  return normalize(result);
}

MatrixXdr error_projection(const VectorXd &state) {
  MatrixXdr projection = MatrixXdr::Zero(22, 21);
  projection.block<3, 3>(0, 0).setIdentity();
  const double w = state(3);
  const double x = state(4);
  const double y = state(5);
  const double z = state(6);
  projection.block<4, 3>(3, 3) << -0.5 * x, -0.5 * y, -0.5 * z,
                                      0.5 * w,  0.5 * z, -0.5 * y,
                                     -0.5 * z,  0.5 * w,  0.5 * x,
                                      0.5 * y, -0.5 * x,  0.5 * w;
  projection.block(7, 6, 15, 15).setIdentity();
  return projection;
}

MatrixXdr orbit_error_transition(const VectorXd &state, double dt) {
  MatrixXdr result = MatrixXdr::Identity(21, 21);
  const Matrix3d transform = rotation(state);
  result.block<3, 3>(0, 6) = Matrix3d::Identity() * dt;
  result.block<3, 3>(3, 3) += -dt * skew(transform * state.segment<3>(10));
  result.block<3, 3>(3, 9) = dt * transform;
  result.block<3, 3>(6, 3) = -dt * skew(transform * state.segment<3>(16));
  result.block<3, 3>(6, 15) = dt * transform;
  return result;
}

MatrixXdr selected_jacobian(int start) {
  MatrixXdr result = MatrixXdr::Zero(3, 21);
  result.block<3, 3>(0, start).setIdentity();
  return result;
}

VectorXd phone_acceleration(const VectorXd &state) {
  const Vector3d position = state.segment<3>(0);
  const Vector3d gravity = rotation(state).transpose() * (EARTH_GM * position / std::pow(position.squaredNorm(), 1.5));
  return gravity + state.segment<3>(16) + state.segment<3>(19);
}

MatrixXdr diagonal(std::initializer_list<double> values) {
  VectorXd vector(values.size());
  int index = 0;
  for (double value : values) vector(index++) = value;
  return vector.asDiagonal();
}

}

OrbitKalman::OrbitKalman() {
  initial_x.resize(22);
  initial_x << 3.88e6, -3.37e6, 3.76e6, 0.42254641, -0.31238054, -0.83602975, -0.15788347,
               0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0;
  initial_P = diagonal({100.0, 100.0, 100.0, 0.0001, 0.0001, 0.0001, 100.0, 100.0, 100.0,
                        1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 10000.0, 10000.0, 10000.0, 0.0001, 0.0001, 0.0001});
  fake_gps_pos_cov = diagonal({1e6, 1e6, 1e6});
  fake_gps_vel_cov = diagonal({100.0, 100.0, 100.0});
  reset_orientation_P = diagonal({1.0, 1.0, 1.0});
  obs_noise = {
    {OBSERVATION_PHONE_GYRO, diagonal({0.000625, 0.000625, 0.000625})},
    {OBSERVATION_PHONE_ACCEL, diagonal({0.25, 0.25, 0.25})},
    {OBSERVATION_CAMERA_ODO_ROTATION, diagonal({0.0025, 0.0025, 0.0025})},
    {OBSERVATION_CAMERA_ODO_TRANSLATION, diagonal({0.25, 0.25, 0.25})},
    {OBSERVATION_NO_ROT, diagonal({0.000025, 0.000025, 0.000025})},
    {OBSERVATION_NO_ACCEL, diagonal({0.0025, 0.0025, 0.0025})},
    {OBSERVATION_ECEF_POS, diagonal({25.0, 25.0, 25.0})},
    {OBSERVATION_ECEF_VEL, diagonal({0.25, 0.25, 0.25})},
    {OBSERVATION_ECEF_ORIENTATION_FROM_GPS, diagonal({0.04, 0.04, 0.04, 0.04})},
  };
  const MatrixXdr process_noise = diagonal({0.0009, 0.0009, 0.0009, 0.000001, 0.000001, 0.000001,
                                             0.0001, 0.0001, 0.0001, 0.01, 0.01, 0.01,
                                             2.5e-9, 2.5e-9, 2.5e-9, 9.0, 9.0, 9.0, 0.000025, 0.000025, 0.000025});
  std::unordered_map<int, std::function<VectorXd(const VectorXd &)>> measurements = {
    {OBSERVATION_PHONE_GYRO, [](const VectorXd &state) { return state.segment<3>(10) + state.segment<3>(13); }},
    {OBSERVATION_NO_ROT, [](const VectorXd &state) { return state.segment<3>(10); }},
    {OBSERVATION_PHONE_ACCEL, phone_acceleration},
    {OBSERVATION_ECEF_POS, [](const VectorXd &state) { return state.segment<3>(0); }},
    {OBSERVATION_ECEF_VEL, [](const VectorXd &state) { return state.segment<3>(7); }},
    {OBSERVATION_ECEF_ORIENTATION_FROM_GPS, [](const VectorXd &state) { return state.segment<4>(3); }},
    {OBSERVATION_CAMERA_ODO_TRANSLATION, [](const VectorXd &state) { return rotation(state).transpose() * state.segment<3>(7); }},
    {OBSERVATION_CAMERA_ODO_ROTATION, [](const VectorXd &state) { return state.segment<3>(10); }},
    {OBSERVATION_NO_ACCEL, [](const VectorXd &state) { return state.segment<3>(16); }},
  };
  std::unordered_map<int, std::function<MatrixXdr(const VectorXd &)>> observation_jacobians = {
    {OBSERVATION_PHONE_GYRO, [](const VectorXd &) {
      MatrixXdr result = selected_jacobian(9);
      result.block<3, 3>(0, 12).setIdentity();
      return result;
    }},
    {OBSERVATION_NO_ROT, [](const VectorXd &) { return selected_jacobian(9); }},
    {OBSERVATION_PHONE_ACCEL, [](const VectorXd &state) {
      MatrixXdr result = MatrixXdr::Zero(3, 21);
      const Vector3d position = state.segment<3>(0);
      const double radius_squared = position.squaredNorm();
      const double radius = std::sqrt(radius_squared);
      const Vector3d gravity = EARTH_GM * position / (radius_squared * radius);
      result.block<3, 3>(0, 0) = rotation(state).transpose() * EARTH_GM *
                                 (Matrix3d::Identity() / (radius_squared * radius) -
                                  3.0 * position * position.transpose() / (radius_squared * radius_squared * radius));
      result.block<3, 3>(0, 3) = rotation(state).transpose() * skew(gravity);
      result.block<3, 3>(0, 15).setIdentity();
      result.block<3, 3>(0, 18).setIdentity();
      return result;
    }},
    {OBSERVATION_ECEF_POS, [](const VectorXd &) { return selected_jacobian(0); }},
    {OBSERVATION_ECEF_VEL, [](const VectorXd &) { return selected_jacobian(6); }},
    {OBSERVATION_ECEF_ORIENTATION_FROM_GPS, [](const VectorXd &state) { return error_projection(state).block(3, 0, 4, 21); }},
    {OBSERVATION_CAMERA_ODO_TRANSLATION, [](const VectorXd &state) {
      MatrixXdr result = MatrixXdr::Zero(3, 21);
      result.block<3, 3>(0, 3) = rotation(state).transpose() * skew(state.segment<3>(7));
      result.block<3, 3>(0, 6) = rotation(state).transpose();
      return result;
    }},
    {OBSERVATION_CAMERA_ODO_ROTATION, [](const VectorXd &) { return selected_jacobian(9); }},
    {OBSERVATION_NO_ACCEL, [](const VectorXd &) { return selected_jacobian(15); }},
  };
  ModelDefinition model{22, 21, transition, measurements, process_noise, obs_noise, inject, error_projection, normalize,
                        orbit_error_transition, observation_jacobians};
  filter = std::make_shared<StateEstimator>(std::move(model), initial_x, initial_P, ORBIT_MAX_REWIND_AGE);
}

void OrbitKalman::init_state(const VectorXd &state, const VectorXd &covs_diag, double filter_time) {
  filter->init_state(state, covs_diag.asDiagonal(), filter_time);
}

void OrbitKalman::init_state(const VectorXd &state, const MatrixXdr &covs, double filter_time) {
  filter->init_state(state, covs, filter_time);
}

void OrbitKalman::init_state(const VectorXd &state, double filter_time) {
  filter->init_state(state, filter->covariance(), filter_time);
}

VectorXd OrbitKalman::get_x() { return filter->state(); }
MatrixXdr OrbitKalman::get_P() { return filter->covariance(); }
double OrbitKalman::get_filter_time() { return filter->time(); }

std::vector<MatrixXdr> OrbitKalman::get_R(int kind, int n) {
  return std::vector<MatrixXdr>(n, obs_noise.at(kind));
}

std::optional<Estimate> OrbitKalman::predict_and_observe(double t, int kind, const std::vector<VectorXd> &meas, std::vector<MatrixXdr> R) {
  return filter->predict_and_observe(t, kind, meas, R);
}

void OrbitKalman::predict(double t) { filter->predict(t); }
const VectorXd &OrbitKalman::get_initial_x() { return initial_x; }
const MatrixXdr &OrbitKalman::get_initial_P() { return initial_P; }
const MatrixXdr &OrbitKalman::get_fake_gps_pos_cov() { return fake_gps_pos_cov; }
const MatrixXdr &OrbitKalman::get_fake_gps_vel_cov() { return fake_gps_vel_cov; }
const MatrixXdr &OrbitKalman::get_reset_orientation_P() { return reset_orientation_P; }

MatrixXdr OrbitKalman::H(const VectorXd &in) {
  if (in.size() != 6) throw std::invalid_argument("local velocity input dimension mismatch");
  auto function = [](const VectorXd &value) {
    const Matrix3d transform = (Eigen::AngleAxisd(value(2), Vector3d::UnitZ()) * Eigen::AngleAxisd(value(1), Vector3d::UnitY()) *
                                Eigen::AngleAxisd(value(0), Vector3d::UnitX())).toRotationMatrix();
    return transform.transpose() * value.segment<3>(3);
  };
  MatrixXdr result(3, 6);
  for (int index = 0; index < 6; ++index) {
    const double step = std::cbrt(Eigen::NumTraits<double>::epsilon()) * std::max(1.0, std::abs(in(index)));
    VectorXd upper = in;
    VectorXd lower = in;
    upper(index) += step;
    lower(index) -= step;
    result.col(index) = (function(upper) - function(lower)) / (2.0 * step);
  }
  return result;
}
