"""Inventory direct and indirect Hopsworks dependencies.

Phase 10P-A is read-only. It scans repository source files and creates a
machine-readable migration inventory without modifying runtime configuration.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "hopsworks_dependency_inventory.json"
)

SCAN_ROOTS = (
    PROJECT_ROOT / "app",
    PROJECT_ROOT / "scripts",
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "config",
)

TEXT_SUFFIXES = {
    ".py",
    ".sh",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".env",
    ".example",
}


PATTERNS: dict[str, re.Pattern[str]] = {
    "hopsworks_reference": re.compile(
        r"\bhopsworks\b",
        re.IGNORECASE,
    ),

    "hsfs_reference": re.compile(
        r"\bhsfs\b",
        re.IGNORECASE,
    ),

    "hsml_reference": re.compile(
        r"\bhsml\b",
        re.IGNORECASE,
    ),

    "feature_store_backend": re.compile(
        r"\bFEATURE_STORE_BACKEND\b",
    ),

    "model_registry_backend": re.compile(
        r"\bMODEL_REGISTRY_BACKEND\b",
    ),

    "feature_group": re.compile(
        r"\bfeature[_ ]?group\b",
        re.IGNORECASE,
    ),

    "feature_view": re.compile(
        r"\bfeature[_ ]?view\b",
        re.IGNORECASE,
    ),

    "training_dataset": re.compile(
        r"\btraining[_ ]?dataset\b",
        re.IGNORECASE,
    ),

    "model_registry": re.compile(
        r"\bmodel[_ ]?registry\b",
        re.IGNORECASE,
    ),

    "hopsworks_environment": re.compile(
        r"\bHOPSWORKS_[A-Z0-9_]+\b",
    ),
}


def relative_path(
    path: Path,
) -> str:
    return str(
        path.relative_to(
            PROJECT_ROOT
        )
    )


def should_scan(
    path: Path,
) -> bool:
    if not path.is_file():
        return False

    if "__pycache__" in path.parts:
        return False

    if path.name.startswith(".env"):
        return (
            path.name.endswith(
                ".example"
            )
        )

    return (
        path.suffix
        in TEXT_SUFFIXES
    )


def scan_file(
    path: Path,
) -> list[dict[str, Any]]:
    try:
        text = path.read_text(
            encoding="utf-8"
        )
    except UnicodeDecodeError:
        return []

    findings: list[
        dict[str, Any]
    ] = []

    for line_number, line in enumerate(
        text.splitlines(),
        start=1,
    ):
        matched_categories = [
            name
            for name, pattern
            in PATTERNS.items()
            if pattern.search(
                line
            )
        ]

        if not matched_categories:
            continue

        # Never persist possible secret values.
        sanitized_line = line.strip()

        if (
            "HOPSWORKS_API_KEY"
            in sanitized_line
            and "=" in sanitized_line
        ):
            left = sanitized_line.split(
                "=",
                1,
            )[0]

            sanitized_line = (
                f"{left}=<redacted>"
            )

        findings.append(
            {
                "line": line_number,
                "categories": (
                    matched_categories
                ),
                "text": (
                    sanitized_line
                ),
            }
        )

    return findings


def classify_file(
    path: str,
    findings: list[
        dict[str, Any]
    ],
) -> list[str]:

    categories = {
        category
        for finding in findings
        for category
        in finding[
            "categories"
        ]
    }

    responsibilities: list[str] = []

    lowered = path.lower()

    if (
        "hourly" in lowered
        or "feature" in lowered
    ) and (
        "feature_group"
        in categories
        or "feature_store_backend"
        in categories
    ):
        responsibilities.append(
            "FEATURE_WRITE_OR_SYNC"
        )

    if (
        "inference" in lowered
        or "forecast" in lowered
    ) and (
        "feature_store_backend"
        in categories
        or "feature_view"
        in categories
    ):
        responsibilities.append(
            "FEATURE_READ_FOR_INFERENCE"
        )

    if (
        "training" in lowered
        or "retraining" in lowered
    ) and (
        "training_dataset"
        in categories
        or "feature_view"
        in categories
    ):
        responsibilities.append(
            "TRAINING_DATA_ACCESS"
        )

    if (
        "model" in lowered
        or "registry" in lowered
        or "retraining" in lowered
    ) and (
        "model_registry"
        in categories
        or "model_registry_backend"
        in categories
    ):
        responsibilities.append(
            "MODEL_REGISTRY_ACCESS"
        )

    if "monitor" in lowered:
        responsibilities.append(
            "MONITORING_OR_HEALTH"
        )

    if "deploy" in lowered:
        responsibilities.append(
            "DEPLOYMENT_CONFIGURATION"
        )

    if not responsibilities:
        responsibilities.append(
            "GENERAL_HOPSWORKS_COUPLING"
        )

    return sorted(
        set(
            responsibilities
        )
    )


def build_inventory() -> dict[
    str,
    Any,
]:

    files: list[
        dict[str, Any]
    ] = []

    category_counts = {
        name: 0
        for name
        in PATTERNS
    }

    for root in SCAN_ROOTS:
        if not root.exists():
            continue

        for path in sorted(
            root.rglob("*")
        ):
            if not should_scan(
                path
            ):
                continue

            findings = scan_file(
                path
            )

            if not findings:
                continue

            for finding in findings:
                for category in (
                    finding[
                        "categories"
                    ]
                ):
                    category_counts[
                        category
                    ] += 1

            file_path = (
                relative_path(
                    path
                )
            )

            files.append(
                {
                    "path": file_path,
                    "responsibilities": (
                        classify_file(
                            file_path,
                            findings,
                        )
                    ),
                    "matches": findings,
                }
            )

    coupled_files = [
        file["path"]
        for file in files
    ]

    direct_library_files = [
        file["path"]
        for file in files
        if any(
            category in {
                "hopsworks_reference",
                "hsfs_reference",
                "hsml_reference",
            }
            for finding
            in file[
                "matches"
            ]
            for category
            in finding[
                "categories"
            ]
        )
    ]

    return {
        "phase": "10P",
        "subphase": "10P-A",
        "generated_at_utc": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "status": (
            "HOPSWORKS_DEPENDENCY_INVENTORY_READY"
        ),
        "read_only": True,
        "runtime_configuration_changed": False,
        "production_backend_changed": False,
        "summary": {
            "coupled_file_count": (
                len(
                    coupled_files
                )
            ),
            "direct_library_file_count": (
                len(
                    direct_library_files
                )
            ),
            "category_counts": (
                category_counts
            ),
        },
        "direct_library_files": (
            direct_library_files
        ),
        "coupled_files": (
            coupled_files
        ),
        "files": files,
        "migration_target": {
            "feature_store": {
                "current": (
                    "hopsworks"
                ),
                "planned_production": (
                    "azure_blob"
                ),
                "hopsworks_retained": (
                    True
                ),
            },
            "model_registry": {
                "current": (
                    "hopsworks"
                ),
                "planned_production": (
                    "azure_blob"
                ),
                "hopsworks_retained": (
                    True
                ),
            },
        },
    }


def save_report(
    report: dict[str, Any],
) -> Path:

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        REPORT_PATH.with_suffix(
            ".json.tmp"
        )
    )

    temporary.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    temporary.replace(
        REPORT_PATH
    )

    return REPORT_PATH


def main() -> int:

    report = build_inventory()

    path = save_report(
        report
    )

    print(
        json.dumps(
            report,
            indent=2,
            default=str,
        )
    )

    print(
        "Report saved:",
        path,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
