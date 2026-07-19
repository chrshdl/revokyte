"""
Unit tests for math_lite module.

Tests cover:
- PchipInterpolator: correctness, edge cases, zero-slope handling
- KDTree: nearest-neighbor correctness, k>1 queries, edge cases
"""

import numpy as np
import pytest

from instrument_cluster.core.delta_calculator.math_lite import KDTree, PchipInterpolator

# =============================================================================
# PchipInterpolator Tests
# =============================================================================


class TestPchipInterpolator:
    """Tests for PchipInterpolator."""

    def test_linear_data_interpolation(self):
        """Linear data should interpolate exactly."""
        x = np.array([0.0, 100.0, 200.0, 300.0, 400.0])
        y = np.array([0.0, 10.0, 20.0, 30.0, 40.0])
        pchip = PchipInterpolator(x, y)

        # Test exact points
        assert pchip(0.0) == pytest.approx(0.0)
        assert pchip(100.0) == pytest.approx(10.0)
        assert pchip(400.0) == pytest.approx(40.0)

        # Test midpoints (should be exact for linear data)
        assert pchip(50.0) == pytest.approx(5.0, abs=0.1)
        assert pchip(150.0) == pytest.approx(15.0, abs=0.1)

    def test_monotonic_preservation(self):
        """PCHIP should preserve monotonicity."""
        x = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([0.0, 1.0, 4.0, 9.0, 16.0, 25.0])  # Quadratic-ish
        pchip = PchipInterpolator(x, y)

        # Sample many points and check monotonicity
        x_test = np.linspace(0, 5, 100)
        y_test = np.array([pchip(xi) for xi in x_test])

        # y should be monotonically increasing
        assert np.all(np.diff(y_test) >= 0)

    def test_extrapolation_below(self):
        """Extrapolation below range should use linear extension."""
        x = np.array([10.0, 20.0, 30.0, 40.0])
        y = np.array([100.0, 200.0, 300.0, 400.0])
        pchip = PchipInterpolator(x, y, extrapolate=True)

        # Query below range
        result = pchip(0.0)
        # Should extrapolate linearly with initial slope
        assert result < 100.0

    def test_extrapolation_above(self):
        """Extrapolation above range should use linear extension."""
        x = np.array([10.0, 20.0, 30.0, 40.0])
        y = np.array([100.0, 200.0, 300.0, 400.0])
        pchip = PchipInterpolator(x, y, extrapolate=True)

        # Query above range
        result = pchip(50.0)
        # Should extrapolate linearly with final slope
        assert result > 400.0

    def test_extrapolation_disabled_raises(self):
        """Should raise ValueError when extrapolation is disabled."""
        x = np.array([10.0, 20.0, 30.0])
        y = np.array([1.0, 2.0, 3.0])
        pchip = PchipInterpolator(x, y, extrapolate=False)

        with pytest.raises(ValueError):
            pchip(0.0)

    def test_zero_slope_handling(self):
        """Should handle zero slopes without NaN or crash."""
        # Simulates car stopped: duplicate y values
        x = np.array([0.0, 100.0, 200.0, 300.0, 400.0])
        y = np.array([0.0, 10.0, 10.0, 10.0, 20.0])  # Flat section
        pchip = PchipInterpolator(x, y)

        # Should not produce NaN
        result = pchip(150.0)
        assert not np.isnan(result)
        assert result == pytest.approx(10.0, abs=0.5)

    def test_nearly_zero_slope_handling(self):
        """Should handle near-zero slopes without numerical issues."""
        x = np.array([0.0, 100.0, 100.001, 200.0, 300.0])
        y = np.array([0.0, 10.0, 10.0, 20.0, 30.0])
        pchip = PchipInterpolator(x, y)

        # Should not produce NaN or Inf
        result = pchip(150.0)
        assert np.isfinite(result)

    def test_non_increasing_x_raises(self):
        """Should raise ValueError for non-increasing x."""
        x = np.array([0.0, 100.0, 50.0, 200.0])  # Not monotonic
        y = np.array([0.0, 10.0, 5.0, 20.0])

        with pytest.raises(ValueError):
            PchipInterpolator(x, y)

    def test_batch_query(self):
        """Should handle array queries."""
        x = np.array([0.0, 100.0, 200.0, 300.0])
        y = np.array([0.0, 10.0, 20.0, 30.0])
        pchip = PchipInterpolator(x, y)

        # Query multiple points at once
        x_query = np.array([50.0, 150.0, 250.0])
        y_result = pchip(x_query)

        assert len(y_result) == 3
        assert y_result[0] == pytest.approx(5.0, abs=0.5)
        assert y_result[1] == pytest.approx(15.0, abs=0.5)
        assert y_result[2] == pytest.approx(25.0, abs=0.5)

    def test_scalar_return_type(self):
        """Scalar input should return float, not array."""
        x = np.array([0.0, 100.0, 200.0])
        y = np.array([0.0, 10.0, 20.0])
        pchip = PchipInterpolator(x, y)

        result = pchip(50.0)
        assert isinstance(result, float)


