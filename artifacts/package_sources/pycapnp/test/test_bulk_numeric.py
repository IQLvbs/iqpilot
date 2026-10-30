# Copyright (c) 2026 IQ.Lvbs. All rights reserved.
import gc

import capnp
import numpy as np
import pytest


@pytest.fixture(scope="module")
def numeric_schema(tmp_path_factory):
    path = tmp_path_factory.mktemp("bulk-schema") / "numeric.capnp"
    path.write_text("""# Copyright (c) 2026 IQ.Lvbs. All rights reserved.
@0xe7ab11f278d8b04a;
struct Numbers {
  f32 @0 :List(Float32);
  f64 @1 :List(Float64);
  i64 @2 :List(Int64);
  u64 @3 :List(UInt64);
  text @4 :List(Text);
  nested @5 :List(List(Float32));
}
""")
    return capnp.load(str(path)).Numbers


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("f32", []),
        ("f32", [0.0, -0.0, 1.25, -2.5, float("inf"), -float("inf"), float("nan")]),
        ("f64", [1e-300, 1e300, 1.23456789012345, -0.0]),
        ("i64", [-(2**63), -1, 0, 2**63 - 1]),
        ("u64", [0, 2**53 + 1, 2**64 - 1]),
    ],
)
def test_bulk_values_and_lifetime(numeric_schema, field, values):
    builder = numeric_schema.new_message(**{field: values})
    encoded = builder.to_bytes()
    with numeric_schema.from_bytes(encoded) as reader:
        data = getattr(reader, field)
        expected = np.array(data, dtype=np.float64)
        buffer = data.to_float64_bytes()
        actual = np.frombuffer(buffer, dtype=np.float64)
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(np.signbit(actual), np.signbit(expected))
        assert not actual.flags.writeable
    del reader, data, encoded, builder, buffer
    gc.collect()
    np.testing.assert_array_equal(actual, expected)


def test_bulk_rejects_text(numeric_schema):
    builder = numeric_schema.new_message(text=["not numeric"])
    with numeric_schema.from_bytes(builder.to_bytes()) as reader:
        with pytest.raises(TypeError):
            reader.text.to_float64_bytes()


def test_bulk_is_an_owned_snapshot(numeric_schema):
    builder = numeric_schema.new_message(f32=[1.0, 2.0])
    reader = builder.as_reader()
    array = np.frombuffer(reader.f32.to_float64_bytes(), dtype=np.float64)
    builder.f32[0] = 9.0
    np.testing.assert_array_equal(array, [1.0, 2.0])
    np.testing.assert_array_equal(np.frombuffer(reader.f32.to_float64_bytes(), dtype=np.float64), [9.0, 2.0])


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("f32", []),
        ("f32", [0.0, -0.0, 1.25, float("inf"), float("nan")]),
        ("f64", [1e-300, 1e300, -0.0]),
        ("i64", [-(2**63), 0, 2**63 - 1]),
        ("u64", [0, 2**64 - 1]),
        ("text", ["a", "bc"]),
    ],
)
@pytest.mark.parametrize("dtype", [None, np.float64, np.complex128, "U32"])
@pytest.mark.parametrize("reader", [False, True])
def test_array_protocol(numeric_schema, field, values, dtype, reader):
    builder = numeric_schema.new_message(**{field: values})
    data = getattr(builder.as_reader() if reader else builder, field)
    if field == "text" and dtype in (np.float64, np.complex128):
        with pytest.raises(ValueError):
            np.array(data, dtype=dtype)
        return
    expected = np.array(list(data), dtype=dtype)
    actual = np.array(data, dtype=dtype)
    np.testing.assert_array_equal(actual, expected)
    assert actual.dtype == expected.dtype
    assert actual.flags.writeable
    assert actual.flags.owndata
    with pytest.raises(ValueError):
        np.asarray(data, copy=False)


def test_float32_array_ownership(numeric_schema):
    builder = numeric_schema.new_message(f32=[1.25, -0.0, float("nan")])
    actual = np.asarray(builder.as_reader().f32, dtype=np.float32)
    expected = np.asarray(list(builder.f32), dtype=np.float32)
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(np.signbit(actual), np.signbit(expected))
    builder.f32[0] = 99.0
    del builder
    gc.collect()
    actual[2] = 7.0
    assert actual[0] == 1.25
    assert actual[2] == 7.0


def test_array_cast_overflow(numeric_schema):
    builder = numeric_schema.new_message(f64=[1e300])
    with pytest.warns(RuntimeWarning, match="overflow"):
        expected = np.array(list(builder.f64), dtype=np.float32)
    with pytest.warns(RuntimeWarning, match="overflow"):
        actual = np.array(builder.as_reader().f64, dtype=np.float32)
    np.testing.assert_array_equal(actual, expected)


def test_nested_arrays(numeric_schema):
    builder = numeric_schema.new_message(nested=[[1.0, 2.0], [3.0, 4.0]])
    for message in (builder, builder.as_reader()):
        actual = np.array(message.nested)
        expected = np.array([list(row) for row in message.nested])
        np.testing.assert_array_equal(actual, expected)
        assert actual.dtype == expected.dtype
