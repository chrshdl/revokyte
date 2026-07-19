import numpy as np

class PchipInterpolator:
    """
    A lightweight, pure-NumPy replacement for scipy.interpolate.PchipInterpolator.
    Preserves monotonicity using the standard PCHIP algorithm.
    """
    def __init__(self, x, y, extrapolate=True):
        self.x = np.asarray(x, dtype=float)
        self.y = np.asarray(y, dtype=float)
        self.extrapolate = extrapolate

        if np.any(np.diff(self.x) <= 0):
            raise ValueError("x must be strictly increasing")

        # 1. Calculate slopes (secants) between points
        hk = np.diff(self.x)
        yk = np.diff(self.y)
        dk = yk / hk

        # 2. Calculate derivatives at the points (preserving monotonicity)
        # Initialize derivatives
        d = np.zeros_like(self.x)
        
        # Internal points: Weighted harmonic mean
        # If slopes change sign (k vs k-1), derivative is 0 to enforce peak/valley
        mask = np.sign(dk[:-1]) != np.sign(dk[1:])
        
        # We process internal points (1 to N-2)
        w1 = 2*hk[1:] + hk[:-1]
        w2 = hk[1:] + 2*hk[:-1]
        
        # Safe harmonic mean with zero-division protection
        # This handles edge cases where car stops (duplicate times/positions)
        valid = (dk[:-1] != 0) & (dk[1:] != 0)
        with np.errstate(divide='ignore', invalid='ignore'):
            whmean = np.where(
                valid,
                (w1 + w2) / (w1 / dk[:-1] + w2 / dk[1:]),
                0.0
            )
        
        # Where slopes have different signs, set derivative to 0
        whmean[mask] = 0.0
        
        d[1:-1] = whmean

        # 3. Endpoints (One-sided differences)
        # Start
        d[0] = ((2*hk[0] + hk[1])*dk[0] - hk[0]*dk[1]) / (hk[0] + hk[1])
        if np.sign(d[0]) != np.sign(dk[0]): 
            d[0] = 0.0
        elif (np.sign(dk[0]) != np.sign(dk[1])) and (np.abs(d[0]) > np.abs(3*dk[0])):
            d[0] = 3*dk[0]

        # End
        d[-1] = ((2*hk[-1] + hk[-2])*dk[-1] - hk[-1]*dk[-2]) / (hk[-1] + hk[-2])
        if np.sign(d[-1]) != np.sign(dk[-1]):
            d[-1] = 0.0
        elif (np.sign(dk[-1]) != np.sign(dk[-2])) and (np.abs(d[-1]) > np.abs(3*dk[-1])):
            d[-1] = 3*dk[-1]

        self.d = d

    def __call__(self, x_query):
        x_query = np.asarray(x_query)
        scalar = x_query.ndim == 0
        if scalar:
            x_query = np.array([x_query])

        # Find indices
        # Clip indices to ensure they are within valid bins [0, N-2]
        idx = np.searchsorted(self.x, x_query, side='right') - 1
        idx = np.clip(idx, 0, len(self.x) - 2)

        # Handle extrapolation if requested
        if not self.extrapolate:
             out_of_bounds = (x_query < self.x[0]) | (x_query > self.x[-1])
             if np.any(out_of_bounds):
                 raise ValueError("A value in x_new is above the interpolation range.")

        # Local variables for the cubic Hermite spline
        x_lo = self.x[idx]
        x_hi = self.x[idx + 1]
        dx = x_hi - x_lo
        
        # Normalized coordinate t in [0, 1]
        t = (x_query - x_lo) / dx
        
        y_lo = self.y[idx]
        y_hi = self.y[idx + 1]
        d_lo = self.d[idx]
        d_hi = self.d[idx + 1]

        # Hermite Basis functions
        h00 = 2*t**3 - 3*t**2 + 1
        h10 = t**3 - 2*t**2 + t
        h01 = -2*t**3 + 3*t**2
        h11 = t**3 - t**2

        y_val = h00*y_lo + h10*dx*d_lo + h01*y_hi + h11*dx*d_hi

        # Simple Linear Extrapolation for points strictly outside bounds 
        # (Optional: PCHIP usually extrapolates via the first/last cubic segment, 
        # but linear is safer for control systems to avoid polynomial explosion)
        below = x_query < self.x[0]
        above = x_query > self.x[-1]
        
        if np.any(below):
            y_val[below] = self.y[0] + (x_query[below] - self.x[0]) * self.d[0]
        if np.any(above):
            y_val[above] = self.y[-1] + (x_query[above] - self.x[-1]) * self.d[-1]

        return float(y_val[0]) if scalar else y_val


class KDTree:
    """
    Brute-force nearest-neighbor search optimized for NumPy vectorization.
    
    COMPLEXITY: O(N) per query (linear scan)
    
    This is NOT a true KDTree - it computes distances to all points.
    For N < 10,000 points, this is often faster than a Python-based tree
    because it runs entirely in C-optimized NumPy code (OpenBLAS/NEON).
    
    USAGE NOTE:
    In DeltaCalculator, this is only used for the FIRST projection of each lap.
    Subsequent projections use project_constrained() which searches ~10 segments.
    For a 25km track (5000 points), expect ~100-200μs per query on a Pi 4.
    """
    def __init__(self, data, leafsize=10):
        # Leafsize is ignored in this flat implementation but kept for API compatibility
        self.data = np.asarray(data)
        # Cache sum of squares for fast distance calc: (a-b)^2 = a^2 + b^2 - 2ab
        self.data_sq = np.sum(self.data**2, axis=1)

    def query(self, x, k=1):
        """
        Find k nearest neighbors. 
        Currently optimized for k=1 (single nearest neighbor).
        """
        x = np.asarray(x)
        n_points = len(self.data)
        k = min(k, n_points)  # Clamp k to available points
        
        # 1. Compute squared Euclidean distance
        # dist^2 = sum((data - x)^2)
        # Using broadcasting: (N, 2) - (2,) -> (N, 2)
        diff = self.data - x
        dists_sq = np.sum(diff**2, axis=1)
        
        if k == 1:
            # Argmin is highly optimized in NumPy
            idx = np.argmin(dists_sq)
            return np.sqrt(dists_sq[idx]), idx
        else:
            # For k > 1, use argpartition (partial sort) which is O(N)
            # Note: argpartition with k >= n_points would fail, but we clamped above
            if k >= n_points:
                # Return all points sorted by distance
                idx = np.argsort(dists_sq)
            else:
                idx = np.argpartition(dists_sq, k)[:k]
                # Provide sorted results
                idx = idx[np.argsort(dists_sq[idx])]
            return np.sqrt(dists_sq[idx]), idx

