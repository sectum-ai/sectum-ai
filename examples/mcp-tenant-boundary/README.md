# MCP Tenant Boundary — cross-tenant agent tool-call hijacking

This example reproduces **Attack Class 7**: an agent's tool calls crossing the
tenant boundary. It shows how a Model Context Protocol (MCP) server that has
lost tenant scope serves one tenant's resources into another tenant's session.

## The attack

Agents reach external systems through MCP servers. If an MCP server does not
bind a tool call to the authenticated caller, two flaws follow:

- **Confused deputy** — the server resolves a tool call without checking which
  tenant asked, so tenant B's `lookup` returns tenant A's resource.
- **Token passthrough** — the server trusts a token supplied by the caller and
  acts as whatever tenant the token names. This is the pattern behind the 2025
  Asana MCP cross-tenant flaw.

Either way, an agent acting for tenant B obtains tenant A's data.

This is **OWASP LLM08:2025 — Vector and Embedding Weaknesses**, on the agentic
tool-call surface.

## What the demo does

`run.sh` runs the Class 7 probe end to end:

1. **`sectum-ai seed`** provisions four synthetic tenants and their canary markers.
2. **`sectum-ai probe --probe agent-tool-hijack`** provisions each tenant's hard
   canary as an MCP resource, then from every other tenant issues four sub-probes
   for it — a direct lookup (confused-deputy), a lookup carrying the owner's
   token (token-passthrough), a lookup routed through a downstream server
   (cross-server confused-deputy), and a search whose attacker-authored tool
   description smuggles the coordinate (tool-description injection) — against an
   MCP server with the confused-deputy and token-passthrough flaws switched on.
3. **`sectum-ai report`** assembles a tamper-evident evidence pack.
4. **`sectum-ai verify`** independently re-checks the pack.

## Run it

```sh
./run.sh
```

Artifacts are written to `out/`.

## Expected result

Every cross-tenant tool call resolves a foreign canary, so the probe confirms a
leak on each:

```
ran 1 probe: 24 confirmed cross-tenant findings
```

`sectum-ai probe` exits with code 2 because it confirmed cross-tenant leaks, and
`sectum-ai verify` confirms the evidence pack is intact.

A tenant-scoped MCP server — one that binds every tool call to the
authenticated caller and ignores caller-supplied tokens — yields zero findings.
