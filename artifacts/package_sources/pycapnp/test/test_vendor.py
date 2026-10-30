"""Validation of malformed wire data through the trimmed C++ core."""

import struct
from pathlib import Path

import capnp
import pytest


@pytest.mark.parametrize("pointer", [3, 7, 0xFFFFFFFF00000003])
def test_capability_and_reserved_pointers_rejected(pointer):
    schema = capnp.load(str(Path(__file__).with_name("addressbook.capnp")))
    # Single segment: AddressBook root (zero data words, one pointer) followed
    # by a capability/reserved pointer where the people list should be.
    data = struct.pack("<IIQQ", 0, 2, 1 << 48, pointer)
    with schema.AddressBook.from_bytes(data) as reader:
        with pytest.raises(capnp.KjException):
            _ = reader.people
        with pytest.raises(capnp.KjException):
            reader.as_builder()
        if pointer == 7:
            with pytest.raises(capnp.KjException):
                _ = reader.total_size


def test_interface_schema_is_rejected(tmp_path):
    schema = tmp_path / "unsupported.capnp"
    schema.write_text("@0xdeadbeefdeadbeef; interface Unsupported { ping @0 () -> (); }")
    with pytest.raises(capnp.KjException, match="Interfaces are not supported"):
        capnp.load(str(schema))
