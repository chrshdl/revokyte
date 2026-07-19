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
