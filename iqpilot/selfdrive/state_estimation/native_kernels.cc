/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
*/
#include "iqpilot/selfdrive/state_estimation/native_kernels.h"

#include <array>
#include <cmath>
#include <stdexcept>

#include <eigen3/Eigen/Dense>

namespace {

using Matrix = Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor>;
using Vector = Eigen::VectorXd;

template <int N>
using FixedMatrix = Eigen::Matrix<double, N, N, Eigen::RowMajor>;

template <int N>
using FixedVector = Eigen::Matrix<double, N, 1>;

template <int N, typename Function>
void predict(double *state_data, double *covariance_data, const double *noise_data, double dt, Function function) {
  Eigen::Map<FixedVector<N>> state(state_data);
  Eigen::Map<FixedMatrix<N>> covariance(covariance_data);
  Eigen::Map<const FixedMatrix<N>> noise(noise_data);
  const FixedVector<N> previous = state;
  FixedMatrix<N> jacobian;
  for (int index = 0; index < N; ++index) {
    const double step = std::cbrt(Eigen::NumTraits<double>::epsilon()) * std::max(1.0, std::abs(previous(index)));
    FixedVector<N> upper = previous;
    FixedVector<N> lower = previous;
    upper(index) += step;
    lower(index) -= step;
    jacobian.col(index) = (function(upper, dt) - function(lower, dt)) / (2.0 * step);
  }
  state = function(previous, dt);
  covariance = jacobian * covariance * jacobian.transpose() + dt * noise;
  covariance = (covariance + covariance.transpose()).eval() * 0.5;
}

template <int N, int Z>
void update(double *state_data, double *covariance_data, const double *measurement_data, const double *noise_data,
            double *innovation_data, const Eigen::Matrix<double, Z, N> &jacobian, const Eigen::Matrix<double, Z, 1> &expected) {
  Eigen::Map<FixedVector<N>> state(state_data);
  Eigen::Map<FixedMatrix<N>> covariance(covariance_data);
  Eigen::Map<const Eigen::Matrix<double, Z, 1>> measurement(measurement_data);
  Eigen::Map<const Eigen::Matrix<double, Z, Z, Eigen::RowMajor>> noise(noise_data);
  const Eigen::Matrix<double, Z, Z> innovation_covariance = jacobian * covariance * jacobian.transpose() + noise;
  const Eigen::Matrix<double, N, Z> gain = innovation_covariance.ldlt().solve(jacobian * covariance).transpose();
  const Eigen::Matrix<double, Z, 1> innovation = measurement - expected;
  state += gain * innovation;
  const FixedMatrix<N> residual = FixedMatrix<N>::Identity() - gain * jacobian;
  covariance = residual * covariance * residual.transpose() + gain * noise * gain.transpose();
  covariance = (covariance + covariance.transpose()).eval() * 0.5;
  Eigen::Map<Eigen::Matrix<double, Z, 1>> innovation_output(innovation_data);
  innovation_output = innovation;
}

FixedVector<9> car_transition(const FixedVector<9> &state, double dt, const double *values) {
  FixedVector<9> result = state;
  const double stiffness = state(0);
  const double steer_ratio = state(1);
  const double angle = state(7) - state(2) - state(3);
  const double speed = state(4);
  const double lateral_speed = state(5);
  const double yaw_rate = state(6);
  const double mass = values[0];
  const double inertia = values[1];
  const double front = values[2];
  const double rear = values[3];
  const double front_stiffness = stiffness * values[4];
  const double rear_stiffness = stiffness * values[5];
  double lateral_dot = -(front_stiffness + rear_stiffness) * lateral_speed / (mass * speed);
  lateral_dot += (-(front_stiffness * front - rear_stiffness * rear) / (mass * speed) - speed) * yaw_rate;
  lateral_dot += front_stiffness * angle / (mass * steer_ratio) - 9.81 * state(8);
  double yaw_dot = -(front_stiffness * front - rear_stiffness * rear) * lateral_speed / (inertia * speed);
  yaw_dot -= (front_stiffness * front * front + rear_stiffness * rear * rear) * yaw_rate / (inertia * speed);
  yaw_dot += front_stiffness * front * angle / (inertia * steer_ratio);
  result(5) += dt * lateral_dot;
  result(6) += dt * yaw_dot;
  return result;
}

Eigen::Matrix3d rotation(const Eigen::Vector3d &euler) {
  return (Eigen::AngleAxisd(euler.z(), Eigen::Vector3d::UnitZ()) * Eigen::AngleAxisd(euler.y(), Eigen::Vector3d::UnitY()) *
          Eigen::AngleAxisd(euler.x(), Eigen::Vector3d::UnitX())).toRotationMatrix();
}

Eigen::Vector3d euler(const Eigen::Matrix3d &matrix) {
  const double pitch = std::asin(-matrix(2, 0));
  return {std::atan2(matrix(2, 1), matrix(2, 2)), pitch, std::atan2(matrix(1, 0), matrix(0, 0))};
}

Eigen::Matrix<double, 3, 6> pose_orientation_jacobian(const Eigen::Vector3d &orientation,
                                                      const Eigen::Vector3d &angular_velocity, double dt) {
  const Eigen::Matrix3d x_rotation = Eigen::AngleAxisd(orientation.x(), Eigen::Vector3d::UnitX()).toRotationMatrix();
  const Eigen::Matrix3d y_rotation = Eigen::AngleAxisd(orientation.y(), Eigen::Vector3d::UnitY()).toRotationMatrix();
  const Eigen::Matrix3d z_rotation = Eigen::AngleAxisd(orientation.z(), Eigen::Vector3d::UnitZ()).toRotationMatrix();
  const Eigen::Vector3d delta = dt * angular_velocity;
  const Eigen::Matrix3d delta_x = Eigen::AngleAxisd(delta.x(), Eigen::Vector3d::UnitX()).toRotationMatrix();
  const Eigen::Matrix3d delta_y = Eigen::AngleAxisd(delta.y(), Eigen::Vector3d::UnitY()).toRotationMatrix();
  const Eigen::Matrix3d delta_z = Eigen::AngleAxisd(delta.z(), Eigen::Vector3d::UnitZ()).toRotationMatrix();
  const Eigen::Matrix3d first = z_rotation * y_rotation * x_rotation;
  const Eigen::Matrix3d second = delta_z * delta_y * delta_x;
  const Eigen::Matrix3d combined = first * second;
  Eigen::Matrix3d generator_x = Eigen::Matrix3d::Zero();
  Eigen::Matrix3d generator_y = Eigen::Matrix3d::Zero();
  Eigen::Matrix3d generator_z = Eigen::Matrix3d::Zero();
  generator_x(1, 2) = -1.0;
  generator_x(2, 1) = 1.0;
  generator_y(0, 2) = 1.0;
  generator_y(2, 0) = -1.0;
  generator_z(0, 1) = -1.0;
  generator_z(1, 0) = 1.0;
  std::array<Eigen::Matrix3d, 6> derivatives = {
    z_rotation * y_rotation * x_rotation * generator_x * second,
    z_rotation * y_rotation * generator_y * x_rotation * second,
    z_rotation * generator_z * y_rotation * x_rotation * second,
    first * delta_z * delta_y * delta_x * generator_x * dt,
    first * delta_z * delta_y * generator_y * delta_x * dt,
    first * delta_z * generator_z * delta_y * delta_x * dt,
  };
  Eigen::Matrix<double, 3, 6> result;
  for (int index = 0; index < 6; ++index) {
    const Eigen::Matrix3d &derivative = derivatives[index];
    result(0, index) = (combined(2, 2) * derivative(2, 1) - combined(2, 1) * derivative(2, 2)) /
                       (combined(2, 1) * combined(2, 1) + combined(2, 2) * combined(2, 2));
    result(1, index) = -derivative(2, 0) / std::sqrt(1.0 - combined(2, 0) * combined(2, 0));
    result(2, index) = (combined(0, 0) * derivative(1, 0) - combined(1, 0) * derivative(0, 0)) /
                       (combined(1, 0) * combined(1, 0) + combined(0, 0) * combined(0, 0));
  }
  return result;
}

FixedVector<18> pose_transition(const FixedVector<18> &state, double dt) {
  FixedVector<18> result = state;
  result.segment<3>(3) += dt * state.segment<3>(12);
  result.segment<3>(0) = euler(rotation(state.segment<3>(0)) * rotation(dt * state.segment<3>(6)));
  return result;
}

Eigen::Vector3d pose_acceleration(const FixedVector<18> &state) {
  return rotation(state.segment<3>(0)).transpose() * Eigen::Vector3d(0.0, 0.0, -9.81) + state.segment<3>(12) +
         state.segment<3>(6).cross(state.segment<3>(3)) + state.segment<3>(15);
}

}

