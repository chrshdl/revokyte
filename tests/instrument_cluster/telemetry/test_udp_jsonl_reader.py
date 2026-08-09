"""
Tests for UdpJsonlReader — source-IP filtering (M-3) and timeout-based
idle behaviour (M-4).

We test _run() logic directly by injecting a fake socket so no real network
ports are opened.
"""

import json
import queue
import socket
import threading
from unittest.mock import MagicMock, patch

import pytest

from instrument_cluster.telemetry.udp_jsonl import UdpJsonlReader
from instrument_cluster.telemetry.models import TelemetryFrame


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_frame_bytes(speed: float = 42.0) -> bytes:
    # Only include fields that pass model_validate without triggering
    # strict-type failures (e.g. gear_ratios: List[float] = None).
    return json.dumps({"car_speed": speed}).encode()


class FakeSocket:
    """
    Drives _run() via a pre-loaded packet queue.

    Packets are tuples of (data, addr).  A None sentinel triggers OSError
    to break the loop cleanly.  An empty queue raises TimeoutError (simulating
    the 1-second socket timeout).
    """

    def __init__(self, packets):
        # packets: list of (bytes, (host, port)) | None
        self._q = queue.Queue()
        for p in packets:
            self._q.put(p)

    def recvfrom(self, bufsize):
        try:
            item = self._q.get_nowait()
        except queue.Empty:
            raise TimeoutError
        if item is None:
            raise OSError("closed")
        return item

    # stubs so _run() doesn't fail on attribute access
    def close(self):
        pass


# ---------------------------------------------------------------------------
# M-4: timeout replaces busy-poll
# ---------------------------------------------------------------------------

class TestTimeoutIdle:
    def test_timeout_does_not_crash_loop(self):
        """TimeoutError must cause the loop to continue, not exit."""
        reader = UdpJsonlReader(host="127.0.0.1", port=5600)
        frame_data = _minimal_frame_bytes(speed=99.0)

        # First call: TimeoutError (idle tick); second call: valid frame; third: OSError to stop
        fake = FakeSocket([None.__class__] * 0)  # will use custom sequence below
        calls = [
            TimeoutError,
            (frame_data, ("127.0.0.1", 9999)),
            None,  # OSError sentinel
        ]
        call_iter = iter(calls)

        def recvfrom(bufsize):
            item = next(call_iter)
            if item is TimeoutError:
                raise TimeoutError
            if item is None:
                raise OSError("closed")
            return item

        mock_sock = MagicMock()
        mock_sock.recvfrom.side_effect = recvfrom

        reader._sock = mock_sock
        reader._running = True
        reader._run()

        assert reader._latest.car_speed == 99.0


# ---------------------------------------------------------------------------
# M-3: source IP filtering
# ---------------------------------------------------------------------------

