"""Guards on db/car_classes.json — a generated table nothing else validates.

It is rebuilt by tools/fetch_car_classes.py from an upstream repository, so
what these pin is the contract the shift-point curve reads it through, not
the data itself: every car the local database knows must resolve a class,
and every value must be one the resolver actually recognises. A silently
renamed upstream field would otherwise land every car on the default curve
with nothing failing.
"""

import json
from pathlib import Path

from instrument_cluster.core.vehicle.car_profiler import CarClassLibrary
from instrument_cluster.core.vehicle.ecu import power_droop_for

_DB = Path(__file__).resolve().parents[4] / "src/instrument_cluster/db"
_CARS = json.loads((_DB / "cars.json").read_text())
_CLASSES = json.loads((_DB / "car_classes.json").read_text())

# Everything the resolver in ecu.py branches on. A value outside these sets
# is not wrong data — it is a car falling through to the default curve.
_ASPIRATIONS = {"NA", "TC", "SC", "TC+SC", "EV"}
_CAR_TYPES = {"street", "tuned", "race"}


def test_every_known_car_has_a_class():
    missing = sorted(set(_CARS) - set(_CLASSES), key=int)
    assert not missing, f"cars.json ids absent from car_classes.json: {missing}"


def test_the_class_table_covers_more_than_the_spec_table():
    """The wire path supplies its own peaks, so a car can reach the curve
    without ever appearing in cars.json. The class table is a superset for
    exactly that reason."""
    assert len(_CLASSES) >= len(_CARS)


def test_every_entry_carries_the_fields_the_curve_reads():
    for car_id, entry in _CLASSES.items():
        assert set(entry) == {
            "aspiration",
            "car_type",
            "category",
            "engine_layout",
        }, car_id


def test_the_values_are_ones_the_resolver_knows():
    """Upstream is free to add a value; this is what makes that visible
    instead of quietly widening the default-curve bucket."""
    unknown_aspiration = {
        e["aspiration"] for e in _CLASSES.values() if e["aspiration"]
    } - _ASPIRATIONS
    unknown_type = {
        e["car_type"] for e in _CLASSES.values() if e["car_type"]
    } - _CAR_TYPES
    assert not unknown_aspiration, unknown_aspiration
    assert not unknown_type, unknown_type


def test_the_library_resolves_a_known_turbo_road_car():
    """Car 1461 (Silvia K's (S13) '90) is the regression: a turbocharged
    road car read as a flat-power engine, whose ladder finished long after
    GT7's own shift flash."""
    library = CarClassLibrary(filepath=_DB / "car_classes.json")

    entry = library.get_class(1461)
    assert entry["aspiration"] == "TC"
    assert entry["car_type"] == "street"
    # Its falloff is measured (11 pulls, droop 0.08-0.10) rather than
    # assumed; what this pins is that the lookup reaches it at all.
    assert power_droop_for(entry["aspiration"], entry["car_type"]) < 0.2

    assert library.get_class(999999) is None


def test_a_missing_table_degrades_to_the_default_curve():
    """Bundled data can go missing on a half-finished deployment; that must
    cost curve accuracy, not the shift lights."""
    library = CarClassLibrary(filepath=_DB / "does-not-exist.json")
    assert library.get_class(1461) is None
