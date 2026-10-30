"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

import numpy as np
cimport numpy as np


cdef extern from "iqpilot/selfdrive/state_estimation/native_kernels.h":
  void iq_estimator_car_predict(double *, double *, const double *, double, const double *)
  void iq_estimator_car_update(double *, double *, int, const double *, const double *, double *)
  void iq_estimator_pose_predict(double *, double *, const double *, double)
  void iq_estimator_pose_update(double *, double *, int, const double *, const double *, double *)


def car_predict(np.ndarray[np.float64_t, ndim=1, mode="c"] state,
                np.ndarray[np.float64_t, ndim=2, mode="c"] covariance,
                np.ndarray[np.float64_t, ndim=2, mode="c"] process_noise,
                double dt,
                np.ndarray[np.float64_t, ndim=1, mode="c"] parameters):
  iq_estimator_car_predict(&state[0], &covariance[0, 0], &process_noise[0, 0], dt, &parameters[0])


def car_update(np.ndarray[np.float64_t, ndim=1, mode="c"] state,
               np.ndarray[np.float64_t, ndim=2, mode="c"] covariance,
               int kind,
               np.ndarray[np.float64_t, ndim=1, mode="c"] measurement,
               np.ndarray[np.float64_t, ndim=2, mode="c"] noise):
  cdef np.ndarray[np.float64_t, ndim=1, mode="c"] innovation = np.empty(measurement.size)
  iq_estimator_car_update(&state[0], &covariance[0, 0], kind, &measurement[0], &noise[0, 0], &innovation[0])
  return innovation


def pose_predict(np.ndarray[np.float64_t, ndim=1, mode="c"] state,
                 np.ndarray[np.float64_t, ndim=2, mode="c"] covariance,
                 np.ndarray[np.float64_t, ndim=2, mode="c"] process_noise,
                 double dt):
  iq_estimator_pose_predict(&state[0], &covariance[0, 0], &process_noise[0, 0], dt)


def pose_update(np.ndarray[np.float64_t, ndim=1, mode="c"] state,
                np.ndarray[np.float64_t, ndim=2, mode="c"] covariance,
                int kind,
                np.ndarray[np.float64_t, ndim=1, mode="c"] measurement,
                np.ndarray[np.float64_t, ndim=2, mode="c"] noise):
  cdef np.ndarray[np.float64_t, ndim=1, mode="c"] innovation = np.empty(measurement.size)
  iq_estimator_pose_update(&state[0], &covariance[0, 0], kind, &measurement[0], &noise[0, 0], &innovation[0])
  return innovation
