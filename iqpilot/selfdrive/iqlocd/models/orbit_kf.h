/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
*/
#pragma once

#include <memory>
#include <optional>
#include <unordered_map>
#include <vector>

#include <eigen3/Eigen/Dense>

#include "iqpilot/selfdrive/iqlocd/models/orbit_kf_constants.h"
#include "iqpilot/selfdrive/state_estimation/estimator.h"

using MatrixXdr = iqpilot::state_estimation::Matrix;
using Estimate = iqpilot::state_estimation::Estimate;

class OrbitKalman {
public:
  OrbitKalman();
  void init_state(const Eigen::VectorXd &state, const Eigen::VectorXd &covs_diag, double filter_time);
  void init_state(const Eigen::VectorXd &state, const MatrixXdr &covs, double filter_time);
  void init_state(const Eigen::VectorXd &state, double filter_time);
  Eigen::VectorXd get_x();
  MatrixXdr get_P();
  double get_filter_time();
  std::vector<MatrixXdr> get_R(int kind, int n);
  std::optional<Estimate> predict_and_observe(double t, int kind, const std::vector<Eigen::VectorXd> &meas, std::vector<MatrixXdr> R = {});
  void predict(double t);
  const Eigen::VectorXd &get_initial_x();
  const MatrixXdr &get_initial_P();
  const MatrixXdr &get_fake_gps_pos_cov();
  const MatrixXdr &get_fake_gps_vel_cov();
  const MatrixXdr &get_reset_orientation_P();
  MatrixXdr H(const Eigen::VectorXd &in);

private:
  std::shared_ptr<iqpilot::state_estimation::StateEstimator> filter;
  Eigen::VectorXd initial_x;
  MatrixXdr initial_P;
  MatrixXdr fake_gps_pos_cov;
  MatrixXdr fake_gps_vel_cov;
  MatrixXdr reset_orientation_P;
  std::unordered_map<int, MatrixXdr> obs_noise;
};
