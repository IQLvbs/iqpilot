import pytest

from iqpilot.system.ubloxd import ubloxd
from iqpilot.system.ubloxd.ubx import Ubx


def _nav_pvt_frame(valid: int) -> bytes:
  payload = bytearray(92)
  payload[11] = valid
  return b"\xb5\x62\x01\x07\x5c\x00" + bytes(payload) + b"\x00\x00"


@pytest.mark.parametrize("valid,published", [(0x07, True), (0x03, False), (0x00, False), (0x04, False), (0x0f, True)])
def test_nav_pvt_publishes_only_once_the_utc_time_is_fully_resolved(valid, published):
  parser = ubloxd.UbloxMsgParser()
  assert Ubx.NavPvt.from_bytes(bytes(_nav_pvt_frame(valid)[6:-2])).valid == valid
  assert (parser.parse_frame(_nav_pvt_frame(valid)) is not None) == published
