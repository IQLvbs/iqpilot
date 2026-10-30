from dataclasses import dataclass
from enum import Enum

import pytest

from iqdbc.car import structs
from iqdbc.car.hyundai.values import HyundaiFlagsIQ

from iqpilot.selfdrive.car.helpers import asdictref, convert_to_capnp


class SampleEnum(Enum):
  value = 7


@dataclass
class SampleStruct:
  enum: SampleEnum
  values: tuple[int, ...]
  mapping: dict[str, list[SampleEnum]]


def test_convert_to_capnp_normalizes_enum_values():
  params = structs.IQCarParams(flags=HyundaiFlagsIQ.HAS_LFA_BUTTON)
  assert asdictref(params)["flags"] == HyundaiFlagsIQ.HAS_LFA_BUTTON.value
  assert convert_to_capnp(params).flags == HyundaiFlagsIQ.HAS_LFA_BUTTON.value


def test_asdictref_preserves_container_types_and_resolves_enums():
  source = SampleStruct(SampleEnum.value, (1, 2), {"items": [SampleEnum.value]})
  converted = asdictref(source)
  assert converted == {"enum": 7, "values": (1, 2), "mapping": {"items": [7]}}
  assert isinstance(converted["values"], tuple)
  assert isinstance(converted["mapping"]["items"], list)


def test_asdictref_rejects_non_dataclass_values():
  with pytest.raises(TypeError, match="dataclass instances"):
    asdictref(object())


def test_convert_to_capnp_supports_iq_car_state():
  state = convert_to_capnp(structs.IQCarState())
  assert state.speedLimit == 0
  assert not state.accelPressed


def test_convert_to_capnp_rejects_unknown_dataclass():
  with pytest.raises(ValueError, match="Unsupported struct type"):
    convert_to_capnp(SampleStruct(SampleEnum.value, (), {}))
