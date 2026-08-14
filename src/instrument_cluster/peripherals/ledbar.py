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


def create_ledbar() -> LEDBar:
    if os.path.exists("/dev/spidev0.0"):
        bar = BlinktSPI()
        bar.self_test()
        return bar

    return FakeLEDBar()
