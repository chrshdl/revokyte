import json
from unittest.mock import MagicMock

import pytest

from instrument_cluster.signals.signal_keys import SignalKey
from instrument_cluster.signals.track_signal import _NO_TRACK_TEXT, TrackSignal
from instrument_cluster.telemetry.models import TelemetryFrame


def _frame(x=0.0, y=0.0, z=0.0, on_track=True, loading=False, lap=None):
    f = MagicMock(spec=TelemetryFrame)
    f.flags = MagicMock()
    f.flags.car_on_track = on_track
    f.flags.loading_or_processing = loading
    f.position = MagicMock()
    f.position.x = x
    f.position.y = y
    f.position.z = z
    f.lap_count = lap
    return f


# Gates run perpendicular to the direction of travel (as in the real DB):
# a vertical line at x=100 crossed moving +x, one at x=500 likewise.
@pytest.fixture
def track_db(tmp_path):
    data = {
        "1": {
            "name": "Nurburgring",
            "gate": {"p1": {"x": 100.0, "z": -10.0}, "p2": {"x": 100.0, "z": 10.0}, "direction": "PX"},
            "bounds": {"min_x": 0.0, "max_x": 600.0, "min_z": -50.0, "max_z": 50.0},
        },
        "2": {
            "name": "Spa",
            "gate": {"p1": {"x": 500.0, "z": 190.0}, "p2": {"x": 500.0, "z": 210.0}, "direction": "PX"},
            "bounds": {"min_x": 400.0, "max_x": 600.0, "min_z": 150.0, "max_z": 250.0},
        },
    }
    path = tmp_path / "tracks.json"
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def signal(track_db):
    ts = TrackSignal(db_path=track_db)
    yield ts
    ts.stop()


def _cross_gate(ts, lap=None):
    """Drive through the fixture's Nurburgring gate (x=100) moving +x."""
    ts.update(_frame(x=90.0, z=0.0, lap=lap), {})
    return ts.update(_frame(x=101.0, z=0.0, lap=lap), {})


# --- No match / prompt ---


def test_prompts_to_set_when_far_from_all_tracks(signal):
    result = signal.update(_frame(x=9000.0, y=0.0, z=9000.0), {})
    assert result[SignalKey.TRACK_ID] is None
    assert result[SignalKey.TRACK_NAME] == _NO_TRACK_TEXT


def test_zero_position_prompts_to_set(signal):
    result = signal.update(_frame(x=0.0, y=0.0, z=0.0), {})
    assert result[SignalKey.TRACK_ID] is None
    assert result[SignalKey.TRACK_NAME] == _NO_TRACK_TEXT


def test_none_frame_publishes_current_lock(signal):
    assert _cross_gate(signal)[SignalKey.TRACK_ID] == "1"
    result = signal.update(None, {})
    assert result[SignalKey.TRACK_ID] == "1"
    assert result[SignalKey.TRACK_NAME] == "Nurburgring"


# --- Identification from a start/finish-line crossing ---


def test_identifies_on_gate_crossing_without_lap_data(signal):
    # Without lap telemetry a crossing anchors on its own: driving through
    # the (unique) gate identifies the track immediately.
    result = _cross_gate(signal)
    assert result[SignalKey.TRACK_ID] == "1"
    assert result[SignalKey.TRACK_NAME] == "Nurburgring"


def test_identifies_on_gate_crossing_with_lap_tick(signal):
    signal.update(_frame(x=90.0, z=0.0, lap=1), {})
    result = signal.update(_frame(x=101.0, z=0.0, lap=2), {})
    assert result[SignalKey.TRACK_ID] == "1"


def test_no_match_when_sitting_on_the_line_without_moving(signal):
    # A single frame on the gate produces no path segment, hence no crossing.
    result = signal.update(_frame(x=100.0, z=0.0), {})
    assert result[SignalKey.TRACK_ID] is None
    assert result[SignalKey.TRACK_NAME] == _NO_TRACK_TEXT


def test_no_match_when_passing_beside_the_gate(signal):
    # Path parallel to travel but 25 m beyond the gate's (padded) end: near
    # the line, but never across it.
    signal.update(_frame(x=90.0, z=25.0), {})
    result = signal.update(_frame(x=101.0, z=25.0), {})
    assert result[SignalKey.TRACK_ID] is None
    assert result[SignalKey.TRACK_NAME] == _NO_TRACK_TEXT


def test_no_match_when_stopping_short_of_the_line(signal):
    signal.update(_frame(x=90.0, z=0.0), {})
    result = signal.update(_frame(x=99.0, z=0.0), {})
    assert result[SignalKey.TRACK_ID] is None


