"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import raylib_nb as rl

from iqpilot.system.ui.lib.text_measure import measure_text_cached

BUBBLE_ALPHA = 210
VALUE_COLOR = rl.Color(255, 255, 255, 255)
UNIT_COLOR = rl.Color(255, 255, 255, 150)
UNIT_GAP = 4


def draw_bubble(rect: rl.Rectangle, alpha: float) -> None:
  rl.draw_rectangle_rounded(rect, 1.0, 16, rl.Color(0, 0, 0, int(BUBBLE_ALPHA * alpha)))


def faded(color: rl.Color, alpha: float) -> rl.Color:
  return rl.Color(color.r, color.g, color.b, int(color.a * alpha))


class ValueUnit:
  def __init__(self, value_font, unit_font, value_size: int, unit_size: int):
    self.value_font, self.unit_font = value_font, unit_font
    self.value_size, self.unit_size = value_size, unit_size

  def width(self, value: str, unit: str) -> float:
    w = measure_text_cached(self.value_font, value, self.value_size).x
    if unit:
      w += UNIT_GAP + measure_text_cached(self.unit_font, unit, self.unit_size).x
    return w

  def draw(self, x: float, mid_y: float, value: str, unit: str, alpha: float) -> float:
    value_extent = measure_text_cached(self.value_font, value, self.value_size)
    top = mid_y - value_extent.y / 2
    rl.draw_text_ex(self.value_font, value, rl.Vector2(x, top), self.value_size, 0, faded(VALUE_COLOR, alpha))
    x += value_extent.x
    if unit:
      x += UNIT_GAP
      unit_extent = measure_text_cached(self.unit_font, unit, self.unit_size)
      unit_top = top + value_extent.y - unit_extent.y - value_extent.y * 0.08
      rl.draw_text_ex(self.unit_font, unit, rl.Vector2(x, unit_top), self.unit_size, 0, faded(UNIT_COLOR, alpha))
      x += unit_extent.x
    return x
