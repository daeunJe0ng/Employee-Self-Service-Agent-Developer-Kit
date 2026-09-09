#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record cassettes for the Copilot Studio minimalBots PPAPI surface used by
the Declarative Agent (DA) re-point checks (G1-G4).

Two cassettes are produced:

  flightcheck_minimalbots_components.yaml
      POST /copilotstudio/minimalBots/api/{cdsBotId}/components
      -> connectionReferenceChanges[] (G1 ENV-004, G2 WD-REST-001/WD-ENV-001)
         botComponentChanges[]        (G3 WD-REF-001/WD-WF-CAT-001)

  flightcheck_minimalbots_alm.yaml
      GET  /copilotstudio/minimalBots/alm/{cdsBotId}/configure?realm=...
      -> values + grsRepositoryId + commitSha  (G4 ESS-SOLN-001 GRS presence)

Both are recorded from the production MinimalBotsClient so the request shape
(host, path, api-version, headers) matches exactly what the checks replay.

Auth: delegated MSAL via the client's own authenticate() (shared
.local/.token_cache.bin). This pops an interactive browser sign-in the first
time; the operator (you) signs in. The token is acquired OUTSIDE the cassette
context so no auth traffic is recorded.

Pre-reqs / knobs (all optional; defaults target prod-alm-hr-import):
    $env:ESS_ENVIRONMENT_ID = "5dd45044-46ac-e5c5-ab49-01f33d403cb0"
    $env:ESS_TENANT_ID      = "935884d7-bdee-469b-a461-fcc530a3ac83"
    $env:ESS_GOOD_BOT_ID    = "dad486e8-a0f5-4d64-8774-fe04df05baf5"  # WD+SNOW, 79 comps
    $env:ESS_BAD_BOT_ID     = "a7828f58-...."   # ServiceNow-only / negative case (optional)
    $env:ESS_MB_RING        = "prod"            # prod | test | int | preprod
    $env:ESS_MB_REALMS      = "Dev,Test,Prod"   # realms to probe for GetConfigure

    python tests\\captures\\record_flightcheck_minimalbots.py

Output: tests/fixtures/cassettes/flightcheck_minimalbots_components.yaml
        tests/fixtures/cassettes/flightcheck_minimalbots_alm.yaml

