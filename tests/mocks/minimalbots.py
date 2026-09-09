# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Mock builders for the Copilot Studio minimalBots PPAPI surface."""

from __future__ import annotations

MOCK_STATUS = "validated"
MOCK_CASSETTE = "tests/fixtures/cassettes/flightcheck_minimalbots_alm.yaml"
MOCK_SCHEMA_SOURCE = (
    "C:\\Users\\dawnjeong\\knowledge\\ess-da-migration\\documents\\swagger.json"
)

MOCK_ENV_ID_TEST_SUFFIX_0 = "5dd45044-46ac-e5c5-ab49-01f33d403cb0"
MOCK_ENV_ID_TEST_SUFFIX_A = "1cdc648c-c9c2-e85a-958b-b1360a6acdaa"
MOCK_ENV_ID_PROD = "ecf4737d-bef7-e58a-aa5e-e71a60780efc"
MOCK_BOT_ID = "00000000-0000-0000-0000-000000001111"
MOCK_NOT_ALM_BOT_ID = "00000000-0000-0000-0000-000000002222"
MOCK_REALM = "Dev"
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


def configure_response(
    *,
    realm: str = MOCK_REALM,
    cds_bot_id: str = MOCK_BOT_ID,
    grs_repository_id: str = "00000000-0000-0000-0000-000000001111",
    commit_sha: str = "0b3007b07220fbbea5a7cf7c5a0c4681a247018a",
) -> dict:
    """Return the validated ALM GetConfigure success shape.

    Source: validated cassette
    ``tests/fixtures/cassettes/flightcheck_minimalbots_alm.yaml``. The
    captured opted-agent branch returns ``grsRepositoryId`` and ``commitSha``:

    {
      "realm": "Dev",
      "cdsBotId": "00000000-0000-0000-0000-000000001111",
      "schemaName": "gptagent_esshr_cosmosda_v2",
      "grsRepositoryId": "00000000-0000-0000-0000-000000001111",
      "commitSha": "0b3007b07220fbbea5a7cf7c5a0c4681a247018a",
      "values": {"botName": "ESS HR - Cosmos DA (ServiceNow, flowless)"}
    }
    """
    return {
        "realm": realm,
        "cdsBotId": cds_bot_id,
        "schemaName": "gptagent_esshr_cosmosda_v2",
        "grsRepositoryId": grs_repository_id,
        "commitSha": commit_sha,
        "values": {
            "botName": "ESS HR - Cosmos DA (ServiceNow, flowless)",
            "gptDisplayName": "ESS HR - Cosmos DA (ServiceNow, flowless)",
        },
        "flows": {},
        "connections": {
            "gptagent_esshr_cosmosda_v2.shared_service-now.servicenow": {
                "connectorId": "/providers/Microsoft.PowerApps/apis/shared_service-now",
                "connectionId": "00000000000000000000000000000000",
            }
        },
    }


def configure_not_opted_response(
    *,
    cds_bot_id: str = MOCK_NOT_ALM_BOT_ID,
) -> dict:
    """Return the validated ALM GetConfigure not-opted error shape.

    Source: validated cassette
    ``tests/fixtures/cassettes/flightcheck_minimalbots_alm.yaml``. The
    captured non-ALM agent branch returns HTTP 400 with ``ErrorCode`` 4003:

    {
      "ErrorCode": 4003,
      "ErrorMessage": "Agent '...' is not opted into ALM. Opt the agent in first.",
      "Error": {"Code": "BadRequest", "Message": "Agent '...' is not opted into ALM. Opt the agent in first."}
    }
    """
    message = f"Agent '{cds_bot_id}' is not opted into ALM. Opt the agent in first."
    return {
        "ErrorCode": 4003,
        "ErrorMessage": message,
        "ErrorInfo": None,
        "Error": {
            "RetryIn": None,
            "InnerErrors": [],
            "Code": "BadRequest",
            "Message": message,
            "Properties": {},
            "Diagnostics": "<internal-diagnostics-redacted>",
        },
    }
