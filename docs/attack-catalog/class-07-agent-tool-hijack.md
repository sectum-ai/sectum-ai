# Class 7 — Cross-tenant agent tool-call hijacking

**OWASP:** LLM08:2025 · **Surface:** MCP · **Probe id:** `agent-tool-hijack`

## Goal

Verify that a Model Context Protocol server preserves tenant scope when a tool
is invoked — no confused deputy, no token passthrough.

## Method

Each tenant's hard canary is provisioned as an MCP resource. From every other
tenant's session the probe issues the same lookup twice:

- a **direct lookup** of the foreign resource key — the confused-deputy pattern;
- the same lookup **carrying the owner's token** — the Asana-class
  token-passthrough pattern.

## Detection

A foreign canary in a tool result means the server acted with the wrong
tenant's authority.

## Status

Implemented in Phase 4 — the v1 MCP confused-deputy and token-passthrough
sub-probes. Broader agent-framework coverage follows in a later phase.
