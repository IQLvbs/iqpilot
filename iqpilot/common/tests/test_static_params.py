from types import SimpleNamespace

from iqpilot.cereal import car
from iqpilot.common.static_params import StaticParams, StaticView


class Reads(SimpleNamespace):
  def __init__(self, **values):
    super().__init__(**values)
    object.__setattr__(self, "reads", [])

  def __getattribute__(self, name):
    if name in ("brand", "pcmCruise"):
      object.__getattribute__(self, "reads").append(name)
    return object.__getattribute__(self, name)


def test_a_field_is_read_from_the_source_once():
  source = Reads(brand="volkswagen", pcmCruise=True)
  params = StaticParams(source)
  assert [params.brand, params.brand, params.pcmCruise, params.pcmCruise] == ["volkswagen", "volkswagen", True, True]
  assert source.reads == ["brand", "pcmCruise"]


def test_a_missing_field_still_raises():
  params = StaticParams(SimpleNamespace(brand="x"))
  assert not hasattr(params, "missing")


def test_capnp_values_compare_like_the_reader():
  reader = car.CarParams.new_message(brand="volkswagen", openpilotLongitudinalControl=True, minSteerSpeed=1.5).as_reader()
  params = StaticParams(reader)
  assert params.brand == reader.brand
  assert params.openpilotLongitudinalControl is reader.openpilotLongitudinalControl
  assert params.minSteerSpeed == reader.minSteerSpeed
  assert params.steerControlType == reader.steerControlType
  assert params.lateralTuning.which() == reader.lateralTuning.which()


class Owner:
  cps = StaticView("CP")

  def __init__(self, cp):
    self.CP = cp


def test_view_is_cached_per_source_and_follows_a_replaced_source():
  first, second = SimpleNamespace(brand="a"), SimpleNamespace(brand="b")
  owner = Owner(first)
  assert owner.cps is owner.cps
  assert owner.cps.brand == "a"
  owner.CP = second
  assert owner.cps.brand == "b"
  assert Owner.cps is Owner.__dict__["cps"]
