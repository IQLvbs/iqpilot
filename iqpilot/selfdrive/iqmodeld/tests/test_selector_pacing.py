"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import bisect
import random

from iqpilot.selfdrive.iqmodeld.modeld_selector import FRAME_RESET_GAP, frame_stream_reset, next_target


def test_the_small_model_alone_paces_the_stream_until_the_big_model_is_active():
  assert next_target(10, 12, 9, False) == 10
  assert next_target(10, 12, 10, False) is None
  assert next_target(None, 12, -1, False) is None


def test_a_frame_the_small_model_skipped_is_taken_from_the_big_model():
  assert next_target(10, 11, 10, True) == 11
  assert next_target(10, 12, 10, True) == 12
  assert next_target(11, 11, 10, True) == 11


def test_a_big_head_too_far_ahead_or_already_published_is_ignored():
  assert next_target(10, 10 + 3, 10, True) is None
  assert next_target(10, 9, 9, True) == 10
  assert next_target(10, 10, 10, True) is None


def test_a_dead_small_model_does_not_stop_a_live_big_model():
  assert next_target(None, 5, 4, True) == 5
  assert next_target(7, 9, 8, True) == 9
  assert next_target(7, 10, 9, True) == 10


def test_a_new_drive_re_arms_the_stream():
  assert frame_stream_reset(3, 100000, False)
  assert frame_stream_reset(3, 100000, True)
  assert not frame_stream_reset(100, 99, False)
  assert not frame_stream_reset(None, 99, True)
  assert not frame_stream_reset(5, -1, True)


def test_a_small_model_lagging_behind_the_big_one_is_not_a_new_drive():
  assert not frame_stream_reset(100 - FRAME_RESET_GAP, 100, True)
  assert frame_stream_reset(100 - FRAME_RESET_GAP - 1, 100, True)
  assert frame_stream_reset(98, 100, False)


def _heads(period_ms: float, jitter_ms: float, frames: int, seed: int) -> list[tuple[float, int]]:
  rng = random.Random(seed)
  done: list[tuple[float, int]] = []
  now, last = 0.0, -1
  while now < frames * 50.0:
    frame = max(int(now // 50.0), last + 1)
    now = max(now, frame * 50.0) + period_ms + rng.uniform(-jitter_ms, jitter_ms)
    done.append((now, frame))
    last = frame
  return done


def _head_at(done: list[tuple[float, int]], now: float) -> int | None:
  idx = bisect.bisect_right(done, (now, 1 << 60)) - 1
  return done[idx][1] if idx >= 0 else None


def _published_ratio(small, big, frames: int, union: bool) -> float:
  published, last = 0, -1
  for tick in range(frames * 5):
    now = tick * 10.0
    target = next_target(_head_at(small, now), _head_at(big, now) if union else None, last, union)
    if target is not None:
      published += 1
      last = target
  return published / frames


def test_union_pacing_removes_the_gaps_a_slow_small_model_leaves():
  frames = 4000
  small = _heads(58.0, 10.0, frames, 1)
  big = _heads(61.0, 8.0, frames, 2)
  small_only = _published_ratio(small, big, frames, False)
  union = _published_ratio(small, big, frames, True)
  assert small_only < 0.9
  assert union > 0.95
  assert union - small_only > 0.07
