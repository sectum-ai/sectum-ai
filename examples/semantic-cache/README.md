# Semantic / prompt-cache contamination — Class 4

This example reproduces **Attack Class 4**: cross-tenant
contamination of a semantic or prompt cache (the engineering spec,
§7). Tenant X primes the cache with a query whose answer contains a
`HARD_CANARY`; tenant Y issues a semantically-near query. On a
cache that does not key by tenant, tenant Y receives tenant X's
cached answer — canary intact.

## The attack

Semantic / prompt caches (GPTCache, Redis-backed key-value caches,
provider-side prompt caching like Anthropic's or OpenAI's) speed
up inference by serving the same answer twice without re-running
the model. When the cache key is just the query text (or its
embedding), a near-paraphrase from a *different* tenant hits the
entry and gets back the original tenant's answer. The cached
response carries any canary that was in the first answer.

This is **OWASP LLM08:2025** on the cache surface. Real deployments
hit it whenever:

- A GPTCache-style semantic cache is shared across all callers
  without `tenant_id` in the key
- A Redis cache uses a hash of the question as the key
- A provider-side prompt cache is enabled on a shared API key

## What the demo does

`run.sh` runs the canonical CLI flow end to end against the in-
memory `FakeCache` with `tenant_scoped: false` (the leaky
condition Class 4 is built to catch):

1. **`sectum-ai seed`** provisions four synthetic tenants and their
   canary markers.
2. **`sectum-ai probe --probe semantic-cache-contamination`** primes
   the cache as each tenant with their hard canary, then from every
   foreign tenant issues the same key lookup. A returned value that
   matches a foreign tenant's primed canary is a confirmed leak;
   the probe exits `2` on at least one such hit.
3. **`sectum-ai report`** assembles the tamper-evident evidence pack.
4. **`sectum-ai verify`** independently re-checks the pack.

## Run it

```sh
./run.sh
```

## Swap the in-memory cache for Redis

```yaml
adapters:
  cache:
    kind: redis
    host: localhost
    port: 6379
    tenant_scoped: false   # delete to enforce per-tenant keying
```

```sh
sectum-ai probe --probe semantic-cache-contamination --config sectum-ai.yaml --workdir out
```

A real engagement runs with `tenant_scoped: true` (or absent) to
*verify* the cache keys carry tenant scope; the demo flips it off
so the walkthrough has a leak to show.

## What the report tells you

Each Class 4 finding carries:

- the priming tenant (X) + the observing tenant (Y)
- the leaked canary's marker id + `evidence_span` (the cached
  answer text)
- the surface (`SEMANTIC_CACHE`)
- OWASP / ATLAS / NIST control IDs
- a remediation pointer naming the standard counter-measure: per-
  tenant cache namespacing (`tenant_id` in the key derivation),
  TTL bounds, or disabling the cache for tenant-sensitive paths

## What's *not* in this example

- **Embedding-proximity-based collisions.** This probe uses exact
  key collisions; a near-paraphrase that hashes to a different key
  but matches via embedding similarity is the variant the live
  semantic-cache adapter would surface — covered as a follow-up
  shape of Class 4.
- **Provider-side prompt-cache attacks.** The probe assumes the
  cache is reachable through the configured `CacheAdapter`; testing
  OpenAI / Anthropic provider-side prompt caches requires a hosted
  cache adapter the catalog will add in a later pass.
