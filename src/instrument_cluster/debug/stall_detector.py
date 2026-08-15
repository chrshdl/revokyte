"""Main-loop stall detector.

A daemon thread watches a heartbeat the main loop beats every frame and,
when it goes stale, writes the main thread's current stack into the log —
once per stall. Exists because the appliance has no debugger: a frozen UI
with live background threads (watchdog still fed) is undiagnosable from
the field without knowing where the main thread actually sits. Costs one
timestamp store per frame and a 1 Hz check.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback

from ..logger import Logger

logger = Logger("stall_detector").get()


class StallDetector:
    def __init__(self, main_thread_id: int, threshold_s: float = 3.0):
        self._main_thread_id = main_thread_id
        self._threshold_s = threshold_s
        self._beat_at = time.monotonic()
        self._reported = False
        self._stop = threading.Event()

    def beat(self) -> None:
        """Called by the main loop every frame."""
        self._beat_at = time.monotonic()
        self._reported = False

    def start(self) -> None:
        threading.Thread(
            target=self._loop, name="stall-detector", daemon=True
        ).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            stale = time.monotonic() - self._beat_at
            if stale < self._threshold_s or self._reported:
                continue
            # One report per stall: beat() re-arms. A recovered-then-stuck
            # loop reports again; a permanently stuck one doesn't spam.
            self._reported = True
            frame = sys._current_frames().get(self._main_thread_id)
            if frame is None:
                logger.error(
                    "Main loop stalled for %.1f s; main thread frame missing",
                    stale,
                )
                continue
            stack = "".join(traceback.format_stack(frame))
            logger.error(
                "Main loop stalled for %.1f s; main thread at:\n%s", stale, stack
            )
