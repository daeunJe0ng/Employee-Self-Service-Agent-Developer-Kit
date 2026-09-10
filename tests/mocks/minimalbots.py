# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Mock builders for the Copilot Studio minimalBots PPAPI surface."""

from __future__ import annotations

MOCK_STATUS = "validated"
MOCK_CASSETTE = "tests/fixtures/cassettes/flightcheck_minimalbots_components.yaml"
MOCK_ALM_CASSETTE = "tests/fixtures/cassettes/flightcheck_minimalbots_alm.yaml"

MOCK_ENV_ID_TEST_SUFFIX_0 = "5dd45044-46ac-e5c5-ab49-01f33d403cb0"
MOCK_ENV_ID_TEST_SUFFIX_A = "1cdc648c-c9c2-e85a-958b-b1360a6acdaa"
MOCK_ENV_ID_PROD = "ecf4737d-bef7-e58a-aa5e-e71a60780efc"
MOCK_BOT_ID = "11111111-2222-3333-4444-555555555555"
MOCK_GOOD_BOT_ID = "dad486e8-a0f5-4d64-8774-fe04df05baf5"
MOCK_BAD_BOT_ID = "a7828f58-bde1-451c-8105-3c2c785cd9e0"
MOCK_ALM_BOT_ID = "00000000-0000-0000-0000-000000001111"
MOCK_REALM = "Dev"
MOCK_GRS_REPOSITORY_ID = "00000000-0000-0000-0000-000000001111"
MOCK_COMMIT_SHA = "0b3007b07220fbbea5a7cf7c5a0c4681a247018a"
MOCK_HOST_TEST_SUFFIX_0 = (
    "https://5dd4504446ace5c5ab4901f33d403cb.0.environment.api.test.powerplatform.com"
)
MOCK_HOST_PROD = (
    "https://ecf4737dbef7e58aaa5ee71a60780e.fc.environment.api.powerplatform.com"
)


def _connection_reference(
    *, connector_id: str, logical_name: str, connection_id: str = "00000000000000000000000000000000"
) -> dict:
    return {
        "$kind": "ConnectionReferenceInsert",
        "connectionReference": {
            "$kind": "ConnectionReference",
            "version": 2,
            "auditInfo": {},
            "id": "00000000-0000-0000-0000-000000001111",
            "connectionId": connection_id,
            "connectorId": f"/providers/Microsoft.PowerApps/apis/{connector_id}",
            "connectionReferenceLogicalName": logical_name,
            "displayName": "Mock Display Name",
            "sharedConnectionParameters": "{}",
        },
    }


def _bot_components(count: int) -> list[dict]:
    return [
        {"schemaName": "cr123_topic", "displayName": "Workday topic"},
        *(
            {"schemaName": f"cr123_component_{i:03d}", "displayName": f"Mock component {i}"}
            for i in range(2, count + 1)
        ),
    ]


def component_change_set() -> dict:
    """Return the validated GOOD minimalBots components payload."""
    return {
        "connectionReferenceChanges": [
            _connection_reference(
                connector_id="shared_service-now",
                logical_name="gptagent_esshr_cosmosda_dual2.shared_service-now.servicenow",
            ),
            _connection_reference(
                connector_id="shared_workdaysoap",
                logical_name="gptagent_esshr_cosmosda_dual2.shared_workdaysoap.workday",
            ),
        ],
        "botComponentChanges": _bot_components(79),
        "cloudFlowDefinitionChanges": [],
        "connectorDefinitionChanges": [],
        "environmentVariableChanges": [],
    }


def component_change_set_missing_workday() -> dict:
    """Return the validated BAD payload where the Workday ref is missing."""
    return {
        "connectionReferenceChanges": [
            _connection_reference(
                connector_id="shared_service-now",
                logical_name="gptagent_esshr_cosmosda_v2.shared_service-now.servicenow",
            )
        ],
        "botComponentChanges": _bot_components(76),
        "cloudFlowDefinitionChanges": [],
        "connectorDefinitionChanges": [],
        "environmentVariableChanges": [],
    }


def configure_response() -> dict:
    """Return the validated minimalBots ALM configure payload."""
    return {
        "realm": MOCK_REALM,
        "cdsBotId": MOCK_ALM_BOT_ID,
        "schemaName": "gptagent_esshr_cosmosda_v2",
        "grsRepositoryId": MOCK_GRS_REPOSITORY_ID,
        "commitSha": MOCK_COMMIT_SHA,
        "values": {"botName": "ESS HR Agent"},
        "flows": {},
        "connections": {},
    }
