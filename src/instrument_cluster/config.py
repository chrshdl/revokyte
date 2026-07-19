import json
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from json import JSONDecodeError
from pathlib import Path
from typing import Optional

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


# Map old persisted values (with double spaces) to the corrected single-spaced form.
_LEGACY_DIFF_MODE_MAP = {
    "previous  lap": "previous lap",
    "fastest  lap": "fastest lap",
}


@dataclass
class Config:
    # Legacy fields, kept only so existing config.json files still parse.
    # The render/layout resolution is now the fixed logical design size in
    # display.py (1280x720); these are ignored. Pick a panel via `display`.
    width: int = field(default=1280)
    height: int = field(default=720)
    # Display profile selector: "auto" (detect by panel resolution),
    # "rpi_display_2", "waveshare_7", or "dev". See display.py.
    display: str = field(default="auto")
    telemetry_mode: str = field(default=TelemetryMode.DEMO.value)
    # Opaque id (see addons/feeds.py) of the last-installed feed, used only so
    # the settings dropdown can show the current selection when telemetry_mode
    # is "udp". The app never branches on its value.
    telemetry_feed: str = field(default="")
    diff_reference_mode: str = field(default=DiffReferenceMode.FASTEST.value)
    recent_connected: list[str] = field(default_factory=list)
    udp_host: str = field(default="127.0.0.1")
    udp_port: int = field(default=5600)
    brightness: int = 50
    # Show the bezel status LEDs (TC/ASM) on the dashboard; off also
    # returns the widget columns to the strip-less layout.
    status_lights: bool = field(default=False)
    # Active dashboard page selection, owned by the exclusive dashboard
    # provider plugin (0 = the built-in default). An invalid or
    # no-longer-available value silently falls back to the default.
    dashboard_slot: int = field(default=0)

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

        if "diff_reference_mode" in config:
            config["diff_reference_mode"] = _LEGACY_DIFF_MODE_MAP.get(
                config["diff_reference_mode"], config["diff_reference_mode"]
            )

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

        valid_telemetry_modes = {m.value for m in TelemetryMode}
        if self.telemetry_mode not in valid_telemetry_modes:
            LOGGER.warning(
                "Invalid telemetry_mode %r — defaulting to demo.", self.telemetry_mode
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
    _config: Optional[Config] = None
    # Serializes background writes so two overlapping persist() calls can't
    # race each other's temp file.
    _write_lock = threading.Lock()

    @classmethod
    def set_path(cls, path: Path) -> None:
        cls.path = path

    @classmethod
    def get_config(cls) -> Config:
        if cls._config is None:
            cls._config = Config.parse_config(cls.path)
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
            cfg.write_to_file(cls.path)

    @classmethod
    def set_telemetry_feed(cls, feed_id: str, persist: bool = True) -> None:
        cfg = cls.get_config()
        cfg.telemetry_feed = str(feed_id)
        if persist:
            cfg.write_to_file(cls.path)

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
            cfg.write_to_file(cls.path)

    @classmethod
    def set_status_lights(cls, enabled: bool, persist: bool = True) -> None:
        cfg = cls.get_config()
        cfg.status_lights = bool(enabled)
        if persist:
            cfg.write_to_file(cls.path)

    @classmethod
    def set_dashboard_slot(cls, slot: int, persist: bool = True) -> None:
        cfg = cls.get_config()
        cfg.dashboard_slot = int(slot)
        if persist:
            cfg.write_to_file(cls.path)

    @classmethod
    def set_brightness_percent(cls, brightness: int, persist: bool = True) -> None:
        cfg = cls.get_config()
        cfg.brightness = int(brightness)
        if persist:
            cfg.write_to_file(cls.path)

    @classmethod
    def persist(cls) -> None:
        """Write the current in-memory config to disk, off the main thread.

        Pair with the setters' ``persist=False`` to apply a change live
        (e.g. so DeltaSignal reacts immediately) while batching the actual
        disk write until the caller knows no more changes are coming —
        e.g. once when the user leaves a settings view, rather than once
        per toggle. This app runs off an SD card, where writes wear out
        the storage faster than on typical disks — and can take long enough
        to stall the UI thread if done synchronously, so the actual file
        I/O runs in a background thread. The dict snapshot is taken now
        (on the caller's thread) so later in-memory config changes can't
        race the write.
        """
        config_dict = asdict(cls.get_config())
        path = cls.path

        def _write():
            with cls._write_lock:
                _write_config_dict(config_dict, path)

        threading.Thread(target=_write, daemon=True).start()

    @classmethod
    def reset(cls) -> None:
        """Clear the cached config instance. Intended for use in tests."""
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
        config.write_to_file(cls.path)
