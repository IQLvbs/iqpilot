"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

from enum import IntEnum
from collections.abc import Callable
from itertools import zip_longest
from typing import Union
import numpy as np
import raylib_nb as rl

from iqpilot.system.ui.lib.application import gui_app, FontWeight, DEFAULT_TEXT_SIZE, DEFAULT_TEXT_COLOR, FONT_SCALE, TextAlignment, TextAlignmentVertical
from iqpilot.system.ui.widgets import Widget
from iqpilot.system.ui.lib.text_measure import measure_text_cached
from iqpilot.system.ui.lib.emoji import find_emoji, emoji_tex
from iqpilot.system.ui.lib.wrap_text import wrap_text

ICON_PADDING = 15


# TODO: make this common
def _resolve_value(value, default=""):
  if callable(value):
    return value()
  return value if value is not None else default


class ScrollState(IntEnum):
  STARTING = 0
  SCROLLING = 1
  ENDING = 2


# TODO: merge anything new here to master
class MiciLabel(Widget):
  def __init__(self,
               text: str,
               font_size: int = DEFAULT_TEXT_SIZE,
               width: int | None = None,
               color: rl.Color = DEFAULT_TEXT_COLOR,
               font_weight: FontWeight = FontWeight.NORMAL,
               alignment: int = TextAlignment.LEFT,
               alignment_vertical: int = TextAlignmentVertical.TOP,
               spacing: int = 0,
               line_height: int | None = None,
               elide_right: bool = True,
               wrap_text: bool = False,
               scroll: bool = False):
    super().__init__()
    self.text = text
    self.wrapped_text: list[str] = []
    self.font_size = font_size
    self.width = width
    self.color = color
    self.font_weight = font_weight
    self.alignment = alignment
    self.alignment_vertical = alignment_vertical
    self.spacing = spacing
    self.line_height = line_height if line_height is not None else font_size
    self.elide_right = elide_right
    self.wrap_text = wrap_text
    self._height = 0

    # Scroll state
    self.scroll = scroll
    self._needs_scroll = False
    self._scroll_offset = 0
    self._scroll_pause_t: float | None = None
    self._scroll_state: ScrollState = ScrollState.STARTING

    assert not (self.scroll and self.wrap_text), "Cannot enable both scroll and wrap_text"
    assert not (self.scroll and self.elide_right), "Cannot enable both scroll and elide_right"

    self.set_text(text)

  @property
  def text_height(self):
    return self._height

  def set_font_size(self, font_size: int):
    self.font_size = font_size
    self.set_text(self.text)

  def set_width(self, width: int):
    if self.width != width:
      self._scroll_offset = 0
      self._scroll_pause_t = None
      self._scroll_state = ScrollState.STARTING
    self.width = width
    self._rect.width = width
    self.set_text(self.text)

  def set_text(self, txt: str):
    if self.text != txt:
      self._scroll_offset = 0
      self._scroll_pause_t = None
      self._scroll_state = ScrollState.STARTING
    self.text = txt
    text_size = measure_text_cached(gui_app.font(self.font_weight), self.text, self.font_size, self.spacing)
    if self.width is not None:
      self._rect.width = self.width
    else:
      self._rect.width = text_size.x

    if self.wrap_text:
      self.wrapped_text = wrap_text(gui_app.font(self.font_weight), self.text, self.font_size, int(self._rect.width))
      self._height = len(self.wrapped_text) * self.line_height
    elif self.scroll:
      self._needs_scroll = self.scroll and text_size.x > self._rect.width
      self._rect.height = text_size.y

  def set_color(self, color: rl.Color):
    self.color = color

  def set_font_weight(self, font_weight: FontWeight):
    self.font_weight = font_weight
    self.set_text(self.text)

  def _render(self, rect: rl.Rectangle):
    # Only scissor when we know there is a single scrolling line
    if self._needs_scroll:
      rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))

    font = gui_app.font(self.font_weight)

    text_y_offset = 0
    # Draw the text in the specified rectangle
    lines = self.wrapped_text or [self.text]
    if self.alignment_vertical == TextAlignmentVertical.BOTTOM:
      lines = lines[::-1]

    for display_text in lines:
      text_size = measure_text_cached(font, display_text, self.font_size, self.spacing)

      # Elide text to fit within the rectangle
      if self.elide_right and text_size.x > rect.width:
        ellipsis = "..."
        left, right = 0, len(display_text)
        while left < right:
          mid = (left + right) // 2
          candidate = display_text[:mid] + ellipsis
          candidate_size = measure_text_cached(font, candidate, self.font_size, self.spacing)
          if candidate_size.x <= rect.width:
            left = mid + 1
          else:
            right = mid
        display_text = display_text[: left - 1] + ellipsis if left > 0 else ellipsis
        text_size = measure_text_cached(font, display_text, self.font_size, self.spacing)

      # Handle scroll state. Pause at both endpoints, then snap back to the
      # readable start position instead of animating backward.
      elif self.scroll and self._needs_scroll:
        max_scroll = max(0.0, text_size.x - rect.width)
        speed = 0.8 / 60. * gui_app.target_fps
        if self._scroll_state == ScrollState.STARTING:
          if self._scroll_pause_t is None:
            self._scroll_pause_t = rl.get_time() + 2.0
          if rl.get_time() >= self._scroll_pause_t:
            self._scroll_state = ScrollState.SCROLLING
            self._scroll_pause_t = None

        elif self._scroll_state == ScrollState.SCROLLING:
          self._scroll_offset = max(-max_scroll, self._scroll_offset - speed)
          if self._scroll_offset <= -max_scroll:
            self._scroll_state = ScrollState.ENDING
            self._scroll_pause_t = None

        elif self._scroll_state == ScrollState.ENDING:
          if self._scroll_pause_t is None:
            self._scroll_pause_t = rl.get_time() + 1.5
          if rl.get_time() >= self._scroll_pause_t:
            self._scroll_offset = 0
            self._scroll_state = ScrollState.STARTING
            self._scroll_pause_t = None

      # Calculate horizontal position based on alignment
      if self._needs_scroll:
        text_x = rect.x + self._scroll_offset
      else:
        text_x = rect.x + {
          TextAlignment.LEFT: 0,
          TextAlignment.CENTER: (rect.width - text_size.x) / 2,
          TextAlignment.RIGHT: rect.width - text_size.x,
        }.get(self.alignment, 0) + self._scroll_offset

      # Calculate vertical position based on alignment
      text_y = rect.y + {
        TextAlignmentVertical.TOP: 0,
        TextAlignmentVertical.MIDDLE: (rect.height - text_size.y) / 2,
        TextAlignmentVertical.BOTTOM: rect.height - text_size.y,
      }.get(self.alignment_vertical, 0)
      text_y += text_y_offset

      rl.draw_text_ex(font, display_text, rl.Vector2(round(text_x), text_y), self.font_size, self.spacing, self.color)
      if self.alignment_vertical == TextAlignmentVertical.BOTTOM:
        text_y_offset -= self.line_height
      else:
        text_y_offset += self.line_height

    if self._needs_scroll:
      # draw black fade on left and right
      fade_width = 20
      text_width = measure_text_cached(font, self.text, self.font_size, self.spacing).x
      if self._scroll_offset > -(text_width - rect.width):
        rl.draw_rectangle_gradient_h(int(rect.x + rect.width - fade_width), int(rect.y), fade_width, int(rect.height), rl.BLANK, rl.BLACK)
      if self._scroll_offset < 0:
        rl.draw_rectangle_gradient_h(int(rect.x), int(rect.y), fade_width, int(rect.height), rl.BLACK, rl.BLANK)

      rl.end_scissor_mode()


