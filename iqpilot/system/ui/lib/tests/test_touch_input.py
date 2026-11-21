# Copyright (c) 2026 IQ.Lvbs. All rights reserved.
from collections import deque
from types import SimpleNamespace

import raylib_nb as rl
import pytest

from iqpilot.system.ui.lib import scroll_panel2
from iqpilot.system.ui.lib.application import MouseEvent, MousePos, gui_app
from iqpilot.system.ui.lib.scroll_panel2 import GuiScrollPanel2, ScrollState, fit_velocity

BOUNDS = rl.Rectangle(0, 0, 500, 1000)
CONTENT_SIZE = 5000


def press(x, y, t, slot=0):
  return MouseEvent(MousePos(x, y), slot, True, False, True, t)


def move(x, y, t, slot=0):
  return MouseEvent(MousePos(x, y), slot, False, False, True, t)


def release(x, y, t, slot=0):
  return MouseEvent(MousePos(x, y), slot, False, True, False, t)


@pytest.fixture
def frame_events(monkeypatch):
  app = SimpleNamespace(mouse_events=[])
  monkeypatch.setattr(scroll_panel2, "gui_app", app)
  monkeypatch.setattr(scroll_panel2.rl, "get_frame_time", lambda: 0.0)

  def feed(panel, events):
    for event in events:
      app.mouse_events = [event]
      panel.update(BOUNDS, CONTENT_SIZE)
  return feed


def vertical_swipe(times, step):
  events = [press(250, 900, times[0])]
  events += [move(250, 900 - step * i, t) for i, t in enumerate(times[1:], start=1)]
  events.append(release(250, 900 - step * (len(times) - 1), times[-1] + 0.007))
  return events


def test_second_finger_does_not_move_scroll_content(frame_events):
  panel = GuiScrollPanel2(horizontal=False)
  events = [press(250, 900, 0.0)]
  for i in range(1, 8):
    events.append(move(250, 900 - 20 * i, 0.01 * i))
    events.append(press(250, 100, 0.01 * i + 0.002, slot=1) if i == 1 else move(250, 100, 0.01 * i + 0.002, slot=1))
  frame_events(panel, events)

  assert panel.state == ScrollState.MANUAL_SCROLL
  assert panel.get_offset() == pytest.approx(-20 * 6)


def test_fit_velocity_is_robust_to_timestamp_jitter():
  true_velocity = -2000.0
  real_t = [0.007 * i for i in range(6)]
  jitter = [0.0, 0.003, -0.003, 0.003, -0.003, 0.0]
  samples = deque((t + j, true_velocity * t) for t, j in zip(real_t, jitter, strict=True))

  assert fit_velocity(samples) == pytest.approx(true_velocity, rel=0.15)
  assert fit_velocity(deque([(0.0, 0.0)])) == 0.0
  assert fit_velocity(deque([(0.1, 0.0), (0.1, 50.0)])) == 0.0


def test_steady_swipe_with_jittery_timestamps_flings(frame_events):
  panel = GuiScrollPanel2(horizontal=False)
  times = [0.0]
  for dt in (0.007, 0.007, 0.007, 0.007, 0.003, 0.007, 0.007, 0.012, 0.007):
    times.append(times[-1] + dt)
  frame_events(panel, vertical_swipe(times, 30))

  assert panel.state == ScrollState.AUTO_SCROLL
  assert panel._velocity < -1000


def test_swipe_stop_then_lift_does_not_fling(frame_events):
  panel = GuiScrollPanel2(horizontal=False)
  steps = [40, 40, 40, 40, 1, 1, 1, 1, 1, 1]
  events = [press(250, 900, 0.0)]
  y = 900
  for i, step in enumerate(steps, start=1):
    y -= step
    events.append(move(250, y, 0.007 * i))
  events.append(release(250, y, 0.007 * (len(steps) + 1)))
  frame_events(panel, events)

  assert panel.state == ScrollState.STEADY


@pytest.fixture
def keyboard(monkeypatch):
  monkeypatch.setattr(gui_app, "font", lambda *args, **kwargs: None, raising=False)
  monkeypatch.setattr(gui_app, "texture", lambda *args, **kwargs: SimpleNamespace(width=520, height=170), raising=False)
  from iqpilot.system.ui.widgets.mici_keyboard import MiciKeyboard
  kb = MiciKeyboard()
  kb.set_rect(rl.Rectangle(0, 0, 520, 240))
  for row in kb._current_keys:
    for key in row:
      key.original_position = rl.Vector2(10000, 10000)
  key_by_char = {key.char: key for row in kb._current_keys for key in row}
  key_by_char["a"].original_position = rl.Vector2(100, 150)
  key_by_char["l"].original_position = rl.Vector2(400, 150)

  def feed(events):
    monkeypatch.setattr(gui_app, "_mouse_events", events, raising=False)
    for event in events:
      if event.slot == 0:
        monkeypatch.setattr(gui_app, "_last_mouse_event", event, raising=False)
    kb._process_mouse_events()
  kb.feed = feed
  return kb


def test_mici_keyboard_second_finger_types_first_fingers_key(keyboard):
  keyboard.feed([press(100, 150, 0.0)])
  assert keyboard.get_candidate_character() == "a"

  keyboard.feed([press(400, 150, 0.1, slot=1)])
  assert keyboard.text() == "a"
  assert keyboard.get_candidate_character() == "l"

  keyboard.feed([release(400, 150, 0.2, slot=1)])
  assert keyboard.text() == "al"

  keyboard.feed([release(100, 150, 0.3)])
  assert keyboard.text() == "al"


def test_mici_keyboard_single_finger_types_on_release(keyboard):
  keyboard.feed([press(100, 150, 0.0), move(250, 150, 0.03), move(400, 150, 0.05)])
  assert keyboard.text() == ""
  keyboard.feed([release(400, 150, 0.1)])
  assert keyboard.text() == "l"


def test_mici_keyboard_disabled_mid_press_does_not_type_stale_key(keyboard):
  keyboard.feed([press(100, 150, 0.0)])
  keyboard.set_enabled(False)
  keyboard._update_state()
  keyboard.set_enabled(True)

  keyboard.feed([press(400, 150, 0.5)])
  keyboard.feed([release(400, 150, 0.6)])
  assert keyboard.text() == "l"
