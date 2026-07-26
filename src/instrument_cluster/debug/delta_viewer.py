#!/usr/bin/env python3
"""
Delta Track Debug Tool - Standalone visualization for delta calculator debugging.

This tool visualizes delta calculator debug state streamed over UDP from a Raspberry Pi,
or uses mock data for local testing.

Usage:
    # Receive from Pi:
    uv run python -m instrument_cluster.debug.delta_viewer --listen 5005

    # Local testing:
    uv run python -m instrument_cluster.debug.delta_viewer --mock
"""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import threading
import time
from collections import deque
from typing import Any, Dict, List, Tuple

# Disable audio before pygame import
os.environ["SDL_AUDIODRIVER"] = "dummy"

import numpy as np
import pygame


# =============================================================================
# Helper Classes
# =============================================================================


class HeadingTracker:
    """
    Handles smoothing of the car's heading to prevent jitter.
    Manages the circular wrapping of angles (radians).
    """

    def __init__(self, smoothing: float = 0.20, min_step_m: float = 0.30):
        self.smoothing = max(0.0, min(1.0, smoothing))
        self.min_step_m = min_step_m
        self.heading_rad = 0.0
        self.has_heading = False
        self.prev_x: float | None = None
        self.prev_z: float | None = None

    def update(self, x: float, z: float) -> float:
        """Updates internal state and returns the smoothed heading."""
        if self.prev_x is None or self.prev_z is None:
            self.prev_x, self.prev_z = x, z
            return self.heading_rad

        dx = x - self.prev_x
        dz = z - self.prev_z
        dist = math.hypot(dx, dz)

        if dist >= self.min_step_m:
            self.prev_x, self.prev_z = x, z
            target_hd = math.atan2(dx, dz)

            if not self.has_heading:
                self.heading_rad = target_hd
                self.has_heading = True
            else:
                delta = target_hd - self.heading_rad
                while delta > math.pi:
                    target_hd -= 2.0 * math.pi
                    delta = target_hd - self.heading_rad
                while delta < -math.pi:
                    target_hd += 2.0 * math.pi
                    delta = target_hd - self.heading_rad

                self.heading_rad = (
                    1.0 - self.smoothing
                ) * self.heading_rad + self.smoothing * target_hd

        return self.heading_rad


class ViewportTransformer:
    """Handles Coordinate Transformations: World (3D) -> Screen (2D)."""

    def __init__(self, width: int, height: int, padding: int = 10):
        self.width = width
        self.height = height
        self.padding = padding
        self.center_x = width * 0.5
        self.center_y = height * 0.5

    def world_to_screen_overview(
        self, x: float, z: float, bounds: Tuple[float, float, float, float]
    ) -> Tuple[int, int] | None:
        """Maps world coordinates to fit the entire track within the viewport."""
        minx, maxx, minz, maxz = bounds
        dx = maxx - minx
        dz = maxz - minz

        if dx <= 1e-6 or dz <= 1e-6:
            return None

        avail_w = self.width - 2 * self.padding
        avail_h = self.height - 2 * self.padding
        scale = min(avail_w / dx, avail_h / dz)

        track_screen_w = dx * scale
        track_screen_h = dz * scale
        offset_x = self.padding + (avail_w - track_screen_w) * 0.5
        offset_y = self.padding + (avail_h - track_screen_h) * 0.5

        px = offset_x + (x - minx) * scale
        py = offset_y + (maxz - z) * scale

        return int(px), int(py)

    def world_to_screen_follow(
        self,
        x: float,
        z: float,
        cam_x: float,
        cam_z: float,
        zoom: float,
        view_width_m: float,
        heading: float,
        heading_up: bool,
    ) -> Tuple[int, int]:
        """Maps world coordinates relative to a camera position."""
        meters_across = max(10.0, float(view_width_m))
        base_scale = min(self.width, self.height) / meters_across
        scale = base_scale * max(0.1, float(zoom))

        dx = x - cam_x
        dz = z - cam_z

        if heading_up:
            cos_a = math.cos(heading)
            sin_a = math.sin(heading)
            rx = dx * cos_a - dz * sin_a
            rz = dx * sin_a + dz * cos_a
        else:
            rx, rz = dx, dz

        px = self.center_x + rx * scale
        py = self.center_y - rz * scale

        return int(px), int(py)


# =============================================================================
# Data Sources
# =============================================================================


