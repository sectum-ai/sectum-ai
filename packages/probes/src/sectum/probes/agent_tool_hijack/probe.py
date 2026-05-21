"""Class 7 - cross-tenant agent tool-call hijacking via MCP (the engineering spec, section 7).

Verify that an MCP server preserves tenant scope when a tool is invoked. From
one tenant's session the probe invokes a lookup for another tenant's resource -
both directly (the confused-deputy pattern) and with the other tenant's token
attached (the Asana-class token-passthrough pattern). A foreign canary in a tool
result means the server acted with the wrong tenant's authority.

This is the v1 of Class 7: the MCP confused-deputy and token-passthrough
sub-probes. Broader agent-framework coverage follows in a later phase.
"""

from sectum.probes.detection import DetectingProbe
from sectum.spec import Finding, MarkerType, Observation, ProbeStep, Substrate, Surface


class AgentToolHijackProbe(DetectingProbe):
    """Class 7: invoke MCP tools across the tenant boundary and detect leakage."""

    id = "agent-tool-hijack"
    name = "Cross-tenant agent tool-call hijacking"
    owasp_llm = "LLM08:2025"
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ()
    surfaces: tuple[Surface, ...] = (Surface.MCP,)
    requires_adapters: tuple[str, ...] = ()

    def plan(self, substrate: Substrate) -> list[ProbeStep]:
        """Plan, per hard canary, a direct and a token-bearing MCP lookup from others."""
        tenant_ids = [tenant.tenant_id for tenant in substrate.tenants]
        steps: list[ProbeStep] = []
        for marker in substrate.manifest.markers:
            if marker.marker_type is not MarkerType.HARD_CANARY:
                continue
            for observer in tenant_ids:
                if observer == marker.owner_tenant_id:
                    continue
                # Confused-deputy: a plain lookup of a foreign resource key.
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer,
                        action="mcp.invoke",
                        payload={"tool": "lookup", "key": marker.marker_id},
                    )
                )
                # Token-passthrough: the same lookup carrying the owner's token.
                steps.append(
                    ProbeStep(
                        step_id=f"{self.id}-{len(steps):04d}",
                        probe_id=self.id,
                        actor_tenant_id=observer,
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
        """Scan an MCP tool result for a foreign canary via the detection pipeline."""
        pipeline = self._providers.pipeline(substrate)
        return pipeline.detect(
            step.actor_tenant_id,
            observation.raw_response,
            observation.surface,
            probe_id=self.id,
        )
