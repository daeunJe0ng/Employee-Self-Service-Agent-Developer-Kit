# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Mock builders for the Copilot Studio minimalBots PPAPI surface."""

from __future__ import annotations

MOCK_STATUS = "documented"
MOCK_SCHEMA_SOURCE = (
    "C:\\Users\\dawnjeong\\knowledge\\ess-da-migration\\documents\\swagger.json"
)

MOCK_ENV_ID_TEST_SUFFIX_0 = "5dd45044-46ac-e5c5-ab49-01f33d403cb0"
MOCK_ENV_ID_TEST_SUFFIX_A = "1cdc648c-c9c2-e85a-958b-b1360a6acdaa"
MOCK_ENV_ID_PROD = "ecf4737d-bef7-e58a-aa5e-e71a60780efc"
MOCK_BOT_ID = "11111111-2222-3333-4444-555555555555"
MOCK_REALM = "contoso"
MOCK_HOST_TEST_SUFFIX_0 = (
    "https://5dd4504446ace5c5ab4901f33d403cb.0.environment.api.test.powerplatform.com"
)
MOCK_HOST_PROD = (
    "https://ecf4737dbef7e58aaa5ee71a60780e.fc.environment.api.powerplatform.com"
)


def component_change_set() -> dict:
    """Return a documented PvaComponentChangeSet sample.

    Source: ``swagger.json`` schema ``PvaComponentChangeSet``. The response
    defines arrays including ``connectionReferenceChanges`` and
    ``botComponentChanges``. Minimal sample:

    {
      "connectionReferenceChanges": [
        {"logicalName": "shared_workdaysoap_ff0df", "displayName": "Workday SOAP"}
      ],
      "botComponentChanges": [
        {"schemaName": "cr123_topic", "displayName": "Workday topic"}
      ]
    }
    """
    return {
        "connectionReferenceChanges": [
            {
                "logicalName": "shared_workdaysoap_ff0df",
                "displayName": "Workday SOAP",
            }
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


def import_result() -> dict:
    """Return a documented AlmImportResult sample.

    Source: ``swagger.json`` schema ``AlmImportResult``. The import endpoint
    mints a fresh Dev agent and returns its CDS bot id and physical schema
    name:

    {
      "cdsBotId": "11111111-2222-3333-4444-555555555555",
      "schemaName": "cr123_essagent"
    }
    """
    return {
        "cdsBotId": MOCK_BOT_ID,
        "schemaName": "cr123_essagent",
    }
