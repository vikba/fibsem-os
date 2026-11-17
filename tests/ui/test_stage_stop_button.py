"""The Stop Stage button and the Esc action that presses it.

The move is a real one on the Demo stage, held open by its own ``_move_absolute``
waiting for the stop, so the halt travels the path it does on an instrument:
``stage.stop()`` from one worker, ``OperationCancelledError`` out of the other.

The Esc action is triggered on the real window's menu bar. That a key press
reaches the action in the running window is not tested here.

Run directly (no display needed):
    QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_stage_stop_button.py
"""

from __future__ import annotations

import os
import sys
import threading

import pytest

pytest.importorskip(
    "qtpy.QtWidgets"
)  # CI installs .[test] only; the UI extra is deliberate

from qtpy.QtCore import QEventLoop, Qt, QTimer
from qtpy.QtGui import QKeySequence

sys.path.insert(0, os.path.dirname(__file__))  # not str.rsplit: Windows paths
from test_viewer_less_widgets import (  # noqa: E402
    _CanvasHost,
    _image_widget,
    _movement_widget,
)

from fibsem.devices.stage import Stage  # noqa: E402
from fibsem.structures.settings import FibsemStagePosition  # noqa: E402
from fibsem.ui import notification_service  # noqa: E402
from fibsem.ui.widgets.stage_control_widget import (  # noqa: E402
    STAGE_CANNOT_STOP,
    STAGE_STOPPED,
)
from tests.fixtures.main_window import main_window_fixture  # noqa: E402

main_ui = main_window_fixture(connect=True)

TARGET = FibsemStagePosition(x=1e-6, y=1e-6, z=1e-6, r=0.0, t=0.0)


def _run(condition, tries: int = 40) -> None:
    """Pump until *condition* holds, or give up and let the assertion report it."""
    for _ in range(tries):
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()
        if condition():
            return


@pytest.fixture
def tab(qapp):
    host = _CanvasHost()
    _image_widget(host)
    widget = _movement_widget(host)
    yield widget
    host.deleteLater()


@pytest.fixture
def toasts(monkeypatch) -> list:
    said: list = []
    monkeypatch.setattr(
        notification_service,
        "show_toast",
        lambda message, *args, **kwargs: said.append(message),
    )
    return said


@pytest.fixture
def held_move(tab, monkeypatch) -> threading.Event:
    """Make the next absolute move block until the stage is stopped. The event is
    set once the move is under way."""
    stage = tab.microscope.stage
    moving = threading.Event()
    released = threading.Event()
    real_stop = stage._stop

    def _move_absolute(position) -> None:
        moving.set()
        assert released.wait(10), "the move was never stopped"

    def _stop() -> None:
        real_stop()
        released.set()

    monkeypatch.setattr(stage, "_move_absolute", _move_absolute)
    monkeypatch.setattr(stage, "_stop", _stop)
    return moving


def test_the_button_is_shown_for_a_stage_that_can_stop(tab):
    control = tab.control_widget
    assert tab.microscope.stage.can_stop()
    assert not control.pushButton_stop.isHidden()
    assert control.pushButton_stop not in control._move_buttons


def test_the_button_is_hidden_for_a_stage_that_cannot_stop(qapp, monkeypatch):
    host = _CanvasHost()
    _image_widget(host)
    monkeypatch.setattr(Stage, "can_stop", lambda self: False)
    control = _movement_widget(host).control_widget
    assert control.pushButton_stop.isHidden()
    host.deleteLater()


def test_a_stop_on_a_stage_that_cannot_stop_says_so(tab, toasts, monkeypatch):
    monkeypatch.setattr(Stage, "can_stop", lambda self: False)
    tab.stop_stage()
    assert toasts == [STAGE_CANNOT_STOP]


def test_the_button_stays_on_through_a_move_and_halts_it(tab, toasts, held_move):
    control = tab.control_widget
    retakes: list = []
    control.update_ui_after_movement = lambda *a, **k: retakes.append(1)

    tab.move_to_position(TARGET)
    _run(held_move.is_set)
    assert held_move.is_set()
    assert not control.pushButton_move.isEnabled()
    assert control.pushButton_stop.isEnabled()

    control.pushButton_stop.click()
    _run(control.pushButton_move.isEnabled)

    assert control.pushButton_move.isEnabled()
    assert toasts == [STAGE_STOPPED]
    assert retakes == []


def test_a_stop_with_nothing_moving_says_nothing(tab, toasts):
    control = tab.control_widget
    tab.stop_stage()
    _run(lambda: False, tries=4)
    assert toasts == []
    assert control.pushButton_move.isEnabled()


def test_esc_stops_the_stage_from_any_tab(main_ui, monkeypatch):
    action = main_ui.menu_bar.action_stop_stage
    assert action.shortcut() == QKeySequence(Qt.Key.Key_Escape)
    assert action.shortcutContext() == Qt.ShortcutContext.WindowShortcut

    stops: list = []
    monkeypatch.setattr(
        main_ui.panel.movement_widget, "stop_stage", lambda: stops.append(1)
    )
    action.trigger()
    assert stops == [1]


def test_esc_with_no_microscope_does_nothing(main_ui, monkeypatch):
    monkeypatch.setattr(main_ui.panel, "movement_widget", None)
    main_ui.menu_bar.action_stop_stage.trigger()
