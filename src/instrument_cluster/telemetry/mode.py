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

    @property
    def label(self) -> str:
        """Display name for this mode.

        One source for both places the driver reads it — Setup's Reference
        Lap dropdown and the delta gauge's header — so the two can't drift
        into naming the same setting differently (the dash once said
        "[Best]" for what Setup called "fastest"). Derived from the value,
        so a new mode is named consistently by construction.
        """
        return self.value.replace("_", " ").title()
