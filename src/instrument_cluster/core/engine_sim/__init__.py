"""Crank-angle-resolved single-zone engine simulation.

A self-contained compute library (no bus/UI imports), sibling of
``core/delta_calculator``: slider-crank kinematics, parametric cam
profiles with compressible valve flow, Wiebe combustion anchored at a
CA50 timing target, Woschni heat transfer and Chen-Flynn friction.

The expensive integrator never runs on the frame loop: ``EngineSimService``
bakes an RPM x throttle torque/fuel map on a background thread and the
runtime interpolates it (see ``service.py`` / ``torque_map.py``).
"""

__version__ = "0.1.0"
