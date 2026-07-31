"""Champion–challenger comparison and promotion gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ChampionChallengerError(RuntimeError):
    """Raised when candidate comparison cannot complete."""


@dataclass(frozen=True)
class PromotionDecision:
    """Result of champion–challenger promotion checks."""

    approved: bool
    checks: dict[str, bool]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe decision metadata."""

        return {
            "approved": self.approved,
            "checks": self.checks,
            "reasons": self.reasons,
        }


def percentage_change(
    *,
    candidate: float,
    champion: float,
) -> float:
    """Return candidate percentage change from champion."""

    if champion == 0:
        return 0.0 if candidate == 0 else float("inf")

    return (
        (candidate - champion)
        / abs(champion)
        * 100.0
    )


def compare_overall_metric(
    *,
    candidate_value: float,
    champion_value: float,
    maximum_regression_pct: float,
) -> tuple[bool, float]:
    """Check one lower-is-better regression metric."""

    change_pct = percentage_change(
        candidate=candidate_value,
        champion=champion_value,
    )

    passed = (
        change_pct
        <= maximum_regression_pct
    )

    return passed, change_pct


def evaluate_promotion_gates(
    *,
    champion_test_metrics: dict[str, Any],
    candidate_test_metrics: dict[str, Any],
    maximum_mae_regression_pct: float,
    maximum_rmse_regression_pct: float,
    maximum_horizon_mae_regression_pct: float,
    minimum_severe_samples: int,
) -> PromotionDecision:
    """Evaluate explicit challenger promotion gates."""

    champion_overall = champion_test_metrics[
        "overall"
    ]

    candidate_overall = candidate_test_metrics[
        "overall"
    ]

    mae_passed, mae_change = (
        compare_overall_metric(
            candidate_value=float(
                candidate_overall["mae"]
            ),
            champion_value=float(
                champion_overall["mae"]
            ),
            maximum_regression_pct=(
                maximum_mae_regression_pct
            ),
        )
    )

    rmse_passed, rmse_change = (
        compare_overall_metric(
            candidate_value=float(
                candidate_overall["rmse"]
            ),
            champion_value=float(
                champion_overall["rmse"]
            ),
            maximum_regression_pct=(
                maximum_rmse_regression_pct
            ),
        )
    )

    checks: dict[str, bool] = {
        "overall_mae": mae_passed,
        "overall_rmse": rmse_passed,
    }

    reasons = [
        (
            "Overall MAE change: "
            f"{mae_change:.4f}%."
        ),
        (
            "Overall RMSE change: "
            f"{rmse_change:.4f}%."
        ),
    ]

    champion_horizons = (
        champion_test_metrics[
            "horizon_groups"
        ]
    )

    candidate_horizons = (
        candidate_test_metrics[
            "horizon_groups"
        ]
    )

    for group_name in champion_horizons:
        champion_group = champion_horizons[
            group_name
        ]

        candidate_group = candidate_horizons.get(
            group_name
        )

        if (
            candidate_group is None
            or champion_group["metrics"] is None
            or candidate_group["metrics"] is None
        ):
            checks[
                f"horizon_{group_name}_mae"
            ] = False

            reasons.append(
                f"Missing metrics for horizon group {group_name}."
            )
            continue

        group_passed, group_change = (
            compare_overall_metric(
                candidate_value=float(
                    candidate_group[
                        "metrics"
                    ]["mae"]
                ),
                champion_value=float(
                    champion_group[
                        "metrics"
                    ]["mae"]
                ),
                maximum_regression_pct=(
                    maximum_horizon_mae_regression_pct
                ),
            )
        )

        checks[
            f"horizon_{group_name}_mae"
        ] = group_passed

        reasons.append(
            f"{group_name} MAE change: "
            f"{group_change:.4f}%."
        )

    champion_severe = champion_test_metrics[
        "severe_pm25"
    ]

    candidate_severe = candidate_test_metrics[
        "severe_pm25"
    ]

    severe_sample_count = min(
        int(champion_severe["sample_count"]),
        int(candidate_severe["sample_count"]),
    )

    if severe_sample_count >= minimum_severe_samples:
        severe_available = all(
            [
                champion_severe["metrics"]
                is not None,
                candidate_severe["metrics"]
                is not None,
            ]
        )

        checks["severe_pm25_metrics"] = (
            severe_available
        )

        if not severe_available:
            reasons.append(
                "Severe PM2.5 metrics are unavailable."
            )
    else:
        checks["severe_pm25_metrics"] = True

        reasons.append(
            "Severe PM2.5 gate was informational because "
            f"only {severe_sample_count} shared samples exist."
        )

    approved = all(checks.values())

    return PromotionDecision(
        approved=approved,
        checks=checks,
        reasons=reasons,
    )