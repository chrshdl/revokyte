"""
Unit tests for delta_calculator.core module.

Tests cover:
- LapRecorder: distance filtering, _last_pos freeze bug regression, reset
- ReferenceManager: reference building, fastest-only mode
- DeltaCalculator: integration with lap transitions and delta calculation
"""

import numpy as np
import pytest

from instrument_cluster.core.delta_calculator.core import (
    DeltaCalculator,
    LapRecorder,
    ProjectionResult,
    ReferenceManager,
    ReferenceTrajectory,
)


class Drive:
    """Feeds ``DeltaCalculator.process`` with GT7's master lap clock.

    ``current_lap_time`` is now the authoritative clock and a new lap is defined
    by that clock *resetting* (not by ``lap_index``). This helper mirrors GT7:
    it advances the clock by ``dt`` each running frame and resets it to ~0 when
    ``lap_index`` ticks — which is what drives the reference build in the
    calculator. A frozen clock while ``running=False`` matches GT7 pausing.
    """

    def __init__(self) -> None:
        self.ms = 0
        self._lap = None

    def __call__(self, calc, lap_index, dt, x, y, z, running=True):
        if running:
            if lap_index != self._lap:
                self.ms = 0  # new lap -> master clock resets -> boundary
                self._lap = lap_index
            self.ms += int(round(dt * 1000))
        return calc.process(
            lap_index=lap_index, dt=dt, x=x, y=y, z=z, running=running,
            gt7_lap_time_ms=self.ms,
        )


# =============================================================================
# LapRecorder Tests
# =============================================================================


class TestLapRecorder:
    """Tests for LapRecorder."""

    def test_first_point_always_recorded(self):
        """First point should always be accepted."""
        rec = LapRecorder(min_step_m=5.0, max_step_m=60.0)
        assert rec.record(0.0, 0.0, 0.0, 0.0) is True
        assert rec.point_count == 1

    def test_point_within_range_recorded(self):
        """Points between min and max step should be recorded."""
        rec = LapRecorder(min_step_m=5.0, max_step_m=60.0)
        rec.record(0.0, 0.0, 0.0, 0.0)
        # Move 10m in X — within [5, 60] range
        assert rec.record(10.0, 0.0, 0.0, 1.0) is True
        assert rec.point_count == 2

    def test_point_too_close_rejected(self):
        """Points closer than min_step_m should be rejected."""
        rec = LapRecorder(min_step_m=5.0, max_step_m=60.0)
        rec.record(0.0, 0.0, 0.0, 0.0)
        # Move only 2m — below min_step_m
        assert rec.record(2.0, 0.0, 0.0, 0.1) is False
        assert rec.point_count == 1

    def test_point_too_far_rejected(self):
        """Points farther than max_step_m should be rejected."""
        rec = LapRecorder(min_step_m=5.0, max_step_m=60.0)
        rec.record(0.0, 0.0, 0.0, 0.0)
        # Move 100m — above max_step_m
        assert rec.record(100.0, 0.0, 0.0, 1.0) is False
        assert rec.point_count == 1

    def test_last_pos_freeze_bug_regression(self):
        """
        Regression test for the _last_pos freeze bug.

        When a point is rejected because it's too far (d > max_step_m),
        _last_pos must still be advanced.  Otherwise all subsequent points
        are also rejected and the entire rest of the lap is unrecorded.
        """
        rec = LapRecorder(min_step_m=5.0, max_step_m=60.0)
        rec.record(0.0, 0.0, 0.0, 0.0)

        # Simulate a large jump (teleport / running=False gap)
        assert rec.record(200.0, 0.0, 0.0, 5.0) is False  # rejected
        assert rec.point_count == 1

        # Next point is 10m from the jumped-to position — should be accepted
        # If _last_pos was NOT advanced, this would also be rejected
        assert rec.record(210.0, 0.0, 0.0, 5.5) is True
        assert rec.point_count == 2

    def test_recording_resumes_after_multiple_jumps(self):
        """Recording should resume even after several consecutive teleports."""
        rec = LapRecorder(min_step_m=5.0, max_step_m=60.0)
        rec.record(0.0, 0.0, 0.0, 0.0)

        # Three consecutive jumps > max_step_m
        rec.record(100.0, 0.0, 0.0, 1.0)
        rec.record(300.0, 0.0, 0.0, 2.0)
        rec.record(500.0, 0.0, 0.0, 3.0)
        assert rec.point_count == 1  # only the first point

        # Now a normal step from 500
        assert rec.record(510.0, 0.0, 0.0, 3.5) is True
        assert rec.point_count == 2

    def test_reset_clears_state(self):
        """Reset should clear all recorded data and position tracking."""
        rec = LapRecorder(min_step_m=5.0, max_step_m=60.0)
        rec.record(0.0, 0.0, 0.0, 0.0)
        rec.record(10.0, 0.0, 0.0, 1.0)
        assert rec.point_count == 2

        rec.reset()
        assert rec.point_count == 0
        assert rec.has_data is False

        # After reset, first point should be recorded again
        assert rec.record(999.0, 0.0, 0.0, 0.0) is True
        assert rec.point_count == 1

    def test_has_data_requires_two_points(self):
        """has_data should be True only with >= 2 points."""
        rec = LapRecorder(min_step_m=5.0, max_step_m=60.0)
        assert rec.has_data is False

        rec.record(0.0, 0.0, 0.0, 0.0)
        assert rec.has_data is False

        rec.record(10.0, 0.0, 0.0, 1.0)
        assert rec.has_data is True

    def test_data_properties(self):
        """xs, ys, zs, times should contain the right data."""
        rec = LapRecorder(min_step_m=5.0, max_step_m=60.0)
        rec.record(1.0, 2.0, 3.0, 0.0)
        rec.record(11.0, 12.0, 13.0, 1.0)

        assert rec.xs == [1.0, 11.0]
        assert rec.ys == [2.0, 12.0]
        assert rec.zs == [3.0, 13.0]
        assert rec.times == [0.0, 1.0]


