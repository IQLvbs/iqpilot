"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from iqpilot.system.hardware.tici import agnos

COMMA_DONGLE = "a15da42415bc1323"


class FakeResponse:
  def __init__(self, status, body):
    self.status_code = status
    self.ok = 200 <= status < 300
    self._body = body
    self.text = str(body)

  def json(self):
    return self._body


@pytest.fixture
def stock_device(tmp_path, monkeypatch):
  key = ec.generate_private_key(ec.SECP256R1())
  (tmp_path / "id_ecdsa").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                                        serialization.NoEncryption()))
  (tmp_path / "dongle_id").write_text(COMMA_DONGLE + "\n")
  monkeypatch.setattr(agnos, "PERSIST_COMMA", str(tmp_path))
  monkeypatch.setattr(agnos, "_k3_identity", {})
  monkeypatch.setattr(agnos, "_device_serial", lambda: "2b6aca39")
  monkeypatch.setattr(agnos, "_device_imeis", lambda: ("", ""))
  monkeypatch.setattr(agnos, "_image_auth_module", lambda: None)
  monkeypatch.setattr(agnos.time, "sleep", lambda _s: None)
  public_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
  return tmp_path, public_pem


def test_a_stock_device_registers_its_comma_dongle_id_without_a_pub_file(stock_device, monkeypatch):
  persist, public_pem = stock_device
  sent = {}

  def post(url, timeout, params):
    sent.update(params, url=url)
    return FakeResponse(200, {"dongle_id": COMMA_DONGLE})

  monkeypatch.setattr(agnos.requests, "post", post)
  proxy_url, headers = agnos._k3_proxy_url("https://git.konn3kt.com/IQ.Lvbs/iqos/raw/branch/main/xbl-abc.img.xz")

  assert sent["url"].endswith("/v2/pilotauth")
  assert sent["public_key"] == public_pem
  claims = jwt.decode(sent["register_token"], public_pem, algorithms=["ES256"])
  assert claims["identity"] == COMMA_DONGLE and claims["register"] is True
  assert f"/v1/devices/{COMMA_DONGLE}/assets/iqos/xbl-abc.img.xz" in proxy_url
  assert jwt.decode(headers["Authorization"].split()[1], public_pem, algorithms=["ES256"])["identity"] == COMMA_DONGLE
  assert (persist / "dongle_id").read_text().strip() == COMMA_DONGLE


def test_a_failed_registration_is_reported_instead_of_using_an_unregistered_id(stock_device, monkeypatch):
  monkeypatch.setattr(agnos.requests, "post", lambda url, timeout, params: FakeResponse(401, "Invalid register token"))
  with pytest.raises(RuntimeError, match="konn3kt registration failed for a15da42415bc1323: HTTP 401"):
    agnos._k3_proxy_url("https://git.konn3kt.com/IQ.Lvbs/iqos/raw/branch/main/xbl-abc.img.xz")


def test_registration_is_done_once_per_update(stock_device, monkeypatch):
  calls = []
  monkeypatch.setattr(agnos.requests, "post", lambda url, timeout, params: calls.append(1) or FakeResponse(200, {"dongle_id": COMMA_DONGLE}))
  for _ in range(5):
    agnos._k3_proxy_url("https://git.konn3kt.com/IQ.Lvbs/iqos/raw/branch/main/boot-abc.img.xz")
  assert len(calls) == 1


def test_a_device_without_any_dongle_id_asks_konn3kt_to_issue_one(stock_device, monkeypatch):
  persist, public_pem = stock_device
  (persist / "dongle_id").unlink()
  monkeypatch.setattr(agnos, "_read_dongle_id", lambda: None)
  sent = {}
  monkeypatch.setattr(agnos.requests, "post", lambda url, timeout, params: sent.update(params) or FakeResponse(200, {"dongle_id": "0123456789abcdef"}))
  proxy_url, _ = agnos._k3_proxy_url("https://git.konn3kt.com/IQ.Lvbs/iqos/raw/branch/main/xbl-abc.img.xz")
  assert jwt.decode(sent["register_token"], public_pem, algorithms=["ES256"])["identity"] == "register"
  assert "/v1/devices/0123456789abcdef/" in proxy_url
  assert not (persist / "dongle_id").exists()
