from enum import IntEnum

import raylib_nb as rl
from iqpilot.common.filter_simple import FirstOrderFilter
from iqpilot.common.params import Params
from iqpilot.selfdrive.ui.mici.onroad.torque_bar import TorqueBar
from iqpilot.selfdrive.ui.ui_state import ui_state
from iqpilot.system.ui.lib.application import gui_app, FontWeight
from iqpilot.system.ui.lib.multilang import tr
from iqpilot.system.ui.lib.raylib_compat import draw_circle_gradient
from iqpilot.system.ui.widgets import Widget
from iqpilot.ui.mici.onroad.lead_stats import LeadStatsBubble

SET_SPEED_NA = 255
KM_TO_MILE = 0.621371
SET_SPEED_PERSISTENCE = 2.5
SET_SPEED_FONT_SIZE = 112
MAX_FONT_SIZE = 36
SET_SPEED_SHADOW_RADIUS = 81
BOTTOM_DISPLAY_PARAM = "IQMiciBottomDisplay"
BOTTOM_DISPLAY_REFRESH_FRAMES = 60


class BottomDisplay(IntEnum):
  OFF = 0
  TORQUE_BAR = 1
  LEAD_STATS = 2


def read_bottom_display(params: Params) -> BottomDisplay:
  try:
    return BottomDisplay(int(params.get(BOTTOM_DISPLAY_PARAM, return_default=True)))
  except (TypeError, ValueError):
    return BottomDisplay.TORQUE_BAR


class HudRenderer(Widget):
  def __init__(self):
    super().__init__()
    self.is_cruise_set = False
    self.set_speed: float = SET_SPEED_NA
    self._set_speed_changed_time = 0.0
    self._engaged = False
    self._can_draw_top_icons = True

    self._font_semi_bold = gui_app.font(FontWeight.SEMI_BOLD)
    self._font_display = gui_app.font(FontWeight.DISPLAY)

    self._params = Params()
    self._bottom_display = read_bottom_display(self._params)
    self._bottom_display_refresh = BOTTOM_DISPLAY_REFRESH_FRAMES
    self._torque_bar = TorqueBar()
    self._lead_stats = LeadStatsBubble()
    self._set_speed_alpha_filter = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)

  def set_can_draw_top_icons(self, can_draw_top_icons: bool):
    self._can_draw_top_icons = can_draw_top_icons

  def _update_state(self) -> None:
    self._bottom_display_refresh -= 1
    if self._bottom_display_refresh <= 0:
      self._bottom_display_refresh = BOTTOM_DISPLAY_REFRESH_FRAMES
      self._bottom_display = read_bottom_display(self._params)

    sm = ui_state.sm
    if sm.recv_frame["carState"] < ui_state.started_frame:
      self.is_cruise_set = False
      self.set_speed = SET_SPEED_NA
      return

    v_cruise_cluster = sm['carState'].vCruiseCluster
    set_speed = sm['controlsState'].vCruiseDEPRECATED if v_cruise_cluster == 0.0 else v_cruise_cluster
    engaged = sm['selfdriveState'].enabled
    if (set_speed != self.set_speed and engaged) or (engaged and not self._engaged):
      self._set_speed_changed_time = rl.get_time()
    self._engaged = engaged
    self.set_speed = set_speed
    self.is_cruise_set = 0 < self.set_speed < SET_SPEED_NA

  def _render(self, rect: rl.Rectangle) -> None:
    if self._bottom_display == BottomDisplay.TORQUE_BAR:
      self._torque_bar.render(rect)
    elif self._bottom_display == BottomDisplay.LEAD_STATS:
      self._lead_stats.render(rect)
    if self.is_cruise_set:
      self._draw_set_speed(rect)

  def _draw_set_speed(self, rect: rl.Rectangle) -> None:
    alpha = self._set_speed_alpha_filter.update(0 < rl.get_time() - self._set_speed_changed_time < SET_SPEED_PERSISTENCE and
                                                self._can_draw_top_icons and self._engaged)
    if alpha < 1e-2:
      return

    r = SET_SPEED_SHADOW_RADIUS
    draw_circle_gradient(int(rect.x + r), int(rect.y + r), r, rl.Color(0, 0, 0, int(255 / 2 * alpha)), rl.BLANK)

    color = rl.Color(255, 255, 255, int(255 * 0.9 * alpha))
    set_speed = self.set_speed if ui_state.is_metric else self.set_speed * KM_TO_MILE
    rl.draw_text_ex(self._font_display, str(round(set_speed)), rl.Vector2(rect.x + 17, rect.y - 4), SET_SPEED_FONT_SIZE, 0, color)
    rl.draw_text_ex(self._font_semi_bold, tr("MAX"), rl.Vector2(rect.x + 25, rect.y + SET_SPEED_FONT_SIZE - 3), MAX_FONT_SIZE, 0, color)
