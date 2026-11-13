# Copyright (c) 2026 IQ.Lvbs. All rights reserved.
import re

import pytest

from iqpilot.selfdrive.assets.fonts import process


@pytest.mark.parametrize('export_succeeds', [True, False])
def test_font_generation_releases_native_allocations(tmp_path, monkeypatch, export_succeeds):
  source = process.FONT_DIR / 'Inter-Regular.ttf'
  monkeypatch.setattr(process, 'FONT_DIR', tmp_path)
  generated = {}
  unloaded = []
  gen_font_atlas = process.rl.gen_font_atlas
  unload_image = process.rl.unload_image

  def generate(*args):
    result = gen_font_atlas(*args)
    generated['atlas'], generated['glyphs'], generated['rects'] = result
    return result

  def free_image(image):
    unloaded.append(image)
    unload_image(image)

  monkeypatch.setattr(process.rl, 'gen_font_atlas', generate)
  monkeypatch.setattr(process.rl, 'unload_image', free_image)
  if not export_succeeds:
    monkeypatch.setattr(process.rl, 'export_image', lambda *args: False)

  try:
    if export_succeeds:
      process._process_font(source, tuple(range(32, 127)))
      assert (tmp_path / 'Inter-Regular.png').is_file()
      fnt = (tmp_path / 'Inter-Regular.fnt').read_text()
      assert 'chars count=95' in fnt
      width, height = map(int, re.search(r'scaleW=(\d+) scaleH=(\d+)', fnt).groups())
      for x, y, w, h in re.findall(r'char id=\d+\s+x=(\d+)\s+y=(\d+)\s+width=(\d+)\s+height=(\d+)', fnt):
        assert 0 <= int(x) <= width - int(w) and 0 <= int(y) <= height - int(h)
    else:
      with pytest.raises(RuntimeError, match='Failed to export atlas image'):
        process._process_font(source, tuple(range(32, 127)))
    assert unloaded == [generated['atlas']]
    assert [glyph.value for glyph in generated['glyphs']] == list(range(32, 127))
    assert len(generated['rects']) == len(generated['glyphs'])
  finally:
    if 'atlas' in generated and not unloaded:
      unload_image(generated['atlas'])
