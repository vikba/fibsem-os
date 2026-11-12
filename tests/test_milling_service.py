"""The milling service on the Demo, and the old milling methods over it.

The Demo mills with the shared demo code through `microscope.milling`. That
`finish_milling` puts the beam back as `setup_milling` found it is in the contract
suite (`test_finish_milling_puts_the_beam_back`), for both demos.
"""

import pytest

from fibsem import utils
from fibsem.devices.core import Device
from fibsem.drivers.demo.services import (
    _PATTERN_SETUP_TIME,
    SIM_MILL_SCALE,
    DemoMilling,
    _mill_seconds,
)
from fibsem.milling.base import estimate_volume_time
from fibsem.services import Service
from fibsem.services.milling import DRAW_HOOKS, Milling, UnsupportedPattern
from fibsem.structures.settings import (
    BeamType,
    FibsemCircleSettings,
    FibsemLineSettings,
    FibsemMillingSettings,
    FibsemPatternSettings,
    FibsemPolygonSettings,
    FibsemRectangleSettings,
    MillingState,
)
from tests.fixtures.microscopes import demo_microscope

microscope = demo_microscope(scope="function")


def _rectangle() -> FibsemRectangleSettings:
    return FibsemRectangleSettings(
        width=10e-6, height=5e-6, depth=1e-6, centre_x=0, centre_y=0
    )


def _patterns():
    return [
        _rectangle(),
        FibsemLineSettings(start_x=0, start_y=0, end_x=1e-6, end_y=0, depth=1e-6),
        FibsemCircleSettings(centre_x=0, centre_y=0, radius=1e-6, depth=1e-6),
    ]


def _recipe(**kwargs) -> FibsemMillingSettings:
    values = dict(milling_current=7.6e-9, milling_voltage=30e3, hfw=80e-6)
    values.update(kwargs)
    return FibsemMillingSettings(**values)


def _conditions(microscope, beam_type=BeamType.ION):
    return tuple(
        microscope._read_beam(key, beam_type) for key in ("voltage", "current", "hfw")
    )


def test_the_demo_has_a_milling_service_that_is_not_a_device(microscope):
    milling = microscope.milling
    assert isinstance(milling, DemoMilling)
    assert isinstance(milling, Service) and not isinstance(milling, Device)
    assert milling not in microscope.beams.values()
    assert milling.ion is microscope.beams[BeamType.ION]
    assert milling.electron is microscope.beams[BeamType.ELECTRON]
    assert milling.resources is microscope.resources
    assert sorted(milling.parameters) == ["progress", "readings", "state"]
    assert {
        "setup",
        "draw",
        "prepare",
        "start",
        "stop",
        "pause",
        "resume",
        "clear",
        "restore",
        "run",
    } <= set(milling.commands)
    assert "estimate_time" in milling.queries


def test_prepare_applies_the_recipe_and_draws(microscope):
    milling = microscope.milling
    prepared = milling.prepare(_recipe(patterning_mode="Parallel"), _patterns())
    assert _conditions(microscope) == (30e3, 7.6e-9, 80e-6)
    assert microscope._connection.milling_system.patterning_mode == "Parallel"
    assert len(microscope._connection.milling_system.patterns) == 3
    assert prepared["milling_current"] == 7.6e-9
    seconds = _mill_seconds(_patterns(), 7.6e-9)
    assert milling.estimate_time() == {"seconds": seconds, **prepared}
    assert microscope.estimate_milling_time() == seconds


def test_a_current_the_beam_does_not_list_is_warned_of(microscope):
    listed = sorted(microscope.beams[BeamType.ION].current.choices)
    asked = (listed[0] + listed[1]) / 2
    prepared = microscope.milling.prepare(_recipe(milling_current=asked), _patterns())
    warning = prepared["warning"]
    assert "is not a current the milling beam lists" in warning
    assert utils.format_current(listed[0]) in warning
    assert utils.format_current(listed[1]) in warning
    assert microscope.milling.estimate_time()["warning"] == warning


