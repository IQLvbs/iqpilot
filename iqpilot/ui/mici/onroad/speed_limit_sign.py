"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import math

from iqpilot.common.filter_simple import FirstOrderFilter
from iqpilot.selfdrive.ui.ui_state import ui_state
from iqpilot.system.ui.iqwidgets.lib import canvas
from iqpilot.system.ui.lib.application import FontWeight, gui_app
from iqpilot.system.ui.widgets import Widget
from iqpilot.ui.onroad.hud_overlays import SpeedLimitState, _SL_ASSIST, _SL_DARK, _dim

_SIGN_X = 17
_SIGN_BOTTOM = 14
_SIGN_W = 46
_SIGN_H = 60
_BADGE_SIDE = 28


class MiciSpeedLimitSign(SpeedLimitState, Widget):
  def __init__(self):
    super().__init__()
    self._visible = FirstOrderFilter(0.0, 0.1, 1 / gui_app.target_fps)
    self.assist_frame = 0
    self._bold = gui_app.font(FontWeight.BOLD)
    self._demi = gui_app.font(FontWeight.SEMI_BOLD)
    self._pulse_ema = FirstOrderFilter(1.0, 0.5, 1 / gui_app.target_fps)

  def _badge(self) -> str:
    offset = round(self.speed_limit_offset)
    return f"{offset:+d}" if offset != 0 else ""

  def _render(self, rect):
    value, _, tint, has_limit = self._spec()
    shown = has_limit and ui_state.speed_limit_mode != 0 and ui_state.is_onroad()
    alpha = self._visible.update(1.0 if shown else 0.0)
    if alpha < 1e-2:
      return
    if self.assist_state == _SL_ASSIST.preActive:
      self.assist_frame += 1
      pulse = 0.65 + 0.35 * math.sin(self.assist_frame * math.pi / gui_app.target_fps)
      alpha *= self._pulse_ema.update(pulse)
    else:
      self.assist_frame = 0
      self._pulse_ema.update(1.0)
    height = _SIGN_W if ui_state.is_metric else _SIGN_H
    box = canvas.Box(rect.x + _SIGN_X, rect.y + rect.height - _SIGN_BOTTOM - height, _SIGN_W, height)
    badge = self._badge()
    (self._vienna if ui_state.is_metric else self._mutcd)(box, value, badge, tint, alpha)

  def _vienna(self, rect, value, badge, tint, alpha):
    radius = rect.width / 2
    hub = canvas.Pt(rect.x + radius, rect.y + rect.height / 2)
    canvas.disc_at(hub, radius, _dim(canvas.WHITE, alpha))
    canvas.annulus(hub, radius * 0.78, radius, 0, 360, 36, _dim(canvas.RED, alpha))
    canvas.glyphs_centered(self._bold, value, 18 if len(value) >= 3 else 22, hub, _dim(tint, alpha))
    if badge:
      br = _BADGE_SIDE / 2
      bc = canvas.Pt(rect.x + rect.width - br * 0.35, rect.y + br * 0.35)
      canvas.disc_at(bc, br, _dim(canvas.BLACK, alpha))
      canvas.annulus(bc, br - 2, br, 0, 360, 24, _dim(_SL_DARK, alpha))
      canvas.glyphs_centered(self._bold, badge, 13 if len(badge) >= 3 else 16, bc, _dim(canvas.WHITE, alpha))

  def _mutcd(self, rect, value, badge, tint, alpha):
    canvas.panel(rect, 0.25, 8, _dim(canvas.WHITE, alpha))
    inner = canvas.Box(rect.x + 3, rect.y + 3, rect.width - 6, rect.height - 6)
    canvas.panel_outline(inner, 0.25, 8, 2, _dim(canvas.BLACK, alpha))
    mid = rect.x + rect.width / 2
    canvas.glyphs_centered(self._demi, "SPEED", 10, canvas.Pt(mid, rect.y + 13), _dim(canvas.BLACK, alpha))
    canvas.glyphs_centered(self._demi, "LIMIT", 10, canvas.Pt(mid, rect.y + 23), _dim(canvas.BLACK, alpha))
    canvas.glyphs_centered(self._bold, value, 27 if len(value) <= 2 else 22, canvas.Pt(mid, rect.y + 42), _dim(tint, alpha))
    if badge:
      chip = canvas.Box(rect.x + rect.width - _BADGE_SIDE * 0.35, rect.y - _BADGE_SIDE * 0.75, _BADGE_SIDE, _BADGE_SIDE)
      canvas.panel(chip, 0.35, 8, _dim(canvas.BLACK, alpha))
      canvas.panel_outline(chip, 0.35, 8, 2, _dim(_SL_DARK, alpha))
      canvas.glyphs_centered(self._bold, badge, 13 if len(badge) >= 3 else 16,
                             canvas.Pt(chip.x + _BADGE_SIDE / 2, chip.y + _BADGE_SIDE / 2), _dim(canvas.WHITE, alpha))