def test_no_match_outside_bounds(signal):
    result = signal.update(_frame(x=5000.0, y=0.0, z=5000.0), {})
    assert result[SignalKey.TRACK_ID] is None


def test_teleport_across_gate_is_ignored(signal):
    # A reset-to-track / replay jump whose segment happens to span the gate
    # must not count as a crossing.
    signal.update(_frame(x=-500.0, z=0.0), {})
    result = signal.update(_frame(x=101.0, z=0.0), {})
    assert result[SignalKey.TRACK_ID] is None


def test_lock_holds_when_car_moves_away(signal):
    assert _cross_gate(signal)[SignalKey.TRACK_ID] == "1"
    result = signal.update(_frame(x=100.0, y=0.0, z=900.0), {})
    assert result[SignalKey.TRACK_ID] == "1"


# --- Crossing direction disambiguates forward/reverse pairs ---


@pytest.fixture
def direction_db(tmp_path):
    data = {
        "1": {
            "name": "Circuit A",
            "gate": {"p1": {"x": 100.0, "z": -10.0}, "p2": {"x": 100.0, "z": 10.0}, "direction": "PX"},
            "bounds": {"min_x": 0.0, "max_x": 600.0, "min_z": -50.0, "max_z": 50.0},
        },
        "2": {
            "name": "Circuit A Reverse",
            "gate": {"p1": {"x": 100.0, "z": 10.0}, "p2": {"x": 100.0, "z": -10.0}, "direction": "NX"},
            "bounds": {"min_x": 0.0, "max_x": 600.0, "min_z": -50.0, "max_z": 50.0},
        },
    }
    path = tmp_path / "tracks.json"
    path.write_text(json.dumps(data))
    return path


def test_direction_disambiguates_forward_crossing(direction_db):
    ts = TrackSignal(db_path=direction_db)
    try:
        ts.update(_frame(x=90.0, z=0.0), {})
        result = ts.update(_frame(x=101.0, z=0.0), {})
        assert result[SignalKey.TRACK_ID] == "1"
        assert result[SignalKey.TRACK_NAME] == "Circuit A"
    finally:
        ts.stop()


def test_direction_disambiguates_reverse_crossing(direction_db):
    ts = TrackSignal(db_path=direction_db)
    try:
        ts.update(_frame(x=110.0, z=0.0), {})
        result = ts.update(_frame(x=99.0, z=0.0), {})
        assert result[SignalKey.TRACK_ID] == "2"
        assert result[SignalKey.TRACK_NAME] == "Circuit A Reverse"
    finally:
        ts.stop()


# --- Lap-tick anchoring: only the true line identifies ---


@pytest.fixture
def shared_tarmac_db(tmp_path):
    # Track B's start/finish line lies on tarmac that track A's lap also
    # drives across (the Nurburgring situation: a 24h lap crosses the
    # Nordschleife layout's and Tourist layout's lines mid-lap).
    data = {
        "A": {
            "name": "Combined Layout",
            "gate": {"p1": {"x": 100.0, "z": -10.0}, "p2": {"x": 100.0, "z": 10.0}, "direction": "PX"},
            "bounds": {"min_x": 0.0, "max_x": 600.0, "min_z": -50.0, "max_z": 50.0},
        },
        "B": {
            "name": "Inner Layout",
            "gate": {"p1": {"x": 400.0, "z": -10.0}, "p2": {"x": 400.0, "z": 10.0}, "direction": "PX"},
            "bounds": {"min_x": 300.0, "max_x": 600.0, "min_z": -50.0, "max_z": 50.0},
        },
    }
    path = tmp_path / "tracks.json"
    path.write_text(json.dumps(data))
    return path


def test_crossing_without_lap_tick_does_not_identify(shared_tarmac_db):
    ts = TrackSignal(db_path=shared_tarmac_db)
    try:
        # Mid-lap on the combined layout, driving across the inner layout's
        # line: the lap counter does not tick, so this is not our line.
        ts.update(_frame(x=390.0, z=0.0, lap=3), {})
        result = ts.update(_frame(x=401.0, z=0.0, lap=3), {})
        assert result[SignalKey.TRACK_ID] is None
        assert result[SignalKey.TRACK_NAME] == _NO_TRACK_TEXT

        # Reaching the true line, the lap counter ticks: identified.
        ts.update(_frame(x=90.0, z=0.0, lap=3), {})
        result = ts.update(_frame(x=101.0, z=0.0, lap=4), {})
        assert result[SignalKey.TRACK_ID] == "A"
        assert result[SignalKey.TRACK_NAME] == "Combined Layout"
    finally:
        ts.stop()