# =============================================================================
# ReferenceManager Tests
# =============================================================================


class TestReferenceManager:
    """Tests for ReferenceManager."""

    @staticmethod
    def _make_recorder_with_circle(n_points: int = 50) -> LapRecorder:
        """Create a LapRecorder pre-filled with a circular track."""
        rec = LapRecorder(min_step_m=0.1, max_step_m=999.0)
        theta = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
        radius = 100.0
        for i, th in enumerate(theta):
            x = radius * np.cos(th)
            z = radius * np.sin(th)
            rec.record(float(x), 0.0, float(z), float(i) * 0.1)
        return rec

    def test_build_reference_from_recorder(self):
        """Should build a valid reference trajectory."""
        mgr = ReferenceManager(
            resample_spacing_m=5.0,
            min_seg_len_m=1e-3,
        )
        rec = self._make_recorder_with_circle()

        updated = mgr.try_update(rec, lap_time=5.0)
        assert updated is True
        assert mgr.has_reference is True
        assert mgr.trajectory is not None
        assert mgr.trajectory.lap_length > 0

    def test_too_few_points_rejected(self):
        """Should not build a reference from < 2 points."""
        mgr = ReferenceManager(
            resample_spacing_m=5.0,
            min_seg_len_m=1e-3,
        )
        rec = LapRecorder(min_step_m=5.0, max_step_m=60.0)
        rec.record(0.0, 0.0, 0.0, 0.0)

        assert mgr.try_update(rec, lap_time=1.0) is False
        assert mgr.has_reference is False

    def test_fastest_only_keeps_fastest(self):
        """In fastest-only mode, only faster laps should update the reference."""
        mgr = ReferenceManager(
            resample_spacing_m=5.0,
            min_seg_len_m=1e-3,
            use_fastest_only=True,
        )
        rec = self._make_recorder_with_circle()

        # First lap — accepted
        assert mgr.try_update(rec, lap_time=10.0) is True
        v1 = mgr.trajectory.version

        # Slower lap — rejected
        assert mgr.try_update(rec, lap_time=12.0) is False
        assert mgr.trajectory.version == v1

        # Faster lap — accepted. Versions are unique per built lap (the
        # rejected lap above still consumed one for the background
        # previous-lap slot), so assert change rather than exact +1.
        assert mgr.try_update(rec, lap_time=8.0) is True
        assert mgr.trajectory.version > v1

    def test_version_increments(self):
        """Reference version should increment on each accepted update."""
        mgr = ReferenceManager(
            resample_spacing_m=5.0,
            min_seg_len_m=1e-3,
        )
        rec = self._make_recorder_with_circle()

        mgr.try_update(rec, lap_time=5.0)
        assert mgr.trajectory.version == 0

        mgr.try_update(rec, lap_time=5.0)
        assert mgr.trajectory.version == 1

    def test_glitch_fast_lap_rejected(self):
        """An implausibly fast lap (below min_lap_fraction of the best) must be
        rejected so it can't lock itself in as the reference for the session."""
        mgr = ReferenceManager(
            resample_spacing_m=5.0,
            min_seg_len_m=1e-3,
            use_fastest_only=True,
            min_lap_fraction=0.5,
        )
        rec = self._make_recorder_with_circle()

        # Establish a sane reference at 100 s.
        assert mgr.try_update(rec, lap_time=100.0) is True
        v = mgr.trajectory.version

        # A 10 s "lap" is faster but implausible (< 50 % of 100 s) -> rejected.
        assert mgr.try_update(rec, lap_time=10.0) is False
        assert mgr.trajectory.version == v

        # A plausibly faster lap (95 s) is still accepted (version is unique
        # per built lap, not sequential per adoption).
        assert mgr.try_update(rec, lap_time=95.0) is True
        assert mgr.trajectory.version > v

    def test_min_lap_fraction_zero_disables_plausibility_gate(self):
        """Setting min_lap_fraction=0 disables the glitch-fast guard."""
        mgr = ReferenceManager(
            resample_spacing_m=5.0,
            min_seg_len_m=1e-3,
            use_fastest_only=True,
            min_lap_fraction=0.0,
        )
        rec = self._make_recorder_with_circle()

        assert mgr.try_update(rec, lap_time=100.0) is True
        # Even an absurdly fast lap is accepted when the gate is off.
        assert mgr.try_update(rec, lap_time=1.0) is True

    def test_mode_flip_swaps_active_reference_immediately(self):
        """Both slots are maintained regardless of mode, so flipping
        use_fastest_only mid-session swaps the active reference at once —
        a previous-lap stint does not destroy the session-best trajectory."""
        mgr = ReferenceManager(
            resample_spacing_m=5.0,
            min_seg_len_m=1e-3,
            use_fastest_only=False,
        )
        rec = self._make_recorder_with_circle()

        assert mgr.try_update(rec, lap_time=100.0) is True
        assert mgr.try_update(rec, lap_time=90.0) is True   # session best
        assert mgr.try_update(rec, lap_time=110.0) is True  # most recent
        assert float(mgr.trajectory.times[-1]) == pytest.approx(110.0)

        mgr.use_fastest_only = True   # -> the 90 s lap, kept in the background
        assert float(mgr.trajectory.times[-1]) == pytest.approx(90.0)

        mgr.use_fastest_only = False  # and back -> the previous lap again
        assert float(mgr.trajectory.times[-1]) == pytest.approx(110.0)

    def test_fastest_mode_keeps_previous_lap_in_background(self):
        """A lap rejected as 'not faster' still refreshes the previous-lap
        slot, so a later switch to previous-lap mode shows the true last lap."""
        mgr = ReferenceManager(
            resample_spacing_m=5.0,
            min_seg_len_m=1e-3,
            use_fastest_only=True,
        )
        rec = self._make_recorder_with_circle()

        assert mgr.try_update(rec, lap_time=100.0) is True
        assert mgr.try_update(rec, lap_time=120.0) is False  # active unchanged
        assert float(mgr.trajectory.times[-1]) == pytest.approx(100.0)

        mgr.use_fastest_only = False
        assert float(mgr.trajectory.times[-1]) == pytest.approx(120.0)

    def test_stale_best_time_wedge_regression(self):
        """Regression: fastest → previous → fastest used to leave
        _best_lap_time_s pointing at a lap whose trajectory had been
        overwritten during the previous-lap stint. The gate then demanded
        beating a time that no longer matched the active reference, wedging
        the reference on a slow lap. With dual slots the best trajectory
        survives the stint and is active again after the switch."""
        mgr = ReferenceManager(
            resample_spacing_m=5.0,
            min_seg_len_m=1e-3,
            use_fastest_only=True,
        )
        rec = self._make_recorder_with_circle()

        assert mgr.try_update(rec, lap_time=89.0) is True

        mgr.use_fastest_only = False
        assert mgr.try_update(rec, lap_time=93.0) is True
        assert mgr.try_update(rec, lap_time=95.0) is True

        mgr.use_fastest_only = True
        # The 89 s trajectory is immediately active again — not the 95 s lap.
        assert float(mgr.trajectory.times[-1]) == pytest.approx(89.0)
        # And the gate is consistent with what is displayed: 91 s loses to the
        # 89 s lap that really is the reference…
        assert mgr.try_update(rec, lap_time=91.0) is False
        assert "not faster" in mgr.last_reject_reason
        # …while a genuine improvement is adopted.
        assert mgr.try_update(rec, lap_time=87.0) is True
        assert float(mgr.trajectory.times[-1]) == pytest.approx(87.0)

    def test_plausibility_gate_protects_best_slot_in_previous_mode(self):
        """In previous-lap mode a glitch-fast lap becomes the previous-lap
        reference (a bad lap lasts one lap, as before) but must NOT poison
        the fastest slot that a later mode switch relies on."""
        mgr = ReferenceManager(
            resample_spacing_m=5.0,
            min_seg_len_m=1e-3,
            use_fastest_only=False,
            min_lap_fraction=0.5,
        )
        rec = self._make_recorder_with_circle()

        assert mgr.try_update(rec, lap_time=100.0) is True
        assert mgr.try_update(rec, lap_time=10.0) is True  # glitch, but previous mode adopts
        assert float(mgr.trajectory.times[-1]) == pytest.approx(10.0)

        mgr.use_fastest_only = True
        assert float(mgr.trajectory.times[-1]) == pytest.approx(100.0)

    def test_mode_flip_keeps_reference_when_last_is_best(self):
        """When the most recent lap IS the session best, both slots hold the
        same trajectory object — a mode flip changes nothing (same version, so
        downstream continuity is not re-latched spuriously)."""
        mgr = ReferenceManager(
            resample_spacing_m=5.0,
            min_seg_len_m=1e-3,
            use_fastest_only=False,
        )
        rec = self._make_recorder_with_circle()

        assert mgr.try_update(rec, lap_time=100.0) is True
        assert mgr.try_update(rec, lap_time=90.0) is True
        traj = mgr.trajectory

        mgr.use_fastest_only = True
        assert mgr.trajectory is traj

    def test_reject_reason_reports_why(self):
        """last_reject_reason explains each kind of rejection and clears on success."""
        mgr = ReferenceManager(
            resample_spacing_m=5.0,
            min_seg_len_m=1e-3,
            use_fastest_only=True,
            min_lap_fraction=0.5,
        )
        rec = self._make_recorder_with_circle()

        # Successful adoption -> no reason.
        assert mgr.try_update(rec, lap_time=100.0) is True
        assert mgr.last_reject_reason is None

        # Slower lap -> "not faster".
        assert mgr.try_update(rec, lap_time=120.0) is False
        assert "not faster" in mgr.last_reject_reason

        # Glitch-fast lap -> "implausibly fast".
        assert mgr.try_update(rec, lap_time=10.0) is False
        assert "implausibly fast" in mgr.last_reject_reason

        # Adopting again clears the reason.
        assert mgr.try_update(rec, lap_time=95.0) is True
        assert mgr.last_reject_reason is None

    def test_reject_reason_lap_too_short(self):
        """A lap shorter than the resample spacing reports a 'too short' reason."""
        mgr = ReferenceManager(resample_spacing_m=50.0, min_seg_len_m=1e-3)
        rec = LapRecorder(min_step_m=1.0, max_step_m=999.0)
        rec.record(0.0, 0.0, 0.0, 0.0)
        rec.record(2.0, 0.0, 0.0, 1.0)  # total length 2 m < 50 m spacing

        assert mgr.try_update(rec, lap_time=1.0) is False
        assert "too short" in mgr.last_reject_reason

    def test_circle_detected_as_closed_loop(self):
        """A circuit whose start and finish meet is detected as a closed loop."""
        mgr = ReferenceManager(resample_spacing_m=5.0, min_seg_len_m=1e-3)
        rec = self._make_recorder_with_circle(120)
        assert mgr.try_update(rec, lap_time=10.0) is True
        assert mgr.trajectory.closed is True

    def test_project_constrained_wraps_across_seam(self):
        """On a closed loop the constrained window wraps the start/finish seam,
        so a search anchored at the last segment still reaches a segment just
        past the start. An equivalent open trajectory cannot, proving the wrap
        is what finds it."""
        mgr = ReferenceManager(resample_spacing_m=5.0, min_seg_len_m=1e-3)
        rec = self._make_recorder_with_circle(120)
        assert mgr.try_update(rec, lap_time=10.0) is True
        traj = mgr.trajectory
        assert traj.closed is True

        num_segs = len(traj.seg_p0)
        # A point exactly on segment 3, just past the seam.
        q = traj.seg_p0[3] + 0.5 * traj.seg_vec[3]

        # Anchored at the LAST segment, the wrapped window reaches segment 3.
        proj = traj.project_constrained(q, last_seg_idx=num_segs - 1, max_seg_jump=5)
        assert proj is not None
        assert proj.dist_3d < 0.5
        assert proj.seg_idx <= 5  # found on the start side via wrap

        # Same geometry, but forced open: the search can't wrap and misses it.
        pts = np.vstack((traj.seg_p0, traj.seg_p0[-1] + traj.seg_vec[-1]))
        open_traj = ReferenceTrajectory(
            s=traj.s, times=traj.times, points=pts, closed=False,
        )
        proj_open = open_traj.project_constrained(
            q, last_seg_idx=num_segs - 1, max_seg_jump=5,
        )
        assert proj_open is not None
        assert proj_open.seg_idx > num_segs // 2  # stuck near the end
        assert proj_open.dist_3d > 5.0


