from types import SimpleNamespace

from iqpilot.selfdrive.car import card
from iqpilot.selfdrive.car.card import CARD_CAN_INVALID_REPORT_FRAMES, Car


class StubParser:
  def __init__(self, invalid):
    self.invalid = invalid

  def invalid_messages(self):
    return self.invalid


def make_car(parsers, frame):
  car = object.__new__(Car)
  car.CI = SimpleNamespace(can_parsers=parsers)
  car.sm = SimpleNamespace(frame=frame)
  return car


def record_events(monkeypatch):
  recorded = []
  monkeypatch.setattr(card.cloudlog, "event", lambda name, **kwargs: recorded.append((name, kwargs)))
  return recorded


def test_invalid_can_reports_every_message_that_is_not_valid(monkeypatch):
  recorded = record_events(monkeypatch)
  missing = {"bus": 1, "address": "0x366", "name": "Blinkmodi_02", "frames_seen": 0, "counter_fail": 0}
  car = make_car({"pt": StubParser([]), "aux": StubParser([missing])}, CARD_CAN_INVALID_REPORT_FRAMES)

  car._report_can_invalid(SimpleNamespace(canValid=False, canTimeout=False))

  assert recorded == [("card.can_invalid", {"invalid": [missing], "canTimeout": False, "error": True})]


def test_valid_can_and_off_cycle_frames_report_nothing(monkeypatch):
  recorded = record_events(monkeypatch)
  parsers = {"aux": StubParser([{"name": "x"}])}

  make_car(parsers, CARD_CAN_INVALID_REPORT_FRAMES)._report_can_invalid(SimpleNamespace(canValid=True, canTimeout=False))
  make_car(parsers, CARD_CAN_INVALID_REPORT_FRAMES + 1)._report_can_invalid(SimpleNamespace(canValid=False, canTimeout=False))

  assert recorded == []


def test_a_failing_reporter_never_raises_into_card(monkeypatch):
  record_events(monkeypatch)
  logged = []
  monkeypatch.setattr(card.cloudlog, "exception", lambda msg: logged.append(msg))
  car = make_car({"aux": SimpleNamespace()}, CARD_CAN_INVALID_REPORT_FRAMES)

  car._report_can_invalid(SimpleNamespace(canValid=False, canTimeout=False))

  assert logged == ["failed to report invalid CAN messages"]
