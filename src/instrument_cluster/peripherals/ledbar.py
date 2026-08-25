import os
import time
from abc import ABC, abstractmethod

from ..ui.colors import Color


class LEDBar(ABC):
    NUM_PIXELS: int

    @abstractmethod
    def set_brightness(self, v: float) -> None:
        pass

    @abstractmethod
    def clear(self) -> None:
        pass

    @abstractmethod
    def set_pixel(self, i: int, r: int, g: int, b: int) -> None:
        pass

    @abstractmethod
    def fill(self, r: int, g: int, b: int) -> None:
        pass

    @abstractmethod
    def show(self) -> None:
        pass

    def reset(self) -> None:
        self.clear()
        self.show()

    def self_test(self, duration_s: float = 0.08) -> None:
        """
        Visual confirmation that the LEDBar is active.
        Default: flash blue briefly.
        """
        self.fill(*Color.BLUE.rgb())
        self.show()
        time.sleep(duration_s)
        self.clear()
        self.show()


class FakeLEDBar(LEDBar):
    NUM_PIXELS = 8

    def __init__(self) -> None:
        self._brightness = 1.0
        self._pixels = [Color.BLACK.rgb()] * self.NUM_PIXELS

    def set_brightness(self, v: float) -> None:
        self._brightness = float(v)

    def clear(self) -> None:
        self._pixels = [Color.BLACK.rgb()] * self.NUM_PIXELS

    def set_pixel(self, i: int, r: int, g: int, b: int) -> None:
        self._pixels[i] = (int(r), int(g), int(b))

    def fill(self, r, g, b):
        for i in range(self.NUM_PIXELS):
            self.set_pixel(i, r, g, b)

    def self_test(self, duration_s: float = 0.0) -> None:
        print(f"[{__class__.__name__}] self_test: OK")

    def show(self) -> None:
        def char(pixel: tuple[int, int, int]) -> str:
            return (
                "."
                if pixel == Color.BLACK.rgb()
                else (
                    "R"
                    if pixel == Color.RED.rgb()
                    else "O"
                    if pixel == Color.ORANGE.rgb()
                    else "G"
                    if pixel == Color.GREEN.rgb()
                    else "B"
                )
            )

        # visualization
        print(
            f"[{__class__.__name__}] {''.join(char(pixel) for pixel in self._pixels)}",
            end="\r",
            flush=True,
        )