extern "C" void iq_estimator_car_predict(double *state, double *covariance, const double *process_noise, double dt, const double *parameters) {
  predict<9>(state, covariance, process_noise, dt, [parameters](const FixedVector<9> &value, double step) {
    return car_transition(value, step, parameters);
  });
}

extern "C" void iq_estimator_car_update(double *state_data, double *covariance, int kind, const double *measurement, const double *noise, double *innovation) {
  Eigen::Map<FixedVector<9>> state(state_data);
  if (kind == 24) {
    Eigen::Matrix<double, 2, 9> jacobian = Eigen::Matrix<double, 2, 9>::Zero();
    jacobian(0, 4) = 1.0;
    jacobian(1, 5) = 1.0;
    update<9, 2>(state_data, covariance, measurement, noise, innovation, jacobian, state.segment<2>(4));
    return;
  }
  int index = -1;
  if (kind == 25) index = 6;
  if (kind == 30) index = 4;
  if (kind == 26) index = 7;
  if (kind == 27) index = 3;
  if (kind == 29) index = 1;
  if (kind == 28) index = 0;
  if (kind == 31) index = 8;
  if (index < 0) throw std::invalid_argument("unknown car observation");
  Eigen::Matrix<double, 1, 9> jacobian = Eigen::Matrix<double, 1, 9>::Zero();
  jacobian(0, index) = 1.0;
  Eigen::Matrix<double, 1, 1> expected;
  expected(0) = state(index);
  update<9, 1>(state_data, covariance, measurement, noise, innovation, jacobian, expected);
}

