# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Helpers for reading Declarative Agent components from AgentBuilder."""

from __future__ import annotations

from typing import Any


def agent_bot_id(config: dict[str, Any]) -> str:
    """Return the active configured botId, or ``""`` when none is available."""
    active_slug = config.get("activeAgent") or (config.get("agent") or {}).get(
        "slug"
    )
    agents = config.get("agents") or []
    if active_slug:
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            if agent.get("slug") == active_slug and agent.get("botId"):
                return str(agent["botId"])
    for agent in agents:
        if isinstance(agent, dict) and agent.get("botId"):
            return str(agent["botId"])
    return str((config.get("agent") or {}).get("botId") or "")


def _component_schema_name(change: Any) -> str:
    if not isinstance(change, dict):
        return ""
    component = change.get("component")
    if not isinstance(component, dict):
        component = change.get("botComponent")
    if not isinstance(component, dict):
        component = change
    return str(
        component.get("schemaName")
        or component.get("name")
        or change.get("schemaName")
        or ""
    )


def read_component_schema_names(runner) -> set[str] | None:
    """Return schema names from AgentBuilder ``botComponentChanges``.

    ``None`` means the AgentBuilder client or active botId is unavailable.
    A missing ``botComponentChanges`` key means the agent has no component
    changes. A present non-list value is an invalid API shape and raises.
    """
    client = getattr(runner, "agentbuilder", None)
    config = getattr(runner, "config", None) or {}
    bot_id = agent_bot_id(config)
    if client is None or not bot_id:
        return None

    payload = client.fetch_components(bot_id) or {}
    changes = payload.get("botComponentChanges")
    if changes is None:
        return set()
    if not isinstance(changes, list):
        raise ValueError("Component fetch returned invalid botComponentChanges.")
    return {name for name in (_component_schema_name(c) for c in changes) if name}
