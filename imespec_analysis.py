"""Numerical analysis shared by Raman-map views. No GUI or input-file writes.

Band integration remains in imespec_bib1._calcular_area_raman. This module
exposes an exact trace of that background for review, and ratios of the
CURRENT integrated-area maps. A ratio is dimensionless and is not a
concentration, defect-density calibration, or quotient of complete spectra.
"""

from dataclasses import dataclass
import hashlib
import numpy as np

AREA_UNIT = "a.u.·cm⁻¹"
RATIO_UNIT = "dimensionless"
REASONS = {
    0: "valid",
    1: "nonfinite_input",
    2: "nonpositive_denominator",
    3: "below_denominator_floor",
    4: "negative_numerator",
    5: "nonfinite_ratio",
}


def _finite_median(values):
    """Median without overflow when averaging two large finite values."""
    ordered = np.sort(np.asarray(values, dtype=float))
    size = ordered.size
    if not size:
        return 0.0
    if size % 2:
        return float(ordered[size // 2])
    left, right = float(ordered[size // 2 - 1]), float(ordered[size // 2])
    if left <= 0 <= right:
        return left / 2 + right / 2
    return left + (right - left) / 2


@dataclass(frozen=True)
class RatioResult:
    values: np.ndarray
    valid: np.ndarray
    reasons: np.ndarray
    floor: float
    reference_median: float
    absolute_floor: float
    relative_floor_percent: float
    exclude_negative_numerator: bool

    def summary(self):
        finite = self.values[self.valid]
        total = int(self.values.size)
        return {
            "total_pixels": total,
            "valid_pixels": int(self.valid.sum()),
            "invalid_pixels": int(total - self.valid.sum()),
            "valid_percent": float(100 * self.valid.sum() / total) if total else 0.0,
            "minimum": float(finite.min()) if finite.size else None,
            "median": _finite_median(finite) if finite.size else None,
            "maximum": float(finite.max()) if finite.size else None,
            "effective_denominator_floor": self.floor,
            "median_positive_denominator": self.reference_median,
            "invalid_reasons": {
                name: int(np.count_nonzero(self.reasons == code))
                for code, name in REASONS.items()
                if code
            },
        }


def area_ratio(
    numerator,
    denominator,
    *,
    absolute_floor=0.0,
    relative_floor_percent=1.0,
    exclude_negative_numerator=True
):
    """Divide corresponding areas; return NaN + reason for excluded pixels.

    B must be strictly greater than max(absolute_floor,
    relative_floor_percent/100 * median(finite positive B)). The default 1%
    is an editable reference-floor heuristic, NOT an estimate of noise/SNR.
    No clipping, absolute-value transform or epsilon substitution is applied.
    """
    a = np.asarray(numerator, dtype=float)
    b = np.asarray(denominator, dtype=float)
    if a.ndim != 2 or a.shape != b.shape or not a.size:
        raise ValueError("Choose two nonempty maps with exactly the same geometry.")
    absolute_floor, relative_floor_percent = float(absolute_floor), float(
        relative_floor_percent
    )
    if not np.isfinite(absolute_floor) or absolute_floor < 0:
        raise ValueError("The minimum denominator area must be finite and nonnegative.")
    if (
        not np.isfinite(relative_floor_percent)
        or not 0 <= relative_floor_percent <= 100
    ):
        raise ValueError("The relative denominator floor must be between 0 and 100%.")
    positive = b[np.isfinite(b) & (b > 0)]
    median = _finite_median(positive) if positive.size else 0.0
    floor = max(absolute_floor, median * (relative_floor_percent / 100.0))
    reasons = np.zeros(a.shape, dtype=np.uint8)
    reasons[~(np.isfinite(a) & np.isfinite(b))] = 1
    reasons[(reasons == 0) & (b <= 0)] = 2
    reasons[(reasons == 0) & (b <= floor)] = 3
    if exclude_negative_numerator:
        reasons[(reasons == 0) & (a < 0)] = 4
    valid = reasons == 0
    values = np.full(a.shape, np.nan, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        np.divide(a, b, out=values, where=valid)
    reasons[valid & ~np.isfinite(values)] = 5
    valid = reasons == 0
    values[~valid] = np.nan
    return RatioResult(
        values,
        valid,
        reasons,
        floor,
        median,
        absolute_floor,
        relative_floor_percent,
        bool(exclude_negative_numerator),
    )


def integration_trace(x, y, start, stop):
    """Reproduce the legacy local background INCLUDING its two endpoints.

    Left anchor = mean(samples start-2 .. start); right anchor =
    mean(samples stop .. stop+2). This exact three-sample convention is
    preserved; it is not replaced by an edge-to-edge baseline.
    """
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    start, stop = sorted((int(start), int(stop)))
    if (
        x.ndim != 1
        or y.shape != x.shape
        or start < 2
        or stop + 2 >= len(x)
        or stop <= start
    ):
        raise ValueError(
            "The band needs two or more samples and two background samples on each side."
        )
    dx = np.diff(x)
    if not np.isfinite(x).all() or not (np.all(dx > 0) or np.all(dx < 0)):
        raise ValueError("The Raman-shift axis must be finite and strictly monotonic.")
    left_x, right_x = float(np.mean(x[start - 2 : start + 1])), float(
        np.mean(x[stop : stop + 3])
    )
    if abs(right_x - left_x) <= np.finfo(float).eps:
        raise ValueError("The background anchors must have different Raman shifts.")
    left_y, right_y = float(np.mean(y[start - 2 : start + 1])), float(
        np.mean(y[stop : stop + 3])
    )
    band_x, band_y = x[start : stop + 1], y[start : stop + 1]
    background = left_y + (band_x - left_x) * (right_y - left_y) / (right_x - left_x)
    corrected = band_y - background
    order = np.argsort(band_x)
    trapezoid = getattr(np, "trapezoid", None) or np.trapz
    value = float(trapezoid(corrected[order], x=band_x[order]))
    return {
        "x": band_x,
        "y": band_y,
        "background": background,
        "corrected": corrected,
        "area": value,
        "anchor_x": (left_x, right_x),
        "anchor_y": (left_y, right_y),
    }


def array_hash(values):
    data = np.ascontiguousarray(values)
    digest = hashlib.sha256()
    digest.update(str((data.shape, str(data.dtype))).encode("ascii"))
    digest.update(memoryview(data).cast("B"))
    return digest.hexdigest()


def finite_limits(values):
    """Display limits only; never alter the numerical map or exported values."""
    valid = np.asarray(values)[np.isfinite(values)]
    if not valid.size:
        return 0.0, 1.0
    lo, hi = float(valid.min()), float(valid.max())
    if lo == hi:
        pad = max(abs(lo) * 0.05, 0.05)
        return lo - pad, hi + pad
    return lo, hi
