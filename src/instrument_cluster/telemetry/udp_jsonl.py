import json
import socket
import threading
import time
from bisect import bisect_right
from pathlib import Path
from typing import Optional, Tuple

from ..telemetry.models import TelemetryFrame


class UdpJsonlReader:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5600,
        bufsize: int = 4096,
    ):
        self.addr: Tuple[str, int] = (host, port)
        self.bufsize = bufsize
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._latest: TelemetryFrame = TelemetryFrame()

    def start(self) -> None:
        """Start listening for telemetry frames on the configured UDP socket."""
        if self._running:
            return
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # receive-only on configured address
        self._sock.bind(self.addr)
        # 1-second timeout: loop wakes at most once/s when idle instead of
        # busy-polling with sleep(0.002) (~500 wakeups/s).
        self._sock.settimeout(1.0)
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

        while self._running:
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
                self._latest = TelemetryFrame.model_validate(obj)
            except Exception:
                pass

    def latest(self) -> TelemetryFrame:
        """
        Return the most recently received telemetry frame.
        """
        return self._latest

    def stop(self) -> None:
        """Stop listening and clean up resources."""
        self._running = False
        try:
            if self._sock:
                self._sock.close()
        finally:
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


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
