#!/usr/bin/env python3
"""Provision a self-hosted Open WebUI from Sectum's seeded marker substrate.

This is the integration flow's "upload" stage. Sectum's substrate (`sectum-ai
seed`) is the ground truth: it produces synthetic-tenant corpora whose pivot
documents carry HARD_CANARY markers and name shared organic entities. This
script uploads each synthetic tenant's marker-bearing documents into the
matching Open WebUI user's Knowledge via the Open WebUI REST API, preserving the
planted markers verbatim, so Sectum can later probe the real chat-with-knowledge
surface and detect leaks against the same manifest.

It is OUR OWN deployment (lawful self-host testing); the corpora are synthetic
(no real PII/secrets).

Outputs `tenant-map.json`: the bridge the RAG shim reads to map a Sectum tenant
UUID to its Open WebUI user (JWT) and knowledge collection id, plus the id of
the SHARED collection that holds every tenant's docs (the shared-collection leak
config).

Open WebUI API surface used (v0.9.x):
  POST /api/v1/auths/signup            {name,email,password}  -> {token,...}
  POST /api/v1/auths/signin            {email,password}       -> {token,...}
  POST /api/v1/auths/add               {name,email,password,role}  -> {...}  (admin)
  POST /api/v1/files/                  multipart file         -> {id,...}
  GET  /api/v1/files/{id}/process/status                      -> {status,...}
  POST /api/v1/knowledge/create        {name,description}     -> {id,...}
  POST /api/v1/knowledge/{id}/file/add {file_id}              -> {...}

Only the Python standard library is used (urllib), matching Sectum's
stdlib-only adapters - no extra dependency to run the harness.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# Map the four default-scenario tenant display names to lab user emails. Order is
# stable, so the same tenant always maps to the same Open WebUI user.
TENANT_EMAILS = {
    "Acme Robotics": "acme@sectum.test",
    "Globex Logistics": "globex@sectum.test",
    "Initech Financial": "initech@sectum.test",
    "Hooli Health": "hooli@sectum.test",
}

SHARED_KB_NAME = "sectum-shared-corpus"
PROCESS_POLL_TIMEOUT_S = 120
PROCESS_POLL_INTERVAL_S = 2


@dataclass
class OwuiClient:
    """A thin Open WebUI REST client over urllib (stdlib only)."""

    base_url: str
    token: str | None = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        data: bytes | None = None,
        content_type: str | None = None,
        timeout: float = 60.0,
    ) -> dict:
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body: bytes | None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            body = data
            if content_type:
                headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")
            raise RuntimeError(f"{method} {path} -> HTTP {err.code}: {detail}") from err
        except urllib.error.URLError as err:
            raise RuntimeError(f"{method} {path} failed: {err}") from err
        if not raw:
            return {}
        return json.loads(raw)

    # --- auth ---------------------------------------------------------------
    def signup(self, name: str, email: str, password: str) -> str:
        body = self._request(
            "POST",
            "/api/v1/auths/signup",
            json_body={"name": name, "email": email, "password": password},
        )
        return body["token"]

    def signin(self, email: str, password: str) -> str:
        body = self._request(
            "POST",
            "/api/v1/auths/signin",
            json_body={"email": email, "password": password},
        )
        return body["token"]

    def ensure_admin(self, name: str, email: str, password: str) -> str:
        """Sign in if the admin exists, else sign up (first user => admin).

        Open WebUI makes the first registered user the admin and then
        auto-disables open signup, so this MUST be called before any tenant user
        is created.
        """
        try:
            return self.signin(email, password)
        except RuntimeError:
            return self.signup(name, email, password)

    def add_user(self, name: str, email: str, password: str, role: str = "user") -> None:
        """Create a user via the admin-only endpoint (bypasses ENABLE_SIGNUP).

        Open WebUI disables open signup after the first user, so additional
        tenant users are created by the admin here rather than self-signup.
        Idempotent: a duplicate email (user already exists) is tolerated.
        """
        try:
            self._request(
                "POST",
                "/api/v1/auths/add",
                json_body={
                    "name": name,
                    "email": email,
                    "password": password,
                    "role": role,
                },
            )
        except RuntimeError as err:
            # Re-running provisioning: the user already exists -> not an error.
            if "already" in str(err).lower() or "taken" in str(err).lower():
                return
            raise

    # --- files + knowledge --------------------------------------------------
    def upload_file(self, filename: str, content: bytes) -> str:
        boundary = f"----sectum{uuid.uuid4().hex}"
        mime = mimetypes.guess_type(filename)[0] or "text/plain"
        parts = [
            f"--{boundary}".encode(),
            (f'Content-Disposition: form-data; name="file"; filename="{filename}"').encode(),
            f"Content-Type: {mime}".encode(),
            b"",
            content,
            f"--{boundary}--".encode(),
            b"",
        ]
        payload = b"\r\n".join(parts)
        body = self._request(
            "POST",
            "/api/v1/files/",
            data=payload,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        return body["id"]

    def wait_file_processed(self, file_id: str) -> None:
        """Poll until the file's content extraction + embedding completes.

        Open WebUI processes uploads asynchronously; adding a still-processing
        file to a knowledge base 400s (empty content). We poll the status
        endpoint and tolerate older builds that lack it (best-effort sleep).
        """
        deadline = time.time() + PROCESS_POLL_TIMEOUT_S
        while time.time() < deadline:
            try:
                status = self._request("GET", f"/api/v1/files/{file_id}/process/status")
            except RuntimeError:
                # Endpoint absent on this build: fall back to a short settle.
                time.sleep(PROCESS_POLL_INTERVAL_S)
                return
            state = str(status.get("status", "")).lower()
            if state in ("completed", "success", "done"):
                return
            if state in ("failed", "error"):
                raise RuntimeError(f"file {file_id} processing failed: {status}")
            time.sleep(PROCESS_POLL_INTERVAL_S)
        raise RuntimeError(f"file {file_id} not processed within {PROCESS_POLL_TIMEOUT_S}s")

    def list_users(self) -> list[dict]:
        """List all users (admin only). Used to resolve a tenant user's id."""
        body = self._request("GET", "/api/v1/users/")
        return body if isinstance(body, list) else body.get("users", [])

    def create_knowledge(self, name: str, description: str) -> str:
        body = self._request(
            "POST",
            "/api/v1/knowledge/create",
            json_body={"name": name, "description": description},
        )
        return body["id"]

    def set_knowledge_access(
        self, knowledge_id: str, name: str, description: str, access_grants: list[dict]
    ) -> None:
        """Set a knowledge base's access grants (admin/owner only).

        v0.9.x uses ``access_grants``: a list of
        ``{principal_type, principal_id, permission}``. Public-read is the
        wildcard principal ``{"principal_type":"user","principal_id":"*",
        "permission":"read"}``; a per-user grant uses that user's id. Verified
        empirically against the live instance during harness development.
        """
        self._request(
            "POST",
            f"/api/v1/knowledge/{knowledge_id}/update",
            json_body={
                "name": name,
                "description": description,
                "access_grants": access_grants,
            },
        )

    def add_file_to_knowledge(self, knowledge_id: str, file_id: str) -> None:
        self._request(
            "POST",
            f"/api/v1/knowledge/{knowledge_id}/file/add",
            json_body={"file_id": file_id},
        )