class DebugReceiver:
    """Receives delta calculator debug state over UDP from a Raspberry Pi."""

    def __init__(self, host: str = "0.0.0.0", port: int = 5005):
        self.host = host
        self.port = port
        self._running = False
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self._latest_state: Dict[str, Any] | None = None
        self._packets_received = 0
        self._last_packet_time: float | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._running:
            return

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.setblocking(False)
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
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
        while self._running:
            try:
                data, _ = self._sock.recvfrom(65535)
                self._parse_packet(data)
            except BlockingIOError:
                time.sleep(0.005)
            except Exception:
                time.sleep(0.01)

    def _parse_packet(self, data: bytes) -> None:
        try:
            state = json.loads(data.decode("utf-8"))
            with self._lock:
                self._latest_state = state
                self._packets_received += 1
                self._last_packet_time = time.time()
        except Exception:
            pass

    def get_debug_state(self) -> Dict[str, Any] | None:
        with self._lock:
            return self._latest_state

    @property
    def is_connected(self) -> bool:
        if self._last_packet_time is None:
            return False
        return (time.time() - self._last_packet_time) < 2.0

    @property
    def packets_received(self) -> int:
        return self._packets_received


class MockCalculator:
    """Mock calculator for local testing without Pi connection."""

    def __init__(self):
        self._ref_version = 1
        self._time = 0.0
        self._lap_time_sec = 60.0
        self._freeze = False

        self._generate_track()

    def _generate_track(self):
        num_pts = 500
        t = np.linspace(0, 2 * np.pi, num_pts, endpoint=False)
        a, b = 200.0, 100.0
        self._xs = a * np.cos(t)
        self._zs = b * np.sin(t)

    def get_debug_state(self) -> Dict[str, Any] | None:
        num_pts = len(self._xs)
        t_norm = (self._time % self._lap_time_sec) / self._lap_time_sec
        idx = int(t_norm * num_pts) % num_pts
        next_idx = (idx + 1) % num_pts

        t_seg = (t_norm * num_pts) % 1.0
        qx = self._xs[idx] * (1 - t_seg) + self._xs[next_idx] * t_seg
        qz = self._zs[idx] * (1 - t_seg) + self._zs[next_idx] * t_seg

        offset = 3.0 * math.sin(self._time * 0.5)
        dx = self._xs[next_idx] - self._xs[idx]
        dz = self._zs[next_idx] - self._zs[idx]
        norm = math.hypot(dx, dz)
        if norm > 1e-6:
            qx += offset * (-dz / norm)
            qz += offset * (dx / norm)

        neighbors = []
        for i in range(-3, 4):
            if i == 0:
                continue
            nb_idx = (idx + i) % num_pts
            nb_next = (nb_idx + 1) % num_pts
            neighbors.append(
                {
                    "seg_idx": nb_idx,
                    "rank": abs(i),
                    "p0x": float(self._xs[nb_idx]),
                    "p0z": float(self._zs[nb_idx]),
                    "p1x": float(self._xs[nb_next]),
                    "p1z": float(self._zs[nb_next]),
                    "mx": float((self._xs[nb_idx] + self._xs[nb_next]) / 2),
                    "mz": float((self._zs[nb_idx] + self._zs[nb_next]) / 2),
                }
            )

        return {
            "ref_version": self._ref_version,
            "ref_xs": self._xs.tolist(),
            "ref_zs": self._zs.tolist(),
            "proj": {
                "qx": float(qx),
                "qz": float(qz),
                "fx": float(self._xs[idx]),
                "fz": float(self._zs[idx]),
                "p0x": float(self._xs[idx]),
                "p0z": float(self._zs[idx]),
                "p1x": float(self._xs[next_idx]),
                "p1z": float(self._zs[next_idx]),
            },
            "state": {"seg_idx": idx, "freeze": self._freeze},
            "neighbors": neighbors,
        }

    def advance(self, dt: float):
        self._time += dt

    def toggle_freeze(self):
        self._freeze = not self._freeze


# =============================================================================
# Renderer
# =============================================================================


