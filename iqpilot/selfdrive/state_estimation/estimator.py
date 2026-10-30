"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""

from collections.abc import Callable
from dataclasses import dataclass
import math

import numpy as np


Array = np.ndarray
Prediction = Callable[[Array, float, dict[str, float]], Array]
Measurement = Callable[[Array, dict[str, float]], Array]
Injection = Callable[[Array, Array], Array]
NativePrediction = Callable[[Array, Array, float, Array, dict[str, float]], None]
NativeUpdate = Callable[[Array, Array, int, Array, Array], Array]


@dataclass(frozen=True)
class Observation:
  kind: int
  values: Array
  noise: Array


@dataclass(frozen=True)
class ModelDefinition:
  state_size: int
  error_size: int
  transition: Prediction
  measurements: dict[int, Measurement]
  process_noise: Array
  observation_noise: dict[int, Array]
  inject_error: Injection | None = None
  error_projection: Callable[[Array], Array] | None = None
  normalize: Callable[[Array], Array] | None = None
  native_predict: NativePrediction | None = None
  native_update: NativeUpdate | None = None


@dataclass
class _Snapshot:
  time: float
  state: Array
  covariance: Array


@dataclass
class _Event:
  time: float
  observation: Observation
  order: int


class StateEstimator:
  def __init__(self, model: ModelDefinition, initial_state: Array, initial_covariance: Array,
               max_rewind_age: float = 0.0):
    self.model = model
    self.parameters: dict[str, float] = {}
    self.max_rewind_age = max_rewind_age
    self._order = 0
    self._default_noise: dict[int, Array] = {}
    self._native_sizes = ({kind: noise.shape[0] for kind, noise in model.observation_noise.items()}
                          if model.native_update is not None else {})
    self.init_state(initial_state, initial_covariance, None)

  @property
  def x(self) -> Array:
    return self._state.copy()

  @property
  def P(self) -> Array:
    return self._covariance.copy()

  @property
  def t(self) -> float:
    return self._time

  def set_global(self, name: str, value: float) -> None:
    self.parameters[name] = float(value)

  def init_state(self, state: Array, covs: Array, filter_time: float | None) -> None:
    state = np.asarray(state, dtype=np.float64).reshape(-1)
    covariance = np.asarray(covs, dtype=np.float64)
    self._validate_state(state, covariance)
    self._state = self._normalize(state.copy())
    self._covariance = self._stabilize(covariance.copy())
    self._time = math.nan if filter_time is None else float(filter_time)
    self._events: list[_Event] = []
    self._snapshots = [_Snapshot(self._time, self._state.copy(), self._covariance.copy())]

  def set_filter_time(self, filter_time: float | None) -> None:
    self._time = math.nan if filter_time is None else float(filter_time)

  def reset_rewind(self) -> None:
    self._events.clear()
    self._snapshots = [_Snapshot(self._time, self._state.copy(), self._covariance.copy())]

  def predict(self, time: float) -> None:
    time = float(time)
    if math.isnan(self._time):
      self._time = time
      return
    if time < self._time:
      raise ValueError("prediction time precedes estimator time")
    dt = time - self._time
    if dt == 0.0:
      return
    if self.model.native_predict is not None:
      self.model.native_predict(self._state, self._covariance, dt, self.model.process_noise, self.parameters)
      self._time = time
      return
    previous = self._state.copy()
    transition_jacobian = self._jacobian(lambda value: self.model.transition(value, dt, self.parameters), previous)
    predicted = self.model.transition(previous, dt, self.parameters)
    projection = self._error_projection(previous)
    if self.model.error_size == self.model.state_size:
      error_transition = transition_jacobian
    else:
      error_transition = np.linalg.pinv(self._error_projection(predicted)) @ transition_jacobian @ projection
    self._state = self._normalize(predicted)
    self._covariance = self._stabilize(error_transition @ self._covariance @ error_transition.T + dt * self.model.process_noise)
    self._time = time

  def predict_and_observe(self, time: float, kind: int, measurements: Array, noise: Array | None = None):
    return self._observe(time, kind, measurements, noise, True)

  def observe(self, time: float, kind: int, measurements: Array, noise: Array | None = None):
    return self._observe(time, kind, measurements, noise, False)

  def _observe(self, time: float, kind: int, measurements: Array, noise: Array | None, full: bool):
    values = self._measurement_batch(kind, measurements)
    noises = self._noise_batch(kind, len(values), noise)
    event = _Event(float(time), Observation(kind, values, noises), self._order)
    self._order += 1
    if not math.isnan(self._time) and event.time < self._time:
      if self.max_rewind_age <= 0.0 or self._time - event.time > self.max_rewind_age:
        return None
      return self._rewind(event, full)
    result = self._apply_event(event, full)
    self._events.append(event)
    self._snapshots.append(_Snapshot(self._time, self._state.copy(), self._covariance.copy()))
    self._trim_history()
    return result

  def _state_is_finite(self) -> bool:
    if math.isfinite(self._state.sum() + self._covariance.sum()):
      return True
    return bool(np.isfinite(self._state).all() and np.isfinite(self._covariance).all())

  def _apply_event(self, event: _Event, full: bool = True):
    self.predict(event.time)
    if not full:
      innovations = []
      for measurement, noise in zip(event.observation.values, event.observation.noise, strict=True):
        innovations.append(self._update(event.observation.kind, measurement, noise))
      return tuple(innovations), self._state_is_finite()
    prior_state = self._state.copy()
    prior_covariance = self._covariance.copy()
    innovations = []
    for measurement, noise in zip(event.observation.values, event.observation.noise, strict=True):
      innovations.append(self._update(event.observation.kind, measurement, noise))
    return (event.time, self.x, prior_state, self.P, prior_covariance, event.observation.kind,
            tuple(innovations), event.observation.values.copy(), event.observation.noise.copy())

  def _update(self, kind: int, measurement: Array, noise: Array) -> Array:
    measurement_function = self.model.measurements.get(kind)
    if measurement_function is None:
      raise KeyError(f"unknown observation kind {kind}")
    measurement = np.asarray(measurement, dtype=np.float64).reshape(-1)
    if noise.shape != (measurement.size, measurement.size):
      raise ValueError("observation noise dimension mismatch")
    if self.model.native_update is not None:
      innovation = self.model.native_update(self._state, self._covariance, kind, measurement, noise)
      return innovation
    predicted = np.asarray(measurement_function(self._state, self.parameters), dtype=np.float64).reshape(-1)
    if predicted.shape != measurement.shape:
      raise ValueError("measurement dimension mismatch")
    innovation = measurement - predicted
    state_jacobian = self._jacobian(lambda value: measurement_function(value, self.parameters), self._state)
    observation_jacobian = state_jacobian @ self._error_projection(self._state)
    innovation_covariance = observation_jacobian @ self._covariance @ observation_jacobian.T + noise
    gain = np.linalg.solve(innovation_covariance, observation_jacobian @ self._covariance).T
    delta = gain @ innovation
    self._state = self._normalize(self._inject(self._state, delta))
    identity = np.eye(self.model.error_size)
    residual = identity - gain @ observation_jacobian
    self._covariance = self._stabilize(residual @ self._covariance @ residual.T + gain @ noise @ gain.T)
    self._require_finite()
    return innovation

  def _rewind(self, new_event: _Event, full: bool = True):
    base_index = next((i for i in range(len(self._snapshots) - 1, -1, -1)
                       if math.isnan(self._snapshots[i].time) or self._snapshots[i].time <= new_event.time), None)
    if base_index is None:
      raise ValueError("no snapshot precedes the observation")
    base = self._snapshots[base_index]
    retained = self._events[:base_index]
    pending = self._events[base_index:]
    insert_at = len(pending)
    while insert_at > 0 and (pending[insert_at - 1].time, pending[insert_at - 1].order) > (new_event.time, new_event.order):
      insert_at -= 1
    replay = pending[:insert_at] + [new_event] + pending[insert_at:]
    self._state = base.state.copy()
    self._covariance = base.covariance.copy()
    self._time = base.time
    self._events = retained.copy()
    self._snapshots = self._snapshots[:base_index + 1]
    result = None
    for event in replay:
      current = self._apply_event(event, full)
      self._events.append(event)
      self._snapshots.append(_Snapshot(self._time, self._state.copy(), self._covariance.copy()))
      if event is new_event:
        result = current
    self._trim_history()
    return result

  def _trim_history(self) -> None:
    if self.max_rewind_age <= 0.0 or math.isnan(self._time):
      return
    cutoff = self._time - self.max_rewind_age
    remove = 0
    while remove < len(self._events) and self._events[remove].time < cutoff:
      remove += 1
    if remove:
      self._events = self._events[remove:]
      self._snapshots = self._snapshots[remove:]

  def _measurement_batch(self, kind: int, measurements: Array) -> Array:
    if measurements.__class__ is np.ndarray and measurements.dtype == np.float64 and measurements.ndim == 1:
      expected = self._native_sizes.get(kind)
      if expected is not None and measurements.shape[0] == expected:
        return measurements.reshape(1, -1)
    measurement_function = self.model.measurements.get(kind)
    if measurement_function is None:
      raise KeyError(f"unknown observation kind {kind}")
    if self.model.native_update is not None and kind in self.model.observation_noise:
      expected = self.model.observation_noise[kind].shape[0]
    else:
      expected = np.asarray(measurement_function(self._state, self.parameters)).size
    values = np.asarray(measurements, dtype=np.float64)
    if values.ndim == 1:
      values = values.reshape(1, -1)
    elif values.ndim != 2:
      raise ValueError("measurements must be one or two dimensional")
    if values.shape[1] != expected:
      raise ValueError("measurement dimension mismatch")
    return values

  def _noise_batch(self, kind: int, count: int, noise: Array | None) -> Array:
    if noise is None and count == 1:
      cached = self._default_noise.get(kind)
      if cached is None:
        base = self.model.observation_noise.get(kind)
        if base is None:
          raise KeyError(f"missing observation noise for kind {kind}")
        cached = self._default_noise[kind] = np.repeat(np.asarray(base, dtype=np.float64)[None, :, :], 1, axis=0)
        cached.setflags(write=False)
      return cached
    if noise is None:
      base = self.model.observation_noise.get(kind)
      if base is None:
        raise KeyError(f"missing observation noise for kind {kind}")
      return np.repeat(np.asarray(base, dtype=np.float64)[None, :, :], count, axis=0)
    noises = np.asarray(noise, dtype=np.float64)
    if noises.ndim == 2:
      noises = noises[None, :, :]
    if noises.shape[0] == 1 and count > 1:
      noises = np.repeat(noises, count, axis=0)
    if noises.shape[0] != count:
      raise ValueError("observation noise batch mismatch")
    return noises

  def _jacobian(self, function: Callable[[Array], Array], value: Array) -> Array:
    output = np.asarray(function(value), dtype=np.float64).reshape(-1)
    result = np.empty((output.size, value.size), dtype=np.float64)
    for index in range(value.size):
      step = np.cbrt(np.finfo(np.float64).eps) * max(1.0, abs(value[index]))
      upper = value.copy()
      lower = value.copy()
      upper[index] += step
      lower[index] -= step
      result[:, index] = (np.asarray(function(upper)).reshape(-1) - np.asarray(function(lower)).reshape(-1)) / (2.0 * step)
    return result

  def _inject(self, state: Array, delta: Array) -> Array:
    if self.model.inject_error is None:
      return state + delta
    return self.model.inject_error(state, delta)

  def _error_projection(self, state: Array) -> Array:
    if self.model.error_projection is None:
      return np.eye(self.model.state_size, self.model.error_size)
    return np.asarray(self.model.error_projection(state), dtype=np.float64)

  def _normalize(self, state: Array) -> Array:
    if self.model.normalize is None:
      return np.asarray(state, dtype=np.float64).reshape(-1)
    return np.asarray(self.model.normalize(state), dtype=np.float64).reshape(-1)

  def _stabilize(self, covariance: Array) -> Array:
    covariance = (covariance + covariance.T) * 0.5
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    if eigenvalues[0] < -1e-10:
      raise FloatingPointError("covariance is not positive semidefinite")
    return (eigenvectors * np.maximum(eigenvalues, 0.0)) @ eigenvectors.T

  def _validate_state(self, state: Array, covariance: Array) -> None:
    if state.shape != (self.model.state_size,):
      raise ValueError("state dimension mismatch")
    if covariance.shape != (self.model.error_size, self.model.error_size):
      raise ValueError("covariance dimension mismatch")
    if self.model.process_noise.shape != covariance.shape:
      raise ValueError("process noise dimension mismatch")
    if not np.isfinite(state).all() or not np.isfinite(covariance).all():
      raise ValueError("state and covariance must be finite")

  def _require_finite(self) -> None:
    if not np.isfinite(self._state).all() or not np.isfinite(self._covariance).all():
      raise FloatingPointError("estimator produced non-finite values")


class EstimatorModel:
  def __init__(self, estimator: StateEstimator):
    self.filter = estimator

  @property
  def x(self) -> Array:
    return self.filter.x

  @property
  def P(self) -> Array:
    return self.filter.P

  @property
  def t(self) -> float:
    return self.filter.t

  def init_state(self, state: Array, covs: Array, filter_time: float | None) -> None:
    self.filter.init_state(state, covs, filter_time)

  def predict(self, time: float) -> None:
    self.filter.predict(time)

  def predict_and_observe(self, time: float, kind: int, measurements: Array, noise: Array | None = None):
    return self.filter.predict_and_observe(time, kind, measurements, noise)

  def observe(self, time: float, kind: int, measurements: Array, noise: Array | None = None):
    return self.filter.observe(time, kind, measurements, noise)

  @property
  def x_view(self) -> Array:
    return self.filter._state
