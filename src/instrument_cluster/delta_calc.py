def make_delta_calculator():
    """The real delta calculator, with a no-op stand-in as the safety net.

    The implementation is vendored pure-Python source
    (core/delta_calculator, from ../delta-calculator) rather than the old
    separately-installed compiled package: .so files are pinned to one
    CPython ABI and would break the moment an OS update bumps the
    interpreter, while vendored source is bytecode-compiled with whatever
    Python the image ships. A stale site-packages delta_calculator on
    already-deployed devices is simply ignored.
    """
    try:
        from .core.delta_calculator import DeltaCalculator

        return DeltaCalculator()
    except Exception:
        from .delta_calc_fallback import DummyDeltaCalculator

        return DummyDeltaCalculator()
