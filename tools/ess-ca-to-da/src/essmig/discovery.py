"""Discover what the customer changed in their Custom Engine Agent.

The algorithm, in order:

1. Resolve the ESS base solution's ``solutionid`` from its unique name.
   ``RetrieveDependenciesForUninstallWithMetadata`` takes a ``SolutionId``
   (``Edm.Guid``), not the unique name.
2. Call that function to enumerate every component that *depends on* the ESS base
   solution — net-new topics, knowledge sources, and other customer-authored
   content. This misses in-place edits of out-of-box components (an edit adds an
   ``Active`` layer but creates no dependency), so also read the agent's own
   ``botcomponent`` records by schema-name prefix and union the two sets.
3. For each target, read its solution **layers** from ``msdyn_componentlayers``.
4. Classify each component from its layer set, and keep the customized,
   migratable ones (untouched out-of-box components are dropped here).
5. Optionally narrow to the customer's preferred (unmanaged) solution.

Hard-won details that are easy to get wrong:

* ``msdyn_componentlayers`` is a **virtual table**. Its ``$filter`` must pair
  ``msdyn_componentid`` with ``msdyn_solutioncomponentname`` (the source table's
  logical name, e.g. ``botcomponent``), and it will **not** honour an ``OR`` over
  several component ids — OR-ing silently returns a couple of rows. One query per
  component is mandatory.
* ``msdyn_overwritetime`` is **not** a customization signal: a net-new unmanaged
  topic reads ``1900-01-01``. Classify from ``msdyn_solutionname`` instead.
* A layer's real attributes live inside ``msdyn_componentjson``, a JSON *string*
  holding an ``Attributes`` list of ``{"Key", "Value"}`` pairs. ``componenttype``
  is itself wrapped as ``{"Value": <int>}``.
* Preferred-solution membership cannot be read from layers — every unmanaged
  solution shares the one ``Active`` layer. Read ``solutioncomponents`` instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from essmig.dataverse import DataverseClient
from essmig.ess import (
    BOT_COMPONENT_TYPE_LABELS,
    CA_AGENT_SCHEMANAMES,
    CA_SOLUTION_BY_VERTICAL,
    MIGRATABLE_COMPONENT_TYPES,
    OOB_CA_SOLUTIONS,
    TARGETS,
    schema_suffix,
)

_DEPENDENCIES_FUNCTION = "RetrieveDependenciesForUninstallWithMetadata"
_SOLUTIONS_ENTITY = "solutions"
_SOLUTION_COMPONENTS_ENTITY = "solutioncomponents"
_COMPONENT_LAYERS_ENTITY = "msdyn_componentlayers"
_BOTCOMPONENTS_ENTITY = "botcomponents"
_BOTCOMPONENT_ENTITY_NAME = "botcomponent"

_OBJECT_ID_FIELD = "dependentcomponentobjectid"
_ENTITY_NAME_FIELD = "dependentcomponententitylogicalname"
_SOLUTION_NAME_FIELD = "msdyn_solutionname"
_COMPONENT_JSON_FIELD = "msdyn_componentjson"
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"


@dataclass
class CaComponent:
    """One customized Custom Engine Agent component, hydrated from its layers."""

    component_id: str
    schemaname: str
    name: str
    component_type: int | None
    data: str | None
    statecode: Any = None
    statuscode: Any = None
    layers: list[dict[str, Any]] = field(default_factory=list)

    @property
    def component_type_label(self) -> str:
        if self.component_type is None:
            return "Unknown"
        return BOT_COMPONENT_TYPE_LABELS.get(self.component_type, f"Type {self.component_type}")

    @property
    def suffix(self) -> str:
        """The agent-independent join key used to find the DA counterpart."""
        return schema_suffix(self.schemaname)

    @property
    def solutions(self) -> list[str]:
        """The unique names of the solutions this component is layered from."""
        return [
            name
            for layer in self.layers
            if isinstance(name := layer.get(_SOLUTION_NAME_FIELD), str) and name
        ]

    @property
    def is_net_new(self) -> bool:
        """True when the customer authored this component, rather than editing OOB content.

        A net-new component exists only in the customer's own (unmanaged) solution,
        so it has exactly one layer and that layer is not an OOB ESS solution.
        """
        return len(self.layers) == 1 and not _in_oob_solution(self.layers[0])

    def to_json(self) -> dict[str, Any]:
        """Snapshot form — everything needed to reconstruct the original, minus raw layers."""
        return {
            "component_id": self.component_id,
            "schemaname": self.schemaname,
            "suffix": self.suffix,
            "name": self.name,
            "component_type": self.component_type,
            "component_type_label": self.component_type_label,
            "is_net_new": self.is_net_new,
            "statecode": self.statecode,
            "statuscode": self.statuscode,
            "solutions": [layer.get(_SOLUTION_NAME_FIELD) for layer in self.layers],
            "data": self.data,
        }


@dataclass
class DiscoveryResult:
    vertical: str
    solution_unique_name: str
    solution_id: str
    components: dict[str, CaComponent]
    skipped: list[dict[str, Any]]
    """Customized components that were dropped, with the reason — reported, not silent."""


def installed_targets(client: DataverseClient) -> list[str]:
    """The ESS agents whose base solution is installed in this environment.

    Returns the matching ``TARGETS`` verticals in canonical order (core, hr, it).
    Lets the CLI migrate every ESS agent a customer actually has without the caller
    naming each one: the three base solutions have fixed unique names, so their mere
    presence in ``solutions`` is the signal. An empty list means no ESS Custom Engine
    Agent is installed here.
    """
    present: list[str] = []
    for vertical in TARGETS:
        unique_name = CA_SOLUTION_BY_VERTICAL[vertical]
        rows = client.query_all(
            _SOLUTIONS_ENTITY, select="solutionid", filter=f"uniquename eq '{unique_name}'"
        )
        if any(isinstance(row.get("solutionid"), str) and row.get("solutionid") for row in rows):
            present.append(vertical)
    return present


def discover(
    client: DataverseClient,
    vertical: str,
    *,
    preferred_solution: str | None = None,
) -> DiscoveryResult:
    """Return the customer's customizations for one ESS vertical ("hr" or "it")."""
    unique_name = CA_SOLUTION_BY_VERTICAL.get(vertical)
    if unique_name is None:
        raise ValueError(
            f"Unknown vertical {vertical!r}; expected one of {list(CA_SOLUTION_BY_VERTICAL)}."
        )

    solution_id = _resolve_solution_id(client, unique_name)
    response = client.call_function(_DEPENDENCIES_FUNCTION, SolutionId=solution_id)
    dependents = _extract_dependents(response)

    # The dependency function only returns components that *depend on* the managed
    # base (net-new topics, knowledge sources, and the like). An in-place edit of an
    # out-of-box component — e.g. changing the agent instructions on gpt.default —
    # adds an "Active" layer to that existing component but creates no such
    # dependency, so it is invisible here. Enumerate the agent's own botcomponents
    # directly and union them in; the layer classification below then drops the ones
    # that were never touched (a single managed layer) and keeps the real edits.
    owned = _owned_botcomponents(client, vertical)
    targets = _dedupe_targets(dependents, owned)

    layers_by_component = {
        object_id: client.query_all(
            _COMPONENT_LAYERS_ENTITY,
            select=None,
            filter=(
                f"msdyn_componentid eq '{object_id}' and "
                f"msdyn_solutioncomponentname eq '{entity_name}'"
            ),
        )
        for object_id, entity_name in targets
    }

    components, skipped = _classify(layers_by_component, vertical)

    if preferred_solution:
        member_ids = _preferred_solution_members(client, preferred_solution)
        for component_id in list(components):
            if _norm_guid(component_id) not in member_ids:
                skipped.append(
                    {
                        "component_id": component_id,
                        "schemaname": components[component_id].schemaname,
                        "reason": f"not a member of preferred solution '{preferred_solution}'",
                    }
                )
                del components[component_id]

    return DiscoveryResult(
        vertical=vertical,
        solution_unique_name=unique_name,
        solution_id=solution_id,
        components=components,
        skipped=skipped,
    )


