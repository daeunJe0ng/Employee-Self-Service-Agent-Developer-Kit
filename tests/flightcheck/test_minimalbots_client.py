# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the Copilot Studio minimalBots PPAPI client.

These are validated-tier tests. They assert request construction and parsing
against the captured components cassette shape.
"""

from __future__ import annotations

import json

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


def test_environment_host_id_uses_test_31_plus_1_split() -> None:
    from flightcheck.minimalbots_client import minimalbots_environment_host_id

    assert (
        minimalbots_environment_host_id(mb.MOCK_ENV_ID_TEST_SUFFIX_0, ring="test")
        == "5dd4504446ace5c5ab4901f33d403cb.0"
    )
    assert (
        minimalbots_environment_host_id(mb.MOCK_ENV_ID_TEST_SUFFIX_A, ring="test")
        == "1cdc648cc9c2e85a958bb1360a6acda.a"
    )


def test_environment_host_id_uses_prod_30_plus_2_split() -> None:
    from flightcheck.minimalbots_client import minimalbots_environment_host_id

    assert (
        minimalbots_environment_host_id(mb.MOCK_ENV_ID_PROD, ring="prod")
        == "ecf4737dbef7e58aaa5ee71a60780e.fc"
    )


@responses.activate
def test_get_components_posts_to_per_environment_host(minimalbots_client) -> None:
    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/api/{mb.MOCK_BOT_ID}/components",
        json=mb.component_change_set(),
        status=200,
        match=[matchers.query_param_matcher({"api-version": "2024-10-01"})],
    )

    data = minimalbots_client.get_components(mb.MOCK_BOT_ID)

    workday_ref = data["connectionReferenceChanges"][0]["connectionReference"]
    assert workday_ref["connectorId"].endswith("/apis/shared_workdaysoap")
    shared_params = json.loads(workday_ref["sharedConnectionParameters"])
    assert shared_params["values"]["restBaseUri"]["value"] == mb.MOCK_WORKDAY_REST_BASE_URI
    assert shared_params["values"]["tenantName"]["value"] == mb.MOCK_WORKDAY_TENANT
    assert data["botComponentChanges"][0]["schemaName"] == "cr123_topic"
    request = responses.calls[0].request
    assert request.method == "POST"
    assert request.headers["x-ms-client-name"] == "EssAdk"
    assert request.headers["Authorization"].startswith("Bearer ")
    assert request.body == b"{}"


@responses.activate
def test_get_connection_references_returns_validated_list(minimalbots_client) -> None:
    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/api/{mb.MOCK_BOT_ID}/components",
        json=mb.component_change_set(),
        status=200,
        match=[matchers.query_param_matcher({"api-version": "2024-10-01"})],
    )

    refs = minimalbots_client.get_connection_references(mb.MOCK_BOT_ID)

    assert refs == mb.component_change_set()["connectionReferenceChanges"]


def test_get_connection_references_returns_empty_when_not_configured() -> None:
    from flightcheck.minimalbots_client import MinimalBotsClient

    assert MinimalBotsClient(environment_id=mb.MOCK_ENV_ID_TEST_SUFFIX_0).get_connection_references(
        mb.MOCK_BOT_ID
    ) == []


@responses.activate
def test_get_configure_sends_realm_and_api_version(minimalbots_client) -> None:
    responses.add(
        responses.GET,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/alm/{mb.MOCK_BOT_ID}/configure",
        json=mb.configure_response(),
        status=200,
        match=[
            matchers.query_param_matcher(
                {"realm": mb.MOCK_REALM, "api-version": "2022-03-01-preview"}
            )
        ],
    )

    data = minimalbots_client.get_configure(
        mb.MOCK_BOT_ID,
        mb.MOCK_REALM,
        api_version="2022-03-01-preview",
    )

    assert data["values"] == {"EnvironmentName": "ESS test"}
    assert data["grsRepositoryId"] == "repo-123"
    assert data["commitSha"] == "abc123"


@responses.activate
def test_export_returns_zip_bytes(minimalbots_client) -> None:
    zip_bytes = b"PK\x03\x04minimal-bot"
    responses.add(
        responses.POST,
        f"{mb.MOCK_HOST_TEST_SUFFIX_0}/copilotstudio/minimalBots/alm/{mb.MOCK_BOT_ID}/export",
        body=zip_bytes,
        status=200,
        content_type="application/zip",
        match=[matchers.query_param_matcher({"api-version": "2024-10-01"})],
    )

    assert minimalbots_client.export(mb.MOCK_BOT_ID) == zip_bytes


def test_unconfigured_client_fails_cleanly_without_network() -> None:
    from flightcheck.minimalbots_client import MinimalBotsClient

    client = MinimalBotsClient(environment_id=mb.MOCK_ENV_ID_TEST_SUFFIX_0)

    assert client.get_components(mb.MOCK_BOT_ID) == {"_error": "not_configured"}
    assert client.get_configure(mb.MOCK_BOT_ID, mb.MOCK_REALM) == {
        "_error": "not_configured"
    }
    assert client.export(mb.MOCK_BOT_ID) == b""
