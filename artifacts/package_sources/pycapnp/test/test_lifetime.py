"""Lifetimes used by realtime message producers and retained log readers."""

import gc
from pathlib import Path

import capnp
import pytest


@pytest.fixture
def schema():
    return capnp.load(str(Path(__file__).with_name("addressbook.capnp")))


def builder_count():
    return sum(type(obj) is capnp._MallocMessageBuilder for obj in gc.get_objects())


def test_kwargs_release_without_gc(schema):
    # Warm lazy schema state before counting. String fields must not create
    # schema/field cycles that keep whole arenas alive until the next GC pass.
    schema.Person.new_message(name="warmup")
    gc.collect()
    enabled = gc.isenabled()
    gc.disable()
    try:
        before = builder_count()
        for _ in range(1000):
            msg = schema.Person.new_message(name="Alice", phones=[{"type": "mobile"}])
            assert msg.name == "Alice"
            assert msg.phones[0].type == "mobile"
            del msg
        assert builder_count() == before
    finally:
        if enabled:
            gc.enable()


def test_unknown_string_field_raises(schema):
    with pytest.raises(capnp.KjException):
        schema.Person.new_message(notAField="Alice")


def test_readers_outlive_input_and_iterator(schema):
    data = b"".join(schema.Person.new_message(name=name).to_bytes() for name in ("Alice", "Bob"))
    messages = schema.Person.read_multiple_bytes(data)
    alice = next(messages)
    bob = next(messages)
    del data, messages
    gc.collect()
    assert (alice.name, bob.name) == ("Alice", "Bob")


def test_nested_reader_outlives_root(schema):
    data = schema.AddressBook.new_message(people=[{"name": "Alice"}]).to_bytes()
    with schema.AddressBook.from_bytes(data) as root:
        person = root.people[0]
    del data, root
    gc.collect()
    assert person.name == "Alice"
