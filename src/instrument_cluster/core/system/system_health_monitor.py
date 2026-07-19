import os
import socket


class SystemHealthMonitor:
    def __init__(self, watchdog_interval=20.0):
        self.timer = 0.0
        self.interval = watchdog_interval

    def notify_ready(self):
        """
        Signals systemd that the application has started and
        is ready to perform its work.
        """
        self._send_notify("READY=1")

    def update(self, dt):
        """Ticks the watchdog timer and sends a ping if interval is reached."""
        self.timer += dt
        if self.timer >= self.interval:
            self._send_notify("WATCHDOG=1")
            self.timer = 0.0

    def _send_notify(self, message):
        """
        Internal helper to send a notification to systemd
        via the NOTIFY_SOCKET.
        """
        notify_socket = os.getenv("NOTIFY_SOCKET")
        if not notify_socket:
            return

        if notify_socket.startswith("@"):
            notify_socket = "\0" + notify_socket[1:]

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.settimeout(2.0)
                sock.connect(notify_socket)
                sock.sendall(message.encode())
        except Exception:
            pass
