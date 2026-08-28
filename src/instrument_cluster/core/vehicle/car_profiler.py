import json

from ...logger import Logger


class CarLibrary:
    def __init__(self, filepath):
        self.logger = Logger(__class__.__name__).get()
        try:
            with open(filepath, "r") as f:
                self.db = json.load(f)
        except FileNotFoundError:
            self.logger.warning("cars.json not found at %s — using default profile.", filepath)
            self.db = {}

    def get_specs(self, car_id):
        car_key = str(car_id)

        if car_key in self.db:
            return self.db[car_key]

        self.logger.debug("Unknown car_id %s — falling back to default profile.", car_id)
        return {
            "name": "Unknown Car",
            "max_power_kw": 300,
            "max_power_rpm": 7000,
            "max_torque_nm": 450,
            "max_torque_rpm": 5000,
            "redline_rpm": 8500,
        }


class CarClassLibrary:
    """What kind of car each id is — the shift-point curve's shape prior.

    ``db/car_classes.json`` (see that directory's NOTICE.md) holds aspiration,
    car type, category and engine layout per GT7 car id. It is a superset of
    cars.json, so a car whose engine peaks only ever arrive on the wire still
    resolves a class.

    An unknown id returns ``None``, which every caller must read as "use the
    default falloff": other games' feeds have no entry here at all, and that
    is not an error.
    """

    def __init__(self, filepath):
        self.logger = Logger(__class__.__name__).get()
        try:
            with open(filepath, "r") as f:
                self.db = json.load(f)
        except FileNotFoundError:
            self.logger.warning(
                "car_classes.json not found at %s — every car falls back to the "
                "default power curve.",
                filepath,
            )
            self.db = {}

    def get_class(self, car_id) -> dict | None:
        return self.db.get(str(car_id))