def test_race_start_grid_tick_then_line_crossing(signal):
    # Standing/flying start: the counter ticks 0 -> 1 at the green light
    # with the car still behind the line (no gate there). That tick must
    # not identify anything; the line crossing that ticks 1 -> 2 does.
    signal.update(_frame(x=50.0, z=0.0, lap=0), {})
    r = signal.update(_frame(x=52.0, z=0.0, lap=1), {})
    assert r[SignalKey.TRACK_ID] is None
    signal.update(_frame(x=90.0, z=0.0, lap=1), {})
    result = signal.update(_frame(x=101.0, z=0.0, lap=2), {})
    assert result[SignalKey.TRACK_ID] == "1"


# --- Gate-sharing siblings: defer, never flip ---


@pytest.fixture
def sibling_db(tmp_path):
    # A short sub-layout nested inside a full circuit, sharing the same
    # start/finish gate and crossing direction (the Brands Hatch GP/Indy
    # shape): indistinguishable at the line itself.
    data = {
        "short": {
            "name": "Short Layout",
            "gate": {"p1": {"x": 100.0, "z": -10.0}, "p2": {"x": 100.0, "z": 10.0}, "direction": "PX"},
            "bounds": {"min_x": 50.0, "max_x": 150.0, "min_z": -50.0, "max_z": 50.0},
        },
        "long": {
            "name": "Long Layout",
            "gate": {"p1": {"x": 100.0, "z": -10.0}, "p2": {"x": 100.0, "z": 10.0}, "direction": "PX"},
            "bounds": {"min_x": 0.0, "max_x": 600.0, "min_z": -100.0, "max_z": 100.0},
        },
    }
    path = tmp_path / "tracks.json"
    path.write_text(json.dumps(data))
    return path


def test_ambiguous_crossing_publishes_placeholder_not_a_guess(sibling_db):
    ts = TrackSignal(db_path=sibling_db)
    try:
        result = _cross_gate(ts)
        assert result[SignalKey.TRACK_ID] is None
        assert result[SignalKey.TRACK_NAME] == _NO_TRACK_TEXT
    finally:
        ts.stop()


def test_escape_identifies_larger_sibling_mid_lap(sibling_db):
    ts = TrackSignal(db_path=sibling_db)
    try:
        assert _cross_gate(ts)[SignalKey.TRACK_ID] is None
        # Well outside the short layout's box (beyond the escape margin),
        # still inside the long one: only the long layout remains.
        result = ts.update(_frame(x=300.0, z=0.0), {})
        assert result[SignalKey.TRACK_ID] == "long"
        assert result[SignalKey.TRACK_NAME] == "Long Layout"
        # Final: returning onto the shared straight must not revisit it.
        result = ts.update(_frame(x=100.0, z=30.0), {})
        assert result[SignalKey.TRACK_ID] == "long"
    finally:
        ts.stop()


def test_full_lap_identifies_smaller_sibling_without_lap_data(sibling_db):
    ts = TrackSignal(db_path=sibling_db)
    try:
        assert _cross_gate(ts)[SignalKey.TRACK_ID] is None
        # A lap that never leaves the short layout's box...
        for x, z in [(140.0, 30.0), (60.0, -30.0), (90.0, 0.0)]:
            r = ts.update(_frame(x=x, z=z), {})
            assert r[SignalKey.TRACK_ID] is None
        # ... closed by re-crossing the line: the observed lap's box fits the
        # short layout, not the long one.
        result = ts.update(_frame(x=101.0, z=0.0), {})
        assert result[SignalKey.TRACK_ID] == "short"
        assert result[SignalKey.TRACK_NAME] == "Short Layout"
    finally:
        ts.stop()


def test_full_lap_identifies_smaller_sibling_with_lap_ticks(sibling_db):
    ts = TrackSignal(db_path=sibling_db)
    try:
        ts.update(_frame(x=90.0, z=0.0, lap=1), {})
        assert ts.update(_frame(x=101.0, z=0.0, lap=2), {})[SignalKey.TRACK_ID] is None
        for x, z in [(140.0, 30.0), (60.0, -30.0), (90.0, 0.0)]:
            assert ts.update(_frame(x=x, z=z, lap=2), {})[SignalKey.TRACK_ID] is None
        result = ts.update(_frame(x=101.0, z=0.0, lap=3), {})
        assert result[SignalKey.TRACK_ID] == "short"
    finally:
        ts.stop()


