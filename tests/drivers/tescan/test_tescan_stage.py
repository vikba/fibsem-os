"""The Tescan stage device converts between fibsem's stage frame and Tescan's (FIB-1114).

``TescanStage.position`` is in fibsem's frame, and every ``Stage.MoveTo`` is in
Tescan's. What the app sends for each move and click is pinned in
``tests/drivers/tescan/test_tescan_frame_pins.py``, which runs through this device. These tests pin
the conversion itself: that it is the change of axes FIB-1114 derives, and how the
device handles a move that leaves axes out. Nothing here has run on an instrument.
"""

import os
import threading

import numpy as np
import pytest

import fibsem.config as cfg
from fibsem import utils
from fibsem.cancellation import OperationCancelledError
from fibsem.devices.stage import UNLIMITED
from fibsem.drivers.tescan import sdk
from fibsem.drivers.tescan.devices import (
    TILT_AXIS_Z,
    TescanStage,
    from_tescan_frame,
    to_tescan_frame,
)
from fibsem.structures.settings import BeamType, FibsemStagePosition
from fibsem.structures.system import STAGE_FRAME_FIBSEM
from tests.fixtures.tescan_sdk import connect

P = FibsemStagePosition
START = [1.2, -0.8, 29.0, 180.0, 30.0]  # mm and degrees
TILTS = np.radians([-10.0, 0.0, 15.0, 35.0, 55.0])


def _system(stage=True):
    system = utils.load_microscope_configuration(
        os.path.join(cfg.SHIPPED_CONFIG_PATH, "tescan-configuration.yaml")
    ).system
    system.stage.enabled = stage
    system.stage.shuttle_pre_tilt = 35.0
    return system


def _connected(monkeypatch):
    microscope, fake = connect(monkeypatch, _system())
    fake.Stage.position = list(START)
    return microscope, fake


def _chamber_tescan(native: P):
    """Where a Tescan stage puts the sample, in the tilt plane: y′ along the tilted
    plate, z′ chamber-vertical and +z′ down, y′ opposite fibsem's y."""
    y, t = -native.y, native.t
    return np.array([y * np.cos(t), y * np.sin(t) - (native.z - TILT_AXIS_Z)])


def _chamber_thermo(position: P):
    """Where a ThermoFisher stage puts it: y and z both ride the tilt."""
    y, z, t = position.y, position.z, position.t
    return np.array([y * np.cos(t) - z * np.sin(t), y * np.sin(t) + z * np.cos(t)])


@pytest.mark.parametrize("t", TILTS)
def test_a_position_puts_the_sample_where_a_thermo_stage_would(t):
    native = P(x=1.2e-3, y=-0.8e-3, z=29.0e-3, r=np.pi, t=t)
    converted = from_tescan_frame(native)
    assert converted.x == pytest.approx(-native.x)
    assert _chamber_thermo(converted) == pytest.approx(_chamber_tescan(native))


@pytest.mark.parametrize("t", TILTS)
def test_the_conversion_round_trips(t):
    native = P(x=1.2e-3, y=-0.8e-3, z=31.0e-3, r=0.5, t=t)
    back = to_tescan_frame(from_tescan_frame(native))
    for axis in "xyzrt":
        assert getattr(back, axis) == pytest.approx(getattr(native, axis), abs=1e-15)


def test_a_tilt_at_the_tilt_axis_height_moves_nothing_else():
    """z′₀ is where the converted frame puts the tilt axis: a fibsem tilt-only move
    there is a pure tilt on the instrument."""
    at_axis = from_tescan_frame(P(x=0.0, y=1e-3, z=TILT_AXIS_Z, r=0.0, t=0.0))
    tilted = to_tescan_frame(P(x=0.0, y=at_axis.y, z=at_axis.z, r=0.0, t=0.6))
    assert (tilted.y, tilted.z) == pytest.approx((1e-3, TILT_AXIS_Z))


def test_the_device_reads_fibsem_frame(monkeypatch):
    microscope, _ = _connected(monkeypatch)
    native = P(x=1.2e-3, y=-0.8e-3, z=29.0e-3, r=np.radians(180.0), t=np.radians(30.0))
    position = microscope.get_stage_position()
    expected = from_tescan_frame(native)
    for axis in "xyzrt":
        assert getattr(position, axis) == pytest.approx(getattr(expected, axis))
    assert microscope.stage.frame == STAGE_FRAME_FIBSEM


def test_an_absolute_move_sends_the_converted_position(monkeypatch):
    microscope, fake = _connected(monkeypatch)
    target = P(x=1e-3, y=2e-3, z=-0.5e-3, r=0.0, t=np.radians(20))
    microscope.move_stage_absolute(target)
    (call,) = fake.calls("Stage.MoveTo")
    native = to_tescan_frame(target)
    assert call == pytest.approx(
        {
            "x": native.x * 1e3,
            "y": native.y * 1e3,
            "z": native.z * 1e3,
            "rot": 0.0,
            "tiltx": 20.0,
        }
    )


