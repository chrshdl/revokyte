import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Where a release image can leave a log the owner can actually read. There
# is no SSH and the journal is volatile, so the boot partition — FAT32, and
# mounted by any desktop OS when the card is inserted — is the only way a
# log gets off the device. Writing there is opt-in: the user drops an empty
# file named like the marker below, reproduces the fault, powers off and
# reads the log on their computer. Devices without the marker never touch
# the boot partition (flash wear, and a FAT filesystem is easy to corrupt
# with a power cut mid-write).
DEBUG_MARKER = Path("/boot/instrument-cluster-debug")
DEBUG_LOG_PATH = Path("/boot/instrument-cluster.log")
DEBUG_LOG_ENV = "IC_DEBUG_LOG"  # explicit path; overrides the marker

_file_log_configured = False


def _resolve_debug_log_path() -> Path | None:
    override = os.environ.get(DEBUG_LOG_ENV)
    if override:
        return Path(override)
    try:
        if DEBUG_MARKER.exists():
            return DEBUG_LOG_PATH
    except OSError:
        pass
    return None


def install_debug_file_log() -> Path | None:
    """Mirror all logging to a file when debugging is requested.

    Attached to the root logger, so every module's records land there
    regardless of import order. Returns the path being written to, or None.
    Never raises: a logging problem must not take the cluster down.
    """
    global _file_log_configured
    if _file_log_configured:
        return None
    _file_log_configured = True

    path = _resolve_debug_log_path()
    if path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Small and rotated: /boot is a 64 MB FAT partition.
        handler = RotatingFileHandler(
            path, maxBytes=512 * 1024, backupCount=1, encoding="utf-8"
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(LogFormatter.format_text))
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
    except OSError as e:
        logging.getLogger("logger").warning(f"Could not open debug log {path}: {e}")
        return None
    return path


class Logger:
    def __init__(self, name: str):
        self.logger: logging.Logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        # `self.logger.handlers`, NOT `hasHandlers()`. hasHandlers() walks the
        # ancestor chain, and install_debug_file_log() attaches its file
        # handler to the *root* logger — so the moment the debug marker was
        # present, hasHandlers() went True for every named logger and none of
        # them ever got a StreamHandler. Turning the support log on therefore
        # turned console/journal logging off, which is the opposite of what a
        # debug switch should do: a field device with the marker set produced
        # a journal containing pygame's banner and nothing else, and a device
        # whose /boot could not be written produced no log at all, anywhere.
        # The two sinks are independent; keep them that way.
        if not self.logger.handlers:
            sh = logging.StreamHandler()
            sh.setLevel(logging.DEBUG)
            sh.setFormatter(LogFormatter())
            self.logger.addHandler(sh)

        # After the console handler is attached, so that a failure to open the
        # debug log is reported somewhere a person can actually read.
        install_debug_file_log()

    def get(self) -> logging.Logger:
        return self.logger


class LogFormatter(logging.Formatter):
    grey: str = "\x1b[38;20m"
    yellow: str = "\x1b[33;20m"
    red: str = "\x1b[91;20m"
    reset: str = "\x1b[0m"
    format_text: str = (
        "%(asctime)s  | %(levelname)s | %(message)s  (%(filename)s:%(lineno)d)"
    )

    FORMATS: dict[int, str] = {
        logging.DEBUG: grey + format_text + reset,
        logging.INFO: grey + format_text + reset,
        logging.WARNING: yellow + format_text + reset,
        logging.ERROR: red + format_text + reset,
    }

    def format(self, record: logging.LogRecord) -> str:
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)
