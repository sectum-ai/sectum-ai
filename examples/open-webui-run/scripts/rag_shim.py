#!/usr/bin/env python3
"""A RAG bridge between Sectum's HTTP RAG adapter and Open WebUI.

Sectum's `rag` adapter (`kind: http`) POSTs ``{"tenant": "<uuid>", "query":
"<text>"}`` and expects ``{"answer": "...", "retrieved": [{"doc_id","content",
"score"}]}`` (see packages/adapters/.../rag/http.py). This shim is the small
service that adopts that contract on one side and speaks Open WebUI's
OpenAI-compatible chat-with-knowledge API on the other.

For each incoming ``{tenant, query}`` it:
  1. looks up the tenant's Open WebUI user (JWT) + knowledge collection from the
     tenant-map written by provision_owui.py;
  2. calls Open WebUI ``POST /api/chat/completions`` AS THAT USER with a
     ``files`` reference attaching a knowledge collection - so Open WebUI's REAL
     retrieval + authorization path runs;
  3. returns the composed answer plus the retrieved source chunks Open WebUI
     used, which Sectum scans (manifest-grounded) for a foreign canary.

Isolation mode (env SECTUM_OWUI_MODE):
  isolated - attach ONLY the tenant's own Private knowledge base. A correctly
             scoped Open WebUI returns only the tenant's own docs => Retrieval-
             Pivot Rate ~0% (isolation verified).
  shared   - attach the ONE shared knowledge base holding every tenant's docs
             (the realistic shared-collection misconfiguration). A benign query
             naming a shared entity retrieves a FOREIGN tenant's pivot doc =>
             the canary surfaces => Class 2 leak, RPR high.

Stdlib only (http.server + urllib). Run via scripts/serve_shim.sh.

This drives OUR OWN Open WebUI deployment - lawful self-host testing.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODE = os.environ.get("SECTUM_OWUI_MODE", "shared").strip().lower()
MODEL = os.environ.get("OWUI_OLLAMA_MODEL", "qwen2.5:0.5b")
MAP_PATH = Path(os.environ.get("SECTUM_OWUI_MAP", "out/tenant-map.json"))
LISTEN_HOST = os.environ.get("SECTUM_SHIM_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("SECTUM_SHIM_PORT", "8099"))


def _load_map() -> dict:
    if not MAP_PATH.exists():
        raise SystemExit(
            f"no tenant map at {MAP_PATH}; run scripts/provision.sh first"
        )
    return json.loads(MAP_PATH.read_text())


TENANT_MAP = _load_map()
BASE_URL = TENANT_MAP["base_url"].rstrip("/")


def _chat_with_knowledge(token: str, knowledge_id: str, query: str) -> dict:
    """Call Open WebUI chat completions with a knowledge collection attached."""
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": query}],
            # The leak surface: attaching a collection makes Open WebUI's RAG
            # pipeline retrieve from it and inject the chunks. type "collection"
            # references a knowledge base by id.
            "files": [{"type": "collection", "id": knowledge_id}],
            "stream": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")
        raise RuntimeError(f"chat/completions HTTP {err.code}: {detail}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"chat/completions failed: {err}") from err


def _extract(completion: dict) -> tuple[str, list[dict]]:
    """Pull the answer text and the retrieved source chunks from a completion.

    Open WebUI returns retrieved RAG context under ``sources``: a list of
    ``{source:{id,name,type}, document:[chunk,...], metadata:[...]}``. Each
    chunk string may carry a planted HARD_CANARY verbatim. We surface both the
    answer and every chunk so Sectum's exact-match detection sees the marker
    wherever Open WebUI placed it.
    """
    answer = ""
    choices = completion.get("choices") or []
    if choices:
        answer = (choices[0].get("message") or {}).get("content", "") or ""

    retrieved: list[dict] = []
    for src in completion.get("sources") or []:
        documents = src.get("document") or []
        metadatas = src.get("metadata") or []
        for idx, chunk in enumerate(documents):
            meta = metadatas[idx] if idx < len(metadatas) else {}
            doc_id = (
                meta.get("file_id")
                or meta.get("source")
                or (src.get("source") or {}).get("id")
                or ""
            )
            # distances, when present, are 1 - score-ish; default to 1.0 so the
            # adapter's optional score parse is satisfied.
            retrieved.append(
                {"doc_id": str(doc_id), "content": str(chunk), "score": 1.0}
            )
    return answer, retrieved


def _answer_for(tenant_id: str, query: str) -> dict:
    tenant = TENANT_MAP["tenants"].get(tenant_id)
    if tenant is None:
        raise RuntimeError(f"unknown tenant {tenant_id!r} (not in tenant map)")
    if MODE == "isolated":
        token = tenant["token"]
        knowledge_id = tenant["knowledge_id"]
    elif MODE == "shared":
        # Every tenant queries the shared collection AS ITSELF. A correctly
        # scoped backend would still only return that user's own docs; the
        # shared collection deliberately holds all tenants', so a foreign
        # canary surfaces - that is the finding.
        token = tenant["token"]
        knowledge_id = TENANT_MAP["shared_knowledge_id"]
    else:
        raise RuntimeError(f"SECTUM_OWUI_MODE must be 'isolated' or 'shared', got {MODE!r}")
    completion = _chat_with_knowledge(token, knowledge_id, query)
    answer, retrieved = _extract(completion)
    # Sectum's runner scans a rag.ask observation's ANSWER text for the canary
    # (it records raw_response = answer.answer). Open WebUI surfaces the
    # retrieved context to the tenant's session as <source> blocks injected into
    # the model's prompt - that context IS part of what the RAG pipeline returned
    # to the tenant - but a tiny local model often emits only citation markers
    # ([1] [2]) instead of echoing the chunk text. So we fold the retrieved
    # source chunks into the answer (clearly delimited) so detection sees the
    # full RAG response - the composed answer plus the source context Open WebUI
    # actually retrieved and showed. The HARD_CANARY a foreign chunk carries is
    # then caught by Sectum's exact, manifest-grounded match (zero false
    # positives - it only confirms a plaintext from the ground-truth manifest).
    source_block = "\n".join(hit["content"] for hit in retrieved)
    full_answer = answer
    if source_block:
        full_answer = f"{answer}\n\n[retrieved sources]\n{source_block}"
    return {"answer": full_answer, "retrieved": retrieved}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            tenant_id = str(payload["tenant"])
            query = str(payload["query"])
            result = _answer_for(tenant_id, query)
            self._send(200, result)
        except KeyError as err:
            self._send(400, {"error": f"missing field: {err}"})
        except Exception as err:
            self._send(502, {"error": str(err)})

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(
        f"sectum RAG shim listening on http://{LISTEN_HOST}:{LISTEN_PORT}  "
        f"mode={MODE} model={MODEL} base_url={BASE_URL}",
        flush=True,
    )
    print(
        f"  tenants: {', '.join(t['display_name'] for t in TENANT_MAP['tenants'].values())}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
