"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from iqpilot.cereal import messaging

PLANNER_SERVICES = (
  'carControl', 'carState', 'controlsState', 'vehicleParameters', 'radarState', 'modelV2', 'selfdriveState',
  'iqLiveLocation', 'iqLiveData', 'iqNavState', 'iqCarState', 'iqConstructionZone', 'gpsLocation', 'gpsLocationExternal',
  'clocks',
)


def _default(service):
  return getattr(messaging.new_message(service), service)


class ReplayState(dict):
  def __init__(self, services=PLANNER_SERVICES):
    super().__init__({service: _default(service) for service in services})
    self.logMonoTime = dict.fromkeys(services, 0)
    self.alive = dict.fromkeys(services, True)
    self.valid = dict.fromkeys(services, True)
    self.freq_ok = dict.fromkeys(services, True)
    self.updated = dict.fromkeys(services, False)
    self.seen = set()
    self.frame = 0

  def feed(self, event):
    name = event.which()
    if name not in self:
      return False
    self[name] = getattr(event, name)
    self.logMonoTime[name] = event.logMonoTime
    self.valid[name] = bool(event.valid)
    self.seen.add(name)
    return True

  def all_checks(self, service_list=None, **_):
    return all(self.valid.get(s, True) for s in (service_list or self.valid))

  def all_alive(self, service_list=None, **_):
    return True

  def all_freq_ok(self, service_list=None, **_):
    return True

  def all_valid(self, service_list=None, **_):
    return all(self.valid.get(s, True) for s in (service_list or self.valid))
