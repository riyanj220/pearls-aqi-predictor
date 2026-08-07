"""Validate Phase 10M production infrastructure."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "phase_10"
    / "production_infrastructure_validation_report.json"
)


class ProductionInfrastructureValidationError(
    RuntimeError
):
    """Raised when production infrastructure validation fails."""


def run_command(
    arguments: list[str],
) -> str:
    """Run one command and return stdout."""

    completed = subprocess.run(
        arguments,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise ProductionInfrastructureValidationError(
            "Command failed.\n"
            f"Command: {' '.join(arguments)}\n"
            f"Error: {completed.stderr.strip()}"
        )

    return completed.stdout.strip()


def run_json_command(
    arguments: list[str],
) -> Any:
    """Run one command and parse JSON."""

    output = run_command(
        [
            *arguments,
            "--output",
            "json",
        ]
    )

    try:
        return json.loads(
            output
        )
    except json.JSONDecodeError as error:
        raise ProductionInfrastructureValidationError(
            "Command did not return valid JSON."
        ) from error


def validate_infrastructure(
    *,
    resource_group: str,
    environment_name: str,
    environment_resource_group: str,
    identity_name: str,
    acr_name: str,
    storage_account: str,
    storage_container: str,
) -> dict[str, Any]:
    """Validate production infrastructure and shared resources."""

    group = run_json_command(
        [
            "az",
            "group",
            "show",
            "--name",
            resource_group,
        ]
    )

    environment = run_json_command(
        [
            "az",
            "containerapp",
            "env",
            "show",
            "--resource-group",
            environment_resource_group,
            "--name",
            environment_name,
        ]
    )

    identity = run_json_command(
        [
            "az",
            "identity",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            identity_name,
        ]
    )

    principal_id = str(
        identity.get(
            "principalId",
            "",
        )
    )

    if not principal_id:
        raise ProductionInfrastructureValidationError(
            "Production identity has no principal ID."
        )

    roles = run_json_command(
        [
            "az",
            "role",
            "assignment",
            "list",
            "--assignee-object-id",
            principal_id,
            "--all",
        ]
    )

    if not isinstance(
        roles,
        list,
    ):
        raise ProductionInfrastructureValidationError(
            "Role-assignment response is invalid."
        )

    role_names = {
        str(
            role.get(
                "roleDefinitionName"
            )
        )
        for role in roles
    }

    container_exists_output = run_command(
        [
            "az",
            "storage",
            "container",
            "exists",
            "--account-name",
            storage_account,
            "--name",
            storage_container,
            "--auth-mode",
            "login",
            "--query",
            "exists",
            "--output",
            "tsv",
        ]
    )

    aqi_pointer_exists_output = run_command(
        [
            "az",
            "storage",
            "blob",
            "exists",
            "--account-name",
            storage_account,
            "--container-name",
            storage_container,
            "--name",
            "aqi/latest/pointer.json",
            "--auth-mode",
            "login",
            "--query",
            "exists",
            "--output",
            "tsv",
        ]
    )

    monitoring_pointer_exists_output = run_command(
        [
            "az",
            "storage",
            "blob",
            "exists",
            "--account-name",
            storage_account,
            "--container-name",
            storage_container,
            "--name",
            (
                "production-health/"
                "latest/pointer.json"
            ),
            "--auth-mode",
            "login",
            "--query",
            "exists",
            "--output",
            "tsv",
        ]
    )

    acr = run_json_command(
        [
            "az",
            "acr",
            "show",
            "--name",
            acr_name,
        ]
    )

    checks = {
        "resource_group_exists": (
            group.get(
                "name"
            )
            == resource_group
        ),
        "resource_group_is_production": (
            group.get(
                "tags",
                {},
            ).get(
                "environment"
            )
            == "production"
        ),
        "shared_environment_provisioned": (
            environment.get(
                "properties",
                {},
            ).get(
                "provisioningState"
            )
            == "Succeeded"
        ),
        "shared_environment_is_staging_environment": (
            environment.get(
                "name"
            )
            == "cae-pearls-aqi-staging"
        ),
        "production_identity_exists": (
            identity.get(
                "name"
            )
            == identity_name
        ),
        "identity_has_client_id": bool(
            identity.get(
                "clientId"
            )
        ),
        "identity_has_principal_id": bool(
            principal_id
        ),
        "acr_exists": (
            acr.get(
                "name"
            )
            == acr_name
        ),
        "identity_has_acr_pull": (
            "AcrPull"
            in role_names
        ),
        "identity_has_blob_contributor": (
            "Storage Blob Data Contributor"
            in role_names
        ),
        "identity_has_resource_group_reader": (
            "Reader"
            in role_names
        ),
        "production_container_exists": (
            container_exists_output.lower()
            == "true"
        ),
        "production_aqi_pointer_not_created_yet": (
            aqi_pointer_exists_output.lower()
            == "false"
        ),
        "production_monitoring_pointer_not_created_yet": (
            monitoring_pointer_exists_output.lower()
            == "false"
        ),
    }

    return {
        "valid": all(
            checks.values()
        ),
        "checks": checks,
        "resource_group": {
            "name": resource_group,
            "location": (
                group.get(
                    "location"
                )
            ),
        },
        "container_apps_environment": {
            "name": environment_name,
            "resource_group": (
                environment_resource_group
            ),
            "shared_between_staging_and_production": (
                True
            ),
            "provisioning_state": (
                environment.get(
                    "properties",
                    {},
                ).get(
                    "provisioningState"
                )
            ),
        },
        "identity": {
            "name": identity_name,
            "client_id_present": bool(
                identity.get(
                    "clientId"
                )
            ),
            "principal_id_present": bool(
                identity.get(
                    "principalId"
                )
            ),
        },
        "storage": {
            "account_name": (
                storage_account
            ),
            "container_name": (
                storage_container
            ),
            "container_exists": (
                container_exists_output.lower()
                == "true"
            ),
            "aqi_pointer_exists": (
                aqi_pointer_exists_output.lower()
                == "true"
            ),
            "monitoring_pointer_exists": (
                monitoring_pointer_exists_output.lower()
                == "true"
            ),
        },
        "role_names": sorted(
            role_names
        ),
    }


def save_report(
    report: dict[str, Any],
) -> Path:
    """Atomically save validation report."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = (
        REPORT_PATH.with_suffix(
            ".json.tmp"
        )
    )

    temporary_path.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    temporary_path.replace(
        REPORT_PATH
    )

    return REPORT_PATH


