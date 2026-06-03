#!/usr/bin/env python3
"""Class 1 - direct cross-user object fetch against Open WebUI's file API.

This is the Open WebUI-native analogue of Sectum's `tenant-boundary-fetch`
probe (docs/attack-catalog/class-01-tenant-boundary.md). Sectum's vector
adapter cannot exercise Open WebUI's authorization boundary (it reads its own
per-tenant collections), so this script issues the BOLA-style direct object
lookup against the surface that DOES enforce Open WebUI's object authz: the file
API.

Method (mirrors the Class 1 probe's plan/detect):
  - From every tenant's session, attempt to GET another tenant's uploaded file
    by id: ``GET /api/v1/files/{id}/content`` with the observer tenant's JWT.
  - Detection is manifest-grounded and zero-FP: a returned body containing a
    FOREIGN tenant's HARD_CANARY plaintext (from the substrate manifest) is a
    confirmed cross-tenant leak; a 403/404 (denied) is the correct deny.

Exit codes mirror the CLI (docs/quickstart.md): 0 = no confirmed leak;
2 = confirmed cross-user leak; 3 = setup error.

The file ids come from the per-tenant upload records in tenant-map.json
(provision_owui.py records each tenant's uploaded doc ids, and we resolve them
to Open WebUI file ids by re-listing the tenant's files). Stdlib only.

This drives OUR OWN Open WebUI deployment - lawful self-host testing.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _get(base_url: str, path: str, token: str) -> tuple[int, bytes]:
    req = urllib.request.Request(
        f"{base_url}{path}",
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()
    except urllib.error.URLError as err:
        raise RuntimeError(f"GET {path} failed: {err}") from err


def _hard_canaries_by_tenant(substrate: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for marker in substrate["manifest"]["markers"]:
        if marker["marker_type"] == "HARD_CANARY":
            out.setdefault(marker["owner_tenant_id"], []).append(marker["plaintext"])
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: class1_boundary_fetch.py <substrate.json> <out/tenant-map.json>",
            file=sys.stderr,
        )
        return 3
    substrate = json.loads(Path(sys.argv[1]).read_text())
    tenant_map = json.loads(Path(sys.argv[2]).read_text())
    base_url = tenant_map["base_url"].rstrip("/")
    tenants = tenant_map["tenants"]
    canaries = _hard_canaries_by_tenant(substrate)

    # Target each tenant's PRIVATE-KB file copies (recorded by provision_owui.py).
    # These are the genuine private-object boundary: on a patched Open WebUI a
    # foreign user must NOT fetch them. We deliberately do NOT target the public
    # shared-KB copies here - those are readable cross-user BY DESIGN (the shared
    # collection is public-read) and would otherwise conflate the shared-
    # collection config with a private-object IDOR.
    owned_file_ids: dict[str, list[str]] = {
        tid: list(t.get("private_file_ids", [])) for tid, t in tenants.items()
    }
    for tid, t in tenants.items():
        print(f"[{t['display_name']}] {len(owned_file_ids[tid])} private-KB marker files")

    confirmed = 0
    attempts = 0
    denied = 0
    for owner_tid, owner in tenants.items():
        owner_canaries = canaries.get(owner_tid, [])
        for file_id in owned_file_ids.get(owner_tid, []):
            for observer_tid, observer in tenants.items():
                if observer_tid == owner_tid:
                    continue
                attempts += 1
                status, body = _get(
                    base_url, f"/api/v1/files/{file_id}/content", observer["token"]
                )
                text = body.decode("utf-8", "replace") if status == 200 else ""
                leaked = status == 200 and any(c in text for c in owner_canaries)
                if leaked:
                    confirmed += 1
                    print(
                        f"  [CONFIRMED LEAK] {observer['display_name']} fetched "
                        f"{owner['display_name']}'s file {file_id} "
                        f"(HARD_CANARY surfaced)"
                    )
                elif status in (401, 403, 404):
                    denied += 1
                # A 200 without a foreign canary is ambiguous (e.g. empty) - not
                # counted as a confirmed leak (zero-FP), not counted as a deny.

    print(
        f"\nClass 1 (cross-user file fetch): {attempts} cross-tenant fetch attempts, "
        f"{denied} correctly denied, {confirmed} CONFIRMED cross-tenant leaks"
    )
    summary = {
        "probe": "tenant-boundary-fetch (open-webui file API)",
        "surface": "api/file",
        "attempts": attempts,
        "denied": denied,
        "confirmed_findings": confirmed,
    }
    out_path = Path(os.environ.get("SECTUM_OWUI_MAP", "out/tenant-map.json")).parent
    (out_path / "class1-boundary.json").write_text(json.dumps(summary, indent=2))
    print(f"summary -> {out_path / 'class1-boundary.json'}")
    return 2 if confirmed else 0


if __name__ == "__main__":
    raise SystemExit(main())