class TestSourceFiltering:
    def _run_with_packets(self, bind_host, packets):
        """Run _run() synchronously with a FakeSocket and return the reader."""
        reader = UdpJsonlReader(host=bind_host, port=5600)
        reader._sock = FakeSocket(packets)
        reader._running = True
        reader._run()
        return reader

    def test_packet_from_expected_host_is_accepted(self):
        frame_data = _minimal_frame_bytes(speed=55.0)
        packets = [
            (frame_data, ("127.0.0.1", 9999)),
            None,
        ]
        reader = self._run_with_packets("127.0.0.1", packets)
        assert reader._latest.car_speed == 55.0

    def test_packet_from_unexpected_host_is_discarded(self):
        """A packet from a different host must not update _latest."""
        frame_data = _minimal_frame_bytes(speed=88.0)
        packets = [
            (frame_data, ("10.0.0.99", 9999)),  # wrong source
            None,
        ]
        reader = self._run_with_packets("127.0.0.1", packets)
        # _latest should remain the default empty TelemetryFrame
        assert reader._latest.car_speed == 0.0

    def test_wildcard_bind_accepts_any_source(self):
        """Binding to 0.0.0.0 disables source filtering."""
        frame_data = _minimal_frame_bytes(speed=77.0)
        packets = [
            (frame_data, ("192.168.1.50", 9999)),  # arbitrary source
            None,
        ]
        reader = self._run_with_packets("0.0.0.0", packets)
        assert reader._latest.car_speed == 77.0

    def test_received_time_is_stamped_when_the_feed_omits_it(self):
        """The receiver owns received_time, not the feed.

        Regression: it defaults to 0.0 in the schema, and the README tells
        feed authors to leave unknown fields at their defaults. A feed that
        never set it produced frames whose freshness clock never advanced,
        which silently killed the delta and fuel signals forever while
        speed and RPM looked perfect.
        """
        packets = [
            (_minimal_frame_bytes(speed=55.0), ("127.0.0.1", 9999)),
            None,
        ]
        reader = self._run_with_packets("127.0.0.1", packets)
        assert reader._latest.received_time > 0.0

    def test_received_time_from_the_feed_is_overridden(self):
        """A feed sending a constant (or nonsense) stamp must not be able to
        freeze the freshness clock."""
        data = json.dumps({"car_speed": 12.0, "received_time": 999.0}).encode()
        reader = self._run_with_packets(
            "127.0.0.1", [(data, ("127.0.0.1", 9999)), None]
        )
        assert reader._latest.received_time != 999.0

    def test_consecutive_packets_get_distinct_stamps(self):
        """Freshness detection needs the value to actually change per packet."""
        stamps = []
        reader = UdpJsonlReader(host="127.0.0.1", port=5600)
        for speed in (10.0, 20.0):
            reader._sock = FakeSocket(
                [(_minimal_frame_bytes(speed=speed), ("127.0.0.1", 9999)), None]
            )
            reader._running = True
            reader._run()
            stamps.append(reader._latest.received_time)

        assert stamps[0] != stamps[1]
        assert stamps[1] > stamps[0], "monotonic clock"

    def test_non_dict_payload_is_counted_as_a_dropped_packet(self):
        """Stamping must not turn malformed JSON into a crash."""
        reader = self._run_with_packets(
            "127.0.0.1", [(b"[1, 2, 3]", ("127.0.0.1", 9999)), None]
        )
        assert reader._dropped == 1
        assert reader._latest.car_speed == 0.0

    def test_multiple_packets_only_accepted_from_correct_host(self):
        """Mixed traffic: only frames from the bound host update state."""
        good = _minimal_frame_bytes(speed=33.0)
        bad = _minimal_frame_bytes(speed=99.0)
        packets = [
            (bad, ("10.0.0.1", 9999)),   # wrong — should be ignored
            (good, ("127.0.0.1", 9999)), # correct
            None,
        ]
        reader = self._run_with_packets("127.0.0.1", packets)
        assert reader._latest.car_speed == 33.0


# ---------------------------------------------------------------------------
# Protocol version marker (PROTOCOL.md §3.2)
# ---------------------------------------------------------------------------

class TestProtocolVersion:
    """Absent or 1 → normal; higher → log once, keep parsing, never crash.

    Version skew is the normal operating condition: the reader ships in OS
    images while feeds ship independently, so a feed speaking a newer
    protocol than the image must degrade to best-effort, not to a dead dash.
    """

    def _run_with_packets(self, packets):
        reader = UdpJsonlReader(host="127.0.0.1", port=5600)
        reader._sock = FakeSocket(packets)
        reader._running = True
        reader._run()
        return reader

    def _frame(self, **fields) -> bytes:
        return json.dumps(fields).encode()

    def test_v1_and_absent_v_parse_silently(self):
        reader = self._run_with_packets([
            (self._frame(car_speed=10.0), ("127.0.0.1", 1)),
            (self._frame(car_speed=20.0, v=1), ("127.0.0.1", 1)),
            None,
        ])
        assert reader._latest.car_speed == 20.0
        assert reader._newer_protocol_logged is False

    def test_higher_v_parses_best_effort_and_logs_once(self):
        reader = UdpJsonlReader(host="127.0.0.1", port=5600)
        with patch.object(reader, "logger") as logger:
            reader._sock = FakeSocket([
                (self._frame(car_speed=42.0, v=2), ("127.0.0.1", 1)),
                (self._frame(car_speed=43.0, v=2), ("127.0.0.1", 1)),
                None,
            ])
            reader._running = True
            reader._run()
        # Frames still land — a newer feed keeps driving the gauges.
        assert reader._latest.car_speed == 43.0
        assert reader._dropped == 0
        # ...and the skew is reported exactly once, not per frame.
        assert logger.warning.call_count == 1
        assert "v2" in logger.warning.call_args[0][0]

    def test_nonsense_v_never_crashes_the_reader(self):
        """`v` is wire input like everything else: garbage must not kill
        parsing of the frame it rides in (strings/bools are not versions)."""
        reader = self._run_with_packets([
            (self._frame(car_speed=7.0, v="two"), ("127.0.0.1", 1)),
            (self._frame(car_speed=8.0, v=True), ("127.0.0.1", 1)),
            None,
        ])
        assert reader._latest.car_speed == 8.0
        assert reader._newer_protocol_logged is False
