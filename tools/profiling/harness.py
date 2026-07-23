"""SIGTERM-safe cProfile harness for the instrument cluster.

Run on the target with the live service stopped (DRM master must be free):

  systemctl stop instrument-cluster
  SDL_VIDEODRIVER=kmsdrm MESA_LOADER_DRIVER_OVERRIDE=v3d PYOPENGL_PLATFORM=egl \
  IC_CONFIG_PATH=/data/profiling/config-demo.json \
  python3 /data/profiling/harness.py --out /data/profiling/demo.prof --duration 120

SIGTERM safety: instrument_cluster.main installs its own SIGTERM handler that
exits the main loop cleanly, so app_main() returns and the finally block dumps
stats. This harness additionally installs a SystemExit-raising SIGTERM handler
to cover the import/startup window before the app's handler exists. --duration
uses SIGALRM -> self-SIGTERM so a run self-terminates through the exact same
path systemctl stop would use.

Threading caveat: on this Python (3.12) a cProfile.Profile enabled on the
main thread ALSO captures threads spawned afterwards, and the concurrent
updates corrupt attribution (verified on-device: a worker thread appears in
the stats with garbage timings, and main-thread entries lose events). The
UDP reader thread therefore must not exist while profiling. --udp-inline
replaces UdpJsonlReader with a non-blocking drain executed from latest() on
the main loop: identical per-packet work (decode + json.loads +
model_validate), correctly attributed, no second thread.
"""

import argparse
import cProfile
import os
import pstats
import signal
import time


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="self-terminate via SIGTERM after N seconds (0 = run until killed)",
    )
    ap.add_argument(
        "--no-gl-error-checking",
        action="store_true",
        help="set OpenGL.ERROR_CHECKING=False before the app imports OpenGL.GL",
    )
    ap.add_argument(
        "--udp-inline",
        action="store_true",
        help="drain the UDP socket on the main loop instead of a reader "
        "thread (required for uncorrupted UDP-mode profiles, see docstring)",
    )
    args = ap.parse_args()

    if args.no_gl_error_checking:
        import OpenGL

        OpenGL.ERROR_CHECKING = False

    def _term(sig, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _term)

    if args.duration > 0:

        def _alarm(sig, frame):
            os.kill(os.getpid(), signal.SIGTERM)

        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(int(args.duration))

    from instrument_cluster.main import main as app_main

    if args.udp_inline:
        import json
        import socket

        from instrument_cluster.telemetry import source as _source
        from instrument_cluster.telemetry import udp_jsonl as _udp_jsonl
        from instrument_cluster.telemetry.models import TelemetryFrame

        class InlineUdpReader:
            """Threadless UdpJsonlReader: latest() drains the socket."""

            def __init__(self, host="127.0.0.1", port=5600, bufsize=4096):
                self.addr = (host, port)
                self.bufsize = bufsize
                self._sock = None
                self._latest = TelemetryFrame()

            def start(self):
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._sock.bind(self.addr)
                self._sock.setblocking(False)

            def latest(self):
                sock = self._sock
                if sock is not None:
                    while True:
                        try:
                            data, _addr = sock.recvfrom(self.bufsize)
                        except (BlockingIOError, OSError):
                            break
                        try:
                            self._latest = TelemetryFrame.model_validate(
                                json.loads(data.decode("utf-8"))
                            )
                        except Exception:
                            pass
                return self._latest

            def stop(self):
                if self._sock is not None:
                    self._sock.close()
                    self._sock = None

        _udp_jsonl.UdpJsonlReader = InlineUdpReader
        _source.UdpJsonlReader = InlineUdpReader

    prof = cProfile.Profile()
    t0 = time.perf_counter()
    code = 0
    try:
        prof.enable()
        try:
            app_main()
        except SystemExit as e:
            code = int(e.code or 0)
    finally:
        prof.disable()
        wall = time.perf_counter() - t0
        prof.dump_stats(args.out)
        with open(args.out + ".txt", "w") as f:
            f.write(
                f"wall={wall:.2f}s exit={code} "
                f"error_checking={'off' if args.no_gl_error_checking else 'on'}\n"
            )
            st = pstats.Stats(prof, stream=f)
            st.sort_stats("cumulative").print_stats(40)
            st.sort_stats("tottime").print_stats(40)
        print(f"profile written to {args.out} (wall {wall:.1f}s, exit {code})")


if __name__ == "__main__":
    main()