def test_session_restart_discards_pending_evidence(sibling_db):
    ts = TrackSignal(db_path=sibling_db)
    try:
        ts.update(_frame(x=90.0, z=0.0, lap=1), {})
        assert ts.update(_frame(x=101.0, z=0.0, lap=2), {})[SignalKey.TRACK_ID] is None
        # Lap counter going backwards = race restart: the pending hypothesis
        # is stale (the car teleports to the grid).
        ts.update(_frame(x=120.0, z=20.0, lap=1), {})
        result = ts.update(_frame(x=300.0, z=0.0, lap=1), {})
        assert result[SignalKey.TRACK_ID] is None
        assert result[SignalKey.TRACK_NAME] == _NO_TRACK_TEXT
    finally:
        ts.stop()


# --- Loading/processing ---


def test_loading_flag_clears_identified_track(signal):
    assert _cross_gate(signal)[SignalKey.TRACK_ID] == "1"

    # A track/replay load clears the identified track so laps on a newly
    # loaded circuit are re-identified from scratch, instead of being
    # attributed to the previous track.
    result = signal.update(_frame(loading=True), {})
    assert signal._current_track_id is None
    assert result[SignalKey.TRACK_ID] is None
    assert result[SignalKey.TRACK_NAME] == _NO_TRACK_TEXT


# --- Brands Hatch regression (real database) ---
#
# GP (119) and Indy (346) share one gate and crossing direction, so the line
# itself cannot tell them apart. The classifier must not guess: placeholder
# until the lap decides, and the first name published is final.


def test_brands_hatch_gp_never_shows_indy(track_db):
    ts = TrackSignal()  # bundled DB
    try:
        ts.update(_frame(x=-160.0, z=-403.0), {})
        crossing = ts.update(_frame(x=-140.0, z=-403.0), {})
        assert crossing[SignalKey.TRACK_ID] is None
        assert crossing[SignalKey.TRACK_NAME] == _NO_TRACK_TEXT
        # Heading into the GP loop, far beyond the Indy circuit's extent
        # (Indy's box ends at z of about -58): locks GP, and only GP was
        # ever displayed.
        result = ts.update(_frame(x=150.0, z=200.0), {})
        assert result[SignalKey.TRACK_ID] == "119"
        assert result[SignalKey.TRACK_NAME] == "Brands Hatch Grand Prix Circuit"
    finally:
        ts.stop()


def test_brands_hatch_indy_identified_after_full_lap(track_db):
    ts = TrackSignal()  # bundled DB
    try:
        ts.update(_frame(x=-160.0, z=-403.0), {})
        assert ts.update(_frame(x=-140.0, z=-403.0), {})[SignalKey.TRACK_ID] is None
        # A lap that stays within the Indy circuit's extent.
        for x, z in [(-300.0, -350.0), (-100.0, -150.0), (50.0, -300.0), (-160.0, -403.0)]:
            r = ts.update(_frame(x=x, z=z), {})
            assert r[SignalKey.TRACK_ID] is None
        # Closing the lap at the shared line: the observed box fits Indy.
        result = ts.update(_frame(x=-140.0, z=-403.0), {})
        assert result[SignalKey.TRACK_ID] == "346"
        assert result[SignalKey.TRACK_NAME] == "Brands Hatch Indy Circuit"
    finally:
        ts.stop()


# --- Loading the bundled database ---


def test_missing_db_file_yields_empty_db(tmp_path):
    ts = TrackSignal(db_path=tmp_path / "does-not-exist.json")
    try:
        assert ts._db == {}
        ts.update(_frame(x=90.0, z=0.0), {})
        result = ts.update(_frame(x=101.0, z=0.0), {})
        assert result[SignalKey.TRACK_ID] is None
    finally:
        ts.stop()


def test_native_track_name_is_published_without_geometry(signal):
    # A source-provided track name is published verbatim even though the
    # position matches no gate in the DB — the geometry path is skipped.
    frame = TelemetryFrame(track_name="Spa-Francorchamps")
    result = signal.update(frame, {})
    assert result[SignalKey.TRACK_ID] == "Spa-Francorchamps"
    assert result[SignalKey.TRACK_NAME] == "Spa-Francorchamps"


def test_absent_native_track_name_uses_geometry(signal):
    # Without a native name, the placeholder shows until a gate is identified.
    result = signal.update(_frame(x=0.0, z=0.0), {})
    assert result[SignalKey.TRACK_NAME] == _NO_TRACK_TEXT


def test_bundled_db_loads_and_is_well_formed():
    ts = TrackSignal()
    try:
        assert len(ts._db) > 50
        for track_id, data in ts._db.items():
            assert "name" in data
            assert "gate" in data
            assert "bounds" in data
            for key in ("p1", "p2", "direction"):
                assert key in data["gate"]
            for key in ("min_x", "max_x", "min_z", "max_z"):
                assert key in data["bounds"]
    finally:
        ts.stop()
