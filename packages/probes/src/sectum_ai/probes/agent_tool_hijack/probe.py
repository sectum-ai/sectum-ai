"""Class 7 - cross-tenant agent tool-call hijacking via MCP (the engineering spec, section 7).

Verify that an MCP server preserves tenant scope when a tool is invoked. From
one tenant's session the probe invokes a lookup for another tenant's resource -
both directly (the confused-deputy pattern) and with the other tenant's token
attached (the Asana-class token-passthrough pattern). A foreign canary in a tool
result means the server acted with the wrong tenant's authority.

This is the v1 of Class 7: the MCP confused-deputy and token-passthrough
sub-probes. Broader agent-framework coverage follows in a later phase.
"""

from sectum_ai.probes.detection import DetectingProbe, is_cross_principal
from sectum_ai.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface


class AgentToolHijackProbe(DetectingProbe):
    """Class 7: invoke MCP tools across the tenant boundary and detect leakage."""

    id = "agent-tool-hijack"
    name = "Cross-tenant agent tool-call hijacking"
    owasp_llm = "LLM08:2025"
    owasp_secondary: tuple[str, ...] = ("LLM06:2025",)
    # T0053 LLM Plugin Compromise is the confused-deputy / token-passthrough
    # technique; T0024 Exfiltration via AI Inference API is the leak it causes.
    atlas_techniques: tuple[str, ...] = ("AML.T0024", "AML.T0053")
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)
    surfaces: tuple[Surface, ...] = (Surface.MCP,)
    requires_adapters: tuple[str, ...] = ("mcp",)

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan, per hard canary, a direct and a token-bearing MCP lookup from foreign principals.

        The lookups are issued from every principal to which the marker is
        foreign - another tenant, or another user within the tenant (ADR-0006) -
        so tool-call scope is verified at both granularities. A plain lookup from
        a sibling user surfaces the owner's resource on a server that scopes by
        tenant alone. With no users declared the principals are the tenants and
        this is the original per-tenant plan.
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
        return steps

    def detect(
        self, step: ProbeStep, observation: Observation, substrate: Substrate
    ) -> list[Finding]:
        """Scan an MCP tool result for a foreign-principal canary via the pipeline."""
        pipeline = self._providers.pipeline(substrate)
        return pipeline.detect(
            step.actor_tenant_id,
            observation.raw_response,
            observation.surface,
            probe_id=self.id,
            observed_user=step.actor_user_id,
            owasp_llm=self.owasp_llm,
            atlas=self.atlas_techniques,
            nist=self.nist_rmf,
            owasp_secondary=self.owasp_secondary,
        )