# =============================================================================
# ReferenceTrajectory Tests
# =============================================================================


class TestReferenceTrajectory:
    """Tests for ReferenceTrajectory projection logic."""

    @staticmethod
    def _make_straight_line_traj() -> ReferenceTrajectory:
        """Create a simple straight-line reference (X axis, 0-100m)."""
        n = 21
        s = np.linspace(0, 100, n, dtype=np.float32)
        t = np.linspace(0, 10, n, dtype=np.float32)
        points = np.column_stack([
            s,
            np.zeros(n, dtype=np.float32),
            np.zeros(n, dtype=np.float32),
        ])
        return ReferenceTrajectory(s=s, times=t, points=points)

    def test_project_on_line(self):
        """Point exactly on the line should have near-zero distance."""
        traj = self._make_straight_line_traj()
        proj = traj.project(np.array([50.0, 0.0, 0.0]))
        assert proj is not None
        assert proj.dist_3d < 0.1
        assert proj.s == pytest.approx(50.0, abs=1.0)

    def test_project_off_line(self):
        """Point offset from line should have correct lateral distance."""
        traj = self._make_straight_line_traj()
        proj = traj.project(np.array([50.0, 0.0, 10.0]))
        assert proj is not None
        assert proj.dist_h == pytest.approx(10.0, abs=1.0)

    def test_get_time_at_s(self):
        """Time interpolation should be linear for linear data."""
        traj = self._make_straight_line_traj()
        assert traj.get_time_at_s(0.0) == pytest.approx(0.0, abs=0.1)
        assert traj.get_time_at_s(50.0) == pytest.approx(5.0, abs=0.2)
        assert traj.get_time_at_s(100.0) == pytest.approx(10.0, abs=0.1)

    def test_project_constrained(self):
        """Constrained projection should only look at nearby segments."""
        traj = self._make_straight_line_traj()
        # Project at segment 10 (s ≈ 50m), constrained to ±2 segments
        proj = traj.project_constrained(
            np.array([50.0, 0.0, 0.0]), last_seg_idx=10, max_seg_jump=2,
        )
        assert proj is not None
        assert proj.dist_3d < 0.1

    def test_straight_line_detected_as_open(self):
        """A point-to-point line (endpoints far apart) is not a closed loop."""
        traj = self._make_straight_line_traj()
        assert traj.closed is False


