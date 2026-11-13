# Copyright (c) 2026 IQ.Lvbs. All rights reserved.
import json

from iqpilot.common import iq_perf


class Sink:
  def __init__(self):
    self.events = []

  def __call__(self, event, **kwargs):
    self.events.append((event, kwargs))


def make_watch(monkeypatch, sink):
  clock = {"delay": 0}
  monkeypatch.setattr(iq_perf, "_run_delay_ns", lambda: clock["delay"])
  monkeypatch.setattr(iq_perf, "_cpu_ticks", dict)
  monkeypatch.setattr(iq_perf, "_thread_ids", list)
  watch = iq_perf.StallWatch("ui", emit=sink)
  watch._last_tick = 100.0
  return watch, clock


def run(watch, start, seconds, beat_until=None, step=iq_perf.STALL_TICK_S):
  now = start
  while now < start + seconds:
    now += step
    if beat_until is None or now <= beat_until:
      watch._beat = now
    watch.tick(now)
  return now


def stall_once(watch, now, seconds=0.6):
  now = run(watch, now, 1.0)
  now = run(watch, now, seconds, beat_until=now)
  return run(watch, now, 0.3)


def test_steady_heartbeat_never_emits(monkeypatch):
  sink = Sink()
  watch, _ = make_watch(monkeypatch, sink)
  run(watch, 100.0, 5.0)
  assert sink.events == []


def test_heartbeat_gap_emits_one_error_event_with_the_gap(monkeypatch):
  sink = Sink()
  watch, _ = make_watch(monkeypatch, sink)
  stall_once(watch, 100.0)
  assert len(sink.events) == 1
  event, kwargs = sink.events[0]
  assert event == iq_perf.STALL_EVENT
  assert kwargs["error"] is True
  assert kwargs["process"] == "ui"
  assert kwargs["flags"] & iq_perf.STALL_FLAG_GAP
  assert 500 <= kwargs["gap_ms"] <= 700
  assert len(kwargs["threads"]) == 2


def test_scheduler_starvation_without_a_heartbeat_emits(monkeypatch):
  sink = Sink()
  watch, clock = make_watch(monkeypatch, sink)
  now = run(watch, 100.0, 1.0)
  clock["delay"] += int(0.4e9)
  now = run(watch, now, 0.1)
  run(watch, now, 0.3)
  assert len(sink.events) == 1
  assert sink.events[0][1]["flags"] & iq_perf.STALL_FLAG_SCHED
  assert sink.events[0][1]["starved_ms"] >= 400


def test_late_watcher_wakeup_emits(monkeypatch):
  sink = Sink()
  watch, _ = make_watch(monkeypatch, sink)
  now = run(watch, 100.0, 1.0)
  watch.tick(now + 0.5)
  run(watch, now + 0.5, 0.3)
  assert len(sink.events) == 1
  assert sink.events[0][1]["flags"] & iq_perf.STALL_FLAG_LATE
  assert sink.events[0][1]["late_ms"] >= 400


def test_stalls_inside_the_minimum_interval_are_dropped(monkeypatch):
  sink = Sink()
  watch, _ = make_watch(monkeypatch, sink)
  now = stall_once(watch, 100.0)
  now = stall_once(watch, now)
  assert len(sink.events) == 1
  now = run(watch, now, iq_perf.STALL_MIN_INTERVAL_S)
  stall_once(watch, now)
  assert len(sink.events) == 2


def test_events_are_capped_per_process(monkeypatch):
  sink = Sink()
  watch, _ = make_watch(monkeypatch, sink)
  now = 100.0
  for _ in range(iq_perf.STALL_MAX_EVENTS + 5):
    now = stall_once(watch, now)
    now = run(watch, now, iq_perf.STALL_MIN_INTERVAL_S)
  assert len(sink.events) == iq_perf.STALL_MAX_EVENTS


def test_thread_detail_stays_within_the_limit(monkeypatch):
  sink = Sink()
  watch, _ = make_watch(monkeypatch, sink)
  long_stack = "<".join(["a_long_file_name.py:123:a_long_function_name"] * iq_perf.STALL_FRAME_DEPTH)
  monkeypatch.setattr(watch, "_snapshot", lambda: [["thread", "R", 5, 40, long_stack] for _ in range(iq_perf.STALL_TOP_THREADS + 1)])
  stall_once(watch, 100.0)
  assert len(json.dumps(sink.events[0][1]["threads"], separators=(",", ":"))) <= iq_perf.STALL_DETAIL_LIMIT
  assert all(len(snap) >= 1 for snap in sink.events[0][1]["threads"])
