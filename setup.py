"""Optional Cython compilation of the vendored delta calculator.

The delta calculator (core/delta_calculator) ships as vendored pure-Python
source so it can never skew against the interpreter, but its per-frame
math benefits from compilation. The OS image build opts in by setting

    CYTHONIZE_DELTA_CALCULATOR=1

(see instrument-cluster-os: package/python-instrument-cluster.mk, which
also provides host-python-cython): the modules are then compiled with the
image's own toolchain and interpreter — same performance as the old
prebuilt delta-calculator tarball, none of its ABI pinning. Python's
import system prefers the built .so over the .py sitting next to it, and
falls back to source wherever the flag was off (dev machines, tests).

Everything else about the package build is declarative (pyproject.toml).
"""

import os
import sys

from setuptools import setup

ext_modules = []
if os.environ.get("CYTHONIZE_DELTA_CALCULATOR") == "1":
    from Cython.Build import cythonize
    from setuptools import Extension

    extra_link_args = []
    if sys.platform.startswith("linux"):
        extra_link_args = ["-Wl,--strip-debug"]

    # Same module set as upstream delta-calculator's setup.py: everything
    # except the pure-NumPy math_lite stand-in.
    _MODULES = ["calculator", "core", "projection", "recorder", "reference"]
    ext_modules = cythonize(
        [
            Extension(
                name=f"instrument_cluster.core.delta_calculator.{mod}",
                sources=[f"src/instrument_cluster/core/delta_calculator/{mod}.py"],
                extra_compile_args=["-O3", "-g0"],
                extra_link_args=extra_link_args,
            )
            for mod in _MODULES
        ],
        compiler_directives={"language_level": "3"},
    )

setup(ext_modules=ext_modules)