def _classify(
    layers_by_component: dict[str, list[dict[str, Any]]], vertical: str
) -> tuple[dict[str, CaComponent], list[dict[str, Any]]]:
    """Keep the components that are both *customized* and *migratable*.

    **Customized** — more than one layer (a managed OOB base plus the customer's
    overlay), or a lone layer outside the OOB ESS solutions (a net-new component
    living in the unmanaged ``Active`` layer). A lone layer inside an OOB ESS
    managed solution is untouched out-of-box content and is dropped silently.

    **Migratable** — an allow-listed ``componenttype`` whose schema name belongs to
    this vertical's agent. Anything customized but not migratable is dropped *with
    a reason*, so the report can tell the customer what was left behind.
    """
    kept: dict[str, CaComponent] = {}
    skipped: list[dict[str, Any]] = []
    prefix = CA_AGENT_SCHEMANAMES[vertical]

    for component_id, layers in layers_by_component.items():
        if not _is_customized(layers):
            continue
        attributes = _component_attributes(layers)
        component = _hydrate(component_id, layers, attributes)

        if not component.schemaname.lower().startswith(prefix):
            skipped.append(
                {
                    "component_id": component_id,
                    "schemaname": component.schemaname,
                    "reason": f"owned by another agent (expected prefix '{prefix}')",
                }
            )
            continue
        if component.component_type not in MIGRATABLE_COMPONENT_TYPES:
            skipped.append(
                {
                    "component_id": component_id,
                    "schemaname": component.schemaname,
                    "reason": f"component type not migratable: {component.component_type_label}",
                }
            )
            continue
        kept[component_id] = component

    return kept, skipped