def test_a_driver_that_lists_no_currents_has_no_warning(microscope, monkeypatch):
    from fibsem.devices.core import ParameterMetadata

    current = microscope.beams[BeamType.ION].current
    monkeypatch.setattr(current, "_metadata_source", ParameterMetadata())
    prepared = microscope.milling.prepare(_recipe(milling_current=1.234e-9), [])
    assert prepared["warning"] is None


def test_a_setup_clears_what_was_drawn(microscope):
    microscope.milling.prepare(_recipe(), _patterns())
    microscope.setup_milling(_recipe())
    assert microscope._connection.milling_system.patterns == []


def test_the_old_methods_go_through_the_service(microscope):
    microscope.setup_milling(_recipe())
    microscope.draw_patterns(_patterns())
    assert len(microscope._connection.milling_system.patterns) == 3

    seen = []
    microscope.milling.state.get_value()
    microscope.milling.changed.connect(lambda name, value: seen.append(value))
    microscope.start_milling()
    assert microscope.milling.state.get_value() is MillingState.RUNNING
    microscope.pause_milling()
    assert microscope.milling.state.get_value() is MillingState.PAUSED
    microscope.resume_milling()
    microscope.milling.state.get_value()
    microscope.stop_milling()
    assert microscope.milling.state.get_value() is MillingState.IDLE
    assert seen == [
        MillingState.RUNNING,
        MillingState.PAUSED,
        MillingState.RUNNING,
        MillingState.IDLE,
    ]
    microscope.milling.clear()
    assert microscope._connection.milling_system.patterns == []


def test_run_milling_mills_what_the_service_drew(microscope):
    microscope.setup_milling(_recipe())
    microscope.draw_patterns([_rectangle()])
    microscope.run_milling()
    assert microscope.milling.state.get_value() is MillingState.IDLE
    assert microscope._connection.milling_system.patterns == []


def test_restore_goes_through_the_beam_device(microscope):
    beam = microscope.beams[BeamType.ION]
    microscope.setup_milling(_recipe())
    seen = []
    beam.changed.connect(lambda name, value: seen.append(name))
    microscope.milling.restore()
    assert {"current", "hfw"} <= set(seen)


def test_the_service_needs_its_hooks():
    for hook in ("_setup", "_start", "_estimate", "_clear"):
        assert getattr(DemoMilling, hook) is not getattr(Milling, hook), hook


def test_the_demo_draws_every_pattern_type():
    assert set(DemoMilling.supported_pattern_types()) == set(DRAW_HOOKS)


class _Unknown(FibsemPatternSettings):
    """A pattern type no driver draws."""

    volume = 0.0


def test_a_pattern_type_the_driver_does_not_draw_raises(microscope):
    microscope.setup_milling(_recipe())
    with pytest.raises(UnsupportedPattern, match="cannot draw _Unknown patterns"):
        microscope.draw_pattern(_Unknown())
    assert microscope._connection.milling_system.patterns == []


def test_nothing_is_drawn_when_one_pattern_cannot_be(microscope):
    """Every pattern is checked first, so a stage is never half drawn."""
    microscope.setup_milling(_recipe())
    with pytest.raises(UnsupportedPattern):
        microscope.draw_patterns(_patterns()[:2] + [_Unknown()])
    assert microscope._connection.milling_system.patterns == []


def test_a_subclass_of_a_drawn_type_is_drawn_as_it(microscope):
    class Notched(FibsemRectangleSettings):
        pass

    microscope.setup_milling(_recipe())
    microscope.draw_pattern(
        Notched(width=1e-6, height=1e-6, depth=1e-6, centre_x=0, centre_y=0)
    )
    assert len(microscope._connection.milling_system.patterns) == 1


def test_without_an_ion_beam_the_demo_does_not_mill(microscope):
    """A configuration with the ion column off builds no ion beam, so no milling
    service: there is nothing to mill with, so milling raises, stopping does nothing
    and the state reads idle."""
    from copy import deepcopy

    from fibsem.drivers.demo.microscope import DemoMicroscope

    system = deepcopy(microscope.system)
    system.ion.enabled = False
    electron_only = DemoMicroscope(system)
    assert BeamType.ION not in electron_only.beams
    assert electron_only.milling is None
    with pytest.raises(ValueError, match="ION beam is not enabled"):
        electron_only.draw_patterns([_rectangle()])
    assert electron_only._connection.milling_system.patterns == []
    electron_only.stop_milling()