def test_a_pose_change_alone_is_a_pure_tilt(monkeypatch):
    """Rotation and tilt without x, y or z send none of them, as before the
    conversion: the instrument tilts about its own axis."""
    microscope, fake = _connected(monkeypatch)
    microscope.move_stage_absolute(P(r=np.radians(0.0), t=np.radians(-20.0)))
    microscope.move_stage_relative(P(t=np.radians(5.0)))
    absolute, relative = fake.calls("Stage.MoveTo")
    assert (absolute["x"], absolute["y"], absolute["z"]) == (None, None, None)
    assert (relative["x"], relative["y"], relative["z"]) == (None, None, None)
    assert relative["tiltx"] == pytest.approx(-15.0)


def test_y_alone_keeps_z_where_it_is(monkeypatch):
    microscope, _ = _connected(monkeypatch)
    before = microscope.get_stage_position()
    microscope.move_stage_absolute(P(y=before.y + 1e-6))
    after = microscope.get_stage_position()
    assert after.z == pytest.approx(before.z, abs=1e-12)
    assert after.y == pytest.approx(before.y + 1e-6, abs=1e-12)


def test_the_moves_go_through_the_device(monkeypatch):
    microscope, _ = _connected(monkeypatch)
    seen = []
    for name in ("_move_absolute", "_move_relative"):
        hook = getattr(TescanStage, name)
        monkeypatch.setattr(
            TescanStage,
            name,
            lambda self, p, n=name, h=hook: (seen.append(n), h(self, p))[1],
        )
    microscope.move_stage_absolute(P(x=0.0))
    microscope.move_stage_relative(P(x=1e-6))
    microscope.stable_move(1e-6, 1e-6, BeamType.ION)
    microscope.vertical_move(1e-6, 0.0, BeamType.ELECTRON)
    # a relative move is an absolute one to where the stage is plus the offset
    relative = ["_move_relative", "_move_absolute"]
    assert seen == ["_move_absolute"] + relative * 3


def test_the_stage_has_position_and_linked_and_every_axis_unlimited(monkeypatch):
    microscope, _ = _connected(monkeypatch)
    stage = microscope.stage
    assert sorted(stage.parameters) == ["linked", "position"]
    assert stage.linked.get_value() is False
    assert list(stage.axes) == ["x", "y", "z", "r", "t"]
    assert all(stage.axes[a].limits == UNLIMITED for a in stage.axes)


def test_a_disabled_stage_gets_no_device(monkeypatch):
    microscope, _ = connect(monkeypatch, _system(stage=False))
    microscope._build_stage()
    assert microscope.stage is None
    with pytest.raises(NotImplementedError, match="get_stage_position"):
        microscope.get_stage_position()


def _stopped_mid_move(monkeypatch, microscope, fake):
    """What a move raised when it was stopped while ``Stage.MoveTo`` was out, and how
    many connections the stop opened. The fake's MoveTo waits for its Stop."""
    started, stopped = threading.Event(), threading.Event()
    opened, raised = [], []

    def move_to(**kwargs):
        fake.record("Stage.MoveTo", (), kwargs)
        started.set()
        assert stopped.wait(10), "the move was never stopped"

    def stop():
        fake.record("Stage.Stop", (), {})
        stopped.set()

    fake.Stage.MoveTo, fake.Stage.Stop = move_to, stop
    monkeypatch.setattr(
        sdk, "Automation", lambda *args, **kwargs: opened.append(args) or fake
    )

    def run():
        try:
            microscope.stage.move_absolute(P(x=2e-3))
        except BaseException as error:  # noqa: BLE001 - the test reads it
            raised.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    assert started.wait(10), "the move never started"
    microscope.stage.stop()
    thread.join(10)
    assert not thread.is_alive(), "the stopped move never returned"
    return (raised[0] if raised else None), opened


def test_stop_is_available_on_the_tescan_stage(monkeypatch):
    microscope, _ = _connected(monkeypatch)
    assert microscope.stage.commands["stop"].available


def test_a_stop_reaches_the_stage_on_a_second_connection(monkeypatch):
    microscope, fake = _connected(monkeypatch)
    error, opened = _stopped_mid_move(monkeypatch, microscope, fake)
    assert isinstance(error, OperationCancelledError)
    assert len(opened) == 1  # MoveTo holds the first connection's lock
    assert len(fake.calls("Stage.Stop")) == 1


def test_a_move_after_a_stopped_one_arrives(monkeypatch):
    microscope, fake = _connected(monkeypatch)
    _stopped_mid_move(monkeypatch, microscope, fake)
    del fake.Stage.MoveTo
    moved = microscope.stage.move_absolute(P(x=2e-3))
    assert moved.x == pytest.approx(2e-3)


def test_a_move_that_fails_without_a_stop_still_raises(monkeypatch):
    microscope, fake = _connected(monkeypatch)

    def move_to(**kwargs):
        raise RuntimeError("stage error")

    fake.Stage.MoveTo = move_to
    with pytest.raises(RuntimeError, match="stage error"):
        microscope.stage.move_absolute(P(x=2e-3))
