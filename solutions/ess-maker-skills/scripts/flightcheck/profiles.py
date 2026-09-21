# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Connect-facing validation profiles.

The Connect Workday skill does not gate on the whole FlightCheck surface at
once; it gates individual setup stages (is the environment ready, is the
Workday connection bound, are the topics wired, does the agent answer). A
**profile** is a named, ordered set of already-registered checkpoint IDs that
maps one Connect stage to the checks that prove it.

This module is pure plumbing over ``registry.py``:

* it introduces **no new checkpoint** and calls **no external API** (so the
  cardinal API-contract rule in ``AGENTS.md`` does not apply here — the checks
  a profile references already own their contracts),
* every member is an existing registry target (a fixed ID like ``WD-PKG-001``
  or a family like ``WD-CONN``), validated at import,
* running a profile reuses the exact hydrate-then-filter machinery a single
  ``--checkpoint`` run uses: the union of every member's transitive
  prerequisite closure hydrates shared state, then a matcher keeps only the
  rows any member owns.

A profile therefore emits the **existing** ``results.json`` contract
(``RunResult`` / ``CheckResult`` in ``runner.py``) unchanged. It does not
define a new result shape.

**Provisional membership.** The specific profile names and their member lists
below are a FlightCheck-side grouping of the current Workday DA checks. The
exact Connect-facing stage boundaries are expected to be pinned by the Connect
Workday skill design doc; until then, treat the names/membership as adjustable.
The *mechanism* (named profiles -> union plan + matcher over the existing
registry) is stable regardless of how the stages are finally cut.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from flightcheck import registry


@dataclass(frozen=True)
class Profile:
    """A named Connect-facing validation stage.

    ``members`` are registry targets (fixed IDs or family keys) in the order a
    reader would reason about the stage. Execution order is still governed by
    ``registry.CATEGORY_ORDER`` when the plan is built, so member order here is
    for readability only — it never changes which checks run first.
    """

    name: str
    title: str
    description: str
    members: tuple = ()


@dataclass
class ProfilePlan:
    """The fully-resolved execution plan for a profile run.

    Mirrors ``registry.ResolvedPlan`` but spans multiple targets: the fields
    are the **union** across every member's transitive prerequisite closure.
    ``matcher`` keeps a hydrated run down to just the rows the profile owns.
    """

    profile: Profile
    clients: frozenset
    requires_config: bool
    requires_dataverse_endpoint: bool
    # (category_label, category_fn) pairs to register on the runner, ordered by
    # registry.CATEGORY_ORDER and de-duped by function — same contract as
    # registry.ResolvedPlan.ordered_fns.
    ordered_fns: list = field(default_factory=list)
    matcher: Callable[[str], bool] = field(default=lambda _cid: False)


# ---------------------------------------------------------------------------
# The profiles. Every member MUST resolve through registry.resolve() — this is
# asserted at import by validate_profiles(). Keep members pointed at real
# registry keys; a typo fails fast rather than silently matching nothing.
# ---------------------------------------------------------------------------
_PROFILES: list[Profile] = [
    Profile(
        name="workday-setup",
        title="Workday setup readiness",
        description=(
            "Environment, ESS solution, and Workday package are present and "
            "healthy enough to begin binding the agent."
        ),
        members=(
            "ENV-001",
            "ENV-002",
            "ENV-009",
            "ENV-CAPACITY-001",
            "ESS-SOLN-001",
            "WD-PKG-001",
        ),
    ),
    Profile(
        name="workday-connection",
        title="Workday connection and prerequisites",
        description=(
            "The Workday connection is authenticated and bound, the REST "
            "endpoint and network path are reachable, and the Entra app / "
            "Workday tenant prerequisites are in place."
        ),
        members=(
            "DV-CONN-001",
            "WD-CONN-AUTH-001",
            "WD-CONN",
            "WD-REST-001",
            "WD-REST-002",
            "WD-NET-001",
            "WD-API-CLIENT-001",
            "WD-TENANT-001",
            "WD-ASSIGN-001",
            "WD-ENTRA-CONSENT-001",
            "WD-ENTRA-NAMEID-001",
            "WD-ENTRA-SCOPE-001",
            "WD-ENTRA-SIGNOPT-001",
        ),
    ),
    Profile(
        name="workday-topics",
        title="Workday topics and integration",
        description=(
            "The Workday topics, triggers, flows, and workflow bindings that "
            "carry a request from the agent into Workday are wired up."
        ),
        members=(
            "TOPIC-INTEGRATION",
            "TOPIC-TRIGGER",
            "WD-WF",
            "WD-FLOW",
            "WD-ENV",
        ),
    ),
    Profile(
        name="workday-runtime",
        title="Workday agent runtime",
        description=(
            "The declarative agent itself is present, connected, has content, "
            "and its Workday connector answers a live probe."
        ),
        members=(
            "DA-AGENT-001",
            "DA-CONN",
            "DA-CONTENT-001",
            "WD-RUN-001",
        ),
    ),
]

def _dedup(members: tuple) -> tuple:
    """De-duplicate members while preserving first-seen order."""
    seen: set = set()
    ordered: list = []
    for m in members:
        if m in seen:
            continue
        seen.add(m)
        ordered.append(m)
    return tuple(ordered)


