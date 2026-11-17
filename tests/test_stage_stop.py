"""A stage move halted from another thread, on the Demo stage."""

import threading

import pytest

from fibsem.cancellation import OperationCancelledError
from fibsem.drivers.demo import simulator
from fibsem.drivers.demo.devices import DemoXYZStage
from fibsem.structures.settings import FibsemStagePosition
from tests.fixtures.demo_stage import demo_session


@pytest.fixture
def stage():
    microscope, _ = demo_session(compustage=False)
    return microscope.stage


@pytest.fixture
def slow_moves(monkeypatch):
    """Demo moves that take a minute, so a stop always lands mid-move."""
    monkeypatch.setenv("FIBSEM_SIM_NO_DELAY", "0")
    monkeypatch.setattr(simulator, "STAGE_MOVEMENT_SLEEP_TIME", 60.0)


def stopped_mid_move(stage, move, stop=None):
    """What *move* raised when it was stopped once the stage was moving."""
    raised = []

    def run():
        try:
            move()
        except BaseException as error:  # noqa: BLE001 - the test reads it
            raised.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    assert stage.sim_moving.wait(10), "the move never started"
    (stop or stage.stop)()
    thread.join(10)
    assert not thread.is_alive(), "the stopped move never returned"
    return raised[0] if raised else None


def test_a_stopped_move_raises_and_leaves_the_stage_partway(stage, slow_moves):
    start = stage.position.get_value().x
    error = stopped_mid_move(
        stage, lambda: stage.move_absolute(FibsemStagePosition(x=start + 1e-3))
    )

    assert isinstance(error, OperationCancelledError)
    ended = stage.position.cached.x
    assert start <= ended < start + 1e-3
    # read back by the stopped move itself, not left at where it began
    assert ended == stage.sim_position.x


def test_a_stopped_relative_move_raises(stage, slow_moves):
    start = stage.position.get_value().x
    error = stopped_mid_move(
        stage, lambda: stage.move_relative(FibsemStagePosition(x=1e-3))
    )
    assert isinstance(error, OperationCancelledError)
    assert stage.position.cached.x < start + 1e-3


def test_the_move_after_a_stopped_one_arrives(stage, slow_moves, monkeypatch):
    start = stage.position.get_value().x
    stopped_mid_move(
        stage, lambda: stage.move_absolute(FibsemStagePosition(x=start + 1e-3))
    )
    monkeypatch.setenv("FIBSEM_SIM_NO_DELAY", "1")
    moved = stage.move_absolute(FibsemStagePosition(x=start + 2e-3))
    assert moved.x == pytest.approx(start + 2e-3)


def test_a_stop_with_nothing_moving_leaves_the_next_move_alone(stage):
    start = stage.position.get_value().x
    stage.stop()
    moved = stage.move_relative(FibsemStagePosition(x=1e-3))
    assert moved.x == pytest.approx(start + 1e-3)


def test_a_stopped_move_through_the_service_raises(slow_moves):
    microscope, _ = demo_session(compustage=False)
    stage = microscope.stage
    start = stage.position.get_value().x
    error = stopped_mid_move(
        stage,
        lambda: microscope.stage_movement.move_absolute(
            FibsemStagePosition(x=start + 1e-3)
        ),
    )
    assert isinstance(error, OperationCancelledError)


def test_stop_is_listed_as_available_where_the_driver_has_one(stage):
    assert stage.commands["stop"].available


def test_a_stage_that_cannot_stop_says_so():
    stage = DemoXYZStage().connect()
    assert not stage.commands["stop"].available
    with pytest.raises(NotImplementedError, match="cannot stop the stage"):
        stage.stop()
    moved = stage.move_absolute(FibsemStagePosition(x=1e-3))
    assert moved.x == pytest.approx(1e-3)
