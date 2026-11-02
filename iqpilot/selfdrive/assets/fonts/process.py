#!/usr/bin/env python3
import os
from contextlib import contextmanager
from pathlib import Path
import json
import sys


@contextmanager
def _quiet_fds(*fds):
  # mute the raylib load banner (printed on first native use, before any log level applies)
  saved = [os.dup(fd) for fd in fds]
  devnull = os.open(os.devnull, os.O_WRONLY)
  try:
    for fd in fds:
      os.dup2(devnull, fd)
    yield
  finally:
    for fd, s in zip(fds, saved):
      os.dup2(s, fd)
      os.close(s)
    os.close(devnull)


if sys.platform == "linux":
  os.environ.setdefault("RAYLIB_BACKEND", "headless")

with _quiet_fds(1, 2):
  import raylib_nb as rl
  rl.set_trace_log_level(rl.TraceLogLevel.LOG_ERROR)  # first native call: triggers the banner

FONT_DIR = Path(__file__).resolve().parent
SELFDRIVE_DIR = FONT_DIR.parents[1]
TRANSLATIONS_DIR = SELFDRIVE_DIR / "ui" / "translations"
LANGUAGES_FILE = TRANSLATIONS_DIR / "languages.json"

GLYPH_PADDING = 6
EXTRA_CHARS = "–‑✓×°§•X⚙✕◀▶✔⌫⇧␣○●↳çêüñ–‑✓×°§•€£¥"
UNIFONT_LANGUAGES = {"ar", "th", "zh-CHT", "zh-CHS", "ko", "ja"}


def _languages():
  if not LANGUAGES_FILE.exists():
    return {}
  with LANGUAGES_FILE.open(encoding="utf-8") as f:
    return json.load(f)


def _char_sets():
  base = set(map(chr, range(32, 127))) | set(EXTRA_CHARS)
  unifont = set(base)

  for language, code in _languages().items():
    unifont.update(language)
    po_path = TRANSLATIONS_DIR / f"app_{code}.po"
    try:
      chars = set(po_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
      continue
    (unifont if code in UNIFONT_LANGUAGES else base).update(chars)

  return tuple(sorted(ord(c) for c in base)), tuple(sorted(ord(c) for c in unifont))


def _glyph_metrics(glyphs, rects):
  entries = []
  min_offset_y, max_extent = None, 0
  for glyph, rect in zip(glyphs, rects, strict=True):
    # Take the codepoint from the glyph itself: the 7-arg LoadFontData returns a
    # compacted array of only the glyphs it found, so positional pairing with the
    # requested codepoint list would misattribute (and previously overran) entries.
    codepoint = glyph.value
    width = int(round(rect.width))
    height = int(round(rect.height))
    offset_y = int(round(glyph.offsetY))
    min_offset_y = offset_y if min_offset_y is None else min(min_offset_y, offset_y)
    max_extent = max(max_extent, offset_y + height)
    entries.append({
      "id": codepoint,
      "x": int(round(rect.x)),
      "y": int(round(rect.y)),
      "width": width,
      "height": height,
      "xoffset": int(round(glyph.offsetX)),
      "yoffset": offset_y,
      "xadvance": int(round(glyph.advanceX)),
    })

  if min_offset_y is None:
    raise RuntimeError("No glyphs were generated")

  line_height = int(round(max_extent - min_offset_y))
  base = int(round(max_extent))
  return entries, line_height, base


def _write_bmfont(path: Path, font_size: int, face: str, atlas_name: str, line_height: int, base: int, atlas_size, entries):
  # TODO: why doesn't raylib calculate these metrics correctly?
  if line_height != font_size:
    line_height = font_size
  lines = [
    f"info face=\"{face}\" size=-{font_size} bold=0 italic=0 charset=\"\" unicode=1 stretchH=100 smooth=0 aa=1 padding=0,0,0,0 spacing=0,0 outline=0",
    f"common lineHeight={line_height} base={base} scaleW={atlas_size[0]} scaleH={atlas_size[1]} pages=1 packed=0 alphaChnl=0 redChnl=4 greenChnl=4 blueChnl=4",
    f"page id=0 file=\"{atlas_name}\"",
    f"chars count={len(entries)}",
  ]
  for entry in entries:
    lines.append(
      ("char id={id:<4} x={x:<5} y={y:<5} width={width:<5} height={height:<5} " +
       "xoffset={xoffset:<5} yoffset={yoffset:<5} xadvance={xadvance:<5} page=0  chnl=15").format(**entry)
    )
  path.write_text("\n".join(lines) + "\n")


def _looks_like_lfs_pointer(data: bytes) -> bool:
  head = data[:256]
  return b"git-lfs.github.com/spec/v1" in head and b"oid sha256:" in head


def _can_reuse_prebuilt(font_path: Path) -> bool:
  return (FONT_DIR / f"{font_path.stem}.fnt").exists() and (FONT_DIR / f"{font_path.stem}.png").exists()


def _process_font(font_path: Path, codepoints: tuple[int, ...]):
  font_size = {
    "unifont.otf": 16,  # unifont is only 16x8 or 16x16 pixels per glyph
  }.get(font_path.name, 200)

  data = font_path.read_bytes()
  image, glyphs, rects = rl.gen_font_atlas(data, font_size, list(codepoints), rl.FontType.FONT_DEFAULT, GLYPH_PADDING, 1)
  if not glyphs:
    rl.unload_image(image)
    if _can_reuse_prebuilt(font_path):
      reason = "raylib failed to load font data"
      if _looks_like_lfs_pointer(data):
        reason += " (file looks like a Git LFS pointer, not real font data)"
      print(f"WARNING: {reason}; reusing prebuilt atlas for {font_path.name}")
      return
    reason = f"raylib failed to load font data for {font_path.name}"
    if _looks_like_lfs_pointer(data):
      reason += " (file looks like a Git LFS pointer, not real font data)"
    raise RuntimeError(reason)

  try:
    if image.width == 0 or image.height == 0:
      if _can_reuse_prebuilt(font_path):
        print(f"WARNING: raylib returned an empty atlas; reusing prebuilt atlas for {font_path.name}")
        return
      raise RuntimeError(f"raylib returned an empty atlas for {font_path.name}")

    atlas_name = f"{font_path.stem}.png"
    atlas_path = FONT_DIR / atlas_name
    entries, line_height, base = _glyph_metrics(glyphs, rects)

    if not rl.export_image(image, atlas_path.as_posix()):
      raise RuntimeError("Failed to export atlas image")

    _write_bmfont(FONT_DIR / f"{font_path.stem}.fnt", font_size, font_path.stem, atlas_name, line_height, base, (image.width, image.height), entries)
  finally:
    rl.unload_image(image)


def main():
  base_cp, unifont_cp = _char_sets()
  fonts = sorted(FONT_DIR.glob("*.ttf")) + sorted(FONT_DIR.glob("*.otf"))
  for font in fonts:
    if "emoji" in font.name.lower():
      continue
    glyphs = unifont_cp if font.stem.lower().startswith("unifont") else base_cp
    _process_font(font, glyphs)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
