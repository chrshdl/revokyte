import json
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from json import JSONDecodeError
from pathlib import Path

from .core.vehicle.accel_timer import DEFAULT_DISTANCE_M, DISTANCES_M
from .logger import Logger
from .telemetry.mode import DiffReferenceMode, TelemetryMode

LOGGER = Logger("config.py").get()


def _write_config_dict(config_dict: dict, path: Path) -> None:
    """The actual (slow, blocking) disk I/O — safe to run off the main
    thread since it only touches the given dict snapshot, never live state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")

    # Write to temporary file
    with tmp_path.open("w") as f:
        json.dump(config_dict, f, indent=4)
        f.flush()
        os.fsync(f.fileno())

    # Atomically replace the original
    os.replace(tmp_path, path)


@dataclass
class Config:
    # Display profile selector: "auto" (detect by panel resolution),
    # "rpi_display_2", "waveshare_7", "waveshare_5", or "dev". See display.py.
    display: str = field(default="auto")
    telemetry_mode: str = field(default=TelemetryMode.DEMO.value)
    # Opaque id (see addons/feeds.py) of the last-installed feed, used only so
    # the settings dropdown can show the current selection when telemetry_mode
    # is "udp". The app never branches on its value.
    telemetry_feed: str = field(default="")
    # Release tag of the feed build actually installed on this device. The
    # install lives on /data and survives OS updates, so the descriptor's pin
    # alone says nothing about what is really running — see
    # feeds.feed_needs_reinstall.
    telemetry_feed_version: str = field(default="")
    diff_reference_mode: str = field(default=DiffReferenceMode.FASTEST.value)
    # Console/game-PC IP the in-process reader connects to when
    # telemetry_mode is "direct" (desktop builds; the appliance runs the
    # installed proxy program instead).
    direct_host: str = field(default="")
    recent_connected: list[str] = field(default_factory=list)
    udp_host: str = field(default="127.0.0.1")
    udp_port: int = field(default=5600)
    brightness: int = field(default=50)
    # Show the bezel status LEDs (TC/ASM) on the dashboard; off also
    # returns the widget columns to the strip-less layout.
    status_lights: bool = field(default=False)
    # Physical Blinkt! shift-light bar; ON is the shipped default — the
    # bar is a headline feature, the toggle exists for photosensitive
    # users (TF-03 O1 measure) and dark-room driving.
    shift_lights: bool = field(default=True)
    # Active dashboard page selection, owned by the exclusive dashboard
    # provider plugin (0 = the built-in default). An invalid or
    # no-longer-available value silently falls back to the default.
    dashboard_slot: int = field(default=0)
    # Log full-throttle pulls to <config dir>/accel_runs, which is how the
    # shift-point curve's falloff gets measured instead of assumed: the runs
    # are read back and fitted offline. Off by default and
    # config-file only — no settings UI row. On the appliance this is the
    # only way to capture: the feed emits to the device's own loopback and
    # the cluster already owns that port, so nothing else can listen.
    accel_logging: bool = field(default=False)
    # Distance the Testing & Validation screen's acceleration timer runs
    # to, in metres (see core/vehicle/accel_timer.py). Remembered between
    # visits so a session of back-to-back runs is set up once.
    accel_test_distance: int = field(default=DEFAULT_DISTANCE_M)
    # Optional Wi-Fi regulatory domain override (ISO 3166-1 alpha-2, e.g.
    # "GB"). Empty (the default) writes no country= line: the radio starts
    # in the world domain and adopts the country the router itself
    # advertises (802.11d), which is correct in any country. Config-file
    # only — no settings UI row.
    wifi_country: str = field(default="")

    @classmethod
    def parse_config(cls, path: Path) -> "Config":
        config: dict = {}
        LOGGER.debug(
            f"Config path {path} exists: {path.exists()} is file: {path.is_file()}"
        )
        if path.exists() and path.is_file():
            try:
                with open(path, "r") as f:
                    config = json.load(f)
            except (JSONDecodeError, OSError) as e:
                # handle empy or corrupt config.json
                LOGGER.warning(
                    f"Config file {path} is invalid or corrupted, using defaults.",
                    exc_info=e,
                )
                config = {}

        # Drop unknown keys so that future config fields don't cause a TypeError.
        known = {f.name for f in fields(Config)}
        config = {k: v for k, v in config.items() if k in known}

        result = Config(**config)
        result._validate_and_clamp()
        LOGGER.info(f"Config: {result}")

        if not path.exists() or not config:
            result.write_to_file(path)

        return result

    def _validate_and_clamp(self) -> None:
        self.brightness = max(0, min(100, self.brightness))
        self.udp_port = max(1, min(65535, self.udp_port))
        self.status_lights = bool(self.status_lights)
        self.shift_lights = bool(self.shift_lights)
        self.accel_logging = bool(self.accel_logging)

        if self.accel_test_distance not in DISTANCES_M:
            LOGGER.warning(
                "Invalid accel_test_distance %r — defaulting to %d m.",
                self.accel_test_distance,
                DEFAULT_DISTANCE_M,
            )
            self.accel_test_distance = DEFAULT_DISTANCE_M

        valid_telemetry_modes = {m.value for m in TelemetryMode}
        if self.telemetry_mode not in valid_telemetry_modes:
            LOGGER.warning(
                "Invalid telemetry_mode %r — defaulting to demo.", self.telemetry_mode
            )
            self.telemetry_mode = TelemetryMode.DEMO.value

        self.direct_host = str(self.direct_host or "")
        if self.telemetry_mode == TelemetryMode.DIRECT.value and not self.direct_host:
            LOGGER.warning(
                "telemetry_mode is direct but no direct_host is set — "
                "defaulting to demo."
            )
            self.telemetry_mode = TelemetryMode.DEMO.value

        valid_diff_modes = {m.value for m in DiffReferenceMode}
        if self.diff_reference_mode not in valid_diff_modes:
            LOGGER.warning(
                "Invalid diff_reference_mode %r — defaulting to fastest.",
                self.diff_reference_mode,
            )
            self.diff_reference_mode = DiffReferenceMode.FASTEST.value

    def write_to_file(self, path: Path) -> None:
        LOGGER.debug(f"Write config to {path}")
        _write_config_dict(asdict(self), path)


class ConfigManager:
    path = Path(
        os.environ.get(
            "IC_CONFIG_PATH",
            Path.home() / ".config" / "instrument-cluster" / "config.json",
        )
    )
    _config: Config | None = None
    # Guards the handoff state below. All runtime disk writes go through a
    # single long-lived "config-writer" thread: persist() publishes the
    # latest snapshot into _pending, the writer drains it.
    _cond = threading.Condition()
    _pending: tuple[dict, Path] | None = None
    _writing = False
    _writer: threading.Thread | None = None
    # Poison flag: True after a factory reset has wiped the config file
    # and the process is going down. See disable_persistence().
    _persistence_disabled = False
    # Last state known synced to disk, as (path, dict) — lets the writer
    # skip no-op writes so callers can persist() unconditionally.
    _last_written: tuple[Path, dict] | None = None

    @classmethod
    def set_path(cls, path: Path) -> None:
        cls.path = path

    @classmethod
    def get_config(cls) -> Config:
        if cls._config is None:
            cls._config = Config.parse_config(cls.path)
            with cls._cond:
                cls._last_written = (cls.path, asdict(cls._config))
        return cls._config

    @classmethod
    def set_telemetry_mode(
        cls, mode: TelemetryMode | str, persist: bool = True
    ) -> None:
        cfg = cls.get_config()
        cfg.telemetry_mode = (
            mode.value if isinstance(mode, TelemetryMode) else TelemetryMode(mode).value
        )
        if persist:
            cls.persist()

    @classmethod
    def set_telemetry_feed(
        cls, feed_id: str, version: str = "", persist: bool = True
    ) -> None:
        """Record which feed is installed, and which build of it.

        The version is what lets a later image tell whether the feed on /data
        is the one it was tested against.
        """
        cfg = cls.get_config()
        cfg.telemetry_feed = str(feed_id)
        cfg.telemetry_feed_version = str(version)
        if persist:
            cls.persist()

    @classmethod
    def set_udp_host(cls, host: str, persist: bool = True) -> None:
        """Which interface the NDJSON reader binds.

        127.0.0.1 for a proxy installed on this device: the only sender is
        local, so nothing off-box should be able to inject frames. A feed's PC
        agent sends from the game PC instead, and those packets only arrive if
        the reader is listening on the LAN interface (0.0.0.0).
        """
        cfg = cls.get_config()
        cfg.udp_host = str(host).strip() or "127.0.0.1"
        if persist:
            cls.persist()

    @classmethod
    def set_direct_host(cls, host: str, persist: bool = True) -> None:
        cfg = cls.get_config()
        cfg.direct_host = str(host).strip()
        if persist:
            cls.persist()

    @classmethod
    def set_diff_reference_mode(
        cls, mode: DiffReferenceMode | str, persist: bool = True
    ) -> None:
        cfg = cls.get_config()
        cfg.diff_reference_mode = (
            mode.value
            if isinstance(mode, DiffReferenceMode)
            else DiffReferenceMode(mode).value
        )
        if persist:
            cls.persist()

    @classmethod
    def set_status_lights(cls, enabled: bool, persist: bool = True) -> None:
        cfg = cls.get_config()
        cfg.status_lights = bool(enabled)
        if persist:
            cls.persist()

    @classmethod
    def set_shift_lights(cls, enabled: bool, persist: bool = True) -> None:
        cfg = cls.get_config()
        cfg.shift_lights = bool(enabled)
        if persist:
            cls.persist()

    @classmethod
    def set_dashboard_slot(cls, slot: int, persist: bool = True) -> None:
        cfg = cls.get_config()
        cfg.dashboard_slot = int(slot)
        if persist:
            cls.persist()

    @classmethod
    def set_accel_test_distance(cls, meters: int, persist: bool = True) -> None:
        cfg = cls.get_config()
        cfg.accel_test_distance = int(meters)
        if persist:
            cls.persist()

    @classmethod
    def set_brightness_percent(cls, brightness: int, persist: bool = True) -> None:
        cfg = cls.get_config()
        cfg.brightness = int(brightness)
        if persist:
            cls.persist()

    @classmethod
    def persist(cls) -> None:
        """Queue a write of the current in-memory config to disk.

        Pair with the setters' ``persist=False`` to apply a change live
        (e.g. so DeltaSignal reacts immediately) while batching the actual
        disk write until the caller knows no more changes are coming —
        e.g. once when the user leaves a settings view, rather than once
        per toggle. This app runs off an SD card, where writes wear out
        the storage faster than on typical disks — and can take long enough
        to stall the UI thread if done synchronously, so the file I/O runs
        on a single long-lived background thread. The dict snapshot is
        taken now (on the caller's thread) so later in-memory config
        changes can't race the write.

        Safe to call from any thread, as often as convenient: calls issued
        before the writer runs coalesce into one write of the latest state,
        and a snapshot matching what's already on disk is skipped without
        I/O. The write completes after this returns — write errors are
        logged by the writer, not raised here; flush() blocks until queued
        writes have drained (main.py does at shutdown).
        """
        cfg = cls.get_config()  # may parse from disk; keep out of the lock
        with cls._cond:
            if cls._persistence_disabled:
                return
            # Snapshot inside the lock so snapshot+publish is atomic — two
            # racing persists can't publish an older snapshot over a newer.
            cls._pending = (asdict(cfg), cls.path)
            if cls._writer is None or not cls._writer.is_alive():
                cls._writer = threading.Thread(
                    target=cls._writer_loop, name="config-writer", daemon=True
                )
                cls._writer.start()
            cls._cond.notify_all()

    @classmethod
    def _writer_loop(cls) -> None:
        while True:
            try:
                with cls._cond:
                    while cls._pending is None:
                        cls._cond.wait()
                    snapshot, path = cls._pending
                    cls._pending = None
                    cls._writing = True
                    last = cls._last_written
                try:
                    if (path, snapshot) != last:
                        # Module-global lookup on purpose — tests monkeypatch
                        # _write_config_dict to observe writes.
                        _write_config_dict(snapshot, path)
                    with cls._cond:
                        cls._last_written = (path, snapshot)
                except Exception:
                    # _last_written stays put, so the next persist() of this
                    # same state retries the write instead of skipping it.
                    LOGGER.exception(f"Failed to write config to {path}")
                finally:
                    with cls._cond:
                        cls._writing = False
                        cls._cond.notify_all()
            except Exception:
                LOGGER.exception("Config writer loop error")

    @classmethod
    def flush(cls, timeout: float | None = None) -> bool:
        """Block until every persist() issued before this call has drained
        (written to disk, or skipped as a no-op). Persists issued while
        waiting are not chased. Returns False only if ``timeout`` (seconds)
        elapsed first — a failed write still counts as drained (the writer
        logs it).
        """
        with cls._cond:
            return cls._cond.wait_for(
                lambda: cls._pending is None and not cls._writing, timeout
            )

    @classmethod
    def disable_persistence(cls) -> None:
        """Drop pending writes and refuse all further ones, permanently.

        Called by the factory reset right before it wipes the config file
        on the appliance: the process is about to die (reboot), and any
        teardown that persists on exit — SetupState does — would otherwise
        faithfully resurrect the just-erased file from the still-live
        in-memory config, personal data (entered IPs) included. The
        writer's no-op skip cannot catch this: ``_last_written`` only
        knows what *this process* wrote, which after a settings-free
        session is nothing.
        """
        with cls._cond:
            cls._persistence_disabled = True
            cls._pending = None
            cls._cond.notify_all()

    @classmethod
    def reset(cls) -> None:
        """Clear the cached config instance. Intended for use in tests."""
        if not cls.flush(timeout=2.0):
            LOGGER.warning("Config writer did not drain before reset")
        with cls._cond:
            cls._pending = None
            cls._last_written = None
            cls._persistence_disabled = False
        cls._config = None

    @classmethod
    def last_connected(cls, ip_address: str) -> None:
        config = cls.get_config()
        if (
            len(config.recent_connected) > 0
            and config.recent_connected[0] == ip_address
        ):
            # already latest connected
            return
        if ip_address in config.recent_connected:
            config.recent_connected.remove(ip_address)
        config.recent_connected.insert(0, ip_address)
        cls.persist()
