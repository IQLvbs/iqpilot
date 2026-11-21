import math

import raylib_nb as rl

from iqpilot.selfdrive.ui.ui_state import ui_state
from iqpilot.system.ui.lib.application import FontWeight, gui_app
from iqpilot.ui.mici.onroad.bubble import ValueUnit, draw_bubble, faded

ICON_SIZE = 32
VALUE_SIZE = 30
UNIT_SIZE = 17
BUBBLE_HEIGHT = 46
BUBBLE_MARGIN = 12
PAD_LEFT = 10
PAD_RIGHT = 16
ICON_GAP = 6


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
    self._text = ValueUnit(gui_app.font(FontWeight.BOLD), gui_app.font(FontWeight.MEDIUM), VALUE_SIZE, UNIT_SIZE)

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

  def render(self, rect: rl.Rectangle, alpha: float = 1.0):
    if alpha < 1e-2 or not self._value:
      return
    icon_w = ICON_SIZE + ICON_GAP if self._icon else 0
    width = PAD_LEFT + icon_w + self._text.width(self._value, self._unit) + PAD_RIGHT
    bubble = rl.Rectangle(rect.x + rect.width - BUBBLE_MARGIN - width, rect.y + BUBBLE_MARGIN, width, BUBBLE_HEIGHT)
    draw_bubble(bubble, alpha)

    x = bubble.x + PAD_LEFT
    mid = bubble.y + BUBBLE_HEIGHT / 2
    if self._icon:
      icon = gui_app.texture('navigation/' + self._icon, ICON_SIZE, ICON_SIZE)
      rl.draw_texture(icon, int(x), int(mid - icon.height / 2), faded(rl.WHITE, alpha))
      x += icon_w
    self._text.draw(x, mid, self._value, self._unit, alpha)