def test_the_demo_says_which_settings_it_mills_with(microscope):
    supported = microscope.milling.supported_settings()
    assert set(supported) == {
        "milling_channel",
        "hfw",
        "milling_current",
        "milling_voltage",
        "application_file",
        "patterning_mode",
    }
    ion = microscope.beams[BeamType.ION]
    # a beam's own parameter carries the beam's metadata, not a copy
    assert supported["milling_current"] is ion.parameters["current"].metadata
    assert list(supported["application_file"].choices) == list(
        microscope._connection.milling_system.application_files
    )
    assert supported["patterning_mode"].choices == ("Serial", "Parallel")
    assert supported["milling_channel"].choices == (BeamType.ION, BeamType.ELECTRON)


def test_the_demo_says_which_directions_it_scans(microscope):
    from fibsem.drivers.demo.simulator import SIMULATOR_SCAN_DIRECTIONS

    supported = microscope.milling.supported_pattern_settings()
    assert set(supported) == {"scan_direction"}
    assert list(supported["scan_direction"].choices) == SIMULATOR_SCAN_DIRECTIONS


def test_the_demo_mills_with_the_settings_it_says(microscope):
    from tests.fixtures.milling_reads import fields_setup_reads

    read = fields_setup_reads(microscope.milling, _recipe())
    assert read == set(microscope.milling.supported_settings())


def test_a_channel_with_no_beam_has_no_settings(microscope):
    del microscope.milling._roles["electron"]
    assert microscope.milling.supported_settings(BeamType.ELECTRON) == {}
    assert microscope.milling.supported_settings()["milling_channel"].choices == (
        BeamType.ION,
    )


@pytest.mark.parametrize(
    "version, polygons", [("4.11", False), ("4.12", True)], ids=["4.11", "4.12"]
)
def test_autoscript_draws_polygons_from_4_12(monkeypatch, version, polygons):
    from packaging.version import parse as parse_version

    from fibsem.drivers.autoscript import microscope as autoscript
    from fibsem.drivers.autoscript.services import AutoScriptMilling

    monkeypatch.setattr(autoscript, "AUTOSCRIPT_VERSION", parse_version(version))
    types = AutoScriptMilling.supported_pattern_types()
    assert (FibsemPolygonSettings in types) is polygons
    assert set(types) | {FibsemPolygonSettings} == set(DRAW_HOOKS)


def test_the_drawn_patterns_are_announced_until_they_are_removed(microscope):
    # FIB-1375: the app draws an agent's mill from these; it has no config of it.
    milling = microscope.milling
    seen = []
    milling.patterns_changed.connect(lambda patterns: seen.append(len(patterns)))
    milling.prepare(_recipe(), _patterns()[:2])
    milling.draw([_rectangle()])
    assert len(milling.drawn_patterns) == 3
    milling.run()
    assert milling.drawn_patterns == []
    milling.prepare(_recipe(), [_rectangle()])
    microscope.milling.clear()
    assert seen == [2, 3, 0, 1, 0]


def test_the_estimate_takes_stages_before_anything_is_drawn(microscope):
    """Round 10 (FIB-1496): the estimate only answered for what was drawn."""
    from fibsem.milling import FibsemMillingStage

    stage = FibsemMillingStage(name="Rough")
    answer = microscope.milling.estimate_time(stages=[stage])
    seconds = DemoMilling.estimate_stage(stage)
    assert answer == {
        "seconds": seconds,
        "stages": [{"name": "Rough", "seconds": seconds}],
    }


def _seconds(microscope, patterns, **recipe) -> float:
    microscope.milling.prepare(_recipe(**recipe), patterns)
    return microscope.milling.estimate_time()["seconds"]