# =============================================================================
# DeltaCalculator Integration Tests
# =============================================================================


class TestDeltaCalculator:
    """Integration tests for DeltaCalculator."""

    def test_no_delta_on_first_lap(self):
        """No delta should be produced until a reference exists."""
        calc = DeltaCalculator(min_step_m=1.0, max_step_m=999.0)
        drive = Drive()
        result = drive(calc, lap_index=1, dt=0.016, x=0.0, y=0.0, z=0.0)
        assert result is None

    def test_delta_after_lap_change(self):
        """After completing a lap, delta should be produced on the next lap."""
        calc = DeltaCalculator(
            min_step_m=1.0, max_step_m=999.0, resample_spacing_m=2.0,
        )
        drive = Drive()

        # Lap 1: drive a straight line to build reference
        for i in range(100):
            drive(calc, lap_index=1, dt=0.1, x=float(i * 2), y=0.0, z=0.0)

        # Transition to lap 2 — the clock reset triggers the reference build
        result = drive(calc, lap_index=2, dt=0.1, x=0.0, y=0.0, z=0.0)

        # There should now be a reference, try a few more points
        for i in range(1, 20):
            result = drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)

        # At some point, delta should be produced
        assert result is not None

    def test_not_running_does_not_accumulate_time(self):
        """When running=False, lap time should not increase."""
        calc = DeltaCalculator(min_step_m=1.0, max_step_m=999.0)
        drive = Drive()
        drive(calc, lap_index=1, dt=0.1, x=0.0, y=0.0, z=0.0)
        time_after_running = calc._lap_time_s

        drive(calc, lap_index=1, dt=0.1, x=5.0, y=0.0, z=0.0, running=False)
        assert calc._lap_time_s == time_after_running

    def test_reset_clears_state(self):
        """Reset should return calculator to initial state."""
        calc = DeltaCalculator(min_step_m=1.0, max_step_m=999.0)
        drive = Drive()
        drive(calc, lap_index=1, dt=0.1, x=0.0, y=0.0, z=0.0)
        calc.reset()
        assert calc._lap_index == -1
        assert calc._recorder.point_count == 0

    def test_use_fastest_reference_only_property(self):
        """Property should delegate to ReferenceManager."""
        calc = DeltaCalculator(use_fastest_reference_only=True)
        assert calc.use_fastest_reference_only is True

        calc.use_fastest_reference_only = False
        assert calc.use_fastest_reference_only is False

    def test_get_debug_state_none_without_reference(self):
        """get_debug_state should return None when no reference exists."""
        calc = DeltaCalculator()
        assert calc.get_debug_state() is None

    def test_defaults_to_fastest_reference_only(self):
        """The default selection policy must be fastest-only so a later, slower
        (but clean) lap — e.g. an in-lap — cannot overwrite a good reference."""
        calc = DeltaCalculator()
        assert calc.use_fastest_reference_only is True

    def test_slow_clean_lap_does_not_poison_reference(self):
        """With the fastest-only default, a slower clean lap (in-lap) following a
        fast lap must NOT replace the reference."""
        calc = DeltaCalculator(
            min_step_m=1.0, max_step_m=999.0, resample_spacing_m=2.0,
        )
        drive = Drive()

        # Lap 1: the fast reference lap (2 m / 0.1 s frame -> ~10 s).
        for i in range(100):
            drive(calc, lap_index=1, dt=0.1, x=float(i * 2), y=0.0, z=0.0)
        # 1->2 transition promotes lap 1.
        drive(calc, lap_index=2, dt=0.1, x=0.0, y=0.0, z=0.0)
        ref_version_after_fast = calc.get_debug_state()["ref_version"]

        # Lap 2: a slower clean "in-lap" over the same geometry (1 m / 0.1 s -> ~20 s).
        for i in range(1, 200):
            drive(calc, lap_index=2, dt=0.1, x=float(i), y=0.0, z=0.0)
        # 2->3 transition: the slower lap must be rejected as a reference.
        drive(calc, lap_index=3, dt=0.1, x=0.0, y=0.0, z=0.0)
        assert calc.get_debug_state()["ref_version"] == ref_version_after_fast

        # The rejection is now observable instead of a silent no-op.
        assert calc.last_reference_reject_reason is not None
        assert "not faster" in calc.last_reference_reject_reason
        assert calc.get_debug_state()["ref_reject_reason"] == calc.last_reference_reject_reason

    def test_reject_reason_clears_on_successful_promotion(self):
        """A clean, qualifying promotion clears any prior rejection reason."""
        calc = DeltaCalculator(
            use_fastest_reference_only=False,
            min_step_m=1.0, max_step_m=999.0, resample_spacing_m=2.0,
        )
        drive = Drive()
        # Lap 1 -> reference.
        for i in range(100):
            drive(calc, lap_index=1, dt=0.1, x=float(i * 2), y=0.0, z=0.0)
        drive(calc, lap_index=2, dt=0.1, x=0.0, y=0.0, z=0.0)
        assert calc.last_reference_reject_reason is None

        # Lap 2 clean -> promoted on 2->3, reason stays None.
        for i in range(1, 100):
            drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)
        drive(calc, lap_index=3, dt=0.1, x=0.0, y=0.0, z=0.0)
        assert calc.last_reference_reject_reason is None

    def test_reject_reason_reports_off_track_dirty_lap(self):
        """A dirty (off-track) lap is rejected for promotion with an explanatory reason."""
        calc = DeltaCalculator(
            min_step_m=1.0, max_step_m=999.0,
            resample_spacing_m=2.0, max_d_perp_m=5.0,
        )
        drive = Drive()
        self._build_reference(calc, drive)
        for i in range(1, 10):
            drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)
        for _ in range(5):
            drive(calc, lap_index=2, dt=0.1, x=20.0, y=0.0, z=20.0)
        for i in range(20, 100):
            drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)

        drive(calc, lap_index=3, dt=0.1, x=0.0, y=0.0, z=0.0)
        assert "off-track" in calc.last_reference_reject_reason

    # -------------------------------------------------------------------------
    # Off-track gating and teleport re-latch tests
    # -------------------------------------------------------------------------

    @staticmethod
    def _build_reference(calc: DeltaCalculator, drive: Drive, lap_x_end: float = 200.0) -> None:
        """Drive lap 1 along the X axis to build a reference, then transition to lap 2."""
        n = int(lap_x_end / 2)
        for i in range(n):
            drive(calc, lap_index=1, dt=0.1, x=float(i * 2), y=0.0, z=0.0)
        # Transition to lap 2 — the clock reset builds the reference from lap 1
        drive(calc, lap_index=2, dt=0.1, x=0.0, y=0.0, z=0.0)

    @staticmethod
    def _drive_circle(calc, drive, lap_index, n=160, radius=100.0, dt=0.1):
        """Drive one lap around a closed circle (start/finish at angle 0)."""
        last = None
        for k in range(n):
            th = 2 * np.pi * k / n
            last = drive(
                calc, lap_index=lap_index, dt=dt,
                x=float(radius * np.cos(th)), y=0.0, z=float(radius * np.sin(th)),
            )
        return last

    # -------------------------------------------------------------------------
    # Closed-loop / start-finish seam tests
    # -------------------------------------------------------------------------

    def test_closed_loop_delta_stable_around_whole_lap(self):
        """Retracing the reference line exactly on a closed loop gives ~0 delta
        at every frame — no spike anywhere, including near the seam."""
        calc = DeltaCalculator(
            use_fastest_reference_only=False,
            min_step_m=1.0, max_step_m=999.0, resample_spacing_m=5.0,
        )
        drive = Drive()
        self._drive_circle(calc, drive, lap_index=1)  # lap 1 data

        deltas = []
        n = 160
        for k in range(n):
            th = 2 * np.pi * k / n
            d = drive(  # k=0 resets the clock -> promotes lap 1 to the reference
                calc, lap_index=2, dt=0.1,
                x=float(100.0 * np.cos(th)), y=0.0, z=float(100.0 * np.sin(th)),
            )
            if d is not None:
                deltas.append(d)
        assert calc._ref_mgr.trajectory.closed is True
        assert deltas
        assert max(abs(d) for d in deltas) < 1.0

    def test_fresh_lap_seam_snap_independent_of_lap_time(self):
        """The start/finish seam snap keys off 'fresh lap', not the old 2 s time
        window, so it still resolves the wrap when the first frame arrives late
        (large dt) and the projection lands on the end of the loop."""
        calc = DeltaCalculator(
            use_fastest_reference_only=False,
            min_step_m=1.0, max_step_m=999.0, resample_spacing_m=5.0,
        )
        drive = Drive()
        self._drive_circle(calc, drive, lap_index=1)  # lap 1 data

        # First frame of lap 2 resets the clock (promotes the reference) AND is
        # the fresh-lap frame. It sits a hair BEFORE the line (projects to
        # s≈lap_len) and arrives 3 s late — past the old 2 s guard. Must still
        # snap to the start.
        th = -2 * np.pi * 0.5 / 160
        delta = drive(
            calc, lap_index=2, dt=3.0,
            x=float(100.0 * np.cos(th)), y=0.0, z=float(100.0 * np.sin(th)),
        )
        lap_len = calc._ref_mgr.trajectory.lap_length
        assert delta is not None
        assert calc._last_s < 0.2 * lap_len      # snapped to the start
        assert delta > -1.0                       # not a ≈ -(full lap) spike

    def test_closed_loop_position_held_until_master_clock_resets(self):
        """Under the master-clock model the lap boundary is GT7's current_lap_time
        resetting — not lap_index or the S/F crossing. If the car crosses S/F
        while the clock still reads the finishing lap's time (the 1-2 frame
        'carryover' before GT7 resets it), the arc-position must be HELD near the
        lap end, not wrapped to s≈0. Wrapping there would read the new lap's
        t_ref(≈0) against the old lap's clock and spike the delta by a full lap.
        The clock reset (a separate frame) is what re-latches s to ~0."""
        calc = DeltaCalculator(
            use_fastest_reference_only=False,
            min_step_m=1.0, max_step_m=999.0, resample_spacing_m=5.0,
            max_backtrack_m=5.0,
        )
        drive = Drive()
        self._drive_circle(calc, drive, lap_index=1)  # lap 1 data

        # Lap 2: full lap to build continuity near the end (clock resets at k=0,
        # promoting lap 1 to the reference).
        n = 160
        for k in range(n):
            th = 2 * np.pi * k / n
            drive(calc, lap_index=2, dt=0.1,
                  x=float(100.0 * np.cos(th)), y=0.0, z=float(100.0 * np.sin(th)))
        lap_len = calc._ref_mgr.trajectory.lap_length
        assert calc._last_s is not None and calc._last_s > 0.8 * lap_len
        stale_ms = int(calc._lap_time_s * 1000.0)  # GT7 clock at end of lap 2

        # Carryover: lap_index has ticked to 3 and the car is ~3 segments past
        # S/F, but GT7's clock has NOT reset yet (still ~stale_ms, ticking up).
        # Feed process() directly to hold the stale clock.
        th = 2 * np.pi * 3.0 / n
        delta = calc.process(
            lap_index=3, dt=0.1,
            x=float(100.0 * np.cos(th)), y=0.0, z=float(100.0 * np.sin(th)),
            running=True, gt7_lap_time_ms=stale_ms + 16,
        )
        assert calc._off_track is False
        # Position held near the lap end (NOT wrapped to ~0) while the clock is stale.
        assert calc._last_s > 0.7 * lap_len
        # And the delta has not spiked by a full lap.
        assert delta is not None and abs(delta) < 2.0

    def test_mode_flip_mid_lap_swaps_reference_and_relatches(self):
        """Flipping use_fastest_reference_only mid-lap must swap the delta to
        the other reference on the very next frame: continuity re-latches onto
        the new trajectory (teleport treatment) instead of clamping against
        the old one's arc-length."""
        calc = DeltaCalculator(
            use_fastest_reference_only=False,  # start in previous-lap mode
            min_step_m=1.0, max_step_m=999.0, resample_spacing_m=5.0,
        )
        drive = Drive()
        n = 160

        # Lap 1 fast (dt=0.1 → 16 s), lap 2 slow (dt=0.2 → 32 s). Each lap
        # lands in the previous-lap slot at its boundary; lap 1 stays the
        # session best in the background.
        self._drive_circle(calc, drive, lap_index=1, dt=0.1)
        self._drive_circle(calc, drive, lap_index=2, dt=0.2)

        # Lap 3 at the slow pace: delta vs the previous (slow) lap stays ≈ 0.
        d_before = None
        for k in range(40):
            th = 2 * np.pi * k / n
            d = drive(calc, lap_index=3, dt=0.2,
                      x=float(100.0 * np.cos(th)), y=0.0,
                      z=float(100.0 * np.sin(th)))
            if d is not None:
                d_before = d
        assert d_before is not None and abs(d_before) < 1.0
        assert calc.get_debug_state()["ref_lap_time"] == pytest.approx(32.0, abs=1.0)

        # Flip to fastest mid-lap: the 16 s lap becomes the reference, so at
        # quarter distance the slow pace is ~4 s down — visible immediately.
        calc.use_fastest_reference_only = True
        th = 2 * np.pi * 40 / n
        d_after = drive(calc, lap_index=3, dt=0.2,
                        x=float(100.0 * np.cos(th)), y=0.0,
                        z=float(100.0 * np.sin(th)))
        assert calc.get_debug_state()["ref_lap_time"] == pytest.approx(16.0, abs=1.0)
        assert d_after is not None and d_after > 2.0

    def test_off_track_dead_reckons_instead_of_blanking(self):
        """When d_perp exceeds max_d_perp_m the delta must KEEP updating
        (dead-reckoned), not blank — pro predictive timers never freeze on a
        brief excursion. The off-track flags are still raised so the lap is not
        promoted to the reference."""
        calc = DeltaCalculator(
            min_step_m=1.0, max_step_m=999.0,
            resample_spacing_m=2.0, max_d_perp_m=5.0,
        )
        drive = Drive()
        self._build_reference(calc, drive)

        # Drive several frames on the reference line to establish continuity
        for i in range(1, 10):
            drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)

        # Now jump 20m off the line (Z axis) — exceeds max_d_perp_m=5m
        result = drive(calc, lap_index=2, dt=0.1, x=20.0, y=0.0, z=20.0)
        assert result is not None  # delta keeps updating, not None
        assert calc._off_track is True
        assert calc._lap_had_off_track is True

    def test_off_track_blanks_only_without_prior_latch(self):
        """If the very first valid projection of the lap is already off-track we
        have no latched position to dead-reckon from, so that frame blanks."""
        calc = DeltaCalculator(
            min_step_m=1.0, max_step_m=999.0,
            resample_spacing_m=2.0, max_d_perp_m=5.0,
        )
        drive = Drive()
        self._build_reference(calc, drive)
        calc._last_s = None
        calc._last_xz = None

        result = drive(calc, lap_index=2, dt=0.1, x=0.0, y=0.0, z=20.0)
        assert result is None
        assert calc._off_track is True

    def test_delta_resumes_after_off_track(self):
        """Delta should resume with correct position after car returns to the reference line."""
        calc = DeltaCalculator(
            min_step_m=1.0, max_step_m=999.0,
            resample_spacing_m=2.0, max_d_perp_m=5.0,
        )
        drive = Drive()
        self._build_reference(calc, drive)

        # Drive on the line to s≈20m
        for i in range(1, 10):
            drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)

        # Go off-track for several frames — delta keeps updating (dead-reckoned)
        for _ in range(5):
            result = drive(calc, lap_index=2, dt=0.1, x=20.0, y=0.0, z=20.0)
            assert result is not None
            assert calc._off_track is True

        # Return to the line but AHEAD of where we left (simulates rejoining after a
        # chicane cut or GT7 teleport landing). KDTree re-latch must find s≈100m.
        for i in range(50, 60):
            result = drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)

        # Delta must be valid again after returning
        assert result is not None
        assert calc._off_track is False

    def test_off_track_lap_not_promoted_to_reference(self):
        """A lap that went off-track must NOT replace the reference. Its
        time-vs-distance curve has the excursion time baked in, which would
        offset every following lap's delta (the ~2s drift bug)."""
        calc = DeltaCalculator(
            min_step_m=1.0, max_step_m=999.0,
            resample_spacing_m=2.0, max_d_perp_m=5.0,
        )
        drive = Drive()
        # Lap 1 clean -> becomes the reference on the 1->2 transition.
        self._build_reference(calc, drive)
        assert calc._ref_mgr.has_reference
        ref_version_before = calc.get_debug_state()["ref_version"]

        # Lap 2: drive, but take an off-track excursion partway through.
        for i in range(1, 10):
            drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)
        for _ in range(5):
            drive(calc, lap_index=2, dt=0.1, x=20.0, y=0.0, z=20.0)
        for i in range(20, 100):
            drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)
        assert calc._lap_had_off_track is True

        # Transition 2->3: the dirty lap 2 must be rejected as a reference.
        drive(calc, lap_index=3, dt=0.1, x=0.0, y=0.0, z=0.0)
        assert calc.get_debug_state()["ref_version"] == ref_version_before

    def test_clean_lap_still_promoted_to_reference(self):
        """Control: a clean lap (no excursion) IS promoted to the reference."""
        # use_fastest_reference_only=False isolates this from the fastest-lap
        # gate — we are testing the off-track promotion gate, not lap selection.
        calc = DeltaCalculator(
            use_fastest_reference_only=False,
            min_step_m=1.0, max_step_m=999.0,
            resample_spacing_m=2.0, max_d_perp_m=5.0,
        )
        drive = Drive()
        self._build_reference(calc, drive)
        ref_version_before = calc.get_debug_state()["ref_version"]

        # Lap 2: clean, all on the reference line.
        for i in range(1, 100):
            drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)
        assert calc._lap_had_off_track is False

        # Transition 2->3: clean lap 2 promoted (version increments).
        drive(calc, lap_index=3, dt=0.1, x=0.0, y=0.0, z=0.0)
        assert calc.get_debug_state()["ref_version"] > ref_version_before

    def test_continuity_not_clamped_on_off_track_relatch(self):
        """After returning from off-track the s position jumps directly to the true
        position without being limited by max_s_jump_m."""
        calc = DeltaCalculator(
            min_step_m=1.0, max_step_m=999.0,
            resample_spacing_m=2.0, max_d_perp_m=5.0,
            max_s_jump_m=5.0,  # deliberately tiny to expose clamping if it fires
        )
        drive = Drive()
        self._build_reference(calc, drive)

        # Establish continuity at s≈10m
        for i in range(1, 6):
            drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)
        s_before = calc._last_s

        # Single off-track frame
        drive(calc, lap_index=2, dt=0.1, x=10.0, y=0.0, z=20.0)
        assert calc._off_track is True

        # Re-latch at s≈80m — 70m ahead of s_before, well past max_s_jump_m=5m.
        # Without the re-latch bypass this would creep forward 5m at a time.
        drive(calc, lap_index=2, dt=0.1, x=80.0, y=0.0, z=0.0)
        assert calc._off_track is False
        # s_final should have jumped to ≈80m, not just s_before + 5m
        assert calc._last_s > (s_before or 0) + 50

    def test_teleport_resets_projection_window(self):
        """After running=False→True the constrained window must be cleared so the full
        KDTree re-latches to the car's new position rather than walking from the old one."""
        calc = DeltaCalculator(
            min_step_m=1.0, max_step_m=999.0,
            resample_spacing_m=2.0,
            max_seg_jump=1,  # ±1 segment — so constrained search barely moves
        )
        drive = Drive()
        self._build_reference(calc, drive)

        # Establish continuity at s≈10m (seg ~5)
        for i in range(1, 6):
            drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)
        assert calc._last_seg_idx is not None
        seg_before = calc._last_seg_idx

        # Pause (teleport / loading screen)
        for _ in range(10):
            drive(calc, lap_index=2, dt=0.1, x=float(seg_before * 2), y=0.0, z=0.0, running=False)

        # _last_was_running is now False; the reset of _last_seg_idx/_last_s
        # happens lazily on the first running=True frame.
        assert calc._last_was_running is False

        # Resume far ahead (s≈180m) — with max_seg_jump=1 the constrained search
        # could never reach there from seg_before≈5; only the KDTree can find it.
        result = None
        for i in range(90, 96):
            result = drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)

        assert result is not None
        assert calc._last_s is not None and calc._last_s > 100.0

    def test_recording_freeze_bug_e2e(self):
        """
        End-to-end regression test for the _last_pos freeze bug.

        Scenario: Car records normally, then has a large gap (simulating
        running=False), then resumes.  The second segment of recording
        should still appear in the reference trajectory.
        """
        calc = DeltaCalculator(
            min_step_m=1.0, max_step_m=50.0, resample_spacing_m=2.0,
        )
        drive = Drive()

        # Phase 1: normal recording (0-40m)
        for i in range(20):
            drive(calc, lap_index=1, dt=0.1, x=float(i * 2), y=0.0, z=0.0)

        # Phase 2: large gap — car teleports to 200m
        # (simulates running=False then back to True far away)
        drive(calc, lap_index=1, dt=1.0, x=200.0, y=0.0, z=0.0)

        # Phase 3: normal recording resumes (200-240m)
        for i in range(20):
            drive(calc, lap_index=1, dt=0.1, x=200.0 + float(i * 2), y=0.0, z=0.0)

        # Points from both phase 1 AND phase 3 should be recorded
        # Phase 1: ~20 points, Phase 3: ~20 points
        # (the teleport itself is skipped but recording resumes)
        assert calc._recorder.point_count >= 30

    # -------------------------------------------------------------------------
    # Numerical delta correctness (known-answer)
    # -------------------------------------------------------------------------

    def test_delta_value_grows_linearly_when_slower(self):
        """Known-answer test for the actual delta arithmetic.

        Reference lap runs at 20 m/s along +X (2 m per 0.1 s frame).
        Current lap runs at 18 m/s along +X (1.8 m per 0.1 s frame), i.e. 10%
        slower.  Distance-based delta at arc-length ``s`` is

            delta(s) = s / v_cur - s / v_ref
                     = s * (1/18 - 1/20)
                     = s / 180

        so it must grow linearly with distance: 0.5 s at 90 m, 1.0 s at 180 m.
        The first-frame timing offset (one ``dt`` before the first recorded
        point) is identical for both laps and cancels exactly.
        """
        calc = DeltaCalculator(
            use_fastest_reference_only=False,  # isolate from lap selection
            min_step_m=1.0, max_step_m=999.0,
            resample_spacing_m=2.0,
        )

        drive = Drive()
        # Reference lap (lap 1): 20 m/s -> 2 m / frame, 0..198 m.
        for i in range(100):
            drive(calc, lap_index=1, dt=0.1, x=float(i * 2), y=0.0, z=0.0)

        # Lap change 1->2 builds the reference; this frame is the current lap at x=0.
        delta0 = drive(calc, lap_index=2, dt=0.1, x=0.0, y=0.0, z=0.0)
        assert delta0 == pytest.approx(0.0, abs=0.02)

        # Current lap (lap 2): 18 m/s -> 1.8 m / frame.
        last_delta = None
        for k in range(1, 101):
            x = 1.8 * k
            last_delta = drive(calc, lap_index=2, dt=0.1, x=x, y=0.0, z=0.0)
            if k == 50:  # x = 90 m -> delta = 0.5 s
                assert last_delta == pytest.approx(0.5, abs=0.05)

        # k = 100 -> x = 180 m -> delta = 1.0 s
        assert last_delta == pytest.approx(1.0, abs=0.05)

    def test_delta_zero_against_identical_lap(self):
        """A current lap identical to the reference must read ~0 delta throughout."""
        calc = DeltaCalculator(
            use_fastest_reference_only=False,
            min_step_m=1.0, max_step_m=999.0,
            resample_spacing_m=2.0,
        )
        drive = Drive()
        for i in range(100):
            drive(calc, lap_index=1, dt=0.1, x=float(i * 2), y=0.0, z=0.0)

        # Replay the exact same trajectory/timing on lap 2.
        drive(calc, lap_index=2, dt=0.1, x=0.0, y=0.0, z=0.0)
        for i in range(1, 100):
            delta = drive(calc, lap_index=2, dt=0.1, x=float(i * 2), y=0.0, z=0.0)
            assert delta == pytest.approx(0.0, abs=0.05)
