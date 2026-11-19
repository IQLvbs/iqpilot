# Copyright (c) 2026 IQ.Lvbs. All rights reserved.
import hashlib
import json
import struct
from pathlib import Path

import capnp
import pytest

ROOT = Path(__file__).parent
CASES = json.loads((ROOT / "serialization-reference.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case["size"]))
def test_serialization_identity(case):
    schema = capnp.load(str(ROOT / "all_types.capnp")).TestAllTypes
    size = case["size"]
    text_size = case["text_size"]
    message = schema.new_message(dataField=b"Z" * size, textField="iq" * text_size, float64List=[1.25, -0.0, 123.0])
    data = message.to_bytes()
    assert len(data) == case["bytes"]
    assert struct.unpack_from("<I", data)[0] + 1 == case["segments"]
    assert hashlib.sha256(data).hexdigest() == case["sha256"]
    with schema.from_bytes(data) as reader:
        assert reader.dataField == b"Z" * size
        assert reader.textField == "iq" * text_size
