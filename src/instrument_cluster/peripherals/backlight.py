from pathlib import Path
from typing import Optional

SYSFS_BACKLIGHT_ROOT = Path("/sys/class/backlight")


class Backlight:
    """
    Controls the display backlight via Linux sysfs interface.

    Attributes:
        _brightness_path (Path): Path to the 'brightness' file (actuator).
        _max_brightness (int): The maximum integer value supported by the driver.
    """

    def __init__(self) -> None:
        self._brightness_path: Optional[Path] = None
        self._max_brightness: int = 100
        self._available: bool = False

        self._initialize_hardware()

    def _initialize_hardware(self) -> None:
        """
        Detects the first available backlight driver and caches hardware capabilities.
        """
        if not SYSFS_BACKLIGHT_ROOT.exists():
            return

        try:
            candidates = sorted(list(SYSFS_BACKLIGHT_ROOT.iterdir()))
            for candidate in candidates:
                brightness_file = candidate / "brightness"
                max_brightness_file = candidate / "max_brightness"

                if brightness_file.exists():
                    self._brightness_path = brightness_file
                    self._max_brightness = self._read_int_file(
                        max_brightness_file, default=100
                    )
                    self._available = True
                    break
        except OSError:
            # sysfs might be temporarily unreadable during boot or permissions issues
            self._available = False

    def _read_int_file(self, path: Path, default: int) -> int:
        """
        Safely reads an integer from a sysfs file.

        Args:
            path: The Path object to read from.
            default: The fallback value if reading fails.

        Returns:
            int: The integer value from the file, or default on error.
        """
        try:
            # 'read_text' handles open/close/encoding automatically
            content = path.read_text(encoding="utf-8").strip()
            return int(content)
        except (ValueError, OSError):
            # ValueError: File content is not an integer (empty or garbage)
            # OSError: File not found, permission denied, or I/O error
            return default

    @property
    def available(self) -> bool:
        """Returns True if a valid backlight driver was found and initialized."""
        return self._available

    def set_percent(self, percent: int) -> bool:
        """
        Sets the backlight brightness as a percentage (0-100).

        This method scales the requested percentage to the hardware's native resolution
        (e.g., scaling 50% to step 15 on a 0-31 scale device).

        Args:
            percent: Integer between 0 and 100.

        Returns:
            bool: True if the write was successful, False otherwise.
        """
        if not self._available or self._brightness_path is None:
            return False

        clamped_pct = max(0, min(100, percent))

        hw_value = int(round((clamped_pct / 100.0) * self._max_brightness))

        try:
            self._brightness_path.write_text(str(hw_value), encoding="utf-8")
            return True
        except (OSError, ValueError):
            return False

    def get_percent(self) -> int:
        """
        Reads the current hardware brightness and converts it back to percentage.

        Note: Due to low-resolution hardware (e.g., 31 steps), this value may
        differ slightly from the value set previously (aliasing).

        Returns:
            int: Current brightness percentage (0-100), or 0 if unavailable.
        """
        if not self._available or self._brightness_path is None:
            return 0

        current_hw_val = self._read_int_file(self._brightness_path, default=0)

        if self._max_brightness <= 0:
            return 0

        return int(round((current_hw_val / self._max_brightness) * 100.0))
