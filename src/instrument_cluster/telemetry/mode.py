from enum import StrEnum


class TelemetryMode(StrEnum):
    DEMO = "demo"
    UDP = "udp"
    # Desktop only: read the console in-process (no proxy program installed).
    # The reader comes from the selected FeedDescriptor's direct_reader.
    DIRECT = "direct"


class DiffReferenceMode(StrEnum):
    PREVIOUS = "previous"
    FASTEST = "fastest"