def test_the_demo_mills_in_proportion_to_the_estimate(microscope, monkeypatch):
    """A fraction of the sputter-rate estimate (a tenth unless the scale is set),
    and a moment to set each pattern up."""
    estimate = estimate_volume_time(_rectangle().volume, 7.6e-9)
    one = _seconds(microscope, [_rectangle()])
    assert one == pytest.approx(0.1 * estimate + _PATTERN_SETUP_TIME)
    monkeypatch.setenv(SIM_MILL_SCALE, "0.5")
    assert _seconds(microscope, [_rectangle()]) == pytest.approx(
        0.5 * estimate + _PATTERN_SETUP_TIME
    )


def test_the_demo_mills_longer_for_more_volume_and_less_current(microscope):
    """Twice the area or the depth is twice the milling; twice the current, half.
    The time a pattern sets is the time it takes."""
    from dataclasses import replace

    def milled(pattern, **recipe):
        return _seconds(microscope, [pattern], **recipe) - _PATTERN_SETUP_TIME

    one = milled(_rectangle())
    assert milled(replace(_rectangle(), width=20e-6)) == pytest.approx(2 * one)
    assert milled(replace(_rectangle(), depth=2e-6)) == pytest.approx(2 * one)
    assert milled(_rectangle(), milling_current=15.2e-9) == pytest.approx(one / 2)
    assert milled(replace(_rectangle(), time=30.0)) == pytest.approx(0.1 * 30.0)


def test_many_small_patterns_cost_only_their_setup_more(microscope):
    """Ten rectangles of a tenth the width: the same volume, nine more setups."""
    from dataclasses import replace

    small = [replace(_rectangle(), width=1e-6, centre_x=i * 2e-6) for i in range(10)]
    assert _seconds(microscope, small) == pytest.approx(
        _seconds(microscope, [_rectangle()]) + 9 * _PATTERN_SETUP_TIME
    )


@pytest.mark.parametrize(
    "end_x,end_y,length",
    [(1e-6, 0, 1e-6), (0, 1e-6, 1e-6), (3e-6, 4e-6, 5e-6), (0, 0, 0)],
)
def test_demo_line_timing_uses_the_simulated_cut_width(
    microscope, monkeypatch, end_x, end_y, length
):
    from fibsem.milling import FibsemMillingStage
    from fibsem.milling.patterning.patterns import LinePattern

    monkeypatch.setenv(SIM_MILL_SCALE, "0.1")
    stage = FibsemMillingStage(
        name="Line",
        milling=_recipe(),
        pattern=LinePattern(start_x=0, start_y=0, end_x=end_x, end_y=end_y, depth=1e-6),
    )
    # The simulated cut is 0.5 micrometres wide; length times depth is an area.
    volume = length * 0.5e-6 * 1e-6
    seconds = 0.1 * estimate_volume_time(volume, 7.6e-9) + _PATTERN_SETUP_TIME
    assert _seconds(microscope, stage.pattern.define()) == pytest.approx(seconds)
    planned = microscope.milling.estimate_time(stages=[stage])
    assert planned["seconds"] == pytest.approx(seconds)
    assert planned["stages"][0]["seconds"] == pytest.approx(seconds)

    ticks = []
    microscope.milling.progress.changed.connect(
        lambda p: ticks.append(p) if not p.status.is_terminal else None
    )
    microscope.milling.run()
    timed = [tick for tick in ticks if tick.estimated_time is not None]
    assert timed
    assert all(tick.estimated_time == pytest.approx(seconds) for tick in timed)
    assert microscope.milling.state.get_value() is MillingState.IDLE


def test_the_settings_it_lists_are_the_ones_it_mills_with(microscope):
    settings = microscope.milling.list_options()["settings"]
    properties = settings["ION"]["properties"]
    assert set(properties) == set(microscope.milling.supported_settings())
    # a number the beam lists values for takes any value; the listed ones are examples
    current = properties["milling_current"]
    assert "enum" not in current
    assert current["examples"] == list(microscope.beams[BeamType.ION].current.choices)
    # a string the beam lists is one of them
    files = microscope.milling.supported_settings()["application_file"].choices
    assert properties["application_file"]["enum"] == list(files)
    assert properties["patterning_mode"]["enum"] == ["Serial", "Parallel"]
