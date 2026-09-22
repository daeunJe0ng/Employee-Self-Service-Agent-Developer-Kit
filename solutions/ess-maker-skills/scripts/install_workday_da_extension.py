# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Install the Workday package required by the active ESS HR agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from flightcheck.checks.workday_da import (
    _DA_HR_WORKDAY_CHILD_SCHEMA,
    _MOS_WORKDAY_RUNTIME_SCHEMA,
)


WORKDAY_PACKAGES = {
    "runtime": {
        "applicationName": _MOS_WORKDAY_RUNTIME_SCHEMA,
        "schemaName": _MOS_WORKDAY_RUNTIME_SCHEMA,
    },
    "legacy-da": {
        "applicationName": "msdyn_EssDAHRWorkdayHCM",
        "schemaName": _DA_HR_WORKDAY_CHILD_SCHEMA,
    },
}


class PacCliError(RuntimeError):
    """Raised when PAC is unavailable or cannot complete an operation."""


def resolve_pac_executable() -> Path:
    """Resolve PAC from the current PATH."""
    for candidate in ("pac", "pac.cmd", "pac.exe"):
        resolved = shutil.which(candidate)
        if resolved:
            return Path(resolved)
    raise PacCliError(
        "PAC CLI is not installed. Install Microsoft Power Platform CLI, "
        "then retry /connect workday."
    )


def _run(command, *, capture_output: bool, timeout: int):
    """Run one PAC command without invoking a shell."""
    try:
        return subprocess.run(
            [str(part) for part in command],
            capture_output=capture_output,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PacCliError(
            f"PAC command did not finish within {timeout // 60} minutes."
        ) from exc


def install_workday_package(
    environment_url: str,
    package_flavor: str,
    *,
    pac_resolver=resolve_pac_executable,
    runner=_run,
) -> str:
    """Install one Workday AppSource package through PAC."""
    if package_flavor not in WORKDAY_PACKAGES:
        raise ValueError(f"Unsupported Workday package flavor: {package_flavor}")
    environment_url = environment_url.rstrip("/")
    if not environment_url.startswith("https://"):
        raise ValueError("The Power Platform environment URL must use HTTPS.")

    package = WORKDAY_PACKAGES[package_flavor]
    pac_executable = pac_resolver()
    installed = runner(
        [
            pac_executable,
            "application",
            "install",
            "--environment",
            environment_url,
            "--application-name",
            package["applicationName"],
        ],
        capture_output=False,
        timeout=20 * 60,
    )
    if installed.returncode != 0:
        raise PacCliError(
            "PAC could not install the Workday package. Review the PAC output "
            "above, confirm environment access, and retry /connect workday."
        )
    return package["schemaName"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install the Workday package required by an ESS HR agent."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Dataverse environment URL",
    )
    parser.add_argument(
        "--vertical",
        required=True,
        choices=["hr"],
        help="ESS vertical (this release supports hr only)",
    )
    parser.add_argument(
        "--package-flavor",
        choices=sorted(WORKDAY_PACKAGES),
        default="runtime",
        help="Package required by the active ESS agent architecture.",
    )
    args = parser.parse_args()

    package = WORKDAY_PACKAGES[args.package_flavor]
    base_result = {
        "environmentUrl": args.url.rstrip("/"),
        "vertical": args.vertical,
        "packageFlavor": args.package_flavor,
        "schemaName": package["schemaName"],
        "applicationName": package["applicationName"],
    }
    try:
        schema_name = install_workday_package(
            args.url,
            args.package_flavor,
        )
    except (OSError, PacCliError, RuntimeError, ValueError) as error:
        print(
            "WORKDAY_PACKAGE_INSTALL_FAILED_JSON:"
            f"{json.dumps({**base_result, 'error': str(error)})}",
            flush=True,
        )
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)

    print(
        "INSTALLED_WORKDAY_DA_EXTENSION_JSON:"
        f"{json.dumps({**base_result, 'schemaName': schema_name})}"
    )


if __name__ == "__main__":
    main()
