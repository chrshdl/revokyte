"""SpeedWidget — m/s to km/h conversion.

The dash claims factory-calibrated accuracy, so the conversion must not
carry a systematic bias.
"""
from dataclasses import dataclass, field

import pytest

from instrument_cluster.ui.widgets.speed_widget import SpeedWidget


@dataclass
class MockFlags:
    car_on_track: bool = True


@dataclass
class MockFrame:
    car_speed: float = 0.0
    flags: MockFlags = field(default_factory=MockFlags)


@dataclass
class MockBus:
    frame: MockFrame = field(default_factory=MockFrame)
    signals: dict = field(default_factory=dict)


@pytest.fixture
def widget():
    return SpeedWidget(rect=(0, 0, 220, 140))


def _displayed(widget, bus, speed_ms):
    bus.frame.car_speed = speed_ms
    widget.update(bus, dt=0.016)
    return widget._last_value_str


@pytest.mark.parametrize(
    "speed_ms, expected",
    [
        (0.0, "0"),
        (27.7778, "100"),      # exactly 100.00 km/h
        (27.7500, "100"),      #  99.90 km/h — rounds up, does not truncate to 99
        (27.7639, "100"),      #  99.95 km/h
        (55.5556, "200"),
        (13.9, "50"),          #  50.04 km/h
    ],
)
def test_speed_is_rounded_not_truncated(widget, speed_ms, expected):
    """Regression: int() biased every reading downward by up to 1 km/h
    (mean -0.5), which is a calibration error rather than a display choice."""
    assert _displayed(widget, MockBus(), speed_ms) == expected


def test_conversion_has_no_systematic_downward_bias(widget):
    """Averaged over a sweep, rounding error must centre on zero."""
    bus = MockBus()
    errors = []
    for i in range(1, 1001):
        speed_ms = i * 0.0777
        shown = int(_displayed(widget, bus, speed_ms))
        errors.append(shown - speed_ms * 3.6)

    mean_error = sum(errors) / len(errors)
    assert abs(mean_error) < 0.05, f"biased by {mean_error:+.3f} km/h"
    assert max(abs(e) for e in errors) <= 0.5 + 1e-9


def test_off_track_reads_zero(widget):
    bus = MockBus()
    bus.frame.flags.car_on_track = False
    assert _displayed(widget, bus, 50.0) == "0"
