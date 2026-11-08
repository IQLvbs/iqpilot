from iqpilot.selfdrive.ui.mici.onroad.torque_bar import TORQUE_REST_HEIGHT, TorqueBar
from iqpilot.selfdrive.ui.ui_state import ui_state
from iqpilot.system.ui.iqwidgets.lib import canvas
from iqpilot.ui.mici.onroad.speed_limit_sign import _SIGN_BOTTOM, _SIGN_H, _SIGN_W, _SIGN_X
from iqpilot.ui.onroad.hud_overlays import ChevronMetrics

FONT_SIZE = 18
SEPARATOR = "   |   "
MARGIN = 10
LEAD_GAP = 12
SHADOW_OFFSET = 1


class MiciChevronMetrics(ChevronMetrics):
  def _one_lead(self, lead, marker, v_ego: float, rect):
    if not self.should_render() or marker.center is None:
      return
    lines = self._labels(lead.dRel, lead.vRel, v_ego)
    if not lines:
      return

    text = SEPARATOR.join(lines)
    width = canvas.span(self._font, text, FONT_SIZE).x
    floor = TorqueBar.resting_bottom(rect) - TORQUE_REST_HEIGHT - MARGIN
    y = marker.center[1] + LEAD_GAP
    if y + FONT_SIZE > floor:
      y = max(rect.y + MARGIN, min(marker.center[1] - LEAD_GAP, floor) - FONT_SIZE)
    left = rect.x + MARGIN
    if ui_state.speed_limit_mode != 0 and y + FONT_SIZE > rect.y + rect.height - _SIGN_BOTTOM - _SIGN_H:
      left = rect.x + _SIGN_X + _SIGN_W + MARGIN
    x = max(left, min(marker.center[0] - width / 2, rect.x + rect.width - width - MARGIN))

    shadow = canvas.shade(0, 0, 0, int(200 * self._alpha))
    color = canvas.shade(255, 255, 255, int(255 * self._alpha))
    canvas.glyphs(self._font, text, canvas.Pt(x + SHADOW_OFFSET, y + SHADOW_OFFSET), FONT_SIZE, shadow)
    canvas.glyphs(self._font, text, canvas.Pt(x, y), FONT_SIZE, color)
