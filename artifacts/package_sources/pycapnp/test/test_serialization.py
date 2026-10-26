import warnings
from contextlib import contextmanager

import pytest
import capnp
import os
import test_regression
import tempfile
import pickle
import mmap

this_dir = os.path.dirname(__file__)


@pytest.fixture
def all_types():
    return capnp.load(os.path.join(this_dir, "all_types.capnp"))


def test_roundtrip_bytes(all_types):
    msg = all_types.TestAllTypes.new_message()
    test_regression.init_all_types(msg)
    message_bytes = msg.to_bytes()

    with all_types.TestAllTypes.from_bytes(message_bytes) as msg:
        test_regression.check_all_types(msg)


def test_roundtrip_bytes_mmap(all_types):
    msg = all_types.TestAllTypes.new_message()
    test_regression.init_all_types(msg)

    with tempfile.TemporaryFile() as f:
        f.write(msg.to_bytes())
        length = f.tell()

        f.seek(0)
        memory = mmap.mmap(f.fileno(), length)

        with all_types.TestAllTypes.from_bytes(memory) as msg:
            test_regression.check_all_types(msg)


def test_roundtrip_bytes_buffer(all_types):
    msg = all_types.TestAllTypes.new_message()
    test_regression.init_all_types(msg)

    b = msg.to_bytes()
    v = memoryview(b)
    try:
        with all_types.TestAllTypes.from_bytes(v) as msg:
            test_regression.check_all_types(msg)
    finally:
        v.release()


def test_roundtrip_bytes_fail(all_types):
    with pytest.raises(TypeError):
        with all_types.TestAllTypes.from_bytes(42) as _:
            pass


@contextmanager
def _warnings(expected_count=2, expected_text="This message has already been written once."):
    with warnings.catch_warnings(record=True) as w:
        yield

        assert len(w) == expected_count
        assert all(issubclass(x.category, UserWarning) for x in w), w
        assert all(expected_text in str(x.message) for x in w), w


def test_roundtrip_bytes_multiple(all_types):
    msg = all_types.TestAllTypes.new_message()
    test_regression.init_all_types(msg)

    msgs = msg.to_bytes()
    with _warnings(2):
        msgs += msg.to_bytes()
        msgs += msg.to_bytes()

    i = 0
    for msg in all_types.TestAllTypes.read_multiple_bytes(msgs):
        test_regression.check_all_types(msg)
        i += 1
    assert i == 3


def test_pickle(all_types):
    msg = all_types.TestAllTypes.new_message()
    test_regression.init_all_types(msg)
    data = pickle.dumps(msg)
    msg2 = pickle.loads(data)

    test_regression.check_all_types(msg2)


def test_from_bytes_traversal_limit(all_types):
    size = 1024
    bld = all_types.TestAllTypes.new_message()
    bld.init("structList", size)
    data = bld.to_bytes()

    with all_types.TestAllTypes.from_bytes(data) as msg:
        with pytest.raises(capnp.KjException):
            for i in range(0, size):
                msg.structList[i].uInt8Field == 0

    with all_types.TestAllTypes.from_bytes(data, traversal_limit_in_words=2**62) as msg:
        for i in range(0, size):
            assert msg.structList[i].uInt8Field == 0


def test_malformed_text_field_reraise():
    SCHEMA = "@0xdbb9ad1f14bf0b36;\nstruct Person { name @0 :Text; age @1 :UInt32; }\n"
    with tempfile.NamedTemporaryFile(suffix=".capnp", mode="w", delete=False) as f:
        f.write(SCHEMA)

    Person = capnp.load(f.name).Person

    # Create valid payload and corrupt the NUL terminator
    buf = bytearray(Person.new_message(name="alice", age=30).to_bytes())
    buf[37] ^= 0xFF

    # An invalid UTF-8 error description may itself raise UnicodeDecodeError.
    with pytest.raises((capnp.KjException, UnicodeDecodeError)):
        with Person.from_bytes(bytes(buf), traversal_limit_in_words=2**20) as reader:
            _ = reader.name
