"""Optional integration checks against a local openpilot checkout.

Set OPENPILOT_PATH and run with openpilot's dependencies available. These tests
use the checkout's real schemas; they never copy or modify them.
"""

import os
import pickle
import sys
from pathlib import Path

import capnp
import pytest


@pytest.fixture(scope="module")
def openpilot():
    path = os.environ.get("OPENPILOT_PATH")
    if path is None:
        pytest.skip("set OPENPILOT_PATH to run openpilot integration tests")
    sys.path.insert(0, str(Path(path).resolve()))
    from openpilot.cereal import log

    return log


def test_event_types(openpilot):
    from openpilot.cereal import messaging
    from openpilot.cereal.services import SERVICE_LIST

    for event in openpilot.Event.schema.union_fields:
        if event not in SERVICE_LIST:
            continue
        try:
            msg = messaging.new_message(event)
        except capnp.KjException:
            msg = messaging.new_message(event, 2)
        with openpilot.Event.from_bytes(msg.to_bytes()) as reader:
            assert reader.which() == event
            assert reader.logMonoTime == msg.logMonoTime
            assert reader.valid == msg.valid


def test_can_fields(openpilot):
    from openpilot.selfdrive.pandad.pandad_api_impl import can_capnp_to_list, can_list_to_can_capnp

    frames = [(0x123, b"\x00\xff\x01", 0), (0x456, b"\x02\x03", 1)]
    raw = can_list_to_can_capnp(frames)
    # Exercise both the writer's and reader's cached schema field paths.
    decoded = can_capnp_to_list([raw])
    assert decoded[0][1] == frames
    with openpilot.Event.from_bytes(raw) as reader:
        assert [(f.address, f.dat, f.src) for f in reader.can] == frames


def test_schema_reflection(openpilot):
    from openpilot.system.webrtc.schema import generate_struct

    from opendbc.car.structs import car

    schema = generate_struct(car.CarState.schema)
    assert schema["vEgo"] == "float32"
    assert schema["gearShifter"] == "text"
    assert isinstance(schema["wheelSpeeds"], dict)
    assert (
        car.CarParams.schema.fields["safetyConfigs"].schema.elementType.node.id
        == car.CarParams.SafetyConfig.schema.node.id
    )


def test_logreader_and_pickle(openpilot):
    from openpilot.cereal import messaging
    from openpilot.tools.lib.logreader import LogReader

    msgs = []
    for i in range(20):
        msg = messaging.new_message("carState")
        msg.carState.vEgo = float(i)
        msgs.append(msg.to_bytes())
    readers = list(LogReader.from_bytes(b"".join(msgs)))
    assert [msg.carState.vEgo for msg in readers] == list(range(20))
    restored = pickle.loads(pickle.dumps(readers[3]))
    assert restored.which() == "carState"
    assert restored.carState.vEgo == 3.0


def test_fuzzy_messages_and_replay_comparison(openpilot):
    from openpilot.common.fuzzy import Fuzzy, capnp_random_dict
    from openpilot.selfdrive.test.process_replay.compare_logs import compare_logs

    for event in ("carState", "carControl", "carParams", "modelV2", "can", "extrinsicsCalibration"):
        data = capnp_random_dict(Fuzzy(42, 51), openpilot.Event.schema, event, real_floats=True)
        builder = openpilot.Event.new_message(**data)
        with openpilot.Event.from_bytes(builder.to_bytes()) as reader:
            assert reader.which() == event
            assert reader.to_dict() == builder.to_dict()
            assert compare_logs([reader], [reader.as_builder().as_reader()]) == []
