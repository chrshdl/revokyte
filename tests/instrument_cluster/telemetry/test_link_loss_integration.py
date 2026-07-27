"""Link loss over a real socket: reader + LinkSignal together.

The unit tests cover each half (udp_jsonl stamps received_time,
link_signal ages it). This covers the seam over an actual UDP socket —
a reader that stamped a constant, or failed to stamp at all, would look
perfectly healthy to every unit test and still leave a dead dash claiming
to be live.
"""
import json
import socket
import time

import pytest

from instrument_cluster.signals.link_signal import LinkSignal
from instrument_cluster.signals.signal_keys import SignalKey
from instrument_cluster.telemetry.udp_jsonl import UdpJsonlReader

DT = 1 / 60


@pytest.fixture
def link_over_udp():
    """A started reader on an ephemeral port, plus a sender aimed at it."""
    reader = UdpJsonlReader(host="127.0.0.1", port=0)
    reader.start()
    port = reader._sock.getsockname()[1]
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.bind(("127.0.0.1", 0))  # source must match the bound host
    try:
        yield reader, sender, port
    finally:
        sender.close()
        reader.stop()


def _send(sender, port, speed):
    # No received_time: a feed is not required to provide one.
    payload = json.dumps(
        {"car_speed": speed, "lap_count": 2, "flags": {"car_on_track": True}}
    ).encode()
    sender.sendto(payload, ("127.0.0.1", port))


def _await_frame(reader, previous_stamp, timeout=2.0):
    """Block until the reader publishes a frame newer than previous_stamp."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = reader.latest()
        if frame.received_time != previous_stamp:
            return frame
        time.sleep(0.005)
    pytest.fail("no telemetry frame arrived within the timeout")


def _pump(link, reader, seconds):
    """Drive LinkSignal for `seconds` off whatever the reader currently holds."""
    out = {}
    for _ in range(int(seconds / DT)):
        out = link.update(reader.latest(), {}, DT)
    return out


def test_live_feed_reads_as_live(link_over_udp):
    reader, sender, port = link_over_udp
    link = LinkSignal()

    stamp = reader.latest().received_time
    for speed in (10.0, 20.0, 30.0):
        _send(sender, port, speed)
        frame = _await_frame(reader, stamp)
        stamp = frame.received_time
        out = link.update(frame, {}, DT)

    assert out[SignalKey.TELEMETRY_STALE] is False
    assert reader.latest().car_speed == 30.0


def test_a_silent_feed_goes_stale(link_over_udp):
    """The reader keeps handing back its last frame forever; that must stop
    reading as live once the link has been quiet past the threshold."""
    reader, sender, port = link_over_udp
    link = LinkSignal()

    _send(sender, port, 88.0)
    frame = _await_frame(reader, reader.latest().received_time)
    assert link.update(frame, {}, DT)[SignalKey.TELEMETRY_STALE] is False

    # Nothing more is sent — the socket goes quiet, as a crashed feed would.
    out = _pump(link, reader, seconds=1.5)

    assert out[SignalKey.TELEMETRY_STALE] is True
    assert reader.latest().car_speed == 88.0, "the stale value is still held"


def test_the_link_recovers_when_the_feed_returns(link_over_udp):
    reader, sender, port = link_over_udp
    link = LinkSignal()

    _send(sender, port, 50.0)
    stamp = _await_frame(reader, reader.latest().received_time).received_time
    assert _pump(link, reader, seconds=1.5)[SignalKey.TELEMETRY_STALE] is True

    _send(sender, port, 51.0)
    frame = _await_frame(reader, stamp)
    out = link.update(frame, {}, DT)

    assert out[SignalKey.TELEMETRY_STALE] is False
    assert out[SignalKey.TELEMETRY_AGE_S] == pytest.approx(0.0)
