"""
Debug tools for instrument-cluster development.

This module provides:
- DebugSender: Streams delta calculator state over UDP (runs on Pi)
- delta_viewer: Standalone visualization tool (runs on Mac)

Usage:
    # On Mac - Run the viewer:
    uv run python -m instrument_cluster.debug.delta_viewer --listen 5005

    # On Pi - Enable sender via env var:
    DEBUG_DEST_IP=10.22.33.48 python -m instrument_cluster
"""

from .debug_sender import DebugSender

__all__ = ["DebugSender"]