@dataclass
class TenantEntry:
    tenant_id: str
    display_name: str
    email: str
    token: str
    knowledge_id: str
    uploaded_doc_ids: list[str] = field(default_factory=list)
    # Open WebUI file ids of this tenant's PRIVATE-KB copies (not the shared-KB
    # copies). Class 1 tests cross-user fetch of exactly these, so a public
    # shared-KB copy of the same doc never muddies the private-boundary result.
    private_file_ids: list[str] = field(default_factory=list)


def _marker_doc_ids(substrate: dict) -> set[str]:
    """The set of doc ids that carry a planted marker (the pivot documents).

    Uploading every filler doc (500/tenant) is slow and unnecessary: only the
    marker-bearing pivot documents are the leak bait Sectum detects. We upload
    exactly those - across ALL marker types: HARD_CANARY (exact),
    SECRET_CANARY (credential-format), and ENTITY_CANARY (semantic). Filtering to
    HARD_CANARY only - as an earlier version did - silently dropped the entity and
    secret pivots, so the flagship's organic entity-bleed and secret-surfacing
    paths were never exercised and the run measured only exact-substring matches.
    """
    ids: set[str] = set()
    for marker in substrate["manifest"]["markers"]:
        for loc in marker["planted_locations"]:
            ids.add(loc["doc_id"])
    return ids


def _doc_to_bytes(doc: dict) -> tuple[str, bytes]:
    """Render a corpus document to an uploadable text file, markers intact.

    Title, body, and the marker_ref metadata are all included verbatim so the
    planted marker survives chunking and can be retrieved by any field - mirroring
    how the substrate plants the marker in body+title+metadata.
    """
    meta_lines = "\n".join(f"{k}: {v}" for k, v in doc.get("metadata", {}).items())
    text = f"Title: {doc['title']}\n{meta_lines}\n\n{doc['content']}\n"
    return f"{doc['doc_id']}.txt", text.encode("utf-8")