# =============================================================================
# KDTree Tests
# =============================================================================


class TestKDTree:
    """Tests for KDTree (brute-force nearest-neighbor)."""

    def test_exact_match(self):
        """Query at exact data point should return that point."""
        data = np.array(
            [
                [0.0, 0.0],
                [10.0, 0.0],
                [0.0, 10.0],
                [10.0, 10.0],
            ]
        )
        tree = KDTree(data)

        dist, idx = tree.query((10.0, 0.0), k=1)
        assert idx == 1
        assert dist == pytest.approx(0.0)

    def test_nearest_neighbor_simple(self):
        """Should find correct nearest neighbor."""
        data = np.array(
            [
                [0.0, 0.0],
                [100.0, 0.0],
                [0.0, 100.0],
                [100.0, 100.0],
            ]
        )
        tree = KDTree(data)

        # Query closest to (100, 100)
        dist, idx = tree.query((95.0, 95.0), k=1)
        assert idx == 3
        assert dist == pytest.approx(np.sqrt(50), abs=0.01)

    def test_k_nearest_neighbors(self):
        """Should return k nearest neighbors in order."""
        data = np.array(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [2.0, 0.0],
                [3.0, 0.0],
                [4.0, 0.0],
            ]
        )
        tree = KDTree(data)

        dists, idxs = tree.query((1.5, 0.0), k=3)

        # Indices 1 and 2 should be closest (both at 0.5)
        # Then index 0 or 3 (both at 1.5)
        assert len(idxs) == 3
        assert set(idxs[:2]) == {1, 2}

    def test_k_equals_all_points(self):
        """Should handle k equal to number of points."""
        data = np.array(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [2.0, 0.0],
            ]
        )
        tree = KDTree(data)

        dists, idxs = tree.query((0.0, 0.0), k=3)
        assert len(idxs) == 3
        assert set(idxs) == {0, 1, 2}

    def test_single_point_data(self):
        """Should work with single data point."""
        data = np.array([[5.0, 5.0]])
        tree = KDTree(data)

        dist, idx = tree.query((0.0, 0.0), k=1)
        assert idx == 0
        assert dist == pytest.approx(np.sqrt(50))

    def test_large_dataset_performance(self):
        """Should handle large datasets without timeout."""
        np.random.seed(42)
        data = np.random.randn(5000, 2) * 1000
        tree = KDTree(data)

        # Run many queries - should complete quickly
        for _ in range(100):
            query = np.random.randn(2) * 1000
            dist, idx = tree.query(query, k=1)
            assert 0 <= idx < 5000
            assert dist >= 0

    def test_2d_query_point_formats(self):
        """Should handle different query point formats."""
        data = np.array([[0.0, 0.0], [10.0, 10.0]])
        tree = KDTree(data)

        # Tuple
        d1, i1 = tree.query((5.0, 5.0), k=1)

        # List
        d2, i2 = tree.query([5.0, 5.0], k=1)

        # NumPy array
        d3, i3 = tree.query(np.array([5.0, 5.0]), k=1)

        assert i1 == i2 == i3
        assert d1 == pytest.approx(d2)
        assert d2 == pytest.approx(d3)


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests simulating real DeltaCalculator usage."""

    def test_typical_lap_reference(self):
        """Simulate building a lap reference and querying it."""
        # 5km track with 5m spacing = 1000 points
        n_points = 1000
        s = np.linspace(0, 5000, n_points)
        t = np.linspace(0, 180, n_points)  # 3 min lap

        pchip = PchipInterpolator(s, t)

        # Query various positions
        assert pchip(0) == pytest.approx(0.0, abs=0.1)
        assert pchip(2500) == pytest.approx(90.0, abs=0.5)
        assert pchip(5000) == pytest.approx(180.0, abs=0.1)

    def test_typical_kdtree_segment_lookup(self):
        """Simulate segment midpoint lookup for projection."""
        # Create 2D midpoints along a curved track
        n_segments = 1000
        theta = np.linspace(0, 2 * np.pi, n_segments)
        x = 1000 * np.cos(theta)  # Circular track
        z = 1000 * np.sin(theta)
        midpoints = np.column_stack([x, z])

        tree = KDTree(midpoints)

        # Query a point on the track
        dist, idx = tree.query((1000.0, 0.0), k=1)

        # Should find segment near theta=0
        assert idx < 50 or idx > 950  # Near start/end of circular track
        assert dist < 50  # Should be close
