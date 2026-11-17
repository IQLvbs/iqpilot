from types import SimpleNamespace

import pytest

from iqpilot.ui.mici.onroad import navigation


@pytest.fixture
def scene(monkeypatch):
  nav = SimpleNamespace(active=True, destinationValid=True, destinationLatitude=41.0, destinationLongitude=-87.0,
                        nextManeuverValid=True, nextManeuverDistance=3000.0, nextManeuverDescription='Turn left onto Main Street',
                        nextManeuverType=SimpleNamespace(raw=1), nextManeuverDirection=SimpleNamespace(raw=1))

  class Messages(dict):
    alive = {'iqNavState': True}
    valid = {'iqNavState': True}

  params = {'NavigationDestination': {'latitude': 41.0, 'longitude': -87.0}, 'NavigationActive': True, 'NavigationEnabled': True}
  sm = Messages(iqNavState=nav)
  state = SimpleNamespace(started=True, is_metric=False, sm=sm,
                          params=SimpleNamespace(get=params.get, get_bool=lambda key: bool(params.get(key))))
  monkeypatch.setattr(navigation, 'ui_state', state)
  monkeypatch.setattr(navigation, 'gui_app', SimpleNamespace(font=lambda _: None))
  screen = navigation.MiciNavigation()
  screen.update()
  return SimpleNamespace(screen=screen, nav=nav, sm=sm, state=state, params=params)


@pytest.mark.parametrize('invalid', ['missing', 'malformed', 'cancelled', 'disabled', 'offroad', 'stale', 'invalid_message',
                                     'inactive', 'wrong_destination', 'no_destination', 'no_maneuver', 'nan', 'negative'])
def test_invalid_guidance_hides_indicator(scene, invalid):
  assert scene.screen.active
  if invalid == 'missing':
    scene.params.pop('NavigationDestination')
  elif invalid == 'malformed':
    scene.params['NavigationDestination'] = {'latitude': float('nan'), 'longitude': -87.0}
  elif invalid == 'cancelled':
    scene.params['NavigationActive'] = False
  elif invalid == 'disabled':
    scene.params['NavigationEnabled'] = False
  elif invalid == 'offroad':
    scene.state.started = False
  elif invalid == 'stale':
    scene.sm.alive['iqNavState'] = False
  elif invalid == 'invalid_message':
    scene.sm.valid['iqNavState'] = False
  else:
    field, value = {'inactive': ('active', False), 'wrong_destination': ('destinationLatitude', 42.0),
                    'no_destination': ('destinationValid', False), 'no_maneuver': ('nextManeuverValid', False),
                    'nan': ('nextManeuverDistance', float('nan')), 'negative': ('nextManeuverDistance', -1.0)}[invalid]
    setattr(scene.nav, field, value)
  scene.screen.update()
  assert not scene.screen.active


def test_guidance_recovers_after_stale_stream(scene):
  scene.sm.alive['iqNavState'] = False
  scene.screen.update()
  assert not scene.screen.active
  scene.sm.alive['iqNavState'] = True
  scene.screen.update()
  assert scene.screen.active


def test_master_switch_hides_live_guidance_and_can_reenable_it(scene):
  scene.params['NavigationEnabled'] = False
  scene.screen.update()
  assert not scene.screen.active
  scene.params['NavigationEnabled'] = True
  scene.screen.update()
  assert scene.screen.active


@pytest.mark.parametrize('maneuver_type, direction, icon', [
  (1, 1, 'direction_turn_left.png'), (1, 2, 'direction_turn_right.png'), (2, 2, 'direction_off_ramp_right.png'),
  (3, 1, 'direction_merge_left.png'), (4, 2, 'direction_fork_right.png'), (6, 1, 'direction_arrive.png'), (0, 0, None),
])
def test_maneuver_icon(scene, maneuver_type, direction, icon):
  scene.nav.nextManeuverType.raw = maneuver_type
  scene.nav.nextManeuverDirection.raw = direction
  scene.screen.update()
  assert scene.screen._icon == icon


@pytest.mark.parametrize('distance, metric, expected', [
  (3000.0, False, ('1.9', 'mi')), (100.0, False, ('330', 'ft')), (3000.0, True, ('3.0', 'km')), (456.0, True, ('460', 'm')),
])
def test_distance_format(distance, metric, expected):
  assert navigation.format_distance(distance, metric) == expected


def test_distance_follows_guidance(scene):
  assert (scene.screen._value, scene.screen._unit) == ('1.9', 'mi')
  scene.nav.nextManeuverDistance = 150.0
  scene.screen.update()
  assert (scene.screen._value, scene.screen._unit) == ('490', 'ft')