# TODO: This should be a Widget class
def gui_label(
  rect: rl.Rectangle,
  text: str,
  font_size: int = DEFAULT_TEXT_SIZE,
  color: rl.Color = DEFAULT_TEXT_COLOR,
  font_weight: FontWeight = FontWeight.NORMAL,
  alignment: int = TextAlignment.LEFT,
  alignment_vertical: int = TextAlignmentVertical.MIDDLE,
  elide_right: bool = True
):
  font = gui_app.font(font_weight)
  text_size = measure_text_cached(font, text, font_size)
  display_text = text

  # Elide text to fit within the rectangle
  if elide_right and text_size.x > rect.width:
    _ellipsis = "..."
    left, right = 0, len(text)
    while left < right:
      mid = (left + right) // 2
      candidate = text[:mid] + _ellipsis
      candidate_size = measure_text_cached(font, candidate, font_size)
      if candidate_size.x <= rect.width:
        left = mid + 1
      else:
        right = mid
    display_text = text[: left - 1] + _ellipsis if left > 0 else _ellipsis
    text_size = measure_text_cached(font, display_text, font_size)

  # Calculate horizontal position based on alignment
  text_x = rect.x + {
    TextAlignment.LEFT: 0,
    TextAlignment.CENTER: (rect.width - text_size.x) / 2,
    TextAlignment.RIGHT: rect.width - text_size.x,
  }.get(alignment, 0)

  # Calculate vertical position based on alignment
  text_y = rect.y + {
    TextAlignmentVertical.TOP: 0,
    TextAlignmentVertical.MIDDLE: (rect.height - text_size.y) / 2,
    TextAlignmentVertical.BOTTOM: rect.height - text_size.y,
  }.get(alignment_vertical, 0)

  # Draw the text in the specified rectangle
  # TODO: add wrapping and proper centering for multiline text
  rl.draw_text_ex(font, display_text, rl.Vector2(text_x, text_y), font_size, 0, color)


