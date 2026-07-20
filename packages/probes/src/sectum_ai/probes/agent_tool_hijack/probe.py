"""Class 7 - cross-tenant agent tool-call hijacking via MCP (the engineering spec, section 7).

Verify that an MCP server preserves tenant scope when a tool is invoked. From a
foreign principal's session the probe runs four sub-probes against each foreign
resource:

- **confused deputy** - a direct lookup of the foreign resource key;
- **token passthrough** - the same lookup carrying the owner's token (the
  Asana-class pattern);
- **cross-server confused deputy** - a lookup routed (``via``) through a second
  MCP server that holds the owner's authority, so a router that forwards under
  the downstream's broad authority leaks across the server boundary;
- **tool-description injection** - a ``search`` whose attacker-authored tool
  description smuggles a foreign coordinate the call never named.

A foreign canary in any tool result means the server (or the router) acted with
the wrong tenant's authority. Detection is manifest-grounded and identical for
every sub-probe: the result is scanned for a canary owned by a principal the
caller is foreign to. The tool-description-injection sub-probe models server-side
scope enforcement when tool metadata supplies an out-of-band coordinate (a
simplification of the LLM-agent-level description-poisoning attack).
"""

from sectum_ai.probes.detection import DetectingProbe, is_cross_principal
from sectum_ai.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface


class AgentToolHijackProbe(DetectingProbe):
    """Class 7: invoke MCP tools across the tenant boundary and detect leakage."""

    id = "agent-tool-hijack"
    name = "Cross-tenant agent tool-call hijacking"
    owasp_llm = "LLM08:2025"
    owasp_secondary: tuple[str, ...] = ("LLM06:2025",)
    # T0053 LLM Plugin Compromise is the confused-deputy / token-passthrough /
    # cross-server technique; T0024 Exfiltration via AI Inference API is the leak it
    # causes. The tool-description-injection sub-probe additionally demonstrates
    # T0051.001 (LLM Prompt Injection: Indirect) - the coordinate arrives through tool
    # metadata the agent ingests rather than through the call. This tuple is the probe's
    # full ATLAS footprint; each finding is stamped with the subset its own sub-probe
    # demonstrates (`_LOOKUP_ATLAS` below), so a confused-deputy leak is never labelled
    # an injection it did not perform.
    atlas_techniques: tuple[str, ...] = ("AML.T0024", "AML.T0051.001", "AML.T0053")
    _LOOKUP_ATLAS: tuple[str, ...] = ("AML.T0024", "AML.T0053")
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)
    surfaces: tuple[Surface, ...] = (Surface.MCP,)
    requires_adapters: tuple[str, ...] = ("mcp",)

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan, per hard canary, the four MCP sub-probes from every foreign principal.

        The sub-probes (confused deputy, token passthrough, cross-server deputy,
        tool-description injection) are issued from every principal to which the
        marker is foreign - another tenant, or another user within the tenant
        (ADR-0006) - so tool-call scope is verified at both granularities. A plain
        lookup from a sibling user surfaces the owner's resource on a server that
        scopes by tenant alone. With no users declared the principals are the
        tenants and this is the original per-tenant plan.
        """
        principals = substrate.principals()
        steps: list[ProbeStep] = []
        for marker in substrate.manifest.markers:
            if marker.marker_type is not MarkerType.HARD_CANARY:
                continue
            for observer in principals:
                if not is_cross_principal(marker, observer):
                    continue
                # Confused-deputy: a plain lookup of a foreign resource key.
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer.tenant_id,
                        actor_user_id=observer.user_id,
                        action="mcp.invoke",
                        payload={"tool": "lookup", "key": marker.marker_id},
                    )
                )
                # Token-passthrough: the same lookup carrying the owner's token.
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer.tenant_id,
                        actor_user_id=observer.user_id,
                        action="mcp.invoke",
                        payload={
                            "tool": "lookup",
                            "key": marker.marker_id,
                            "token": str(marker.owner_tenant_id),
                        },
                    )
                )
                # Cross-server confused deputy: route the lookup (``via``) through
                # a downstream server that holds the owner's authority. A router
                # that forwards under the downstream's broad authority leaks the
                # foreign resource across the server boundary (the Asana-class
                # cross-server pattern); a scoped router forwards the real caller.
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer.tenant_id,
                        actor_user_id=observer.user_id,
                        action="mcp.invoke",
                        payload={"tool": "lookup", "key": marker.marker_id, "via": "downstream"},
                    )
                )
                # Tool-description injection: invoke ``search`` whose attacker-
                # authored description smuggles the foreign coordinate. A server
                # that honours the description's coordinate (instead of the
                # caller's scope) returns the foreign resource the call never named.
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer.tenant_id,
                        actor_user_id=observer.user_id,
                        action="mcp.invoke",
                        payload={"tool": "search", "desc_key": marker.marker_id},
                    )
                )
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan an MCP tool result for a foreign-principal canary via the pipeline.

        The ATLAS stamp is the sub-probe's own, not the probe's whole footprint: only the
        tool-description-injection sub-probe (the ``search`` tool) smuggles its coordinate
        through ingested tool metadata, so only its findings carry T0051.001. The three
        ``lookup`` sub-probes reach the resource by naming it, which is a plugin-scope
        failure and not an injection.
        """
        pipeline = self._providers.pipeline(substrate)
        injected = step.payload.get("tool") == "search"
        return pipeline.detect(
            step.actor_tenant_id,
            observation.raw_response,
            observation.surface,
            probe_id=self.id,
            observed_user=step.actor_user_id,
            owasp_llm=self.owasp_llm,
            atlas=self.atlas_techniques if injected else self._LOOKUP_ATLAS,
            nist=self.nist_rmf,
            owasp_secondary=self.owasp_secondary,
        )
