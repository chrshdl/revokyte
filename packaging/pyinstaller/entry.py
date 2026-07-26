"""Desktop entry point for the PyInstaller build.

Equivalent to ``python -m instrument_cluster``; PyInstaller needs a plain
script rather than a ``-m`` module reference.
"""

import multiprocessing

from instrument_cluster.main import main

if __name__ == "__main__":
    # Required guard for frozen Windows executables: without it, any
    # multiprocessing use (even inside a dependency) respawns the app.
    multiprocessing.freeze_support()
    main()
