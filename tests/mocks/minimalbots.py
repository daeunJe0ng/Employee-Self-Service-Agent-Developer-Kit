# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Mock builders for the Copilot Studio minimalBots PPAPI surface."""

from __future__ import annotations

MOCK_STATUS = "validated"
MOCK_SCHEMA_SOURCE = (
    "tests\\fixtures\\cassettes\\flightcheck_minimalbots_components.yaml"
)

MOCK_ENV_ID_TEST_SUFFIX_0 = "5dd45044-46ac-e5c5-ab49-01f33d403cb0"
MOCK_ENV_ID_TEST_SUFFIX_A = "1cdc648c-c9c2-e85a-958b-b1360a6acdaa"
MOCK_ENV_ID_PROD = "ecf4737d-bef7-e58a-aa5e-e71a60780efc"
MOCK_BOT_ID = "11111111-2222-3333-4444-555555555555"
MOCK_GOOD_WORKDAY_BOT_ID = "dad486e8-a0f5-4d64-8774-fe04df05baf5"
MOCK_BAD_SERVICENOW_BOT_ID = "a7828f58-bde1-451c-8105-3c2c785cd9e0"
MOCK_REALM = "contoso"
MOCK_HOST_TEST_SUFFIX_0 = (
    "https://5dd4504446ace5c5ab4901f33d403cb.0.environment.api.test.powerplatform.com"
)
MOCK_HOST_PROD = (
    "https://ecf4737dbef7e58aaa5ee71a60780e.fc.environment.api.powerplatform.com"
)


def component_change_set() -> dict:
    """Return a validated minimalBots components sample for a Workday DA.

    Source: ``flightcheck_minimalbots_components.yaml``. Values and IDs are
    redacted, but the envelope shape and schemaName patterns match the cassette.
    """
    return {
        "connectionReferenceChanges": [
            {
                "logicalName": "shared_workdaysoap_ff0df",
                "displayName": "Workday SOAP",
            }
        ],
        "botComponentChanges": [
            _dialog_component("gptagent_esshr_cosmosda_v2.topic.WorkdayGetVisas"),
            _dialog_component("gptagent_esshr_cosmosda_v2.topic.WorkdayGetMyPaySlips"),
            _dialog_component("gptagent_esshr_cosmosda_v2.topic.WorkdayUpdatePhoneNumber"),
            _dialog_component("gptagent_esshr_cosmosda_v2.topic.WorkdayUpdateEmail"),
            _dialog_component("gptagent_esshr_cosmosda_v2.topic.WorkdaySystemGetReferenceData"),
            _dialog_component("gptagent_esshr_cosmosda_v2.topic.WorkdaySystemRefreshReferenceData"),
            _variable_component("gptagent_esshr_cosmosda_v2.variable.CompanyNameLookupTable"),
            _variable_component("gptagent_esshr_cosmosda_v2.variable.VisaTypeLookupTable"),
            _variable_component("gptagent_esshr_cosmosda_v2.variable.PassportIdTypeLookupTable"),
        ],
        "cloudFlowDefinitionChanges": [],
        "connectorDefinitionChanges": [],
        "environmentVariableChanges": [],
    }


def servicenow_component_change_set() -> dict:
    """Return a validated ServiceNow-only minimalBots components sample."""
    return {
        "connectionReferenceChanges": [
            {
                "logicalName": "shared_service-now_ff0df",
                "displayName": "ServiceNow",
            }
        ],
        "botComponentChanges": [
            _dialog_component("gptagent_esshr_servicenow.topic.ServiceNowCreateTicket"),
            _dialog_component("gptagent_esshr_servicenow.topic.ServiceNowGetTickets"),
            _variable_component("gptagent_esshr_servicenow.variable.CaseCategoryList"),
        ],
        "cloudFlowDefinitionChanges": [],
        "connectorDefinitionChanges": [],
        "environmentVariableChanges": [],
    }


def _dialog_component(schema_name: str) -> dict:
    return {
        "$kind": "BotComponentInsert",
        "component": {
            "$kind": "DialogComponent",
            "schemaName": schema_name,
            "displayName": schema_name.rsplit(".", 1)[-1],
        },
    }


def _variable_component(schema_name: str) -> dict:
    return {
        "$kind": "BotComponentInsert",
        "component": {
            "$kind": "GlobalVariableComponent",
            "schemaName": schema_name,
            "variable": {
                "$kind": "Variable",
                "name": schema_name.rsplit(".", 1)[-1],
                "scope": "User",
            },
        },
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