extern "C" void iq_estimator_pose_predict(double *state, double *covariance, const double *process_noise, double dt) {
  Eigen::Map<FixedVector<18>> mapped_state(state);
  Eigen::Map<FixedMatrix<18>> mapped_covariance(covariance);
  Eigen::Map<const FixedMatrix<18>> noise(process_noise);
  const FixedVector<18> previous = mapped_state;
  FixedMatrix<18> jacobian = FixedMatrix<18>::Identity();
  const Eigen::Matrix<double, 3, 6> orientation_jacobian = pose_orientation_jacobian(previous.segment<3>(0), previous.segment<3>(6), dt);
  jacobian.block<3, 3>(0, 0) = orientation_jacobian.leftCols<3>();
  jacobian.block<3, 3>(0, 6) = orientation_jacobian.rightCols<3>();
  jacobian.block<3, 3>(3, 12) = Eigen::Matrix3d::Identity() * dt;
  mapped_state = pose_transition(previous, dt);
  mapped_covariance = jacobian * mapped_covariance * jacobian.transpose() + dt * noise;
  mapped_covariance = (mapped_covariance + mapped_covariance.transpose()).eval() * 0.5;
}

extern "C" void iq_estimator_pose_update(double *state_data, double *covariance, int kind, const double *measurement, const double *noise, double *innovation) {
  Eigen::Map<FixedVector<18>> state(state_data);
  Eigen::Matrix<double, 3, 18> jacobian = Eigen::Matrix<double, 3, 18>::Zero();
  Eigen::Vector3d expected;
  if (kind == 4) {
    jacobian.block<3, 3>(0, 6).setIdentity();
    jacobian.block<3, 3>(0, 9).setIdentity();
    expected = state.segment<3>(6) + state.segment<3>(9);
  } else if (kind == 10) {
    expected = pose_acceleration(state);
    for (int index = 0; index < 3; ++index) {
      const double step = std::cbrt(Eigen::NumTraits<double>::epsilon()) * std::max(1.0, std::abs(state(index)));
      FixedVector<18> upper = state;
      FixedVector<18> lower = state;
      upper(index) += step;
      lower(index) -= step;
      jacobian.col(index) = (pose_acceleration(upper) - pose_acceleration(lower)) / (2.0 * step);
    }
    const Eigen::Vector3d velocity = state.segment<3>(3);
    const Eigen::Vector3d omega = state.segment<3>(6);
    jacobian.block<3, 3>(0, 3) << 0.0, -omega.z(), omega.y(), omega.z(), 0.0, -omega.x(), -omega.y(), omega.x(), 0.0;
    jacobian.block<3, 3>(0, 6) << 0.0, velocity.z(), -velocity.y(), -velocity.z(), 0.0, velocity.x(), velocity.y(), -velocity.x(), 0.0;
    jacobian.block<3, 3>(0, 12).setIdentity();
    jacobian.block<3, 3>(0, 15).setIdentity();
  } else if (kind == 13) {
    jacobian.block<3, 3>(0, 3).setIdentity();
    expected = state.segment<3>(3);
  } else if (kind == 14) {
    jacobian.block<3, 3>(0, 6).setIdentity();
    expected = state.segment<3>(6);
  } else {
    throw std::invalid_argument("unknown pose observation");
  }
  update<18, 3>(state_data, covariance, measurement, noise, innovation, jacobian, expected);
}