def _is_customized(layers: list[dict[str, Any]]) -> bool:
    if len(layers) > 1:
        return True
    return any(not _in_oob_solution(layer) for layer in layers)


def _in_oob_solution(layer: dict[str, Any]) -> bool:
    return layer.get(_SOLUTION_NAME_FIELD) in OOB_CA_SOLUTIONS


def _hydrate(
    component_id: str, layers: list[dict[str, Any]], attributes: dict[str, Any]
) -> CaComponent:
    return CaComponent(
        component_id=component_id,
        schemaname=_str(attributes.get("schemaname")),
        name=_str(attributes.get("name")),
        component_type=_component_type(attributes),
        data=attributes.get("data") if isinstance(attributes.get("data"), str) else None,
        statecode=attributes.get("statecode"),
        statuscode=attributes.get("statuscode"),
        layers=layers,
    )


def _ordered_base_first(layers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the layers base-first: managed OOB layers, then the customer's overlay.

    The ``msdyn_componentlayers`` virtual table does not honour ``$orderby`` and its
    row order is undocumented, so we must not rely on it. Solution-layer semantics
    are unambiguous, though: the customer's unmanaged overlay (the ``Active`` layer,
    which is *not* one of the OOB ESS solutions) always sits above the managed OOB
    base. A stable sort that places OOB layers first therefore makes the customer's
    edit win in :func:`_component_attributes`, whichever order Dataverse returned —
    the difference between reading the customer's instructions and silently reading
    the shipped baseline.
    """
    return sorted(layers, key=lambda layer: 0 if _in_oob_solution(layer) else 1)


def _component_attributes(layers: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge each layer's ``msdyn_componentjson`` attributes, topmost layer winning.

    Layers are ordered base-first (see :func:`_ordered_base_first`), so later entries
    overwrite earlier ones and the customer's unmanaged overlay ends up as the
    effective value regardless of the order Dataverse returned the rows.
    """
    merged: dict[str, Any] = {}
    for layer in _ordered_base_first(layers):
        raw = layer.get(_COMPONENT_JSON_FIELD)
        if not isinstance(raw, str) or not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        attributes = payload.get("Attributes") if isinstance(payload, dict) else None
        if not isinstance(attributes, list):
            continue
        for entry in attributes:
            if isinstance(entry, dict) and isinstance(entry.get("Key"), str):
                merged[entry["Key"]] = entry.get("Value")
    return merged


def _component_type(attributes: dict[str, Any]) -> int | None:
    """``componenttype`` is wrapped as ``{"Value": <int>}``, unlike the plain attributes."""
    value = attributes.get("componenttype")
    if isinstance(value, dict):
        value = value.get("Value")
    return value if isinstance(value, int) else None


