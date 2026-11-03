"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
import time
from collections.abc import Callable, Iterable

PERSIST_SECONDS = 4.0
PERSIST_SCANS = 2


class NetworkPersistenceFilter:
  def __init__(self, min_seconds: float = PERSIST_SECONDS, min_scans: int = PERSIST_SCANS,
               clock: Callable[[], float] = time.monotonic):
    self._min_seconds = min_seconds
    self._min_scans = min_scans
    self._clock = clock
    self._sightings: dict[str, tuple[float, int]] = {}
    self._persistent: set[str] = set()

  def observe(self, ssids: Iterable[str]) -> None:
    now = self._clock()
    updated: dict[str, tuple[float, int]] = {}
    for ssid in ssids:
      first_seen, scans = self._sightings.get(ssid, (now, 0))
      scans += 1
      updated[ssid] = (first_seen, scans)
      if scans >= self._min_scans and now - first_seen >= self._min_seconds:
        self._persistent.add(ssid)
    self._sightings = updated

  def is_persistent(self, ssid: str) -> bool:
    return ssid in self._persistent

  def reset_sightings(self) -> None:
    self._sightings = {}
