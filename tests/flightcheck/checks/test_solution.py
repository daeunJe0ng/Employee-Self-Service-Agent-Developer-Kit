# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ESS-SOLN-001 minimalBots ALM package-presence validation."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import responses
from responses import matchers

from tests.conftest import require_validated_mock
from tests.mocks import minimalbots as mb

require_validated_mock(mb)

from flightcheck.checks.solution import _check_ess_solution_installed  # noqa: E402
from flightcheck.minimalbots_client import MinimalBotsClient  # noqa: E402


@dataclass
class _MinimalRunner:
    minimalbots: MinimalBotsClient | None
    config: dict


@pytest.fixture
def minimalbots_client(fake_token: str) -> MinimalBotsClient:
    client = MinimalBotsClient(
        tenant_id="00000000-0000-0000-0000-000000001111",
        environment_id=mb.MOCK_ENV_ID_TEST_SUFFIX_0,
        ring="test",
    )
    client._token = fake_token
    return client


@pytest.fixture
def runner(minimalbots_client: MinimalBotsClient) -> _MinimalRunner:
    return _MinimalRunner(
        minimalbots=minimalbots_client,
        config={
            "activeAgent": "ess",
            "agents": [{"slug": "ess", "botId": mb.MOCK_BOT_ID}],
            "almRealm": mb.MOCK_REALM,
        },
    )


def _register_get_configure(
    *,
    bot_id: str = mb.MOCK_BOT_ID,
    status: int = 200,
    payload: dict | None = None,
) -> None:
    responses.add(
        responses.GET,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/alm/{bot_id}/configure",
        json=payload or mb.configure_response(cds_bot_id=bot_id),
        status=status,
        match=[
            matchers.query_param_matcher(
                {"realm": mb.MOCK_REALM, "api-version": "2024-10-01"}
            )
        ],
    )


def test_skipped_when_minimalbots_client_missing() -> None:
    r = _check_ess_solution_installed(
        _MinimalRunner(
            minimalbots=None,
            config={
                "activeAgent": "ess",
                "agents": [{"slug": "ess", "botId": mb.MOCK_BOT_ID}],
            },
        )
    )[0]

    assert r.checkpoint_id == "ESS-SOLN-001"
    assert r.status == "Skipped"
    assert "minimalBots PPAPI client not available" in r.result


@responses.activate
def test_passed_when_grs_repository_and_commit_are_present(
    runner: _MinimalRunner,
) -> None:
    _register_get_configure()

    r = _check_ess_solution_installed(runner)[0]

    assert r.checkpoint_id == "ESS-SOLN-001"
    assert r.status == "Passed"
    assert "GRS" in r.result
    assert "00000000-0000-0000-0000-000000001111" in r.result
    assert "0b3007b07220fbbea5a7cf7c5a0c4681a247018a" in r.result
    assert r.remediation == ""


@responses.activate
def test_failed_when_agent_is_not_opted_into_alm(
    minimalbots_client: MinimalBotsClient,
) -> None:
    _register_get_configure(
        bot_id=mb.MOCK_NOT_ALM_BOT_ID,
        status=400,
        payload=mb.configure_not_opted_response(cds_bot_id=mb.MOCK_NOT_ALM_BOT_ID),
    )
    runner = _MinimalRunner(
        minimalbots=minimalbots_client,
        config={
            "activeAgent": "ess",
            "agents": [{"slug": "ess", "botId": mb.MOCK_NOT_ALM_BOT_ID}],
            "almRealm": mb.MOCK_REALM,
        },
    )

    r = _check_ess_solution_installed(runner)[0]

    assert r.checkpoint_id == "ESS-SOLN-001"
    assert r.status == "Failed"
    assert "not opted into ALM" in r.result
    assert "ErrorCode 4003" in r.result
    assert "Opt the agent into Application Lifecycle Management (ALM)" in r.remediation


@responses.activate
def test_failed_when_get_configure_has_no_grs_package(
    runner: _MinimalRunner,
) -> None:
    _register_get_configure(
        payload=mb.configure_response(grs_repository_id="", commit_sha="")
    )

    r = _check_ess_solution_installed(runner)[0]

    assert r.status == "Failed"
    assert "did not return both grsRepositoryId and commitSha" in r.result
    assert "Install or import the Employee Self Service agent package" in r.remediation
