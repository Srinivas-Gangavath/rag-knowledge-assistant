"""Deterministic Anomaly Detection Service.

Calculates statistical baseline over rolling historical windows and evaluates current
window metric drift against configured deviation ratios with sample-size gates.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class AnomalyEvaluationResult:
    is_anomaly: bool
    metric_name: str
    baseline_value: float
    current_value: float
    deviation_ratio: float
    multiplier: float
    sample_size: int
    historical_sample_size: int
    window_minutes: int
    reason: str


class AnomalyDetectionService:
    """Deterministic statistical baseline anomaly detection."""

    @classmethod
    def evaluate_metric(
        cls,
        *,
        metric_name: str,
        current_samples: Sequence[float],
        historical_samples: Sequence[float],
        multiplier: float = 2.0,
        minimum_sample_size: int = 5,
        window_minutes: int = 15,
    ) -> AnomalyEvaluationResult:
        """Evaluate whether current window values deviate significantly from historical baseline."""
        cur_count = len(current_samples)
        hist_count = len(historical_samples)

        # Gate 1: Check sample sizes
        if cur_count < minimum_sample_size:
            return AnomalyEvaluationResult(
                is_anomaly=False,
                metric_name=metric_name,
                baseline_value=0.0,
                current_value=0.0,
                deviation_ratio=1.0,
                multiplier=multiplier,
                sample_size=cur_count,
                historical_sample_size=hist_count,
                window_minutes=window_minutes,
                reason=f"Insufficient current sample size ({cur_count} < {minimum_sample_size})",
            )

        if hist_count < minimum_sample_size:
            return AnomalyEvaluationResult(
                is_anomaly=False,
                metric_name=metric_name,
                baseline_value=0.0,
                current_value=0.0,
                deviation_ratio=1.0,
                multiplier=multiplier,
                sample_size=cur_count,
                historical_sample_size=hist_count,
                window_minutes=window_minutes,
                reason=f"Insufficient historical baseline sample size ({hist_count} < {minimum_sample_size})",
            )

        # Gate 2: Compute statistical baseline (median) and current window metric (median or mean)
        baseline = float(statistics.median(historical_samples))
        current_val = float(statistics.median(current_samples))

        # Handle zero or near-zero baseline
        effective_baseline = baseline if baseline > 1e-4 else 1e-4
        deviation_ratio = current_val / effective_baseline

        is_anomaly = deviation_ratio >= multiplier

        reason = (
            f"Current {metric_name} ({current_val:.2f}) exceeds baseline ({baseline:.2f}) by {deviation_ratio:.2f}x (threshold {multiplier:.2f}x)"
            if is_anomaly
            else f"Current {metric_name} ({current_val:.2f}) within normal baseline ({baseline:.2f}, {deviation_ratio:.2f}x < {multiplier:.2f}x)"
        )

        return AnomalyEvaluationResult(
            is_anomaly=is_anomaly,
            metric_name=metric_name,
            baseline_value=baseline,
            current_value=current_val,
            deviation_ratio=round(deviation_ratio, 2),
            multiplier=multiplier,
            sample_size=cur_count,
            historical_sample_size=hist_count,
            window_minutes=window_minutes,
            reason=reason,
        )
