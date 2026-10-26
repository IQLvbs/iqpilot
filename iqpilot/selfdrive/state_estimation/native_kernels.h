/*
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
*/
#pragma once

extern "C" {
void iq_estimator_car_predict(double *state, double *covariance, const double *process_noise, double dt, const double *parameters);
void iq_estimator_car_update(double *state, double *covariance, int kind, const double *measurement, const double *noise, double *innovation);
void iq_estimator_pose_predict(double *state, double *covariance, const double *process_noise, double dt);
void iq_estimator_pose_update(double *state, double *covariance, int kind, const double *measurement, const double *noise, double *innovation);
}
