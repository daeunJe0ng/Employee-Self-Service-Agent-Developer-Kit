# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — ESS solution package validation (ESS-SOLN-xxx)

Verifies that the base ESS declarative agent package is present in the target
Power Platform environment (skill-2 ``install-ess``). The check reads the
Copilot Studio minimalBots ALM configure surface so it works after the DA
re-point away from Dataverse solution-table state.
"""

from ..runner import CheckResult, Priority, Role, Status

_ESS_SOLN_DOC_LINK = (
    "https://learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/install"
)
_ESS_SOLN_DESCRIPTION = "ESS base agent package present in the environment"
_DEFAULT_ALM_REALM = "Dev"
_ALM_NOT_OPTED_IN_ERROR_CODE = 4003


def run_solution_checks(runner) -> list[CheckResult]:
    """Emit the ESS-SOLN-xxx solution-installation checkpoints.

    Currently a single check (``ESS-SOLN-001``); kept as a category function so
    additional ESS-SOLN-* rows can be added without changing the registry /
    cli wiring.
    """
    return _check_ess_solution_installed(runner)


def _check_ess_solution_installed(runner) -> list[CheckResult]:
    """ESS-SOLN-001: the base ESS agent package is installed in the target env."""
    minimalbots = getattr(runner, "minimalbots", None)
    bot_id = _active_agent_bot_id(runner)
    realm = _alm_realm(runner)

    if minimalbots is None:
        return [
            CheckResult(
                checkpoint_id="ESS-SOLN-001",
                category="Solution",
                priority=Priority.CRITICAL.value,
                status=Status.SKIPPED.value,
                description=_ESS_SOLN_DESCRIPTION,
                result="Copilot Studio minimalBots PPAPI client not available in this run.",
                remediation=(
                    "Run FlightCheck with a configured environment and retry. "
                    "The check needs minimalBots PPAPI access to read ALM package state."
                ),
                doc_link=_ESS_SOLN_DOC_LINK,
                roles=[Role.ESS_MAKER.value],
            )
        ]
    if not bot_id:
        return [
            CheckResult(
                checkpoint_id="ESS-SOLN-001",
                category="Solution",
                priority=Priority.CRITICAL.value,
                status=Status.SKIPPED.value,
                description=_ESS_SOLN_DESCRIPTION,
                result="No agent botId is recorded in .local/config.json.",
                remediation=(
                    "Run /setup so the agent's botId is recorded, then re-run FlightCheck."
                ),
                doc_link=_ESS_SOLN_DOC_LINK,
                roles=[Role.ESS_MAKER.value],
            )
        ]

    try:
        config = minimalbots.get_configure(bot_id, realm)

        if _is_not_opted_into_alm(config):
            return [
                CheckResult(
                    checkpoint_id="ESS-SOLN-001",
                    category="Solution",
                    priority=Priority.CRITICAL.value,
                    status=Status.FAILED.value,
                    description=_ESS_SOLN_DESCRIPTION,
                    result=(
                        f"Agent {bot_id} is not opted into ALM, so FlightCheck "
                        "cannot confirm its GRS package state."
                    ),
                    remediation=(
                        "Opt the agent into Application Lifecycle Management (ALM) "
                        "in Copilot Studio, then re-run FlightCheck."
                    ),
                    doc_link=_ESS_SOLN_DOC_LINK,
                    roles=[Role.ESS_MAKER.value],
                )
            ]

        if not isinstance(config, dict):
            raise TypeError(f"minimalBots GetConfigure returned {type(config).__name__}")
        if config.get("_error"):
            return [_error_result(config, bot_id, realm)]

        grs_repository_id = config.get("grsRepositoryId")
        commit_sha = config.get("commitSha")
        if not grs_repository_id or not commit_sha:
            return [
                CheckResult(
                    checkpoint_id="ESS-SOLN-001",
                    category="Solution",
                    priority=Priority.CRITICAL.value,
                    status=Status.FAILED.value,
                    description=_ESS_SOLN_DESCRIPTION,
                    result=(
                        "minimalBots ALM GetConfigure did not return both "
                        "grsRepositoryId and commitSha. The ESS package state is absent."
                    ),
                    remediation=(
                        "Install or import the Employee Self Service agent package "
                        "for this environment, then re-run FlightCheck."
                    ),
                    doc_link=_ESS_SOLN_DOC_LINK,
                    roles=[Role.ESS_MAKER.value],
                )
            ]

        return [
            CheckResult(
                checkpoint_id="ESS-SOLN-001",
                category="Solution",
                priority=Priority.CRITICAL.value,
                status=Status.PASSED.value,
                description=_ESS_SOLN_DESCRIPTION,
                result=(
                    "ESS base agent package present in GRS: "
                    f"repository {grs_repository_id}, commit {commit_sha}."
                ),
                doc_link=_ESS_SOLN_DOC_LINK,
                roles=[Role.ESS_MAKER.value],
            )
        ]
    except Exception as e:
        error_payload = _response_json(e)
        if _is_not_opted_into_alm(error_payload):
            return [
                CheckResult(
                    checkpoint_id="ESS-SOLN-001",
                    category="Solution",
                    priority=Priority.CRITICAL.value,
                    status=Status.FAILED.value,
                    description=_ESS_SOLN_DESCRIPTION,
                    result=(
                        f"Agent {bot_id} is not opted into ALM. "
                        "minimalBots GetConfigure returned ErrorCode 4003."
                    ),
                    remediation=(
                        "Opt the agent into Application Lifecycle Management (ALM) "
                        "in Copilot Studio, then re-run FlightCheck."
                    ),
                    doc_link=_ESS_SOLN_DOC_LINK,
                    roles=[Role.ESS_MAKER.value],
                )
            ]
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        status_hint = f" [HTTP {status_code}]" if status_code is not None else ""
        return [
            CheckResult(
                checkpoint_id="ESS-SOLN-001",
                category="Solution",
                priority=Priority.CRITICAL.value,
                status=Status.WARNING.value,
                description=_ESS_SOLN_DESCRIPTION,
                result=(
                    "Unable to verify ESS package state from minimalBots ALM "
                    f"GetConfigure: {type(e).__name__}{status_hint}: {e}"
                ),
                remediation=(
                    "Inspect the error above; common causes are insufficient "
                    "Copilot Studio minimalBots PPAPI permissions or a transient platform error."
                ),
                doc_link=_ESS_SOLN_DOC_LINK,
                roles=[Role.ESS_MAKER.value],
            )
        ]


def _active_agent_bot_id(runner) -> str | None:
    config = getattr(runner, "config", None) or {}
    active_slug = config.get("activeAgent")
    for agent in config.get("agents", []) or []:
        if active_slug and agent.get("slug") != active_slug:
            continue
        bot_id = agent.get("botId")
        if bot_id:
            return bot_id
    single = config.get("agent") or {}
    return single.get("botId")


def _alm_realm(runner) -> str:
    config = getattr(runner, "config", None) or {}
    single = config.get("agent") or {}
    realm = (
        config.get("almRealm")
        or single.get("almRealm")
        or single.get("realm")
        or _DEFAULT_ALM_REALM
    )
    return str(realm).strip() or _DEFAULT_ALM_REALM


def _is_not_opted_into_alm(payload) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("ErrorCode") == _ALM_NOT_OPTED_IN_ERROR_CODE
    )


def _response_json(error) -> dict:
    response = getattr(error, "response", None)
    if response is None:
        return {}
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _error_result(config: dict, bot_id: str, realm: str) -> CheckResult:
    error = config.get("_error")
    status_code = config.get("_status")
    status_hint = f" [HTTP {status_code}]" if status_code else ""
    return CheckResult(
        checkpoint_id="ESS-SOLN-001",
        category="Solution",
        priority=Priority.CRITICAL.value,
        status=Status.WARNING.value,
        description=_ESS_SOLN_DESCRIPTION,
        result=(
            f"minimalBots ALM GetConfigure could not read package state for "
            f"agent {bot_id} in realm {realm}: {error}{status_hint}."
        ),
        remediation=(
            "Resolve minimalBots PPAPI authentication or permission issues, "
            "then re-run FlightCheck."
        ),
        doc_link=_ESS_SOLN_DOC_LINK,
        roles=[Role.ESS_MAKER.value],
    )
