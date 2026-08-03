"""EngineSimService: background baking of per-car torque/fuel maps.

The frame loop never waits on this. Consumers call ``request(car_id)``
(non-blocking) on car change and ``poll(car_id)`` per frame; a map
appears once the worker thread has baked it (~0.5-2 s), and until then
the caller keeps whatever fallback it already has — the heuristic
``EngineModel`` for shift lights, no fuel model for the fuel signal.

Latest-request-wins: flipping through cars in a menu abandons stale
bakes mid-integration via the integrator's pace hook, which doubles as
the yield point that keeps the worker from monopolising a core.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np

from ...logger import Logger
from .engine import EngineSimulator
from .params import EngineParams, load_params_db
from .torque_map import TorqueFuelMap

# Non-uniform throttle axis, denser where MAP moves fastest.
_THROTTLE_AXIS = np.array([0.0, 0.05, 0.12, 0.22, 0.35, 0.5, 0.7, 0.85, 1.0])
_RPM_STEP = 250.0
_MAP_CACHE_SIZE = 8
_PACE_SLEEP_S = 0.002
# Re-bake when telemetry reports a rev limit this far beyond the axis.
_RPM_EXTEND_TRIGGER = 1.02
_RPM_EXTEND_FACTOR = 1.1

_service_singleton = None


def get_service() -> "EngineSimService":
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = EngineSimService()
    return _service_singleton


class _BakeCancelled(Exception):
    pass


class EngineSimService:
    def __init__(self, params_path: Path | None = None):
        self.logger = Logger(__class__.__name__).get()
        if params_path is None:
            params_path = (
                Path(__file__).resolve().parent.parent.parent
                / "db"
                / "engine_params.json"
            )
        self._params_path = params_path
        self._params_db: dict | None = None

        self._maps: OrderedDict[int, TorqueFuelMap] = OrderedDict()
        self._failed: set[int] = set()
        self._queue: queue.Queue = queue.Queue()
        self._latest_gen = 0
        # (car_id, rpm_top) of the newest queued/in-flight job: several
        # consumers request the same car on a car change, and without
        # this the second request would cancel the first's bake midway
        # and start over.
        self._pending: tuple | None = None
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    # -- consumer API (frame-loop safe) --

    def poll(self, car_id: int) -> TorqueFuelMap | None:
        """Lock-free read; None until a bake for this car has landed."""
        return self._maps.get(car_id)

    def request(self, car_id: int) -> None:
        """Queue a bake for this car. No-op for unknown-invalid ids,
        cars already baked/failed, and EV/failed-fit entries."""
        if car_id is None or car_id < 0:
            return
        with self._lock:
            if car_id in self._maps or car_id in self._failed:
                return
            if self._pending == (car_id, None):
                return
            params = self._resolve_params(car_id)
            if params is None:
                self._failed.add(car_id)
                return
            self._latest_gen += 1
            self._pending = (car_id, None)
            self._queue.put((self._latest_gen, car_id, params, None))
            self._ensure_worker()

    def ensure_rpm(self, car_id: int, rpm: float) -> None:
        """Extend a baked map whose axis the live rev limit outgrew
        (in-game tuning can raise it past the DB redline)."""
        existing = self._maps.get(car_id)
        if existing is None or rpm <= existing.rpm_max * _RPM_EXTEND_TRIGGER:
            return
        with self._lock:
            rpm_top = rpm * _RPM_EXTEND_FACTOR
            if self._pending == (car_id, rpm_top):
                return
            params = self._resolve_params(car_id)
            if params is None:
                return
            self._latest_gen += 1
            self._pending = (car_id, rpm_top)
            self._queue.put((self._latest_gen, car_id, params, rpm_top))
            self._ensure_worker()

    # -- internals --

    def _resolve_params(self, car_id: int) -> EngineParams | None:
        if self._params_db is None:
            self._params_db = load_params_db(self._params_path)
        entry = self._params_db.get(str(car_id)) or self._params_db.get("default")
        if not entry or entry.get("fit") != "ok" or not entry.get("params"):
            return None
        try:
            return EngineParams.from_dict(entry["params"])
        except (KeyError, TypeError) as exc:
            self.logger.warning(f"bad engine params for car {car_id}: {exc!r}")
            return None

    def _ensure_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._run, name="engine-sim-bake", daemon=True
            )
            self._worker.start()

    def _run(self) -> None:
        while True:
            generation, car_id, params, rpm_top = self._queue.get()
            if generation != self._latest_gen:
                continue  # a newer request superseded this one
            try:
                baked = self._bake(generation, params, rpm_top)
            except _BakeCancelled:
                continue
            except Exception as exc:  # noqa: BLE001 — worker must survive
                self.logger.error(f"engine map bake failed for car {car_id}: {exc!r}")
                self._failed.add(car_id)
                if self._pending and self._pending[0] == car_id:
                    self._pending = None
                continue
            self._maps[car_id] = baked
            self._maps.move_to_end(car_id)
            while len(self._maps) > _MAP_CACHE_SIZE:
                self._maps.popitem(last=False)
            if self._pending and self._pending[0] == car_id:
                self._pending = None
            self.logger.info(
                f"engine map ready for car {car_id} "
                f"({len(baked.rpm_axis)}x{len(baked.throttle_axis)})"
            )

    def _bake(
        self, generation: int, params: EngineParams, rpm_top: float | None
    ) -> TorqueFuelMap:
        top = 1.05 * params.rated_rpm
        if rpm_top is not None:
            top = max(top, rpm_top)
        rpm_axis = np.arange(params.idle_rpm, top + _RPM_STEP, _RPM_STEP)

        def pace():
            time.sleep(_PACE_SLEEP_S)
            if generation != self._latest_gen:
                raise _BakeCancelled

        sim = EngineSimulator(params)
        torque, fuel = sim.simulate_grid(
            rpm_axis, _THROTTLE_AXIS, pace_hook=pace
        )
        return TorqueFuelMap(rpm_axis, _THROTTLE_AXIS, torque, fuel)