def main() -> int:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description=(
            "Validate Azure production "
            "infrastructure."
        )
    )

    parser.add_argument(
        "--resource-group",
        default="rg-pearls-aqi-prod",
    )

    parser.add_argument(
        "--environment",
        default="cae-pearls-aqi-staging",
    )

    parser.add_argument(
        "--environment-resource-group",
        default="rg-pearls-aqi-staging",
    )

    parser.add_argument(
        "--identity",
        default="id-pearls-aqi-prod",
    )

    parser.add_argument(
        "--acr",
        default="walpole",
    )

    parser.add_argument(
        "--storage-account",
        default="stpearlsaqiriyan",
    )

    parser.add_argument(
        "--storage-container",
        default="artifacts-prod",
    )

    arguments = parser.parse_args()

    try:
        validation = validate_infrastructure(
            resource_group=(
                arguments.resource_group
            ),
            environment_name=(
                arguments.environment
            ),
            environment_resource_group=(
                arguments.environment_resource_group
            ),
            identity_name=(
                arguments.identity
            ),
            acr_name=(
                arguments.acr
            ),
            storage_account=(
                arguments.storage_account
            ),
            storage_container=(
                arguments.storage_container
            ),
        )

        report = {
            "phase": "10M",
            "subphase": "10M-B",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_INFRASTRUCTURE_VALIDATED"
                if validation["valid"]
                else (
                    "PRODUCTION_INFRASTRUCTURE_INVALID"
                )
            ),
            "production_resources_created": (
                True
            ),
            "shared_container_apps_environment": (
                True
            ),
            "application_services_deployed": (
                False
            ),
            "scheduled_jobs_deployed": (
                False
            ),
            **validation,
        }

        exit_code = (
            0
            if validation["valid"]
            else 1
        )

    except Exception as error:
        report = {
            "phase": "10M",
            "subphase": "10M-B",
            "generated_at_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "status": (
                "PRODUCTION_INFRASTRUCTURE_VALIDATION_FAILED"
            ),
            "valid": False,
            "error_type": (
                type(error).__name__
            ),
            "error_message": str(
                error
            ),
        }

        exit_code = 1

    report_path = save_report(
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
        report_path,
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())