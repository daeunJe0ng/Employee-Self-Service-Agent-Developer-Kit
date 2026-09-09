# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Publishing & QA Validation (PUB-xxx, QA-xxx)

Most checks are organizational/process gates that the kit cannot
verify by reading an API (test sets live in Copilot Studio behind the
Analytics surface; UAT sign-off lives in the operator's
change-management system; M365 admin approval lives in the Microsoft
365 admin center). PUB-001 and PUB-002 use the Copilot Studio
minimalBots ALM APIs when the required client and opt-in gate are
available.

Rows that the kit cannot verify still emit ``Status.MANUAL`` — meaning
"the operator must confirm this themselves" — and the remediation provides
the concrete steps plus best available deep link for that specific action.

Bucketing: MANUAL routes to the "Needs manual verification" section
of the FlightCheck report. PUB-001/PUB-002 can pass or fail readiness
when their API probes run.
"""

from ..runner import CheckResult, Role, Status

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"
STUDIO_BASE = "https://copilotstudio.microsoft.com"
M365_INTEGRATED_APPS_URL = (
    "https://admin.microsoft.com/Adminportal/Home#/Settings/IntegratedApps"
)
ZIP_MAGIC = b"PK\x03\x04"


def _studio_agent_url(runner) -> str | None:
    """Build a deep link to the first configured agent's Studio page.

    The publishing/QA checks are agent-scoped in spirit (the maker
    runs evaluations against a specific agent), but the result rows
    themselves are emitted once per checklist item — not per agent.
    We pick the first configured agent so the deep link lands on a
    real Studio surface rather than the generic homepage; if a tenant
    runs multi-agent the operator can switch from the agent picker.
    """
    env_id = getattr(runner, "env_id", None)
    if not env_id:
        return None
    config = getattr(runner, "config", None) or {}
    bot_id = None
    for agent in config.get("agents", []) or []:
        bot_id = agent.get("botId")
        if bot_id:
            break
    if not bot_id:
        bot_id = (config.get("agent") or {}).get("botId")
    if not bot_id:
        return None
    return f"{STUDIO_BASE}/environments/{env_id}/bots/{bot_id}/overview"


def _maker_solutions_url(runner) -> str | None:
    env_id = getattr(runner, "env_id", None)
    if not env_id:
        return None
    return f"https://make.powerapps.com/environments/{env_id}/solutions"


def _configured_bot_id(runner) -> str | None:
    config = getattr(runner, "config", None) or {}
    for agent in config.get("agents", []) or []:
        bot_id = agent.get("botId")
        if bot_id:
            return bot_id
    return (config.get("agent") or {}).get("botId")


def _api_result(
    *,
    checkpoint_id: str,
    row: dict,
    status: Status,
    result: str,
    remediation: str,
) -> CheckResult:
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category="Publishing",
        priority=row["p"],
        status=status.value,
        description=row["desc"],
        result=result,
        remediation=remediation,
        doc_link=row["doc_link"],
        roles=row["roles"],
    )


def _minimalbots_unavailable(checkpoint_id: str, row: dict) -> CheckResult:
    fallback = f" Manual fallback: {row['remediation']}" if row.get("remediation") else ""
    return _api_result(
        checkpoint_id=checkpoint_id,
        row=row,
        status=Status.SKIPPED,
        result="Copilot Studio minimalBots ALM client is unavailable for this run.",
        remediation=(
            "Re-run FlightCheck in a scope that authenticates the Copilot Studio "
            "minimalBots Power Platform API client, and make sure the environment "
            f"ID can be resolved.{fallback}"
        ),
    )


def _bot_id_missing(checkpoint_id: str, row: dict) -> CheckResult:
    return _api_result(
        checkpoint_id=checkpoint_id,
        row=row,
        status=Status.SKIPPED,
        result="No configured agent botId was found in .local/config.json.",
        remediation=(
            "Run /setup or update .local/config.json so the active ESS agent has "
            "a botId, then re-run FlightCheck."
        ),
    )


def _check_pub_001_export(runner, row: dict) -> CheckResult:
    client = getattr(runner, "minimalbots", None)
    if client is None:
        return _minimalbots_unavailable("PUB-001", row)

    bot_id = _configured_bot_id(runner)
    if not bot_id:
        return _bot_id_missing("PUB-001", row)

    try:
        package = client.export(bot_id)
    except Exception as e:  # noqa: BLE001 - surface client failure in report
        return _api_result(
            checkpoint_id="PUB-001",
            row=row,
            status=Status.ERROR,
            result=f"minimalBots ALM export failed for configured agent {bot_id}: {e}",
            remediation=(
                "Confirm the signed-in maker has CopilotStudio.MinimalBot.ReadWrite "
                "access for this environment, then re-run FlightCheck."
            ),
        )

    if not package:
        return _api_result(
            checkpoint_id="PUB-001",
            row=row,
            status=Status.FAILED,
            result=f"minimalBots ALM export returned an empty package for {bot_id}.",
            remediation=(
                "Open the agent in Copilot Studio and confirm it can be exported. "
                "If export still returns no bytes, fix the agent/package issue "
                "before promoting it."
            ),
        )

    if not package.startswith(ZIP_MAGIC):
        return _api_result(
            checkpoint_id="PUB-001",
            row=row,
            status=Status.FAILED,
            result=(
                f"minimalBots ALM export returned {len(package)} bytes for {bot_id}, "
                "but the payload is not a zip package."
            ),
            remediation=(
                "Re-run export from Copilot Studio or Power Apps. The promotion "
                "artifact must be a valid .zip package."
            ),
        )

    return _api_result(
        checkpoint_id="PUB-001",
        row=row,
        status=Status.PASSED,
        result=(
            f"minimalBots ALM export returned a valid zip package for {bot_id} "
            f"({len(package)} bytes)."
        ),
        remediation="No action required for PUB-001.",
    )


def _pub_002_requires_opt_in(row: dict) -> CheckResult:
    return _api_result(
        checkpoint_id="PUB-002",
        row=row,
        status=Status.SKIPPED,
        result=(
            "PUB-002 did not run because the ALM import probe was not explicitly "
            "enabled. FlightCheck stayed read-only and did not create anything."
        ),
        remediation=(
            "Re-run FlightCheck with --alm-import-probe to export the configured "
            "agent, import it as a transient Dev agent, and delete that transient "
            "agent in a finally block before the check reports. Manual fallback: "
            f"{row['remediation']}"
        ),
    )


def _check_pub_002_import_probe(runner, row: dict) -> CheckResult:
    if not bool(getattr(runner, "alm_import_probe", False)):
        return _pub_002_requires_opt_in(row)

    client = getattr(runner, "minimalbots", None)
    if client is None:
        return _minimalbots_unavailable("PUB-002", row)

    bot_id = _configured_bot_id(runner)
    if not bot_id:
        return _bot_id_missing("PUB-002", row)

    imported_bot_id: str | None = None
    cleanup_succeeded = False
    import_result: dict | None = None
    try:
        package = client.export(bot_id)
        if not package or not package.startswith(ZIP_MAGIC):
            return _api_result(
                checkpoint_id="PUB-002",
                row=row,
                status=Status.FAILED,
                result=(
                    "PUB-002 could not obtain a valid ALM export package to use "
                    "for the import probe."
                ),
                remediation=(
                    "Fix PUB-001 first. The import probe needs the target agent's "
                    "exported .zip package."
                ),
            )

        import_result = client.import_package(package)
        if not isinstance(import_result, dict):
            return _api_result(
                checkpoint_id="PUB-002",
                row=row,
                status=Status.FAILED,
                result="minimalBots ALM import returned a non-object response.",
                remediation="Retry the import after confirming minimalBots ALM API health.",
            )

        if import_result.get("_error") == "schema_collision":
            return _api_result(
                checkpoint_id="PUB-002",
                row=row,
                status=Status.FAILED,
                result=(
                    "minimalBots ALM import returned HTTP 409 schema_collision. "
                    "The package could not mint a new transient agent."
                ),
                remediation=(
                    "Retry without a schemaName override. If the collision persists, "
                    "capture the minimalBots ALM response and investigate the package "
                    "schema identity before promotion."
                ),
            )

        if import_result.get("_error"):
            return _api_result(
                checkpoint_id="PUB-002",
                row=row,
                status=Status.FAILED,
                result=(
                    "minimalBots ALM import failed with "
                    f"{import_result.get('_error')} (status {import_result.get('_status', 'unknown')})."
                ),
                remediation=(
                    "Confirm the maker has import permission and the minimalBots "
                    "ALM API is reachable for this environment."
                ),
            )

        imported_bot_id = str(import_result.get("cdsBotId") or "").strip()
        schema_name = str(import_result.get("schemaName") or "").strip()
        if not imported_bot_id or not schema_name:
            return _api_result(
                checkpoint_id="PUB-002",
                row=row,
                status=Status.FAILED,
                result=(
                    "minimalBots ALM import did not return both cdsBotId and "
                    "schemaName for the transient agent."
                ),
                remediation=(
                    "Treat this as a failed import. The API must return the "
                    "transient agent ID so FlightCheck can verify cleanup."
                ),
            )
    except Exception as e:  # noqa: BLE001 - cleanup still runs in finally
        return _api_result(
            checkpoint_id="PUB-002",
            row=row,
            status=Status.ERROR,
            result=f"minimalBots ALM import probe failed: {e}",
            remediation=(
                "Review the minimalBots ALM API error, then re-run with "
                "--alm-import-probe after the underlying issue is fixed."
            ),
        )
    finally:
        if imported_bot_id:
            try:
                cleanup_succeeded = bool(client.delete_bot(imported_bot_id))
            except Exception:  # noqa: BLE001 - reported below through success flag
                cleanup_succeeded = False

    if not cleanup_succeeded:
        return _api_result(
            checkpoint_id="PUB-002",
            row=row,
            status=Status.FAILED,
            result=(
                f"minimalBots ALM import created transient agent {imported_bot_id}, "
                "but cleanup did not confirm deletion."
            ),
            remediation=(
                "Delete the transient agent manually from Copilot Studio or the "
                "minimalBots API before re-running the probe."
            ),
        )

    return _api_result(
        checkpoint_id="PUB-002",
        row=row,
        status=Status.PASSED,
        result=(
            f"minimalBots ALM import created transient agent {imported_bot_id} "
            f"with schema {import_result.get('schemaName')}, and cleanup deleted it."
        ),
        remediation="No action required for PUB-002.",
    )


def _qa_remediation(runner, action: str, doc_anchor: str) -> str:
    """Build a QA-* remediation that points at Copilot Studio Analytics
    when the deep link is available, falling back to documentation."""
    studio = _studio_agent_url(runner)
    if studio:
        return (
            f"{action} Open the agent in [Copilot Studio]({studio}) → "
            f"**Analytics → Evaluations**. "
            f"See [{doc_anchor}]({DOC_BASE}/evaluations) for guidance on "
            f"building test sets and interpreting results."
        )
    return (
        f"{action} In Copilot Studio open your agent → **Analytics → "
        f"Evaluations**. See [{doc_anchor}]({DOC_BASE}/evaluations) for "
        f"guidance on building test sets and interpreting results."
    )


def _build_checks(runner) -> list[dict]:
    """Per-check authored content. Constructed at call-time so deep
    links can incorporate the runner's environment / agent IDs."""
    studio = _studio_agent_url(runner)
    solutions = _maker_solutions_url(runner)
    publish_doc = f"{DOC_BASE}/publish"
    deploy_doc = f"{DOC_BASE}/deploy-overview-alm"
    evaluations_doc = f"{DOC_BASE}/evaluations"

    # Studio link as a markdown fragment ready to splice into prose,
    # or the literal phrase "Copilot Studio" when no deep link exists.
    studio_md = f"[Copilot Studio]({studio})" if studio else "Copilot Studio"
    solutions_md = (
        f"[Power Apps → Solutions]({solutions})"
        if solutions else "Power Apps → Solutions"
    )

    return [
        {
            "id": "QA-001",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value],
            "desc": "Build a library of ≥50 evaluation prompts (golden queries)",
            "result": (
                "The kit can't inspect Copilot Studio evaluation test sets — "
                "confirm a library of ≥50 representative prompts exists for this agent."
            ),
            "remediation": _qa_remediation(
                runner,
                action=(
                    "Create at least one test set covering your top intents (PTO, "
                    "payroll, benefits, IT password reset, common policy lookups, "
                    "etc.) with ≥50 prompts in total."
                ),
                doc_anchor="ESS evaluations guide",
            ),
            "doc_link": evaluations_doc,
        },
        {
            "id": "QA-002",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value],
            "desc": "Run the evaluation test set against the agent",
            "result": (
                "The kit can't read evaluation runs — "
                "confirm the golden-prompt test set was executed against this agent at least once."
            ),
            "remediation": _qa_remediation(
                runner,
                action=(
                    "Select your test set, click **Run evaluation**, wait for "
                    "the run to finish, and verify every prompt produced a "
                    "response (no agent errors / timeouts)."
                ),
                doc_anchor="ESS evaluations guide",
            ),
            "doc_link": evaluations_doc,
        },
        {
            "id": "QA-012",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value],
            "desc": "Review evaluation scores against an accuracy target",
            "result": (
                "The kit can't measure response accuracy — "
                "confirm evaluation scores were reviewed against a target agreed with stakeholders."
            ),
            "remediation": _qa_remediation(
                runner,
                action=(
                    "Open the latest run, review per-prompt scores (groundedness, "
                    "relevance, completeness), record the accept rate, and confirm "
                    "it meets the target you agreed with business stakeholders "
                    "before promoting the agent."
                ),
                doc_anchor="ESS evaluations guide",
            ),
            "doc_link": evaluations_doc,
        },
        {
            "id": "PUB-001",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value],
            "desc": "Export your customization solution as a managed solution",
            "result": (
                "The kit can't inspect maker-portal solution exports — "
                "confirm a managed (.zip) export exists for promotion to test/UAT/prod."
            ),
            "remediation": (
                f"In {solutions_md} → select the solution that contains your "
                f"agent customizations → ⋯ → **Export solution** → **Publish** "
                f"(publish all customizations first) → **Next** → choose "
                f"**Managed** → **Export** → **Download**. Keep the .zip — "
                f"it's the artifact you import into test/UAT/prod. See the "
                f"[publish guide]({publish_doc}) for the full deployment flow."
            ),
            "doc_link": publish_doc,
        },
        {
            "id": "PUB-002",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
            "desc": "Import the managed solution into a test environment",
            "result": (
                "The kit only sees the configured environment — "
                "confirm the managed solution was imported into a non-production environment and smoke-tested."
            ),
            "remediation": (
                "Switch to your test environment in the Power Apps maker → "
                "**Solutions** → **Import solution** → upload the managed .zip "
                "from PUB-001 → install any prompted dependencies (the ESS "
                "agent itself plus any connector solutions) → open the agent "
                f"and smoke-test a handful of representative prompts. See the "
                f"[publish guide]({publish_doc}) for the full deployment flow."
            ),
            "doc_link": publish_doc,
        },
        {
            "id": "PUB-003",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value],
            "desc": "Complete UAT and capture business sign-off",
            "result": (
                "The kit can't track sign-off — "
                "confirm business stakeholders ran user-acceptance testing and recorded a pass decision."
            ),
            "remediation": (
                "Run a pilot with the business stakeholders who own the use "
                "cases the agent answers. Capture pass/fail decisions on the "
                "representative prompts you tested and record sign-off in "
                "your change-management system (release ticket, ADO work "
                "item, ServiceNow change, etc.) before promoting to "
                "production. This is an organizational gate — no portal link applies."
            ),
            "doc_link": deploy_doc,
        },
        {
            "id": "PUB-006",
            "p": "Critical",
            "roles": [Role.ESS_MAKER.value, Role.M365_ADMIN.value],
            "desc": "Obtain Microsoft 365 admin approval for the agent",
            "result": (
                "The kit can't read the Microsoft 365 admin center — "
                "confirm a tenant admin approved the publish request in Integrated apps."
            ),
            "remediation": (
                f"In {studio_md} → **Channels** → **Microsoft Teams** → "
                f"**Submit for admin approval** (the maker does this). Then a "
                f"tenant admin opens the "
                f"[Microsoft 365 admin center → Settings → Integrated apps]"
                f"({M365_INTEGRATED_APPS_URL}) → **Review request** for the "
                f"agent → approves and deploys to the chosen user audience. "
                f"Until both steps complete the agent won't appear in users' "
                f"Microsoft 365 Copilot."
            ),
            "doc_link": publish_doc,
        },
        {
            "id": "PUB-011",
            "p": "Medium",
            "roles": [Role.M365_ADMIN.value],
            "desc": "Allow up to 48 hours for rollout to Microsoft 365 Copilot",
            "result": (
                "Informational — after admin approval, Teams/Microsoft 365 Copilot "
                "rollout to end users can take up to 48 hours."
            ),
            "remediation": (
                f"No action required at publish time. If the agent still isn't "
                f"visible to users in Microsoft 365 Copilot 48 hours after admin "
                f"approval, return to the "
                f"[Microsoft 365 admin center → Integrated apps]"
                f"({M365_INTEGRATED_APPS_URL}) and check the deployment status "
                f"for this agent."
            ),
            "doc_link": publish_doc,
        },
    ]


def run_publishing_checks(runner) -> list[CheckResult]:
    """Return publishing/QA checks, using minimalBots ALM where available.

    PUB-001 validates export without mutating the environment. PUB-002 is
    intentionally gated by explicit opt-in because it creates a transient Dev
    agent, then deletes it in a finally block.
    """
    results: list[CheckResult] = []
    for c in _build_checks(runner):
        if c["id"] == "PUB-001":
            results.append(_check_pub_001_export(runner, c))
            continue
        if c["id"] == "PUB-002":
            results.append(_check_pub_002_import_probe(runner, c))
            continue
        results.append(CheckResult(
            checkpoint_id=c["id"],
            category="Publishing",
            priority=c["p"],
            status=Status.MANUAL.value,
            description=c["desc"],
            result=c["result"],
            remediation=c["remediation"],
            doc_link=c["doc_link"],
            roles=c["roles"],
        ))
    return results
