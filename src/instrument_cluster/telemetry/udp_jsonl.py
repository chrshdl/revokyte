import json
import select
import socket
import threading
import time
from bisect import bisect_right
from pathlib import Path
from typing import Tuple

from ..logger import Logger
from ..telemetry.models import TelemetryFrame


class UdpJsonlReader:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5600,
        bufsize: int = 4096,
    ):
        self.logger = Logger(__class__.__name__).get()
        self.addr: Tuple[str, int] = (host, port)
        self.bufsize = bufsize
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        # Shutdown wakeup: stop() writes a byte here so the reader thread
        # leaves select() at once instead of waiting out a socket timeout.
        self._wake_r: socket.socket | None = None
        self._wake_w: socket.socket | None = None
        self._running = False
        self._latest: TelemetryFrame = TelemetryFrame()
        self._dropped = 0
        self._last_drop_log = 0.0
        self._newer_protocol_logged = False

    def start(self) -> None:
        """Start listening for telemetry frames on the configured UDP socket."""
        if self._running:
            return
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # receive-only on configured address
        self._sock.bind(self.addr)
        # No socket timeout: the loop blocks in select() until either a frame
        # arrives or stop() nudges the wake pair, so it costs zero wakeups
        # while idle AND shuts down immediately. It previously polled with
        # settimeout(1.0), which meant stop() had to wait out the current
        # recvfrom - up to a full second of the caller's thread. That caller
        # is the UI thread (back button -> on_resume -> sync_mode ->
        # switch_mode -> stop), so leaving Gran Turismo 7 for demo dropped
        # the dashboard to 10-20 fps for a frame-second, at 3-6% CPU because
        # it was blocked rather than busy.
        self._wake_r, self._wake_w = socket.socketpair()
        self._wake_r.setblocking(False)
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """Internal thread loop that receives and parses UDP frames."""
        # Capture a local reference so stop() setting self._sock = None cannot
        # cause AttributeError mid-iteration on a NoneType.
        sock = self._sock
        assert sock is not None
        # When bound to a specific host (not wildcard), only accept frames
        # from that address to reject injection from other LAN hosts.
        bound_host = self.addr[0]
        check_source = bound_host not in ("0.0.0.0", "")
        # Present only when the reader was brought up through start(). Unit
        # tests inject a fake socket and call _run() directly; without a wake
        # pair the loop falls back to a plain blocking read, which is exactly
        # the contract those fakes implement (recvfrom raising TimeoutError).
        wake = self._wake_r

        while self._running:
            if wake is not None:
                try:
                    ready, _, _ = select.select([sock, wake], [], [])
                except OSError:
                    break
                if wake in ready:
                    break
            try:
                data, addr = sock.recvfrom(self.bufsize)
            except TimeoutError:
                continue
            except OSError:
                break
            if check_source and addr[0] != bound_host:
                continue
            try:
                obj = json.loads(data.decode("utf-8"))
                # Protocol version marker (PROTOCOL.md §3.2): absent or 1 is
                # this build's dialect. A higher version is noted once and
                # then parsed best-effort under v1 rules — the tolerant-reader
                # contract (unknown fields ignored, invalid frames dropped)
                # is exactly what makes that safe, and a newer feed must
                # never take the dash down mid-race.
                v = obj.get("v") if isinstance(obj, dict) else None
                if (
                    isinstance(v, int)
                    and not isinstance(v, bool)
                    and v > 1
                    and not self._newer_protocol_logged
                ):
                    self._newer_protocol_logged = True
                    self.logger.warning(
                        f"Feed speaks telemetry protocol v{v}; this build "
                        f"implements v1 — parsing best-effort"
                    )
                # The receiver owns received_time, not the feed. It is the
                # freshness clock every downstream consumer gates on
                # (DeltaSignal's lap timer, FuelSignal's whole update,
                # LinkSignal's staleness), and the schema gives it a
                # plausible-looking default of 0.0 — so a feed that simply
                # never set it used to leave the delta and fuel silently
                # dead forever while speed and RPM looked perfect. Stamping
                # it here makes those consumers independent of feed quality.
                obj["received_time"] = time.monotonic()
                self._latest = TelemetryFrame.model_validate(obj)
            except Exception as e:
                # One bad packet must not kill the reader, but total loss
                # (e.g. a feed emitting nulls the schema rejects) must not
                # be silent either — the dash would freeze with no trace.
                self._dropped += 1
                now = time.monotonic()
                if now - self._last_drop_log >= 5.0:
                    self._last_drop_log = now
                    self.logger.warning(
                        f"Dropped {self._dropped} invalid telemetry "
                        f"packet(s) so far; last error: {e}"
                    )

    def latest(self) -> TelemetryFrame:
        """
        Return the most recently received telemetry frame.
        """
        return self._latest

    def stop(self) -> None:
        """Stop listening and clean up resources.

        Signals the reader through the wake pair BEFORE joining, so the join
        returns in microseconds. Closing the socket is deliberately left until
        after the join: on Linux, closing an fd another thread is blocked on
        does not reliably wake it (the blocked call keeps its own reference),
        so close() was never the shutdown mechanism it looked like.
        """
        self._running = False
        if self._wake_w is not None:
            try:
                self._wake_w.send(b"\0")
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                self.logger.warning("UDP reader thread did not exit within 2s")
            self._thread = None
        try:
            if self._sock:
                self._sock.close()
        finally:
            self._sock = None
        for s_ in (self._wake_r, self._wake_w):
            if s_ is not None:
                try:
                    s_.close()
                except OSError:
                    pass
        self._wake_r = self._wake_w = None


