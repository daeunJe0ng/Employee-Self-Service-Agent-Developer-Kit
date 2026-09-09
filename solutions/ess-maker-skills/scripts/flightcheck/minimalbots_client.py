# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Copilot Studio minimalBots PPAPI client.

Provides authenticated, read-oriented access to the per-environment
Power Platform API host used by Copilot Studio minimalBots APIs.
"""

from __future__ import annotations

import os
import sys
import uuid

try:
    import msal
except ImportError:
    print("ERROR: 'msal' package not found. Run: pip install msal")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package not found. Run: pip install requests")
    sys.exit(1)

try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("ERROR: 'urllib3' / 'requests' not found. Run: pip install requests")
    sys.exit(1)


CLIENT_ID = "417219b4-3a7d-42a2-bdb1-972bd8281a02"
DEFAULT_TENANT_ID = "935884d7-bdee-469b-a461-fcc530a3ac83"
DEFAULT_API_VERSION = "2024-10-01"
# ALM routes also accept 2022-03-01-preview. Do not use 2022-01-15 in TEST.
ALM_PREVIEW_API_VERSION = "2022-03-01-preview"

_RETRY = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "POST", "HEAD", "OPTIONS"]),
    respect_retry_after_header=True,
)
_SESSION = requests.Session()
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY))


def minimalbots_environment_host_id(environment_id: str, ring: str = "prod") -> str:
    """Return the minimalBots PPAPI environment host id for a BAP environment id.

    Copilot Studio's per-environment PPAPI host removes hyphens from the
    environment guid and inserts the host separator by ring: INT, TEST, and
    preprod use a 31+1 split, while prod uses a 30+2 split.
    """
    compact = str(environment_id or "").strip("{}").replace("-", "").lower()
    if len(compact) != 32:
        raise ValueError("environment_id must be a 32-character guid")

    split = 30 if ring.lower() == "prod" else 31
    return f"{compact[:split]}.{compact[split:]}"


def minimalbots_environment_base_url(environment_id: str, ring: str = "prod") -> str:
    """Return the per-environment PPAPI base URL for minimalBots requests."""
    host_id = minimalbots_environment_host_id(environment_id, ring=ring)
    normalized_ring = ring.lower()
    ring_segment = "" if normalized_ring == "prod" else f".{normalized_ring}"
    return f"https://{host_id}.environment.api{ring_segment}.powerplatform.com"


def _scope_resource_for_ring(ring: str) -> str:
    normalized_ring = ring.lower()
    if normalized_ring == "prod":
        return "https://api.powerplatform.com"
    return f"https://api.{normalized_ring}.powerplatform.com"


class MinimalBotsClient:
    """Client for Copilot Studio minimalBots PPAPI endpoints."""

    def __init__(
        self,
        tenant_id: str | None = None,
        environment_id: str | None = None,
        *,
        ring: str = "prod",
    ):
        self.tenant_id = tenant_id or DEFAULT_TENANT_ID
        self.environment_id = environment_id
        self.ring = ring
        self._token: str | None = None

    @property
    def base_url(self) -> str | None:
        if not self.environment_id:
            return None
        return minimalbots_environment_base_url(self.environment_id, ring=self.ring)

    @property
    def is_configured(self) -> bool:
        return bool(self._token and self.environment_id)

    @property
    def headers(self) -> dict:
        if not self._token:
            raise RuntimeError("Call authenticate() first")
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-ms-client-name": "EssAdk",
            "x-ms-client-session-id": str(uuid.uuid4()),
            "x-ms-retry-count": "0",
            "x-ms-last-retry": "false",
        }

    def authenticate(self) -> str:
        """Acquire a delegated minimalBots access token using the shared MSAL cache."""
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        cache = msal.SerializableTokenCache()
        cache_path = os.path.join(".local", ".token_cache.bin")

        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(
            CLIENT_ID, authority=authority, token_cache=cache
        )
        accounts = app.get_accounts()
        scopes = [
            f"{_scope_resource_for_ring(self.ring)}/CopilotStudio.MinimalBot.ReadWrite",
            f"{_scope_resource_for_ring(self.ring)}/CopilotStudio.MakerOperations.ReadWrite",
        ]

        result = None
        if accounts:
            result = app.acquire_token_silent(scopes, account=accounts[0])

        if not result or "access_token" not in result:
            print("Opening browser for Copilot Studio minimalBots sign-in...")
            result = app.acquire_token_interactive(scopes, prompt="select_account")

        if "access_token" not in result:
            error = result.get("error", "unknown_error")
            raise RuntimeError(f"minimalBots auth failed ({error}).")

        if cache.has_state_changed:
            os.makedirs(".local", exist_ok=True)
            try:
                os.chmod(".local", 0o700)
            except OSError:
                pass
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            fd = os.open(cache_path, flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(cache.serialize())

        self._token = result["access_token"]
        return self._token

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict:
        if not self.is_configured or not self.base_url:
            return {"_error": "not_configured"}
        resp = _SESSION.request(
            method,
            f"{self.base_url}{path}",
            headers=self.headers,
            params=params,
            json=json_body,
            timeout=60,
        )
        if resp.status_code in (401, 403):
            return {"_error": "insufficient_permissions", "_status": resp.status_code}
        resp.raise_for_status()
        return resp.json()

    def _get_all(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> list | dict:
        if not self.is_configured or not self.base_url:
            return {"_error": "not_configured"}

        items: list = []
        url = f"{self.base_url}{path}"
        while url:
            resp = _SESSION.request(
                method,
                url,
                headers=self.headers,
                params=params,
                json=json_body,
                timeout=60,
            )
            if resp.status_code in (401, 403):
                return {"_error": "insufficient_permissions", "_status": resp.status_code}
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("nextLink") or data.get("@odata.nextLink")
            params = None
        return items

    def get_components(
        self,
        cds_bot_id: str,
        *,
        api_version: str = DEFAULT_API_VERSION,
    ) -> dict:
        """Fetch minimal bot component changes for a bot.

        The internal OpenAPI contract exposes this read as POST with an empty
        body, even though callers consume it as a get-style read.
        """
        return self._request_json(
            "POST",
            f"/copilotstudio/minimalBots/api/{cds_bot_id}/components",
            params={"api-version": api_version},
            json_body={},
        )

    def get_connection_references(
        self,
        cds_bot_id: str,
        *,
        api_version: str = DEFAULT_API_VERSION,
    ) -> list:
        data = self.get_components(cds_bot_id, api_version=api_version)
        if not isinstance(data, dict) or "_error" in data:
            return []
        return data.get("connectionReferenceChanges") or []

    def get_configure(
        self,
        cds_bot_id: str,
        realm: str,
        *,
        api_version: str = DEFAULT_API_VERSION,
    ) -> dict:
        return self._request_json(
            "GET",
            f"/copilotstudio/minimalBots/alm/{cds_bot_id}/configure",
            params={"realm": realm, "api-version": api_version},
        )

    def export(
        self,
        cds_bot_id: str,
        *,
        api_version: str = DEFAULT_API_VERSION,
    ) -> bytes:
        if not self.is_configured or not self.base_url:
            return b""
        resp = _SESSION.post(
            f"{self.base_url}/copilotstudio/minimalBots/alm/{cds_bot_id}/export",
            headers=self.headers,
            params={"api-version": api_version},
            timeout=60,
        )
        if resp.status_code in (401, 403):
            return b""
        resp.raise_for_status()
        return resp.content

    def _multipart_headers(self) -> dict:
        """Auth headers for multipart uploads.

        Deliberately omits Content-Type so ``requests`` sets the correct
        ``multipart/form-data`` boundary itself; reusing the JSON header would
        corrupt the upload.
        """
        base = dict(self.headers)
        base.pop("Content-Type", None)
        return base

    def import_package(
        self,
        package: bytes,
        *,
        schema_name: str | None = None,
        api_version: str = DEFAULT_API_VERSION,
    ) -> dict:
        """Import an ALM package zip as a Dev agent (mutating).

        Omit ``schema_name`` to mint a brand-new agent; a schema collision is
        rejected with HTTP 409. Returns the ``AlmImportResult``
        (``cdsBotId`` + ``schemaName``) on success.
        """
        if not self.is_configured or not self.base_url:
            return {"_error": "not_configured"}
        files: dict = {"package": ("package.zip", package, "application/zip")}
        if schema_name:
            files["schemaName"] = (None, schema_name)
        resp = _SESSION.post(
            f"{self.base_url}/copilotstudio/minimalBots/alm/import",
            headers=self._multipart_headers(),
            params={"api-version": api_version},
            files=files,
            timeout=120,
        )
        if resp.status_code in (401, 403):
            return {"_error": "insufficient_permissions", "_status": resp.status_code}
        if resp.status_code == 409:
            return {"_error": "schema_collision", "_status": 409}
        resp.raise_for_status()
        return resp.json()

    def delete_bot(
        self,
        cds_bot_id: str,
        *,
        api_version: str = DEFAULT_API_VERSION,
    ) -> bool:
        """Delete a minimal bot by CDS bot id. Returns True on success (204).

        Used to clean up agents created by :meth:`import_package` so an import
        probe leaves no residue in the target environment.
        """
        if not self.is_configured or not self.base_url:
            return False
        resp = _SESSION.delete(
            f"{self.base_url}/copilotstudio/minimalBots/api/{cds_bot_id}",
            headers=self.headers,
            params={"api-version": api_version},
            timeout=60,
        )
        return resp.status_code in (200, 202, 204)
