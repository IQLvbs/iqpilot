"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import raylib_nb as rl

from iqpilot.common.filter_simple import FirstOrderFilter
from iqpilot.selfdrive.ui.ui_state import ui_state
from iqpilot.system.ui.lib.application import FontWeight, gui_app
from iqpilot.system.ui.widgets import Widget
from iqpilot.ui.mici.onroad.bubble import UNIT_COLOR, ValueUnit, draw_bubble, faded
from iqpilot.ui.onroad.hud_overlays import _gap_label, _pace_label, _ttc_label

VALUE_SIZE = 26
UNIT_SIZE = 15
BUBBLE_HEIGHT = 40
PAD_X = 16
STAT_GAP = 12
DIVIDER_HEIGHT = 18
BOTTOM_MARGIN = 10


def split_label(label: str) -> tuple[str, str]:
  value, _, unit = label.partition(" ")
  return value, unit


def lead_stats_parts(d_rel: float, v_rel: float, v_ego: float) -> list[tuple[str, str]]:
  v_lead = v_rel + v_ego
  return [split_label(_gap_label(d_rel, v_lead)), split_label(_pace_label(d_rel, v_lead)), split_label(_ttc_label(d_rel, v_lead, v_ego))]


class LeadStatsBubble(Widget):
  def __init__(self):
    super().__init__()
    self._text = ValueUnit(gui_app.font(FontWeight.BOLD), gui_app.font(FontWeight.MEDIUM), VALUE_SIZE, UNIT_SIZE)
    self._alpha = FirstOrderFilter(0.0, 0.15, 1 / gui_app.target_fps)
    self._parts: list[tuple[str, str]] = []

  def _update_state(self) -> None:
    sm = ui_state.sm
    lead = sm['radarState'].leadOne if sm.valid['radarState'] else None
    has_lead = lead is not None and lead.status
    if has_lead:
      self._parts = lead_stats_parts(lead.dRel, lead.vRel, sm['carState'].vEgo)
    self._alpha.update(1.0 if has_lead else 0.0)

  def _render(self, rect: rl.Rectangle) -> None:
    alpha = self._alpha.x
    if alpha < 1e-2 or not self._parts:
      return
    widths = [self._text.width(value, unit) for value, unit in self._parts]
    width = 2 * PAD_X + sum(widths) + 2 * STAT_GAP * (len(widths) - 1)
    bubble = rl.Rectangle(rect.x + (rect.width - width) / 2, rect.y + rect.height - BOTTOM_MARGIN - BUBBLE_HEIGHT, width, BUBBLE_HEIGHT)
    draw_bubble(bubble, alpha)

    mid = bubble.y + BUBBLE_HEIGHT / 2
    x = bubble.x + PAD_X
    for i, (value, unit) in enumerate(self._parts):
      if i:
        x += STAT_GAP
        rl.draw_rectangle_rounded(rl.Rectangle(x - 1, mid - DIVIDER_HEIGHT / 2, 2, DIVIDER_HEIGHT), 1.0, 4, faded(UNIT_COLOR, alpha))
        x += STAT_GAP
      self._text.draw(x, mid, value, unit, alpha)
      x += widths[i]
