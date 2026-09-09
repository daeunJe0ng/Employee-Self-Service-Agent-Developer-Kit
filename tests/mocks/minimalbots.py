# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Mock builders for the Copilot Studio minimalBots PPAPI surface."""

from __future__ import annotations

import json

MOCK_STATUS = "validated"
MOCK_SCHEMA_SOURCE = (
    "tests\\fixtures\\cassettes\\flightcheck_minimalbots_components.yaml"
)

MOCK_ENV_ID_TEST_SUFFIX_0 = "5dd45044-46ac-e5c5-ab49-01f33d403cb0"
MOCK_ENV_ID_TEST_SUFFIX_A = "1cdc648c-c9c2-e85a-958b-b1360a6acdaa"
MOCK_ENV_ID_PROD = "ecf4737d-bef7-e58a-aa5e-e71a60780efc"
MOCK_BOT_ID = "11111111-2222-3333-4444-555555555555"
MOCK_REALM = "contoso"
MOCK_WORKDAY_REST_BASE_URI = "https://wd5-impl-services1.workday.com/ccx/api"
MOCK_WORKDAY_BASE_URI = "https://wd5-impl-services1.workday.com/ccx"
MOCK_WORKDAY_TENANT = "contoso_pt1"
MOCK_WORKDAY_RESOURCE_URI = "https://wd5-impl-services1.workday.com"
MOCK_WORKDAY_TOKEN_URI = "https://wd5-impl-services1.workday.com/ccx/oauth2/token"
MOCK_WORKDAY_CLIENT_ID = "00000000-0000-0000-0000-000000000000"
MOCK_HOST_TEST_SUFFIX_0 = (
    "https://5dd4504446ace5c5ab4901f33d403cb.0.environment.api.test.powerplatform.com"
)
MOCK_HOST_PROD = (
    "https://ecf4737dbef7e58aaa5ee71a60780e.fc.environment.api.powerplatform.com"
)


def workday_shared_connection_parameters(
    *,
    rest_base_uri: str = MOCK_WORKDAY_REST_BASE_URI,
    base_uri: str = MOCK_WORKDAY_BASE_URI,
    tenant_name: str = MOCK_WORKDAY_TENANT,
    resource_uri: str = MOCK_WORKDAY_RESOURCE_URI,
    token_uri: str = MOCK_WORKDAY_TOKEN_URI,
    client_id: str = MOCK_WORKDAY_CLIENT_ID,
) -> dict:
    """Return the validated Workday sharedConnectionParameters shape."""
    return {
        "name": "oauth",
        "values": {
            "token:ResourceUri": {"value": resource_uri},
            "token:WorkdayTokenUri": {"value": token_uri},
            "token:WorkdayClientId": {"value": client_id},
            "baseUri": {"value": base_uri},
            "restBaseUri": {"value": rest_base_uri},
            "tenantName": {"value": tenant_name},
        },
    }


def workday_connection_reference(
    *,
    rest_base_uri: str = MOCK_WORKDAY_REST_BASE_URI,
    include_shared_parameters: bool = True,
) -> dict:
    """Return a cassette-shaped Workday connection reference change."""
    ref = {
        "connectionReferenceLogicalName": (
            "cr123_shared_workdaysoap.shared_workdaysoap.workday"
        ),
        "connectorId": "/providers/Microsoft.PowerApps/apis/shared_workdaysoap",
        "displayName": "Workday SOAP",
    }
    if include_shared_parameters:
        ref["sharedConnectionParameters"] = json.dumps(
            workday_shared_connection_parameters(rest_base_uri=rest_base_uri)
        )
    return {"connectionReference": ref}


def servicenow_connection_reference() -> dict:
    """Return a cassette-shaped non-Workday connection reference change."""
    return {
        "connectionReference": {
            "connectionReferenceLogicalName": (
                "cr123_shared_service-now.shared_service-now.servicenow"
            ),
            "connectorId": "/providers/Microsoft.PowerApps/apis/shared_service-now",
            "displayName": "ServiceNow",
        }
    }


def component_change_set() -> dict:
    """Return a validated PvaComponentChangeSet sample from the cassette."""
    return {
        "connectionReferenceChanges": [
            workday_connection_reference(),
            servicenow_connection_reference(),
        ],
        "botComponentChanges": [
            {
                "schemaName": "cr123_topic",
                "displayName": "Workday topic",
            }
        ],
        "cloudFlowDefinitionChanges": [],
        "connectorDefinitionChanges": [],
        "environmentVariableChanges": [],
    }


def component_change_set_without_workday() -> dict:
    """Return a validated bad-agent sample with only ServiceNow references."""
    data = component_change_set()
    data["connectionReferenceChanges"] = [servicenow_connection_reference()]
    return data


def configure_response() -> dict:
    """Return a documented AlmReadConfigResult sample.

    Source: ``swagger.json`` schema ``AlmReadConfigResult``. Minimal sample:

    {
      "realm": "contoso",
      "cdsBotId": "11111111-2222-3333-4444-555555555555",
      "schemaName": "cr123_essagent",
      "grsRepositoryId": "repo-123",
      "commitSha": "abc123",
      "values": {"EnvironmentName": "ESS test"}
    }
    """
    return {
        "realm": MOCK_REALM,
        "cdsBotId": MOCK_BOT_ID,
        "schemaName": "cr123_essagent",
        "grsRepositoryId": "repo-123",
        "commitSha": "abc123",
        "values": {"EnvironmentName": "ESS test"},
    }