def gui_text_box(
  rect: rl.Rectangle,
  text: str,
  font_size: int = DEFAULT_TEXT_SIZE,
  color: rl.Color = DEFAULT_TEXT_COLOR,
  alignment: int = TextAlignment.LEFT,
  alignment_vertical: int = TextAlignmentVertical.TOP,
  font_weight: FontWeight = FontWeight.NORMAL,
  line_scale: float = 1.0,
):
  if not text:
    return
  font = gui_app.font(font_weight)
  text_size = round(font_size * FONT_SCALE)
  line_spacing = round(font_size * FONT_SCALE * line_scale)
  key = (text, rect.x, rect.y, rect.width, rect.height, font.texture.id, font.baseSize, font.glyphCount,
         text_size, line_spacing, int(alignment), int(alignment_vertical))
  glyphs = _text_box_layouts.get(key)
  if glyphs is None:
    glyphs = _layout_text_box(font, text, rect, text_size, line_spacing, int(alignment), int(alignment_vertical))
    if len(_text_box_layouts) >= 32:
      _text_box_layouts.pop(next(iter(_text_box_layouts)))
    _text_box_layouts[key] = glyphs
  draw_text_ex = getattr(rl, "_orig_draw_text_ex", rl.draw_text_ex)
  for glyph, x, y in glyphs:
    draw_text_ex(font, glyph, rl.Vector2(x, y), text_size, 0, color)


_WRAP_CHAR = 1
_WRAP_WORD = 2
_text_box_layouts: dict[tuple, list[tuple[str, float, float]]] = {}


def _codepoint(buf: bytes, i: int) -> int:
  octet = buf[i]
  if octet <= 0x7f:
    return octet
  if (octet & 0xe0) == 0xc0:
    octet1 = buf[i + 1]
    if octet1 == 0 or (octet1 >> 6) != 2 or not 0xc2 <= octet <= 0xdf:
      return 0x3f
    return ((octet & 0x1f) << 6) | (octet1 & 0x3f)
  if (octet & 0xf0) == 0xe0:
    octet1, octet2 = buf[i + 1], buf[i + 2]
    if octet1 == 0 or (octet1 >> 6) != 2 or octet2 == 0 or (octet2 >> 6) != 2:
      return 0x3f
    if (octet == 0xe0 and not 0xa0 <= octet1 <= 0xbf) or (octet == 0xed and not 0x80 <= octet1 <= 0x9f):
      return 0x3f
    return ((octet & 0xf) << 12) | ((octet1 & 0x3f) << 6) | (octet2 & 0x3f)
  if (octet & 0xf8) == 0xf0 and octet <= 0xf4:
    octet1, octet2, octet3 = buf[i + 1], buf[i + 2], buf[i + 3]
    if any(o == 0 or (o >> 6) != 2 for o in (octet1, octet2, octet3)):
      return 0x3f
    if (octet == 0xf0 and not 0x90 <= octet1 <= 0xbf) or (octet == 0xf4 and not 0x80 <= octet1 <= 0x8f):
      return 0x3f
    codepoint = ((octet & 0x7) << 18) | ((octet1 & 0x3f) << 12) | ((octet2 & 0x3f) << 6) | (octet3 & 0x3f)
    return codepoint if codepoint <= 0x10ffff else 0x3f
  return 0x3f


def _codepoint_next(buf: bytes, i: int) -> tuple[int, int]:
  octet = buf[i]
  if (octet & 0xf8) == 0xf0:
    if any((buf[i + k] & 0xc0) != 0x80 for k in (1, 2, 3)):
      return 0x3f, 1
    return ((octet & 0x07) << 18) | ((buf[i + 1] & 0x3f) << 12) | ((buf[i + 2] & 0x3f) << 6) | (buf[i + 3] & 0x3f), 4
  if (octet & 0xf0) == 0xe0:
    if any((buf[i + k] & 0xc0) != 0x80 for k in (1, 2)):
      return 0x3f, 1
    return ((octet & 0x0f) << 12) | ((buf[i + 1] & 0x3f) << 6) | (buf[i + 2] & 0x3f), 3
  if (octet & 0xe0) == 0xc0:
    if (buf[i + 1] & 0xc0) != 0x80:
      return 0x3f, 1
    return ((octet & 0x1f) << 6) | (buf[i + 1] & 0x3f), 2
  if (octet & 0x80) == 0:
    return octet, 1
  return 0x3f, 1


