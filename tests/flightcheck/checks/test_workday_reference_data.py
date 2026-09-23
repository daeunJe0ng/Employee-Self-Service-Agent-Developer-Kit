# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for WD-REF-001 DA reference-data component inventory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tests.conftest import require_validated_mock
from tests.mocks import agentbuilder_connectivity as ab

require_validated_mock(ab)

from flightcheck.checks.workday import _check_workday_reference_data  # noqa: E402
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
    results = _check_workday_reference_data(runner)
    assert len(results) == 1
    assert results[0].checkpoint_id == "WD-REF-001"
    return results[0]


def test_lookup_tables_and_reference_topics_present_pass():
    r = _run(_runner_with_components([
        "msdyn_copilotforemployeeselfservicehr.variable.PhoneLookupTable",
        "msdyn_copilotforemployeeselfservicehr.variable.CountryLookupTable",
        "msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetReferenceData",
        (
            "msdyn_copilotforemployeeselfservicehr.topic."
            "WorkdaySystemRefreshReferenceData"
        ),
    ]))

    assert r.status == Status.PASSED.value
    assert "2 Workday LookupTable variable component(s)" in r.result
    assert "reference-data topic component(s)" in r.result
    assert "US 7792327" in r.result
    assert r.remediation == ""


def test_missing_lookup_tables_fail_with_repair_path():
    r = _run(_runner_with_components([
        "msdyn_copilotforemployeeselfservicehr.topic.WorkdaySystemGetReferenceData",
        (
            "msdyn_copilotforemployeeselfservicehr.topic."
            "WorkdaySystemRefreshReferenceData"
        ),
    ]))

    assert r.status == Status.FAILED.value
    assert "0 .variable.*LookupTable component schemaName(s)" in r.result
    assert "LookupTable variables" in r.remediation
    assert "re-import" in r.remediation


def test_missing_reference_topics_fail_with_repair_path():
    r = _run(_runner_with_components([
        "msdyn_copilotforemployeeselfservicehr.variable.PhoneLookupTable",
    ]))

    assert r.status == Status.FAILED.value
    assert "missing reference-data topic component schemaName(s)" in r.result
    assert "WorkdaySystemGetReferenceData" in r.result
    assert "WorkdaySystemRefreshReferenceData" in r.result
    assert "WorkdaySystemGetReferenceData" in r.remediation


def test_empty_components_fail():
    r = _run(_runner_with_components([]))

    assert r.status == Status.FAILED.value
    assert "0 .variable.*LookupTable" in r.result
    assert "missing reference-data topic" in r.result
    assert "repair or re-import" in r.remediation


def test_no_client_or_bot_id_skips():
    no_client = _run(_Runner(agentbuilder=None))
    assert no_client.status == Status.SKIPPED.value
    assert "AgentBuilder client or active-agent botId not available" in no_client.result
    assert "Run /setup" in no_client.remediation

    no_bot = _run(_Runner(config={}, agentbuilder=_FakeAgentBuilder({})))
    assert no_bot.status == Status.SKIPPED.value
    assert "AgentBuilder client or active-agent botId not available" in no_bot.result
    assert "active agent botId" in no_bot.remediation


def test_malformed_bot_component_changes_warns():
    r = _run(_Runner(
        agentbuilder=_FakeAgentBuilder({"botComponentChanges": {"bad": "shape"}})
    ))

    assert r.status == Status.WARNING.value
    assert "invalid botComponentChanges" in r.result
    assert "report the checkpoint ID (WD-REF-001)" in r.remediation
