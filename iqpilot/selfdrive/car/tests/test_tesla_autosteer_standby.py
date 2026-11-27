# Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
from types import SimpleNamespace

from iqpilot.selfdrive.car.card import STOCK_AUTOSTEER_RELEASE_FRAMES, Car


class StubParams:
  def __init__(self):
    self.values = {}

  def put_bool(self, key, value):
    self.values[key] = value


def make_car(standby, passive=None, enabled=False):
  car = object.__new__(Car)
  car.CP = SimpleNamespace(brand="tesla", passive=standby if passive is None else passive)
  car.params = StubParams()
  car.sm = {"carControl": SimpleNamespace(enabled=enabled)}
  car.stock_autosteer_standby = standby
  car.stock_autosteer_idle_frames = 0
  return car


def car_state(invalid=False, cruise=False, can_valid=True):
  return SimpleNamespace(invalidLkasSetting=invalid, canValid=can_valid, cruiseState=SimpleNamespace(enabled=cruise))


def run(car, cs, frames):
  for _ in range(frames):
    car._yield_to_stock_autosteer(cs)


def test_standby_is_released_once_stock_autosteer_stays_idle():
  car = make_car(standby=True)

  run(car, car_state(), STOCK_AUTOSTEER_RELEASE_FRAMES)

  assert not car.stock_autosteer_standby
  assert car.params.values == {"TeslaStockAutosteerActive": False, "OnroadCycleRequested": True}


def test_standby_holds_while_stock_autosteer_is_active():
  car = make_car(standby=True)

  run(car, car_state(invalid=True, cruise=True), STOCK_AUTOSTEER_RELEASE_FRAMES * 3)

  assert car.stock_autosteer_standby
  assert car.params.values == {}


def test_standby_holds_while_stock_cruise_is_engaged():
  car = make_car(standby=True)

  run(car, car_state(cruise=True), STOCK_AUTOSTEER_RELEASE_FRAMES * 3)

  assert car.stock_autosteer_standby
  assert car.params.values == {}


def test_any_stock_activity_restarts_the_idle_window():
  car = make_car(standby=True)

  run(car, car_state(), STOCK_AUTOSTEER_RELEASE_FRAMES - 1)
  run(car, car_state(invalid=True), 1)
  run(car, car_state(), STOCK_AUTOSTEER_RELEASE_FRAMES - 1)

  assert car.stock_autosteer_standby
  assert car.params.values == {}


def test_invalid_can_never_counts_as_idle():
  car = make_car(standby=True)

  run(car, car_state(can_valid=False), STOCK_AUTOSTEER_RELEASE_FRAMES * 2)

  assert car.stock_autosteer_standby


def test_active_stock_autosteer_still_latches_standby():
  car = make_car(standby=False, passive=False)

  car._yield_to_stock_autosteer(car_state(invalid=True))

  assert car.stock_autosteer_standby
  assert car.params.values == {"TeslaStockAutosteerActive": True, "OnroadCycleRequested": True}


def test_engaged_iqpilot_is_not_interrupted_by_stock_autosteer():
  car = make_car(standby=False, passive=False, enabled=True)

  car._yield_to_stock_autosteer(car_state(invalid=True))

  assert not car.stock_autosteer_standby
  assert car.params.values == {}


def test_dashcam_passive_never_enters_standby():
  car = make_car(standby=False, passive=True)

  car._yield_to_stock_autosteer(car_state(invalid=True))

  assert not car.stock_autosteer_standby


def test_non_tesla_is_ignored():
  car = make_car(standby=True)
  car.CP.brand = "toyota"

  run(car, car_state(), STOCK_AUTOSTEER_RELEASE_FRAMES)

  assert car.stock_autosteer_standby
