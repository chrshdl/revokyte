from enum import StrEnum


class TelemetryMode(StrEnum):
    DEMO = "demo"
    UDP = "udp"


class DiffReferenceMode(StrEnum):
    PREVIOUS = "previous"
    FASTEST = "fastest"
