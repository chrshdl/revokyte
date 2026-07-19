"""Vendored delta calculator (pure-Python source of ../delta-calculator).

Vendored so the implementation ships inside the OS bundle and is
bytecode-compiled with the image's own interpreter: the previously
separate compiled package (`delta_calculator` .so files) is pinned to a
specific CPython ABI and would break the moment an OS update bumps
Python. Keep this in sync with the upstream repo — copy the *.py sources
verbatim and update __version__ (upstream tags via setuptools_scm).
"""

from .core import DeltaCalculator

__version__ = "0.2.4"
__all__ = ["DeltaCalculator"]
