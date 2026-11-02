import time
import pytest
from iqpilot.selfdrive.test.helpers import with_processes


@pytest.mark.linux
@with_processes(["ui"])
def test_raylib_ui():
  """Test initialization of the UI widgets is successful."""
  time.sleep(1)



def test_text_box_wraps_words_on_raygui_glyph_grid(monkeypatch):
  from types import SimpleNamespace
  from iqpilot.system.ui.widgets import label
  monkeypatch.setattr(label.rl, "get_glyph_info", lambda font, codepoint: SimpleNamespace(advanceX=9))
  monkeypatch.setattr(label.rl, "get_glyph_atlas_rec", lambda font, codepoint: SimpleNamespace(width=9))
  font = SimpleNamespace(baseSize=10)
  glyphs = label._layout_text_box(font, "ab cd ef", label.rl.Rectangle(3.6, 7.2, 50, 100), 10, 12,
                                  label.TextAlignment.LEFT, label.TextAlignmentVertical.TOP)
  assert glyphs == [('a', 3, 7), ('b', 13, 7), ('c', 33, 7), ('d', 43, 7), ('e', 3, 19), ('f', 13, 19)]
  centered = label._layout_text_box(font, "ab", label.rl.Rectangle(0, 0, 51, 31), 10, 12,
                                    label.TextAlignment.CENTER, label.TextAlignmentVertical.MIDDLE)
  assert centered == [('a', 15, 11), ('b', 25, 11)]
