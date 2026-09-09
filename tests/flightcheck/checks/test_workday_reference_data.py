# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for WD-REF-001 minimalBots Workday reference-data inventory."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import responses
from responses import matchers

from tests.conftest import require_validated_mock
from tests.mocks import minimalbots as mb

require_validated_mock(mb)


@pytest.fixture
def minimalbots_client(fake_token: str):
    from flightcheck.minimalbots_client import MinimalBotsClient

    client = MinimalBotsClient(
        tenant_id="00000000-0000-0000-0000-000000001111",
        environment_id=mb.MOCK_ENV_ID_TEST_SUFFIX_0,
        ring="test",
    )
    client._token = fake_token
    return client


def _runner(client, bot_id: str = mb.MOCK_GOOD_WORKDAY_BOT_ID):
    return SimpleNamespace(
        minimalbots=client,
        env_id=mb.MOCK_ENV_ID_TEST_SUFFIX_0,
        config={
            "activeAgent": "esshr",
            "agents": [{"slug": "esshr", "botId": bot_id}],
        },
    )


def _register_components(bot_id: str, payload: dict) -> None:
    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/api/{bot_id}/components",
        json=payload,
        status=200,
        match=[matchers.query_param_matcher({"api-version": "2024-10-01"})],
    )


def _run(runner):
    from flightcheck.checks.workday import _check_workday_reference_data

    results = _check_workday_reference_data(runner)
    assert len(results) == 1
    assert results[0].checkpoint_id == "WD-REF-001"
    return results[0]


@responses.activate
def test_workday_lookup_tables_and_reference_topics_pass(minimalbots_client) -> None:
    _register_components(mb.MOCK_GOOD_WORKDAY_BOT_ID, mb.component_change_set())

    r = _run(_runner(minimalbots_client))

    assert r.status == "Passed"
    assert "minimalBots botComponentChanges" in r.result
    assert "CompanyNameLookupTable" in r.result
    assert "VisaTypeLookupTable" in r.result
    assert "WorkdaySystemGetReferenceData" in r.result
    assert "WorkdaySystemRefreshReferenceData" in r.result
    assert r.remediation == ""


@responses.activate
def test_servicenow_only_components_fail_reference_inventory(minimalbots_client) -> None:
    _register_components(mb.MOCK_BAD_SERVICENOW_BOT_ID, mb.servicenow_component_change_set())

    r = _run(_runner(minimalbots_client, mb.MOCK_BAD_SERVICENOW_BOT_ID))

    assert r.status == "Failed"
    assert ".variable.*LookupTable" in r.result
    assert "WorkdaySystemGetReferenceData" in r.result
    assert "WorkdaySystemRefreshReferenceData" in r.result
    assert "repair or re-import" in r.remediation
    assert "copilotstudio.microsoft.com" in r.remediation


def test_missing_minimalbots_client_skips() -> None:
    r = _run(SimpleNamespace(minimalbots=None, config={}))

    assert r.status == "Skipped"
    assert "minimalBots PPAPI client not available" in r.result
    assert "minimalBots PPAPI access" in r.remediation
