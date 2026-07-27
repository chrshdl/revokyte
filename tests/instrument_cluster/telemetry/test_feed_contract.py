"""The feed-authoring contract must not have invisible mandatory fields.

README tells feed authors to populate what the game exposes and "leave the
rest at their defaults". `received_time` defaults to 0.0 and is *not* named
as required — yet DeltaSignal and FuelSignal both gate on it advancing.

Before the reader stamped it, a conforming feed that omitted the field
produced a dashboard where speed, RPM and gear were perfect and the delta
and fuel readouts were silently, permanently dead — with the only log line
misdiagnosing the cause as a flying start.
"""
import json
import queue

from instrument_cluster.signals.fuel_signal import FuelSignal
from instrument_cluster.signals.link_signal import LinkSignal
from instrument_cluster.signals.signal_keys import SignalKey
from instrument_cluster.telemetry.udp_jsonl import UdpJsonlReader

DT = 1 / 60


class _OneShotSocket:
    """Delivers a single packet, then breaks the reader loop."""

    def __init__(self, payload):
        self._q = queue.Queue()
        self._q.put((payload, ("127.0.0.1", 9999)))
        self._q.put(None)

    def recvfrom(self, bufsize):
        item = self._q.get_nowait()
        if item is None:
            raise OSError("closed")
        return item

    def close(self):
        pass


def _frame_from_feed(**fields):
    """Push one received_time-less feed packet through the real reader."""
    payload = json.dumps(fields).encode()
    reader = UdpJsonlReader(host="127.0.0.1", port=5600)
    reader._sock = _OneShotSocket(payload)
    reader._running = True
    reader._run()
    return reader.latest()


def _lap(lap_count, clock_ms, gas):
    return _frame_from_feed(
        car_speed=50.0,
        gas_level=gas,
        gas_capacity=100.0,
        lap_count=lap_count,
        current_lap_time=clock_ms,
        flags={"car_on_track": True},
    )


def test_feed_omitting_received_time_still_produces_fuel_numbers():
    fuel = FuelSignal()
    signals = {SignalKey.TRACK_ID: "t", SignalKey.TRACK_NAME: "T"}

    # Race start (0 -> 1) arms lap 1, then a full lap burning 2.0 units.
    fuel.update(_lap(0, 0, 50.0), signals, DT)
    fuel.update(_lap(1, 0, 50.0), signals, DT)
    fuel.update(_lap(1, 45_000, 49.0), signals, DT)
    out = fuel.update(_lap(2, 0, 48.0), signals, DT)

    assert out[SignalKey.FUEL_PER_LAP] == 2.0
    assert out[SignalKey.FUEL_LAPS_REMAINING] == 24.0


def test_feed_omitting_received_time_reads_as_a_live_link():
    """The same field drives staleness — an unstamped feed used to look
    permanently dead to LinkSignal too."""
    link = LinkSignal()
    out = {}
    for i in range(300):  # 5 s of traffic, well past the 1 s threshold
        out = link.update(_lap(1, i * 16, 50.0), {}, DT)

    assert out[SignalKey.TELEMETRY_STALE] is False


def test_frames_from_successive_packets_are_seen_as_distinct():
    """The freshness comparison is `!=` on received_time, so two packets
    carrying otherwise-identical telemetry must still differ."""
    first = _lap(1, 1000, 50.0)
    second = _lap(1, 1000, 50.0)
    assert first.received_time != second.received_time
