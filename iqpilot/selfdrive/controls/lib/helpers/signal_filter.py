"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""


class SignalFilter:
  def __init__(self, initial=0.0, measurement_noise=0.1, process_noise=0.01, process_decay=1.0, smoothing_floor=0.85):
    self._value = initial
    self._variance = 1.0
    self._measurement_noise = measurement_noise
    self._process_noise = process_noise
    self._process_decay = process_decay
    self._smoothing_floor = smoothing_floor
    self._initialized = False

  def push(self, measurement: float) -> None:
    if not self._initialized:
      self._value = measurement
      self._initialized = True
      return

    self._variance = self._process_decay * self._variance + self._process_noise
    gain = self._variance / (self._variance + self._measurement_noise)
    effective_gain = gain * (1.0 - self._smoothing_floor) + self._smoothing_floor * 0.1

    self._value = self._value + effective_gain * (measurement - self._value)
    self._variance = (1.0 - effective_gain) * self._variance

  def value(self):
    return self._value if self._initialized else None

  def reset(self) -> None:
    self._initialized = False