def _layout_text_box(font, text: str, rect, text_size: int, line_spacing: int, alignment: int, alignment_vertical: int):
  # Mirrors raygui 4.5 GuiLabel word-wrap layout in float32 so text lands on the same pixels the raygui renderer used.
  f32 = np.float32
  spacing = f32(1)
  scale = f32(text_size) / f32(font.baseSize)
  metrics: dict[int, tuple[np.float32, np.float32]] = {}

  def glyph_metrics(codepoint: int) -> tuple[np.float32, np.float32]:
    metric = metrics.get(codepoint)
    if metric is None:
      advance = rl.get_glyph_info(font, codepoint).advanceX
      unscaled = f32(rl.get_glyph_atlas_rec(font, codepoint).width) if advance == 0 else f32(advance)
      # raygui's cursor advance compiles to a fused multiply-add on arm64; the exact double product rounds once like fmaf.
      metric = (unscaled * scale, f32(float(unscaled) * float(scale) + float(spacing)))
      metrics[codepoint] = metric
    return metric

  def glyph_width(codepoint: int) -> np.float32:
    return glyph_metrics(codepoint)[0]

  def text_width(start: int) -> int:
    size = 0
    while size < 256 and buf[start + size] not in (0, 10):
      size += 1
    width = f32(0)
    i = 0
    while i < size:
      codepoint, codepoint_size = _codepoint_next(buf, start + i)
      width = width + (glyph_width(codepoint) + spacing)
      i += codepoint_size
    return int(width)

  def next_space_width(start: int) -> np.float32:
    width = f32(0)
    i = start
    while buf[i] != 0 and buf[i] != 32:
      width = width + (glyph_width(_codepoint(buf, i)) + spacing)
      i += 1
    return width

  encoded = text.encode()
  buf = encoded + b"\0\0\0\0"
  starts = [0]
  for index, byte in enumerate(encoded):
    if byte == 10 and len(starts) < 128:
      starts.append(index + 1)

  bounds_x, bounds_y, bounds_width, bounds_height = f32(rect.x), f32(rect.y), f32(rect.width), f32(rect.height)
  height_int = int(bounds_height)
  valign_offset = f32(height_int - int(height_int / 2) * 2)
  line_count = len(starts)
  total_height = f32(line_count * text_size + (line_count - 1) * text_size // 2)
  wrap_mode = _WRAP_WORD
  pos_offset_y = f32(0)
  glyphs: list[tuple[str, float, float]] = []

  for start in starts:
    text_size_x = text_width(start)
    position_x = bounds_x
    if alignment == TextAlignment.CENTER:
      position_x = bounds_x + bounds_width / f32(2) - f32(text_size_x // 2)
    elif alignment == TextAlignment.RIGHT:
      position_x = bounds_x + bounds_width - f32(text_size_x)
    if f32(text_size_x) > bounds_width and buf[start] != 0:
      position_x = bounds_x

    position_y = bounds_y
    if alignment_vertical == TextAlignmentVertical.TOP:
      position_y = bounds_y + pos_offset_y
    elif alignment_vertical == TextAlignmentVertical.MIDDLE:
      position_y = bounds_y + pos_offset_y + bounds_height / f32(2) - total_height / f32(2) + valign_offset
    elif alignment_vertical == TextAlignmentVertical.BOTTOM:
      position_y = bounds_y + pos_offset_y + bounds_height - total_height + valign_offset
    position_x = f32(int(position_x))
    position_y = f32(int(position_y))

    line_size = 0
    while buf[start + line_size] not in (0, 10, 13):
      line_size += 1
    last_space_index = 0
    temp_wrap_char_mode = False
    offset_y = 0
    offset_x = f32(0)
    c = 0
    while c < line_size:
      codepoint, codepoint_size = _codepoint_next(buf, start + c)
      if codepoint == 0x3f:
        codepoint_size = 1
      width, advance = glyph_metrics(codepoint)

      if wrap_mode == _WRAP_CHAR:
        if offset_x + width > bounds_width:
          offset_x = f32(0)
          offset_y += line_spacing
          if temp_wrap_char_mode:
            wrap_mode = _WRAP_WORD
            temp_wrap_char_mode = False
      elif wrap_mode == _WRAP_WORD:
        if codepoint == 32:
          last_space_index = c
        next_width = next_space_width(start + c)
        next_word_width = next_space_width(start + last_space_index + 1)
        if next_word_width > bounds_width:
          temp_wrap_char_mode = True
          wrap_mode = _WRAP_CHAR
        elif offset_x + next_width > bounds_width:
          offset_x = f32(0)
          offset_y += line_spacing

      if codepoint not in (32, 9) and position_y + f32(offset_y) <= bounds_y + bounds_height - f32(text_size):
        glyphs.append((chr(codepoint), float(position_x + offset_x), float(position_y + f32(offset_y))))
      offset_x = offset_x + advance
      c += codepoint_size

    pos_offset_y = pos_offset_y + (f32(offset_y) + f32(line_spacing))

  return glyphs


# Non-interactive text area. Can render emojis and an optional specified icon.
class Label(Widget):
  def __init__(self,
               text: str | Callable[[], str],
               font_size: int = DEFAULT_TEXT_SIZE,
               font_weight: FontWeight = FontWeight.NORMAL,
               text_alignment: int = TextAlignment.CENTER,
               text_alignment_vertical: int = TextAlignmentVertical.MIDDLE,
               text_padding: int = 0,
               text_color: rl.Color = DEFAULT_TEXT_COLOR,
               icon: Union[rl.Texture, None] = None,
               elide_right: bool = False,
               line_scale=1.0,
               ):

    super().__init__()
    self._font_weight = font_weight
    self._font = gui_app.font(self._font_weight)
    self._font_size = font_size
    self._text_alignment = text_alignment
    self._text_alignment_vertical = text_alignment_vertical
    self._text_padding = text_padding
    self._text_color = text_color
    self._icon = icon
    self._elide_right = elide_right
    self._line_scale = line_scale

    self._text = text
    self.set_text(text)

  def set_text(self, text):
    self._text = text
    self._update_text(self._text)

  def set_text_color(self, color):
    self._text_color = color

  def set_font_size(self, size):
    self._font_size = size
    self._update_text(self._text)

  def _update_text(self, text):
    self._emojis = []
    self._text_size = []
    text = _resolve_value(text)

    if self._elide_right:
      display_text = text

      # Elide text to fit within the rectangle
      text_size = measure_text_cached(self._font, text, self._font_size)
      content_width = self._rect.width - self._text_padding * 2
      if self._icon:
        content_width -= self._icon.width + ICON_PADDING
      if text_size.x > content_width:
        _ellipsis = "..."
        left, right = 0, len(text)
        while left < right:
          mid = (left + right) // 2
          candidate = text[:mid] + _ellipsis
          candidate_size = measure_text_cached(self._font, candidate, self._font_size)
          if candidate_size.x <= content_width:
            left = mid + 1
          else:
            right = mid
        display_text = text[: left - 1] + _ellipsis if left > 0 else _ellipsis

      self._text_wrapped = [display_text]
    else:
      self._text_wrapped = wrap_text(self._font, text, self._font_size, round(self._rect.width - (self._text_padding * 2)))

    for t in self._text_wrapped:
      self._emojis.append(find_emoji(t))
      self._text_size.append(measure_text_cached(self._font, t, self._font_size))

  def _render(self, _):
    # Text can be a callable
    # TODO: cache until text changed
    self._update_text(self._text)

    text_size = self._text_size[0] if self._text_size else rl.Vector2(0.0, 0.0)
    if self._text_alignment_vertical == TextAlignmentVertical.MIDDLE:
      total_text_height = sum(ts.y for ts in self._text_size) or self._font_size * FONT_SCALE
      text_pos = rl.Vector2(self._rect.x, (self._rect.y + (self._rect.height - total_text_height) // 2))
    else:
      text_pos = rl.Vector2(self._rect.x, self._rect.y)

    if self._icon:
      icon_y = self._rect.y + (self._rect.height - self._icon.height) / 2
      if len(self._text_wrapped) > 0:
        if self._text_alignment == TextAlignment.LEFT:
          icon_x = self._rect.x + self._text_padding
          text_pos.x = self._icon.width + ICON_PADDING
        elif self._text_alignment == TextAlignment.CENTER:
          total_width = self._icon.width + ICON_PADDING + text_size.x
          icon_x = self._rect.x + (self._rect.width - total_width) / 2
          text_pos.x = self._icon.width + ICON_PADDING
        else:
          icon_x = (self._rect.x + self._rect.width - text_size.x - self._text_padding) - ICON_PADDING - self._icon.width
      else:
        icon_x = self._rect.x + (self._rect.width - self._icon.width) / 2
      rl.draw_texture_v(self._icon, rl.Vector2(icon_x, icon_y), rl.WHITE)

    for text, text_size, emojis in zip_longest(self._text_wrapped, self._text_size, self._emojis, fillvalue=[]):
      line_pos = rl.Vector2(text_pos.x, text_pos.y)
      if self._text_alignment == TextAlignment.LEFT:
        line_pos.x += self._text_padding
      elif self._text_alignment == TextAlignment.CENTER:
        line_pos.x += (self._rect.width - text_size.x) // 2
      elif self._text_alignment == TextAlignment.RIGHT:
        line_pos.x += self._rect.width - text_size.x - self._text_padding

      prev_index = 0
      for start, end, emoji in emojis:
        text_before = text[prev_index:start]
        width_before = measure_text_cached(self._font, text_before, self._font_size)
        rl.draw_text_ex(self._font, text_before, line_pos, self._font_size, 0, self._text_color)
        line_pos.x += width_before.x

        tex = emoji_tex(emoji)
        if tex is not None:
          rl.draw_texture_ex(tex, line_pos, 0.0, self._font_size / tex.height * FONT_SCALE, self._text_color)
        line_pos.x += self._font_size * FONT_SCALE
        prev_index = end
      rl.draw_text_ex(self._font, text[prev_index:], line_pos, self._font_size, 0, self._text_color)
      text_pos.y += (text_size.y or self._font_size * FONT_SCALE) * self._line_scale


class UnifiedLabel(Widget):
  """
  Unified label widget that combines functionality from gui_label, gui_text_box, Label, and MiciLabel.

  Supports:
  - Emoji rendering
  - Text wrapping
  - Automatic eliding (single-line or multiline)
  - Proper multiline vertical alignment
  - Height calculation for layout purposes
  """
  def __init__(self,
               text: str | Callable[[], str],
               font_size: int = DEFAULT_TEXT_SIZE,
               font_weight: FontWeight = FontWeight.NORMAL,
               text_color: rl.Color = DEFAULT_TEXT_COLOR,
               alignment: int = TextAlignment.LEFT,
               alignment_vertical: int = TextAlignmentVertical.TOP,
               text_padding: int = 0,
               max_width: int | None = None,
               elide: bool = True,
               wrap_text: bool = True,
               scroll: bool = False,
               line_height: float = 1.0,
               letter_spacing: float = 0.0):
    super().__init__()
    self._text = text
    self._font_size = font_size
    self._font_weight = font_weight
    self._font = gui_app.font(self._font_weight)
    self._text_color = text_color
    self._alignment = alignment
    self._alignment_vertical = alignment_vertical
    self._text_padding = text_padding
    self._max_width = max_width
    self._elide = elide
    self._wrap_text = wrap_text
    self._scroll = scroll
    self._line_height = line_height * 0.9
    self._letter_spacing = letter_spacing  # 0.1 = 10%
    self._spacing_pixels = font_size * letter_spacing

    # Scroll state
    self._scroll = scroll
    self._needs_scroll = False
    self._scroll_offset = 0
    self._scroll_pause_t: float | None = None
    self._scroll_state: ScrollState = ScrollState.STARTING
    self._scroll_active = True

    # Scroll mode does not support eliding or multiline wrapping
    if self._scroll:
      self._elide = False
      self._wrap_text = False

    # Cached data
    self._cached_text: str | None = None
    self._cached_wrapped_lines: list[str] = []
    self._cached_line_sizes: list[rl.Vector2] = []
    self._cached_line_emojis: list[list[tuple[int, int, str]]] = []
    self._cached_total_height: float | None = None
    self._cached_width: int = -1

    # If max_width is set, initialize rect size for Scroller support
    if max_width is not None:
      self._rect.width = max_width
      self._rect.height = self.get_content_height(max_width)

  def set_text(self, text: str | Callable[[], str]):
    """Update the text content."""
    old_text = self.text
    new_text = str(_resolve_value(text))
    self._text = text
    if old_text != new_text:
      self.reset_scroll()
      self._cached_text = None
    # No need to update cache here, will be done on next render if needed

  @property
  def text(self) -> str:
    """Get the current text content."""
    return str(_resolve_value(self._text))

  def set_text_color(self, color: rl.Color):
    """Update the text color."""
    self._text_color = color

  def set_color(self, color: rl.Color):
    """Update the text color (alias for set_text_color)."""
    self.set_text_color(color)

  def set_font_size(self, size: int):
    """Update the font size."""
    if self._font_size != size:
      self._font_size = size
      self._spacing_pixels = size * self._letter_spacing  # Recalculate spacing
      self._cached_text = None  # Invalidate cache

  def set_font_weight(self, font_weight: FontWeight):
    """Update the font weight."""
    if self._font_weight != font_weight:
      self._font_weight = font_weight
      self._font = gui_app.font(self._font_weight)
      self._cached_text = None  # Invalidate cache

  def set_alignment(self, alignment: int):
    """Update the horizontal text alignment."""
    self._alignment = alignment

  def set_alignment_vertical(self, alignment_vertical: int):
    """Update the vertical text alignment."""
    self._alignment_vertical = alignment_vertical

  def set_line_height(self, line_height: float):
    """Update line height (multiplier, e.g., 1.0 = default)."""
    new_line_height = line_height * 0.9
    if self._line_height != new_line_height:
      self._line_height = new_line_height
      self._cached_text = None

  def reset_scroll(self):
    """Reset scroll state to initial position."""
    self._scroll_offset = 0
    self._scroll_pause_t = None
    self._scroll_state = ScrollState.STARTING

  def set_scroll_active(self, active: bool) -> None:
    if self._scroll_active == active:
      return
    self._scroll_active = active
    if not active:
      self.reset_scroll()

  def set_max_width(self, max_width: int | None):
    """Set the maximum width constraint for wrapping/eliding."""
    if self._max_width != max_width:
      self.reset_scroll()
      self._max_width = max_width
      self._cached_text = None  # Invalidate cache
      # Update rect size for Scroller support
      if max_width is not None:
        self._rect.width = max_width
        self._rect.height = self.get_content_height(max_width)

  def _update_text_cache(self, available_width: int):
    """Update cached text processing data."""
    text = self.text

    # Check if cache is still valid
    if (self._cached_text == text and
        self._cached_width == available_width and
        self._cached_wrapped_lines):
      return

    if self._cached_text is not None and (self._cached_text != text or self._cached_width != available_width):
      self.reset_scroll()

    self._cached_text = text
    self._cached_width = available_width

    # Determine wrapping width
    content_width = available_width - (self._text_padding * 2)
    if content_width <= 0:
      content_width = 1

    # Wrap text if enabled
    if self._wrap_text:
      self._cached_wrapped_lines = wrap_text(self._font, text, self._font_size, content_width, self._spacing_pixels)
    else:
      # Split by newlines but don't wrap
      self._cached_wrapped_lines = text.split('\n') if text else [""]

    # Elide lines if needed (for width constraint)
    self._cached_wrapped_lines = [self._elide_line(line, content_width) for line in self._cached_wrapped_lines]

    if self._scroll:
      self._cached_wrapped_lines = self._cached_wrapped_lines[:1]  # Only first line for scrolling

    # Process each line: measure and find emojis
    self._cached_line_sizes = []
    self._cached_line_emojis = []

    for line in self._cached_wrapped_lines:
      emojis = find_emoji(line)
      self._cached_line_emojis.append(emojis)
      # Empty lines should still have height (use font size as line height)
      if not line:
        size = rl.Vector2(0, self._font_size * FONT_SCALE)
      else:
        size = measure_text_cached(self._font, line, self._font_size, self._spacing_pixels)

      # This is the only line
      if self._scroll:
        self._needs_scroll = size.x > content_width

      self._cached_line_sizes.append(size)

    # Calculate total height
    # Each line contributes its measured height * line_height (matching Label's behavior)
    # This includes spacing to the next line
    if self._cached_line_sizes:
      # Match the rendering logic: first line doesn't get line_height scaling
      total_height = 0.0
      for idx, size in enumerate(self._cached_line_sizes):
        if idx == 0:
          total_height += size.y
        else:
          total_height += size.y * self._line_height
      self._cached_total_height = total_height
    else:
      self._cached_total_height = 0.0

  def _elide_line(self, line: str, max_width: int, force: bool = False) -> str:
    """Elide a single line if it exceeds max_width. If force is True, always elide even if it fits."""
    if not self._elide and not force:
      return line

    text_size = measure_text_cached(self._font, line, self._font_size, self._spacing_pixels)
    if text_size.x <= max_width and not force:
      return line

    ellipsis = "..."
    # If force=True and line fits, just append ellipsis without truncating
    if force and text_size.x <= max_width:
      ellipsis_size = measure_text_cached(self._font, ellipsis, self._font_size, self._spacing_pixels)
      if text_size.x + ellipsis_size.x <= max_width:
        return line + ellipsis
      # If line + ellipsis doesn't fit, need to truncate
      # Fall through to binary search below

    left, right = 0, len(line)
    while left < right:
      mid = (left + right) // 2
      candidate = line[:mid] + ellipsis
      candidate_size = measure_text_cached(self._font, candidate, self._font_size, self._spacing_pixels)
      if candidate_size.x <= max_width:
        left = mid + 1
      else:
        right = mid
    return line[:left - 1] + ellipsis if left > 0 else ellipsis

  def get_content_height(self, max_width: int) -> float:
    """
    Returns the height needed for text at given max_width.
    Similar to HtmlRenderer.get_total_height().
    """
    # Use max_width if provided, otherwise use self._max_width or a default
    width = max_width if max_width > 0 else (self._max_width if self._max_width else 1000)
    self._update_text_cache(width)

    if self._cached_total_height is not None:
      return self._cached_total_height
    return 0.0

  def _render(self, _):
    """Render the label."""
    if self._rect.width <= 0 or self._rect.height <= 0:
      return

    # Determine available width
    available_width = self._rect.width
    if self._max_width is not None:
      available_width = min(available_width, self._max_width)

    # Update text cache
    self._update_text_cache(int(available_width))

    if not self._cached_wrapped_lines:
      return

    # Calculate which lines fit in the available height
    visible_lines: list[str] = []
    visible_sizes: list[rl.Vector2] = []
    visible_emojis: list[list[tuple[int, int, str]]] = []

    current_height = 0.0
    broke_early = False
    for line, size, emojis in zip(
      self._cached_wrapped_lines,
      self._cached_line_sizes,
      self._cached_line_emojis,
      strict=True):

      # Calculate height needed for this line
      # Each line contributes its height * line_height (matching Label's behavior)
      line_height_needed = size.y * self._line_height

      # Check if this line fits
      if current_height + line_height_needed > self._rect.height:
        # This line doesn't fit
        if len(visible_lines) == 0:
          # First line doesn't fit by height - still show it (will be clipped by scissor if needed)
          # Continue to add this line below
          pass
        else:
          # We have visible lines and this one doesn't fit - mark that we broke early
          broke_early = True
          break

      visible_lines.append(line)
      visible_sizes.append(size)
      visible_emojis.append(emojis)

      current_height += line_height_needed

    # If we broke early (there are more lines that don't fit) and elide is enabled, elide the last visible line
    if broke_early and len(visible_lines) > 0 and self._elide:
      content_width = int(available_width - (self._text_padding * 2))
      if content_width <= 0:
        content_width = 1

      last_line_idx = len(visible_lines) - 1
      last_line = visible_lines[last_line_idx]
      # Force elide the last line to show "..." even if it fits in width (to indicate more content)
      elided = self._elide_line(last_line, content_width, force=True)
      visible_lines[last_line_idx] = elided
      visible_sizes[last_line_idx] = measure_text_cached(self._font, elided, self._font_size, self._spacing_pixels)

    if not visible_lines:
      return

    # Calculate total visible text block height
    # First line is not changed by line_height scaling
    total_visible_height = 0.0
    for idx, size in enumerate(visible_sizes):
      if idx == 0:
        total_visible_height += size.y
      else:
        total_visible_height += size.y * self._line_height

    # Calculate vertical alignment offset
    if self._alignment_vertical == TextAlignmentVertical.TOP:
      start_y = self._rect.y
    elif self._alignment_vertical == TextAlignmentVertical.BOTTOM:
      start_y = self._rect.y + self._rect.height - total_visible_height
    else:  # TEXT_ALIGN_MIDDLE
      start_y = self._rect.y + (self._rect.height - total_visible_height) / 2

    # Only scissor when we know there is a single scrolling line
    # Pad a little since descenders like g or j may overflow below rect from font_scale
    if self._needs_scroll:
      scissor_x = int(self._rect.x + self._text_padding)
      scissor_w = int(max(1, self._rect.width - self._text_padding * 2))
      rl.begin_scissor_mode(scissor_x, int(self._rect.y - self._font_size / 2), scissor_w, int(self._rect.height + self._font_size))

    # Render each line
    current_y = start_y
    for idx, (line, size, emojis) in enumerate(zip(visible_lines, visible_sizes, visible_emojis, strict=True)):
      if self._needs_scroll and self._scroll_active:
        content_width = max(1.0, available_width - self._text_padding * 2)
        max_scroll = max(0.0, size.x - content_width)
        speed = 0.8 / 60. * gui_app.target_fps
        if self._scroll_state == ScrollState.STARTING:
          if self._scroll_pause_t is None:
            self._scroll_pause_t = rl.get_time() + 2.0
          if rl.get_time() >= self._scroll_pause_t:
            self._scroll_state = ScrollState.SCROLLING
            self._scroll_pause_t = None

        elif self._scroll_state == ScrollState.SCROLLING:
          self._scroll_offset = max(-max_scroll, self._scroll_offset - speed)
          if self._scroll_offset <= -max_scroll:
            self._scroll_state = ScrollState.ENDING
            self._scroll_pause_t = None

        elif self._scroll_state == ScrollState.ENDING:
          if self._scroll_pause_t is None:
            self._scroll_pause_t = rl.get_time() + 1.5
          if rl.get_time() >= self._scroll_pause_t:
            self._scroll_offset = 0
            self._scroll_state = ScrollState.STARTING
            self._scroll_pause_t = None
      else:
        self.reset_scroll()

      self._render_line(line, size, emojis, current_y)

      # Move to next line (if not last line)
      if idx < len(visible_lines) - 1:
        # Use current line's height * line_height for spacing to next line
        current_y += size.y * self._line_height

    if self._needs_scroll:
      # draw black fade on left and right
      fade_width = 20
      left_edge = self._rect.x + self._text_padding
      right_edge = self._rect.x + self._rect.width - self._text_padding
      content_width = max(1.0, available_width - self._text_padding * 2)
      max_scroll = max(0.0, visible_sizes[0].x - content_width)
      if self._scroll_offset > -max_scroll:
        rl.draw_rectangle_gradient_h(
          int(right_edge - fade_width), int(self._rect.y),
          fade_width, int(self._rect.height), rl.BLANK, rl.BLACK,
        )
      if self._scroll_active and self._scroll_offset < 0:
        rl.draw_rectangle_gradient_h(
          int(left_edge), int(self._rect.y), fade_width, int(self._rect.height), rl.BLACK, rl.BLANK,
        )

      rl.end_scissor_mode()

  def _render_line(self, line, size, emojis, current_y, x_offset=0.0):
    # Calculate horizontal position
    if self._needs_scroll:
      line_x = self._rect.x + self._text_padding
    elif self._alignment == TextAlignment.LEFT:
      line_x = self._rect.x + self._text_padding
    elif self._alignment == TextAlignment.CENTER:
      line_x = self._rect.x + (self._rect.width - size.x) / 2
    elif self._alignment == TextAlignment.RIGHT:
      line_x = self._rect.x + self._rect.width - size.x - self._text_padding
    else:
      line_x = self._rect.x + self._text_padding
    line_x += self._scroll_offset + x_offset

    # Render line with emojis
    line_pos = rl.Vector2(line_x, current_y)
    prev_index = 0

    for start, end, emoji in emojis:
      # Draw text before emoji
      text_before = line[prev_index:start]
      if text_before:
        rl.draw_text_ex(self._font, text_before, line_pos, self._font_size, self._spacing_pixels, self._text_color)
        width_before = measure_text_cached(self._font, text_before, self._font_size, self._spacing_pixels)
        line_pos.x += width_before.x

      # Draw emoji
      tex = emoji_tex(emoji)
      if tex is not None:
        emoji_scale = self._font_size / tex.height * FONT_SCALE
        rl.draw_texture_ex(tex, line_pos, 0.0, emoji_scale, self._text_color)
      # Emoji width is font_size * FONT_SCALE (as per measure_text_cached)
      line_pos.x += self._font_size * FONT_SCALE
      prev_index = end

    # Draw remaining text after last emoji
    text_after = line[prev_index:]
    if text_after:
      rl.draw_text_ex(self._font, text_after, line_pos, self._font_size, self._spacing_pixels, self._text_color)
