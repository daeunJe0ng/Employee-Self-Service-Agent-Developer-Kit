# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Helpers for reading connection references from minimalBots components."""

from __future__ import annotations

from ._agent_connection_refs import AgentRefScope, _agent_bot_ids
from ._dlp_utils import normalize_connector_id


def normalize_connection_reference_change(change: dict) -> dict:
    """Convert a minimalBots connectionReferenceChange to the legacy row shape."""
    ref = (change or {}).get("connectionReference") or change or {}
    return {
        "connectionreferenceid": ref.get("id"),
        "connectionreferencelogicalname": ref.get("connectionReferenceLogicalName"),
        "connectionreferencedisplayname": ref.get("displayName"),
        "connectorid": ref.get("connectorId"),
        "connectionid": ref.get("connectionId"),
        "statuscode": ref.get("statuscode", ref.get("statusCode", 1)),
    }


def configured_bot_ids(runner) -> list[str]:
    config = getattr(runner, "config", None) or {}
    return _agent_bot_ids(config)


def read_minimalbots_connection_references(runner) -> list[dict] | None:
    """Return normalized minimalBots connection references, or None if unavailable."""
    minimalbots = getattr(runner, "minimalbots", None)
    bot_ids = configured_bot_ids(runner)
    if not minimalbots or not bot_ids:
        return None

    refs: list[dict] = []
    for bot_id in bot_ids:
        raw = minimalbots.get_connection_references(bot_id)
        if isinstance(raw, dict) and raw.get("_error"):
            if raw.get("_error") == "not_configured":
                return None
            raise RuntimeError(
                f"minimalBots connection reference read failed: {raw['_error']}"
            )
        refs.extend(
            normalize_connection_reference_change(change)
            for change in (raw or [])
        )
    return refs


def scope_from_refs(refs: list[dict]) -> AgentRefScope:
    return AgentRefScope(
        logical_names=frozenset(
            (r.get("connectionreferencelogicalname") or "").lower()
            for r in refs
            if r.get("connectionreferencelogicalname")
        ),
        connectors=frozenset(
            normalize_connector_id(r.get("connectorid"))
            for r in refs
            if r.get("connectorid")
        ),
    )
