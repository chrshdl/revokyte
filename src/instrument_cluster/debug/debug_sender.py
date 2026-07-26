"""
DebugSender - Streams delta calculator debug state over UDP.

Usage:
    sender = DebugSender(delta_signal, dest_ip="10.22.33.48")
    sender.start()
    # ... app runs ...
    sender.stop()
"""

import json
import socket
import threading
import time
from typing import Any, Dict

import numpy as np


class DebugSender:
    """
    Streams delta calculator debug state over UDP to a remote visualization client.

    The sender runs in a background thread and periodically fetches the debug
    state from the delta calculator, serializes it to JSON, and sends it over UDP.
    """

    def __init__(
        self,
        delta_signal,
        dest_ip: str = "10.22.33.48",
        port: int = 5005,
        interval: float = 0.033,  # ~30 Hz
    ):
        """
        Initialize the debug sender.

        Args:
            delta_signal: DeltaSignal instance that owns the calculator
            dest_ip: Destination IP address to send debug data to
            port: UDP port to send data to
            interval: Time between sends in seconds (default ~30 Hz)
        """
        self.delta_signal = delta_signal
        self.dest_ip = dest_ip
        self.port = port
        self.interval = interval

        self._running = False
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None

        # Stats
        self._packets_sent = 0
        self._last_error: str | None = None

    def start(self) -> None:
        """Start the debug sender background thread."""
        if self._running:
            return

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the debug sender."""
        self._running = False

        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _run(self) -> None:
        """Background thread loop that sends debug state."""
        while self._running:
            try:
                self._send_debug_state()
            except Exception as e:
                self._last_error = str(e)

            time.sleep(self.interval)

    def _send_debug_state(self) -> None:
        """Fetch debug state from calculator and send over UDP."""
        if self.delta_signal is None:
            return

        calculator = getattr(self.delta_signal, "calculator", None)
        if calculator is None:
            return

        try:
            debug_state = calculator.get_debug_state()
        except Exception:
            return

        if debug_state is None:
            return

        # Serialize to JSON (handling numpy arrays)
        json_data = self._serialize_debug_state(debug_state)
        if json_data is None:
            return

        # Send over UDP
        try:
            self._sock.sendto(json_data, (self.dest_ip, self.port))
            self._packets_sent += 1
        except Exception as e:
            self._last_error = str(e)

    def _serialize_debug_state(self, state: Dict[str, Any]) -> bytes | None:
        """
        Serialize debug state to JSON bytes, converting numpy arrays to lists.

        Args:
            state: Debug state dictionary from calculator.get_debug_state()

        Returns:
            JSON bytes or None if serialization fails
        """
        try:
            # Deep copy and convert numpy arrays
            serializable = self._make_serializable(state)
            return json.dumps(serializable).encode("utf-8")
        except Exception:
            return None

    def _make_serializable(self, obj: Any) -> Any:
        """
        Recursively convert numpy arrays and other non-JSON-serializable types.
        """
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, (np.integer, np.floating)):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._make_serializable(v) for v in obj]
        else:
            return obj

    @property
    def stats(self) -> Dict[str, Any]:
        """Return sender statistics."""
        return {
            "packets_sent": self._packets_sent,
            "last_error": self._last_error,
            "running": self._running,
            "dest": f"{self.dest_ip}:{self.port}",
        }