The redactor in _common.py scrubs the per-env PPAPI host, GUIDs, emails, and
the Authorization header before write. Eyeball the cassette for any leftover
tenant-specific strings (real connector display names, real repo ids) before
committing.
"""

from __future__ import annotations

import os

from _common import announce, build_cassette, chdir_kit_root, confirm_or_exit

DEFAULT_ENV_ID = "5dd45044-46ac-e5c5-ab49-01f33d403cb0"
DEFAULT_TENANT_ID = "935884d7-bdee-469b-a461-fcc530a3ac83"
DEFAULT_GOOD_BOT_ID = "dad486e8-a0f5-4d64-8774-fe04df05baf5"
# ALM-opted agent used for the export -> import -> delete publishing probe.
DEFAULT_ALM_BOT_ID = "a7828f58-bde1-451c-8105-3c2c785cd9e0"
DEFAULT_RING = "prod"
DEFAULT_REALMS = "Dev,Test,Prod"


def _summarize_components(label: str, agent_id: str, data: dict) -> None:
    if not isinstance(data, dict) or "_error" in data:
        print(f"    [{label}] components -> ERROR {data!r}")
        return
    conn_refs = data.get("connectionReferenceChanges") or []
    comp_changes = data.get("botComponentChanges") or []
    print(f"    [{label}] connectionReferenceChanges={len(conn_refs)}  "
          f"botComponentChanges={len(comp_changes)}")


def _summarize_configure(label: str, realm: str, cfg: dict) -> None:
    if not isinstance(cfg, dict) or "_error" in cfg:
        print(f"    [{label}] configure realm={realm} -> ERROR {cfg!r}")
        return
    grs = cfg.get("grsRepositoryId")
    commit = cfg.get("commitSha")
    values = cfg.get("values")
    n_values = len(values) if isinstance(values, (list, dict)) else "n/a"
    print(f"    [{label}] realm={realm}  grsRepositoryId={grs!r}  "
          f"commitSha={commit!r}  values={n_values}")


def main() -> None:
    announce("flightcheck_minimalbots_components / _alm")

    env_id = os.environ.get("ESS_ENVIRONMENT_ID", DEFAULT_ENV_ID)
    tenant_id = os.environ.get("ESS_TENANT_ID", DEFAULT_TENANT_ID)
    good_id = os.environ.get("ESS_GOOD_BOT_ID", DEFAULT_GOOD_BOT_ID)
    bad_id = os.environ.get("ESS_BAD_BOT_ID")  # optional
    ring = os.environ.get("ESS_MB_RING", DEFAULT_RING)
    realms = [r.strip() for r in
              os.environ.get("ESS_MB_REALMS", DEFAULT_REALMS).split(",") if r.strip()]

    agents = [("good", good_id)]
    if bad_id:
        agents.append(("bad", bad_id))

    print(f"  Environment: {env_id}  (ring={ring})")
    print(f"  Tenant:      {tenant_id}")
    for label, aid in agents:
        print(f"  Agent[{label}]: {aid}")
    if not bad_id:
        print("  Agent[bad]:  (not set) - set ESS_BAD_BOT_ID to capture the "
              "ServiceNow-only / ALM-opted negative case.")
    print(f"  Realms:      {realms}")
    print()

    confirm_or_exit()
    chdir_kit_root()

    from flightcheck.minimalbots_client import MinimalBotsClient

    client = MinimalBotsClient(tenant_id, environment_id=env_id, ring=ring)

    # Authenticate OUTSIDE the cassette so no auth traffic is recorded.
    print("  Step 1: authenticating (interactive browser on first run)...")
    client.authenticate()
    print("  Step 1: OK")
    print()

    # ---- Cassette 1: components (connection refs + component changes) ----
    print("  Step 2: recording components cassette...")
    with build_cassette("flightcheck_minimalbots_components"):
        for label, aid in agents:
            try:
                data = client.get_components(aid)
                _summarize_components(label, aid, data)
            except Exception as exc:  # noqa: BLE001 - record then continue
                print(f"    [{label}] components raised: {exc!s}")
    print()

    # ---- Cassette 2: ALM GetConfigure across realms (GRS presence) ----
    print("  Step 3: recording ALM configure cassette...")
    with build_cassette("flightcheck_minimalbots_alm"):
        for label, aid in agents:
            for realm in realms:
                try:
                    cfg = client.get_configure(aid, realm)
                    _summarize_configure(label, realm, cfg)
                except Exception as exc:  # noqa: BLE001 - record then continue
                    print(f"    [{label}] configure realm={realm} raised: {exc!s}")
    print()

    # ---- Cassette 3 (opt-in): publishing export -> import -> delete probe ----
    # Two-way door: imports a transient Dev agent from a real export, then
    # deletes it so the environment is left clean. Gated behind an explicit
    # env flag because it MUTATES the target environment. The redactor swaps
    # the real package bytes (export response body + import request body) for
    # a synthetic stand-in zip before anything is written to disk.
    if os.environ.get("ESS_MB_CAPTURE_PUBLISHING") == "1":
        alm_id = os.environ.get("ESS_ALM_BOT_ID", DEFAULT_ALM_BOT_ID)
        print(f"  Step 4: recording publishing cassette (MUTATING two-way door)")
        print(f"    export source (ALM-opted): {alm_id}")
        created_id = None
        try:
            with build_cassette("flightcheck_minimalbots_publishing"):
                package = client.export(alm_id)
                print(f"    export -> {len(package)} bytes"
                      f"{' (EMPTY - export failed)' if not package else ''}")
                if package:
                    result = client.import_package(package)
                    if isinstance(result, dict) and "_error" not in result:
                        created_id = result.get("cdsBotId")
                        print(f"    import -> created transient agent {created_id} "
                              f"schemaName={result.get('schemaName')!r}")
                        ok = client.delete_bot(created_id)
                        print(f"    delete {created_id} -> {'OK (204)' if ok else 'FAILED'}")
                        if ok:
                            created_id = None
                    else:
                        print(f"    import -> ERROR {result!r}")
        finally:
            # Safety net: guarantee no residue even if an assertion/exception
            # interrupted the recorded flow above.
            if created_id:
                print(f"    CLEANUP: deleting leftover agent {created_id} ...")
                if client.delete_bot(created_id):
                    print(f"    CLEANUP: deleted {created_id}")
                else:
                    print(f"    CLEANUP FAILED - manually delete agent {created_id} "
                          f"in env {env_id}")
        print()

    print("Cassettes written:")
    print("  tests/fixtures/cassettes/flightcheck_minimalbots_components.yaml")
    print("  tests/fixtures/cassettes/flightcheck_minimalbots_alm.yaml")
    if os.environ.get("ESS_MB_CAPTURE_PUBLISHING") == "1":
        print("  tests/fixtures/cassettes/flightcheck_minimalbots_publishing.yaml")
    print()
    print("Review by hand for leftover tenant-specific data (connector display")
    print("names, real GRS repository ids) before committing. The publishing")
    print("cassette must contain the SYNTHETIC stand-in zip, never real bytes.")


if __name__ == "__main__":
    main()