# The umbrella profile Connect calls at the final readiness gate. Goutham's
# Connect Workday design doc refers to "the Workday FlightCheck profile"
# (singular); this is that profile — the union of every staged profile above,
# de-duped in stage order. The staged profiles remain for incremental gating
# (Connect calls FlightCheck before setup, after each step, and at the final
# gate — design doc "FlightCheck integration").
_PROFILES.append(
    Profile(
        name="workday",
        title="Workday FlightCheck profile",
        description=(
            "The full Workday declarative-agent readiness profile: setup, "
            "connection, topics, and runtime. Connect calls this at the final "
            "readiness gate; the staged profiles gate individual setup steps."
        ),
        members=_dedup(
            tuple(m for p in _PROFILES for m in p.members)
        ),
    )
)

PROFILES: dict[str, Profile] = {p.name: p for p in _PROFILES}


class ProfileError(ValueError):
    """Raised when a profile name is unknown or a profile is malformed."""


def resolve_profile(name: str) -> Optional[Profile]:
    """Return the profile registered under ``name``, or None if unknown."""
    if not name:
        return None
    return PROFILES.get(name)


def list_profiles() -> list[Profile]:
    """Return all profiles, sorted by name, for ``--list-profiles``."""
    return sorted(PROFILES.values(), key=lambda p: p.name)


def profile_matcher(members: tuple) -> Callable[[str], bool]:
    """Build a runner ``target_matcher`` that keeps rows owned by ANY member.

    Reuses ``registry.matches`` per member so family membership (``WD-CONN`` ->
    ``WD-CONN-012``) and exact IDs behave identically to a single-checkpoint
    run.
    """
    member_list = tuple(members)

    def _matches(emitted_id: str) -> bool:
        return any(registry.matches(m, emitted_id) for m in member_list)

    return _matches


def combined_requirements(members: tuple) -> tuple:
    """Union every member's transitive requirements into one execution plan.

    Returns ``(clients, requires_config, requires_dataverse_endpoint,
    ordered_fns)`` where ``ordered_fns`` is the de-duped set of
    ``(category_label, category_fn)`` pairs ordered by
    ``registry.CATEGORY_ORDER`` — the same contract cli.py consumes for a
    single checkpoint, so the runner hydrates cross-category shared state
    correctly for the whole profile.
    """
    clients: frozenset = frozenset()
    requires_config = False
    requires_dataverse_endpoint = False

    seen_fns: set = set()
    unique: list[tuple] = []
    for member in members:
        plan = registry.transitive_requirements(member)
        clients = clients | plan.clients
        requires_config = requires_config or plan.requires_config
        requires_dataverse_endpoint = (
            requires_dataverse_endpoint or plan.requires_dataverse_endpoint
        )
        for label, fn in plan.ordered_fns:
            if fn in seen_fns:
                continue
            seen_fns.add(fn)
            unique.append((label, fn))

    def _order_index(label: str) -> int:
        try:
            return registry.CATEGORY_ORDER.index(label)
        except ValueError:
            return len(registry.CATEGORY_ORDER)

    unique.sort(key=lambda pair: _order_index(pair[0]))
    return clients, requires_config, requires_dataverse_endpoint, unique


def resolve_plan(name: str) -> ProfilePlan:
    """Resolve a profile name to its full execution plan.

    Raises ``ProfileError`` on an unknown profile name.
    """
    profile = resolve_profile(name)
    if profile is None:
        known = ", ".join(sorted(PROFILES)) or "(none)"
        raise ProfileError(
            f"Profile {name!r} is not registered. Known profiles: {known}."
        )

    clients, requires_config, requires_dv, ordered_fns = combined_requirements(
        profile.members
    )
    return ProfilePlan(
        profile=profile,
        clients=clients,
        requires_config=requires_config,
        requires_dataverse_endpoint=requires_dv,
        ordered_fns=ordered_fns,
        matcher=profile_matcher(profile.members),
    )


def validate_profiles() -> None:
    """Fail fast if any profile is malformed.

    Asserts (1) profile names are unique and non-empty, (2) every profile has
    at least one member, and (3) every member resolves through
    ``registry.resolve`` (no typos, no references to unregistered checkpoints).
    Called at import time and re-asserted by the profile tests.
    """
    seen_names: set = set()
    for profile in _PROFILES:
        if not profile.name:
            raise ProfileError("A profile has an empty name.")
        if profile.name in seen_names:
            raise ProfileError(f"Duplicate profile name {profile.name!r}.")
        seen_names.add(profile.name)

        if not profile.members:
            raise ProfileError(
                f"Profile {profile.name!r} has no members; a profile must "
                f"reference at least one checkpoint."
            )
        for member in profile.members:
            if registry.resolve(member) is None:
                raise ProfileError(
                    f"Profile {profile.name!r} references {member!r}, which "
                    f"does not resolve to any registered checkpoint or family."
                )


# Fail fast at import — a malformed profile is a programming error, not a
# runtime condition to handle, mirroring registry.validate_registry().
validate_profiles()
