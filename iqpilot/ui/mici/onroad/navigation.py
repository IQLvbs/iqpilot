import math

import raylib_nb as rl

from iqpilot.selfdrive.ui.ui_state import ui_state
from iqpilot.system.ui.lib.application import FontWeight, gui_app
from iqpilot.system.ui.lib.text_measure import measure_text_cached

ICON_SIZE = 44
ICON_TOP = 12
VALUE_SIZE = 22
UNIT_SIZE = 15
UNIT_COLOR = rl.Color(255, 255, 255, 190)


def format_distance(distance_m: float, metric: bool) -> tuple[str, str]:
  if metric:
    return (f"{distance_m / 1000:.1f}", "km") if distance_m >= 1000 else (f"{round(distance_m / 10) * 10}", "m")
  feet = distance_m / 0.3048
  return (f"{distance_m / 1609.344:.1f}", "mi") if feet >= 1000 else (f"{round(feet / 10) * 10}", "ft")


class MiciNavigation:
  def __init__(self):
    self.active = False
    self._icon: str | None = None
    self._value = ""
    self._unit = ""
    self._value_font = gui_app.font(FontWeight.BOLD)
    self._unit_font = gui_app.font(FontWeight.MEDIUM)

  def update(self):
    self.active = False
    if not (ui_state.started and ui_state.params.get_bool("NavigationEnabled") and ui_state.params.get_bool("NavigationActive")):
      return
    destination = ui_state.params.get("NavigationDestination")
    try:
      lat, lon = float(destination['latitude']), float(destination['longitude'])
    except (KeyError, TypeError, ValueError, OverflowError):
      return
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
      return

    sm = ui_state.sm
    nav = sm['iqNavState']
    fresh = sm.alive['iqNavState'] and sm.valid['iqNavState']
    matches = (nav.destinationValid and abs(nav.destinationLatitude - lat) < 1e-5 and
               abs(nav.destinationLongitude - lon) < 1e-5)
    distance = nav.nextManeuverDistance
    if not (fresh and nav.active and matches and nav.nextManeuverValid and math.isfinite(distance) and distance >= 0):
      return

    self.active = True
    self._value, self._unit = format_distance(distance, ui_state.is_metric)
    direction = 'left' if nav.nextManeuverDirection.raw == 1 else 'right'
    kind = {1: 'turn', 2: 'off_ramp', 3: 'merge', 4: 'fork', 7: 'turn'}.get(nav.nextManeuverType.raw)
    if nav.nextManeuverType.raw == 6:
      self._icon = 'direction_arrive.png'
    elif kind is None:
      self._icon = None
    else:
      self._icon = f'direction_{kind}_{direction}.png'

  def render(self, rect: rl.Rectangle):
    if not self.active:
      return
    cx = rect.x + rect.width / 2
    y = rect.y + ICON_TOP
    if self._icon:
      icon = gui_app.texture('navigation/' + self._icon, ICON_SIZE, ICON_SIZE)
      rl.draw_texture(icon, int(cx - icon.width / 2), int(y), rl.WHITE)
    y += ICON_SIZE + 4
    for text, font, size, color in ((self._value, self._value_font, VALUE_SIZE, rl.WHITE),
                                    (self._unit, self._unit_font, UNIT_SIZE, UNIT_COLOR)):
      width = measure_text_cached(font, text, size).x
      rl.draw_text_ex(font, text, rl.Vector2(cx - width / 2, y), size, 0, color)
      y += size