class ReplayReader:
    def __init__(self, path: Path, loop: bool = True, speed: float = 1.0):
        self._path = Path(path)
        self._loop = loop
        self._speed = speed
        self._frames: list[TelemetryFrame] = []
        self._times: list[float] = []  # dt values
        self._t0: float | None = None

        self._load()

    def _load(self) -> None:
        frames: list[TelemetryFrame] = []
        times: list[float] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                dt = float(obj["dt"])
                frame = TelemetryFrame(**obj["frame"])
                times.append(dt)
                frames.append(frame)

        if not frames:
            raise ValueError(f"No frames in replay file {self._path}")

        self._frames = frames
        self._times = times
        self._duration = self._times[-1]

    def start(self) -> None:
        self._t0 = time.perf_counter()

    def latest(self) -> TelemetryFrame:
        if self._t0 is None:
            self.start()

        elapsed = (time.perf_counter() - self._t0) * self._speed

        if self._loop:
            # wrap around
            elapsed = elapsed % self._duration
        else:
            # clamp at end
            if elapsed >= self._duration:
                return self._frames[-1]

        # find right frame index
        idx = bisect_right(self._times, elapsed) - 1
        if idx < 0:
            idx = 0

        return self._frames[idx]

    def stop(self) -> None:
        pass


class TelemetryRecorder:
    def __init__(self, reader: UdpJsonlReader, path: Path, fps: float = 30.0):
        self._reader = reader
        self._path = Path(path)
        self._fps = fps

    def run(self, duration_sec: float | None = None) -> None:
        self._reader.start()
        t0 = time.perf_counter()
        next_frame_time = t0
        frame_interval = 1.0 / self._fps

        with self._path.open("w", encoding="utf-8") as f:
            while True:
                now = time.perf_counter()
                if duration_sec is not None and (now - t0) >= duration_sec:
                    break

                if now < next_frame_time:
                    time.sleep(next_frame_time - now)
                    continue

                dt = now - t0
                frame = self._reader.latest()
                payload = {
                    "dt": dt,
                    "frame": frame.model_dump(mode="json"),
                }
                f.write(json.dumps(payload) + "\n")

                next_frame_time += frame_interval

        self._reader.stop()


if __name__ == "__main__":
    reader = UdpJsonlReader(host="127.0.0.1", port=5600)  # live GT7 telemetry reader
    recorder = TelemetryRecorder(reader, Path("data/goodwood.ndjson"))
    recorder.run(duration_sec=360)  # e.g. 6 minutes of driving
