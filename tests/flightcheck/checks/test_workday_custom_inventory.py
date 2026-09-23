# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for WD-WF-CAT-001 DA Workday topic component inventory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tests.conftest import require_validated_mock
from tests.mocks import agentbuilder_connectivity as ab

require_validated_mock(ab)

from flightcheck.checks.workday import _check_custom_workflow_inventory  # noqa: E402
from flightcheck.runner import Status  # noqa: E402


class _FakeAgentBuilder:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def fetch_components(self, _agent_id: str) -> dict[str, Any]:
        return self._payload


@dataclass
class _Runner:
    config: dict[str, Any] = field(
        default_factory=lambda: {"agent": {"botId": ab.MOCK_AGENT_ID}}
    )
    agentbuilder: Any = None
    _workday_package_flavor: str | None = None


def _runner_with_components(schema_names: list[str]) -> _Runner:
    return _Runner(
        agentbuilder=_FakeAgentBuilder(
            ab.components_with_bot_components(
                bot_components=[
                    ab.bot_component_change(schema_name=name)
                    for name in schema_names
                ]
            )
        )
    )


def _run(runner: _Runner):
    results = _check_custom_workflow_inventory(runner)
    assert len(results) == 1
    assert results[0].checkpoint_id == "WD-WF-CAT-001"
    return results[0]


def test_workday_topics_present_pass_and_enumerate_components():
    r = _run(_runner_with_components([
        "msdyn_copilotforemployeeselfservicehr.topic.WorkdayAbsenceBalance",
        "msdyn_copilotforemployeeselfservicehr.topic.WorkdayUpdatePhoneNumber",
        "msdyn_copilotforemployeeselfservicehr.topic.Greeting",
    ]))

    assert r.status == Status.PASSED.value
    assert "2 Workday topic component(s)" in r.result
    assert "WorkdayAbsenceBalance" in r.result
    assert "WorkdayUpdatePhoneNumber" in r.result
    assert "Greeting" not in r.result
    assert "US 7792327" in r.result
    assert r.remediation == ""


def test_workday_topics_absent_fails_with_repair_path():
    r = _run(_runner_with_components([
        "msdyn_copilotforemployeeselfservicehr.topic.Greeting",
        "msdyn_copilotforemployeeselfservicehr.variable.PhoneLookupTable",
    ]))

    assert r.status == Status.FAILED.value
    assert "0 schemaName values matching" in r.result
    assert ".topic.Workday*" in r.result
    assert "Install or repair the Workday Declarative Agent extension" in (
        r.remediation
    )


def test_empty_components_fail():
    r = _run(_runner_with_components([]))

    assert r.status == Status.FAILED.value
    assert "0 schemaName values" in r.result
    assert "re-run FlightCheck" in r.remediation


def test_no_client_or_bot_id_skips():
    no_client = _run(_Runner(agentbuilder=None))
    assert no_client.status == Status.SKIPPED.value
    assert "AgentBuilder client or active-agent botId not available" in (
        no_client.result
    )
    assert "Run /setup" in no_client.remediation

    no_bot = _run(_Runner(config={}, agentbuilder=_FakeAgentBuilder({})))
    assert no_bot.status == Status.SKIPPED.value
    assert "AgentBuilder client or active-agent botId not available" in (
        no_bot.result
    )
    assert "active agent botId" in no_bot.remediation


def test_malformed_bot_component_changes_warns():
    r = _run(_Runner(
        agentbuilder=_FakeAgentBuilder({"botComponentChanges": {"bad": "shape"}})
    ))

    assert r.status == Status.WARNING.value
    assert "invalid botComponentChanges" in r.result
    assert "report the checkpoint ID (WD-WF-CAT-001)" in r.remediation


def test_simplified_install_still_skips_before_api_read():
    runner = _Runner(
        agentbuilder=_FakeAgentBuilder({"botComponentChanges": {"bad": "shape"}}),
        _workday_package_flavor="simplified",
    )

    r = _run(runner)

    assert r.status == Status.SKIPPED.value
    assert "simplified" in r.result.lower()
    assert "WD-PKG-001" in r.result