def provision(substrate_path: Path, base_url: str, out_path: Path) -> None:
    substrate = json.loads(substrate_path.read_text())
    admin_email = os.environ["OWUI_ADMIN_EMAIL"]
    admin_password = os.environ["OWUI_ADMIN_PASSWORD"]
    tenant_password = os.environ["OWUI_TENANT_PASSWORD"]

    # 1. Admin first (Open WebUI makes the first registered user admin).
    #
    # The admin owns and creates EVERY knowledge base. Open WebUI's default RBAC
    # does NOT let a regular user create a knowledge base (POST
    # /api/v1/knowledge/create requires admin or the workspace.knowledge
    # permission), and it enforces retrieval access control by default
    # (BYPASS_RETRIEVAL_ACCESS_CONTROL=false: a user can only retrieve from a
    # collection it can read). So we model the real sharing surface with access
    # grants:
    #   - each tenant's PRIVATE KB is granted read to exactly that tenant user;
    #   - the SHARED KB is granted public read (wildcard principal), so every
    #     tenant user can attach it - the shared-collection misconfiguration the
    #     Class 2 flagship is built to catch.
    # Tenant users still QUERY as themselves (their own JWT), so the isolation
    # test is real: isolated mode attaches their own KB (readable); shared mode
    # attaches the public KB holding all tenants' docs (cross-tenant leak).
    admin = OwuiClient(base_url)
    admin.token = admin.ensure_admin("Sectum Admin", admin_email, admin_password)
    print(f"[admin] {admin_email} ready")

    marker_ids = _marker_doc_ids(substrate)
    docs_by_tenant: dict[str, list[dict]] = {}
    for doc in substrate["documents"]:
        if doc["doc_id"] in marker_ids:
            docs_by_tenant.setdefault(doc["tenant_id"], []).append(doc)

    # Create the tenant users first so we can resolve their ids for grants.
    for tenant in substrate["tenants"]:
        name = tenant["display_name"]
        email = TENANT_EMAILS.get(name)
        if email is None:
            raise RuntimeError(f"no lab email mapped for tenant {name!r}")
        admin.add_user(name, email, tenant_password, role="user")
    users_by_email = {u["email"]: u for u in admin.list_users()}

    # The shared knowledge base (admin-owned), public-read.
    shared_kb = admin.create_knowledge(
        SHARED_KB_NAME, "Sectum cross-tenant shared corpus (leak config)"
    )
    admin.set_knowledge_access(
        shared_kb,
        SHARED_KB_NAME,
        "Sectum cross-tenant shared corpus (leak config)",
        [{"principal_type": "user", "principal_id": "*", "permission": "read"}],
    )
    print(f"[shared] public knowledge base {SHARED_KB_NAME} -> {shared_kb}")

    entries: list[TenantEntry] = []
    for tenant in substrate["tenants"]:
        name = tenant["display_name"]
        tid = tenant["tenant_id"]
        email = TENANT_EMAILS[name]
        user_rec = users_by_email.get(email)
        if user_rec is None:
            raise RuntimeError(f"user {email} not found after creation")
        user_id = user_rec["id"]

        # Sign in AS the tenant user to capture its JWT for the shim.
        user = OwuiClient(base_url)
        user.token = user.signin(email, tenant_password)

        # Admin creates the tenant's PRIVATE KB and grants read to that user.
        kb_desc = f"Private knowledge for {name}"
        kb_id = admin.create_knowledge(f"sectum-{name}", kb_desc)
        admin.set_knowledge_access(
            kb_id,
            f"sectum-{name}",
            kb_desc,
            [{"principal_type": "user", "principal_id": user_id, "permission": "read"}],
        )
        print(f"[{name}] user {email} ({user_id}) ready; private KB -> {kb_id}")

        uploaded: list[str] = []
        private_file_ids: list[str] = []
        for doc in docs_by_tenant.get(tid, []):
            filename, content = _doc_to_bytes(doc)
            # Admin uploads (admin owns the KBs). Two SEPARATE copies of each doc:
            # one in the tenant's PRIVATE KB (the Class 1 boundary target) and one
            # in the public SHARED KB (the Class 2 leak surface). Keeping them
            # separate means the private-file boundary is tested cleanly, distinct
            # from the by-design public reachability of the shared collection.
            file_id = admin.upload_file(filename, content)
            admin.wait_file_processed(file_id)
            admin.add_file_to_knowledge(kb_id, file_id)
            private_file_ids.append(file_id)
            shared_file_id = admin.upload_file(filename, content)
            admin.wait_file_processed(shared_file_id)
            admin.add_file_to_knowledge(shared_kb, shared_file_id)
            uploaded.append(doc["doc_id"])
        print(f"[{name}] uploaded {len(uploaded)} marker docs to private + shared KBs")

        entries.append(
            TenantEntry(
                tenant_id=tid,
                display_name=name,
                email=email,
                token=user.token,
                knowledge_id=kb_id,
                uploaded_doc_ids=uploaded,
                private_file_ids=private_file_ids,
            )
        )

    tenant_map = {
        "base_url": base_url,
        "shared_knowledge_id": shared_kb,
        "admin_token": admin.token,
        "tenants": {
            e.tenant_id: {
                "display_name": e.display_name,
                "email": e.email,
                "token": e.token,
                "knowledge_id": e.knowledge_id,
                "uploaded_doc_ids": e.uploaded_doc_ids,
                "private_file_ids": e.private_file_ids,
            }
            for e in entries
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(tenant_map, indent=2))
    print(f"\nwrote tenant map -> {out_path}")
    print("  (holds JWTs - treat as a lab secret; it is under out/ which is gitignored)")


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: provision_owui.py <substrate.json> <base_url> <out/tenant-map.json>",
            file=sys.stderr,
        )
        return 2
    substrate_path = Path(sys.argv[1])
    base_url = sys.argv[2].rstrip("/")
    out_path = Path(sys.argv[3])
    if not substrate_path.exists():
        print(f"no substrate at {substrate_path}; run 'sectum-ai seed' first", file=sys.stderr)
        return 2
    provision(substrate_path, base_url, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