class DeltaViewer:
    """Main viewer class that handles rendering and interaction."""

    # Colors
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    LIGHT_GREY = (120, 120, 120)
    DARK_GREY = (60, 60, 60)
    TRAIL_BLUE = (80, 160, 255)
    NEIGHBOR_BLUE = (140, 140, 255)
    SEGMENT_YELLOW = (255, 255, 0)
    CAR_GREEN = (80, 255, 80)
    CAR_RED = (255, 80, 80)
    HUD_TEXT = (200, 200, 200)

    def __init__(
        self,
        width: int,
        height: int,
        source,  # DebugReceiver or MockCalculator
        *,
        trail_len: int = 50,
        follow_car: bool = True,
        zoom: float = 1.0,
        view_width_m: float = 150.0,
        heading_up: bool = True,
        show_neighbors: bool = True,
        show_neighbor_rank: bool = False,
    ):
        self.width = width
        self.height = height
        self.source = source

        self.transformer = ViewportTransformer(width, height)
        self.heading_tracker = HeadingTracker()

        # Configuration
        self.follow_car = follow_car
        self.zoom = zoom
        self.view_width_m = view_width_m
        self.heading_up = heading_up
        self.show_neighbors = show_neighbors
        self.show_neighbor_rank = show_neighbor_rank

        # State
        self._trail: deque = deque(maxlen=trail_len)
        self._cam_x: float | None = None
        self._cam_z: float | None = None

        # Cache
        self._ref_version_seen: int = -1
        self._static_track: pygame.Surface | None = None
        self._world_bounds: Tuple[float, float, float, float] | None = None
        self._ref_pts_world: List[Tuple[float, float]] = []

        # Font
        self._font = pygame.font.Font(None, 24)
        self._font_small = pygame.font.Font(None, 20)

    def zoom_in(self):
        self.zoom = min(10.0, self.zoom * 1.2)

    def zoom_out(self):
        self.zoom = max(0.2, self.zoom / 1.2)

    def update(self, dt: float) -> Dict[str, Any] | None:
        """Fetch latest state and update internal state. Returns debug state."""
        dbg = self.source.get_debug_state()
        if dbg is None:
            return None

        self._update_reference_cache(dbg)
        self._update_car_state(dbg)
        return dbg

    def _update_reference_cache(self, dbg: Dict[str, Any]):
        ref_version = int(dbg.get("ref_version", -1))
        if ref_version == self._ref_version_seen:
            return

        self._ref_version_seen = ref_version

        xs = dbg.get("ref_xs")
        zs = dbg.get("ref_zs")

        if xs is None or zs is None or len(xs) < 2:
            self._reset_cache()
            return

        xs_list = [float(v) for v in xs]
        zs_list = [float(v) for v in zs]
        step = max(1, len(xs_list) // 800)

        self._ref_pts_world = [
            (xs_list[i], zs_list[i]) for i in range(0, len(xs_list), step)
        ]
        self._world_bounds = (min(xs_list), max(xs_list), min(zs_list), max(zs_list))

        # Render static overview surface
        self._static_track = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        pts = []
        for x, z in self._ref_pts_world:
            p = self.transformer.world_to_screen_overview(x, z, self._world_bounds)
            if p:
                pts.append(p)

        if len(pts) >= 2:
            pygame.draw.lines(self._static_track, self.LIGHT_GREY, False, pts, 2)

        self._trail.clear()

    def _reset_cache(self):
        self._static_track = None
        self._world_bounds = None
        self._ref_pts_world.clear()

    def _update_car_state(self, dbg: Dict[str, Any]):
        proj = dbg.get("proj") or {}
        qx, qz = proj.get("qx"), proj.get("qz")

        if qx is not None and qz is not None:
            qx, qz = float(qx), float(qz)
            self.heading_tracker.update(qx, qz)
            self._cam_x, self._cam_z = qx, qz
            self._trail.append((qx, qz))

    def _project_point(self, x: float, z: float) -> Tuple[int, int] | None:
        if self.follow_car and self._cam_x is not None:
            return self.transformer.world_to_screen_follow(
                x,
                z,
                self._cam_x,
                self._cam_z,
                self.zoom,
                self.view_width_m,
                self.heading_tracker.heading_rad,
                self.heading_up,
            )
        elif self._world_bounds:
            return self.transformer.world_to_screen_overview(x, z, self._world_bounds)
        return None

    def render(self, surface: pygame.Surface, dbg: Dict[str, Any] | None):
        """Render the scene to the given surface."""
        surface.fill(self.BLACK)

        if dbg is None:
            self._render_placeholder(surface)
            return

        self._draw_reference_track(surface)
        self._draw_trail(surface)

        if self.show_neighbors:
            self._draw_neighbors(surface, dbg)

        self._draw_projection(surface, dbg)

    def _render_placeholder(self, surface: pygame.Surface):
        lines = ["Waiting for data...", "No reference available"]
        y = self.height // 2 - 20
        for line in lines:
            txt = self._font.render(line, True, self.HUD_TEXT)
            x = (self.width - txt.get_width()) // 2
            surface.blit(txt, (x, y))
            y += 25

    def _draw_reference_track(self, surface: pygame.Surface):
        if not self.follow_car and self._static_track:
            surface.blit(self._static_track, (0, 0))
        elif self.follow_car and len(self._ref_pts_world) >= 2:
            pts = [self._project_point(x, z) for (x, z) in self._ref_pts_world]
            valid_pts = [p for p in pts if p is not None]

            if len(valid_pts) >= 2:
                pygame.draw.lines(surface, self.LIGHT_GREY, False, valid_pts, 4)

            cx, cy = self.transformer.center_x, self.transformer.center_y
            pygame.draw.line(surface, self.DARK_GREY, (cx - 8, cy), (cx + 8, cy), 1)
            pygame.draw.line(surface, self.DARK_GREY, (cx, cy - 8), (cx, cy + 8), 1)

    def _draw_trail(self, surface: pygame.Surface):
        if len(self._trail) < 2:
            return
        pts = [self._project_point(x, z) for (x, z) in self._trail]
        valid_pts = [p for p in pts if p is not None]
        if len(valid_pts) >= 2:
            pygame.draw.lines(surface, self.TRAIL_BLUE, False, valid_pts, 2)

    def _draw_neighbors(self, surface: pygame.Surface, dbg: Dict[str, Any]):
        neighbors = dbg.get("neighbors") or []
        state = dbg.get("state") or {}
        chosen_idx = state.get("seg_idx")

        for nb in neighbors:
            if chosen_idx is not None and nb.get("seg_idx") == chosen_idx:
                continue

            p0 = self._project_point(nb.get("p0x", 0.0), nb.get("p0z", 0.0))
            p1 = self._project_point(nb.get("p1x", 0.0), nb.get("p1z", 0.0))
            mid = self._project_point(nb.get("mx", 0.0), nb.get("mz", 0.0))

            if p0 and p1:
                pygame.draw.line(surface, self.NEIGHBOR_BLUE, p0, p1, 2)

            if mid:
                pygame.draw.circle(surface, self.NEIGHBOR_BLUE, mid, 6)
                if self.show_neighbor_rank:
                    rank = nb.get("rank", 0)
                    if rank:
                        txt = self._font_small.render(str(rank), True, (180, 180, 255))
                        surface.blit(txt, (mid[0] + 4, mid[1] - 6))

    def _draw_projection(self, surface: pygame.Surface, dbg: Dict[str, Any]):
        proj = dbg.get("proj") or {}
        st = dbg.get("state") or {}

        s_p0 = self._project_point(proj.get("p0x", 0.0), proj.get("p0z", 0.0))
        s_p1 = self._project_point(proj.get("p1x", 0.0), proj.get("p1z", 0.0))

        if s_p0 and s_p1:
            pygame.draw.line(surface, self.SEGMENT_YELLOW, s_p0, s_p1, 4)

        car_pos = self._project_point(proj.get("qx", 0.0), proj.get("qz", 0.0))
        foot_pos = self._project_point(proj.get("fx", 0.0), proj.get("fz", 0.0))

        freeze = bool(st.get("freeze", False))
        car_color = self.CAR_RED if freeze else self.CAR_GREEN

        if car_pos:
            pygame.draw.circle(surface, car_color, car_pos, 8)
        if foot_pos:
            pygame.draw.circle(surface, self.WHITE, foot_pos, 5)
        if car_pos and foot_pos:
            pygame.draw.line(surface, (200, 200, 200), car_pos, foot_pos, 2)


# =============================================================================
# Main
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Delta Track Debug Tool - Visualize delta calculator debug data"
    )
    parser.add_argument(
        "--listen",
        type=int,
        default=None,
        metavar="PORT",
        help="Listen for debug data on UDP port (receives from Pi)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock calculator for local testing",
    )
    parser.add_argument(
        "--width", type=int, default=800, help="Window width (default: 800)"
    )
    parser.add_argument(
        "--height", type=int, default=600, help="Window height (default: 600)"
    )
    args = parser.parse_args()

    if args.listen is None and not args.mock:
        print("No mode specified, defaulting to --mock mode")
        print("Use --listen PORT to receive data from Raspberry Pi")
        args.mock = True

    pygame.init()

    screen = pygame.display.set_mode((args.width, args.height))

    if args.listen is not None:
        source = DebugReceiver(port=args.listen)
        source.start()
        mode_str = f"Listening on UDP port {args.listen}"
        pygame.display.set_caption(f"Delta Debug - :{args.listen}")
    else:
        source = MockCalculator()
        mode_str = "Mock mode (simulated data)"
        pygame.display.set_caption("Delta Debug - Mock")

    viewer = DeltaViewer(args.width, args.height, source)

    clock = pygame.time.Clock()
    running = True
    paused = False
    sim_speed = 1.0

    hud_font = pygame.font.Font(None, 24)

    print("=" * 60)
    print("DELTA TRACK DEBUG TOOL")
    print("=" * 60)
    print(f"Mode: {mode_str}")
    print("=" * 60)
    print("Controls:")
    print("  [+/-]      Zoom in/out")
    print("  [F]        Toggle follow car mode")
    print("  [H]        Toggle heading up mode")
    print("  [N]        Toggle neighbor display")
    print("  [R]        Toggle neighbor rank display")
    if args.mock:
        print("  [SPACE]    Toggle freeze simulation")
        print("  [1-9]      Set simulation speed")
    else:
        print("  [SPACE]    Pause/Resume display")
    print("  [ESC/Q]    Quit")
    print("=" * 60)

    while running:
        dt = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS):
                    viewer.zoom_in()
                    print(f"Zoom: {viewer.zoom:.2f}x")
                elif event.key == pygame.K_MINUS:
                    viewer.zoom_out()
                    print(f"Zoom: {viewer.zoom:.2f}x")
                elif event.key == pygame.K_f:
                    viewer.follow_car = not viewer.follow_car
                    print(f"Follow car: {viewer.follow_car}")
                elif event.key == pygame.K_h:
                    viewer.heading_up = not viewer.heading_up
                    print(f"Heading up: {viewer.heading_up}")
                elif event.key == pygame.K_n:
                    viewer.show_neighbors = not viewer.show_neighbors
                    print(f"Show neighbors: {viewer.show_neighbors}")
                elif event.key == pygame.K_r:
                    viewer.show_neighbor_rank = not viewer.show_neighbor_rank
                    print(f"Show neighbor rank: {viewer.show_neighbor_rank}")
                elif event.key == pygame.K_SPACE:
                    if args.mock:
                        source.toggle_freeze()
                        print(f"Freeze: {source._freeze}")
                    else:
                        paused = not paused
                        print(f"Paused: {paused}")
                elif args.mock and event.key in range(pygame.K_1, pygame.K_9 + 1):
                    sim_speed = float(event.key - pygame.K_0)
                    print(f"Simulation speed: {sim_speed}x")

        # Update simulation (mock mode only)
        if args.mock and not getattr(source, "_freeze", False):
            source.advance(dt * sim_speed)

        # Update viewer
        if not paused:
            dbg = viewer.update(dt)
        else:
            dbg = source.get_debug_state()

        # Render
        viewer.render(screen, dbg)

        # HUD
        fps = clock.get_fps()
        if args.listen is not None:
            connected = source.is_connected
            pkts = source.packets_received
            status = "CONNECTED" if connected else "WAITING..."
            hud_lines = [
                f"FPS: {fps:.1f} | {status}",
                f"Port: {args.listen} | Packets: {pkts}",
                f"Zoom: {viewer.zoom:.1f}x | Follow: {viewer.follow_car}",
            ]
        else:
            freeze = getattr(source, "_freeze", False)
            hud_lines = [
                f"FPS: {fps:.1f} | MOCK MODE",
                f"Speed: {sim_speed}x | Freeze: {freeze}",
                f"Zoom: {viewer.zoom:.1f}x | Follow: {viewer.follow_car}",
            ]

        y_pos = 10
        for line in hud_lines:
            txt = hud_font.render(line, True, (200, 200, 200))
            screen.blit(txt, (10, y_pos))
            y_pos += 20

        pygame.display.flip()

    if hasattr(source, "stop"):
        source.stop()
    pygame.quit()
    print("Debug session ended.")


if __name__ == "__main__":
    main()