def _extract_dependents(response: Any) -> list[tuple[str, str]]:
    """Unique ``(objectid, entity_logical_name)`` pairs from the dependency metadata.

    The entity logical name is required: ``msdyn_componentlayers`` cannot resolve a
    component without it. The all-zero GUID is a placeholder and is skipped.
    """
    seen: set[str] = set()
    dependents: list[tuple[str, str]] = []
    for info in _dependency_infos(response):
        if not isinstance(info, dict):
            continue
        object_id = info.get(_OBJECT_ID_FIELD)
        entity_name = info.get(_ENTITY_NAME_FIELD)
        if (
            isinstance(object_id, str)
            and object_id
            and object_id != _EMPTY_GUID
            and isinstance(entity_name, str)
            and entity_name
            and object_id not in seen
        ):
            seen.add(object_id)
            dependents.append((object_id, entity_name))
    return dependents


def _owned_botcomponents(client: DataverseClient, vertical: str) -> list[tuple[str, str]]:
    """``(botcomponentid, "botcomponent")`` for the agent's own migratable components.

    Read straight from the ``botcomponent`` table by schema-name prefix, so an
    in-place edit of an out-of-box component (which the uninstall-dependency function
    never reports) still reaches the layer classification. Restricted to the
    migratable component types to keep the follow-up per-component layer queries
    bounded; untouched components are dropped there, not here.
    """
    prefix = CA_AGENT_SCHEMANAMES[vertical]
    type_filter = " or ".join(
        f"componenttype eq {component_type}"
        for component_type in sorted(MIGRATABLE_COMPONENT_TYPES)
    )
    rows = client.query_all(
        _BOTCOMPONENTS_ENTITY,
        select="botcomponentid",
        filter=f"startswith(schemaname,'{prefix}.') and ({type_filter})",
    )
    owned: list[tuple[str, str]] = []
    for row in rows:
        object_id = row.get("botcomponentid")
        if isinstance(object_id, str) and object_id and object_id != _EMPTY_GUID:
            owned.append((object_id, _BOTCOMPONENT_ENTITY_NAME))
    return owned


def _dedupe_targets(
    dependents: list[tuple[str, str]], owned: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Union two ``(object_id, entity_name)`` lists, deduped by object-id.

    Dependents come first so their (already-correct) entity name wins when a
    component is reported by both sources.
    """
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []
    for object_id, entity_name in [*dependents, *owned]:
        key = _norm_guid(object_id)
        if key in seen:
            continue
        seen.add(key)
        targets.append((object_id, entity_name))
    return targets


def _dependency_infos(response: Any) -> list[Any]:
    if not isinstance(response, dict):
        return []
    collection = response.get("DependencyMetadataCollection")
    if not isinstance(collection, dict):
        return []
    infos = collection.get("DependencyMetadataInfoCollection")
    return infos if isinstance(infos, list) else []


def _resolve_solution_id(client: DataverseClient, unique_name: str) -> str:
    rows = client.query_all(
        _SOLUTIONS_ENTITY, select="solutionid", filter=f"uniquename eq '{unique_name}'"
    )
    for row in rows:
        solution_id = row.get("solutionid")
        if isinstance(solution_id, str) and solution_id:
            return solution_id
    raise RuntimeError(
        f"Solution '{unique_name}' was not found in this environment. "
        "Is the ESS Custom Engine Agent installed here?"
    )


def _preferred_solution_members(client: DataverseClient, unique_name: str) -> set[str]:
    """Object-ids of the components contained in a solution.

    Confirmed live: a Copilot topic appears as its own ``solutioncomponents`` row
    with ``objectid`` equal to its ``botcomponentid`` and ``componenttype`` 10213.
    """
    solution_id = _resolve_solution_id(client, unique_name)
    rows = client.query_all(
        _SOLUTION_COMPONENTS_ENTITY,
        select="objectid",
        filter=f"_solutionid_value eq {solution_id}",
    )
    return {
        _norm_guid(object_id)
        for row in rows
        if isinstance((object_id := row.get("objectid")), str) and object_id
    }


def _norm_guid(value: str) -> str:
    return value.strip().strip("{}").lower()


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""