class BlinktSPI(LEDBar):
    """
    Pimoroni Blinkt! over hardware SPI. Because we <3 fast.

    Wiring:
      DI->GPIO10 (MOSI)
      CI->GPIO11 (SCLK)
      5V/GND as usual
    """

    def __init__(
        self,
        num_pixels: int = 8,
        bus: int = 0,
        device: int = 0,
        max_speed_hz: int = 2_000_000,
    ):
        import spidev

        self.NUM_PIXELS = num_pixels
        self._spi = spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.max_speed_hz = max_speed_hz
        self._spi.mode = 0b00

        self._brightness = 0.10  # 0..1 (we map to 5-bit APA102 global)
        self._buf = [(0, 0, 0)] * self.NUM_PIXELS

        self.reset()

    def set_brightness(self, v: float) -> None:
        self._brightness = max(0.0, min(1.0, float(v)))

    def clear(self) -> None:
        self.fill(0, 0, 0)

    def set_pixel(self, i: int, r: int, g: int, b: int) -> None:
        if 0 <= i < self.NUM_PIXELS:
            self._buf[i] = (int(r), int(g), int(b))

    def fill(self, r: int, g: int, b: int) -> None:
        rgb = (int(r), int(g), int(b))
        self._buf = [rgb] * self.NUM_PIXELS

    def show(self) -> None:
        # APA102 frame:
        # start frame: 4x 0x00
        # LED frames: [0b111xxxxx, B, G, R] * N
        # end frame: at least (N+15)//16 bytes of 0xFF
        gb = int(self._brightness * 31)  # 0..31
        gb = 0 if gb < 0 else min(gb, 31)
        global_byte = 0b1110_0000 | gb

        # pre-allocate bytearray for speed
        # start(4) + LEDs(N*4) + end(N/16 rounded up)
        end_frame_len = max(4, (self.NUM_PIXELS + 15) // 16)
        out = bytearray([0x00] * 4)

        for r, g, b in self._buf:
            out.append(global_byte)
            out.append(b & 0xFF)  # B
            out.append(g & 0xFF)  # G
            out.append(r & 0xFF)  # R

        # append end frame
        out.extend([0x00] * end_frame_len)

        self._spi.xfer2(out)


"""
LP5036 shift-light bar driver.

Drop-in replacement for BlinktSPI. Same LEDBar interface, so nothing above
this class changes: set_pixel / fill / clear / set_brightness / show all keep
their existing semantics and signatures.

Requires: smbus2, gpiozero
    pip install smbus2 gpiozero

Register map is shared by LP5030 and LP5036 per TI's "hardware and software
compatible" claim, but the Linux and Zephyr in-tree drivers disagree on
whether LP5030 shifts OUT0_COLOR down to 0x12. If you spec the LP5030,
re-derive the base addresses from the datasheet before trusting this file.
"""


from collections.abc import Sequence

# Registers (LP5036, 12 modules / 36 channels)
_DEVICE_CONFIG0 = 0x00
_DEVICE_CONFIG1 = 0x01
_LED_CONFIG0 = 0x02
_LED_CONFIG1 = 0x03
_BANK_BRIGHTNESS = 0x04
_LED0_BRIGHTNESS = 0x08  # 0x08..0x13, one byte per RGB module
_OUT0_COLOR = 0x14  # 0x14..0x37, one byte per channel
_RESET = 0x38

# DEVICE_CONFIG0
_CHIP_EN = 1 << 6

# DEVICE_CONFIG1
_LED_GLOBAL_OFF = 1 << 0
_MAX_CURRENT_35MA = 1 << 1
_PWM_DITHERING_EN = 1 << 2
_AUTO_INCR_EN = 1 << 3
_POWER_SAVE_EN = 1 << 4
_LOG_SCALE_EN = 1 << 5

_NUM_MODULES = 12
_NUM_CHANNELS = _NUM_MODULES * 3

_ENABLE_DELAY_S = 0.0005
_DISABLE_DELAY_S = 0.00001


def _gamma_table(gamma: float = 2.2) -> bytes:
    return bytes(round(((i / 255.0) ** gamma) * 255.0) for i in range(256))


class LP5036Bar(LEDBar):
    """
    Ten-LED shift-light bar driven by a TI LP5036 over I2C.

    Wiring:
      SDA  -> GPIO2  (pin 3)
      SCL  -> GPIO3  (pin 5)
      EN   -> GPIO17 (pin 11), pulled down on the bar
      VCC  -> 3V3    (pin 1)
      VLED -> from the main 5 V supply, NOT the Pi header

    CHANNEL_MAP is the only board-specific part. Each entry is the
    (red, green, blue) output index for one physical LED, left to right.
    Keep each LED's three channels inside one module -- OUT 3n, 3n+1, 3n+2 --
    because LEDn_BRIGHTNESS dims per module, not per channel. Permuting R/G/B
    *within* a triplet is free and lets layout route the shortest traces.
    """

    CHANNEL_MAP: Sequence[tuple[int, int, int]] = tuple(
        (3 * i, 3 * i + 1, 3 * i + 2) for i in range(10)
    )

    def __init__(
        self,
        num_pixels: int = 10,
        bus: int = 1,
        address: int = 0x30,  # ADDR0=ADDR1=GND; 0x30..0x33 available
        enable_pin: int | None = 17,
        gamma: float | None = 2.2,
        max_current_35ma: bool = False,
    ):
        from smbus2 import SMBus

        if num_pixels > len(self.CHANNEL_MAP):
            raise ValueError(
                f"CHANNEL_MAP covers {len(self.CHANNEL_MAP)} pixels, asked for {num_pixels}"
            )

        self.NUM_PIXELS = num_pixels
        self._addr = address
        self._config1 = (
            _AUTO_INCR_EN
            | _PWM_DITHERING_EN
            | _LOG_SCALE_EN
            | (_MAX_CURRENT_35MA if max_current_35ma else 0)
        )
        # Power save deliberately left off: it costs wake latency on the first
        # frame after a dark period, and the dashboard is mains powered anyway.

        self._gamma = _gamma_table(gamma) if gamma else bytes(range(256))
        self._buf = [(0, 0, 0)] * self.NUM_PIXELS
        self._out = bytearray(_NUM_CHANNELS)  # persistent: spare channels survive
        self._brightness = 0.10
        self._brightness_dirty = True

        self._en = None
        if enable_pin is not None:
            from gpiozero import DigitalOutputDevice

            self._en = DigitalOutputDevice(enable_pin, initial_value=False)

        self._bus = SMBus(bus)
        self._power_up()

    # ---- lifecycle -------------------------------------------------------

    def _power_up(self) -> None:
        if self._en is not None:
            self._en.off()
            time.sleep(_DISABLE_DELAY_S)
            self._en.on()
            time.sleep(_ENABLE_DELAY_S)
        self._write(_DEVICE_CONFIG0, _CHIP_EN)
        self._write(_DEVICE_CONFIG1, self._config1)
        self._write(_LED_CONFIG0, 0x00)  # independent control, not bank
        self._write(_LED_CONFIG1, 0x00)
        self._brightness_dirty = True
        self._out = bytearray(_NUM_CHANNELS)
        self.show()

    def reset(self) -> None:
        self._write(_RESET, 0xFF)
        time.sleep(0.01)
        self._power_up()

    def close(self) -> None:
        try:
            self._write(_DEVICE_CONFIG0, 0x00)
        except OSError:
            pass
        if self._en is not None:
            self._en.off()
            self._en.close()
        self._bus.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- LEDBar interface ------------------------------------------------

    def set_brightness(self, v: float) -> None:
        v = max(0.0, min(1.0, float(v)))
        if v != self._brightness:
            self._brightness = v
            self._brightness_dirty = True

    def clear(self) -> None:
        self.fill(0, 0, 0)

    def set_pixel(self, i: int, r: int, g: int, b: int) -> None:
        if 0 <= i < self.NUM_PIXELS:
            self._buf[i] = (int(r), int(g), int(b))

    def fill(self, r: int, g: int, b: int) -> None:
        self._buf = [(int(r), int(g), int(b))] * self.NUM_PIXELS

    def show(self) -> None:
        g = self._gamma
        for i, (r, gr, b) in enumerate(self._buf):
            r_out, g_out, b_out = self.CHANNEL_MAP[i]
            self._out[r_out] = g[r & 0xFF]
            self._out[g_out] = g[gr & 0xFF]
            self._out[b_out] = g[b & 0xFF]

        try:
            if self._brightness_dirty:
                level = round(self._brightness * 255)
                self._write_block(_LED0_BRIGHTNESS, bytes([level]) * _NUM_MODULES)
                self._brightness_dirty = False
            self._write_block(_OUT0_COLOR, bytes(self._out))
        except OSError:
            # I2C wedges under EMI. Toggle EN, re-init, retry once; if that
            # fails let it propagate so the caller can fall back.
            self._power_up()
            self._write_block(_OUT0_COLOR, bytes(self._out))

    def self_test(self) -> None:
        cfg = self._read(_DEVICE_CONFIG0)
        if not cfg & _CHIP_EN:
            raise RuntimeError(
                f"LP5036 at 0x{self._addr:02x} did not latch CHIP_EN "
                f"(read 0x{cfg:02x}); check EN, VCC and I2C ACK"
            )
        for colour in ((255, 0, 0), (0, 255, 0), (0, 0, 255)):
            self.fill(*colour)
            self.show()
            time.sleep(0.12)
        self.clear()
        self.show()

    # ---- I2C plumbing ----------------------------------------------------

    def _write(self, reg: int, value: int) -> None:
        self._bus.write_byte_data(self._addr, reg, value)

    def _read(self, reg: int) -> int:
        return self._bus.read_byte_data(self._addr, reg)

    def _write_block(self, reg: int, payload: bytes) -> None:
        # write_i2c_block_data caps at 32 data bytes (SMBus limit), and a full
        # colour update is 36. Use a raw I2C transaction instead.
        from smbus2 import i2c_msg

        self._bus.i2c_rdwr(i2c_msg.write(self._addr, bytes([reg]) + payload))


def create_ledbar() -> LEDBar:
    # /dev/i2c-1 exists whenever I2C is enabled, whether or not the bar is
    # plugged in -- so probe the chip, don't just stat the device node.
    if os.path.exists("/dev/i2c-1"):
        try:
            bar = LP5036Bar()
            bar.self_test()
            return bar
        except (OSError, RuntimeError, ImportError):
            pass
    if os.path.exists("/dev/spidev0.0"):
        bar = BlinktSPI()
        bar.self_test()
        return bar

    return FakeLEDBar()
