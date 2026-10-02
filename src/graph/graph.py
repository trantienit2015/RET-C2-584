"""AgentCore Platform v1.0 - RET-C2-584 outer graph (Cat 2).

Cat 2: outer AgentBaseGraph with the fixed 5-node backbone. Domain
complexity is encapsulated in APPIAuditReportGraphNode (the `main` slot),
which wraps the inner APPIAuditReportWorkflowGraph. Do NOT override
add_edges().

Backbone: initialize -> pre_process(InputValidateSystemInventoryParse) ->
          main(GraphNode) -> post_process(OutputValidate) -> finalize

APPIAuditReportGraphNode lives here (not under src/nodes/) to match the
scaffold canonical Cat 2 layout and to avoid a single-node probe pulling
in the whole inner subgraph. This is an architectural placement, not a
PB-6 test-scope evasion: this class is out of PB-6's discovery path (it
only walks src/nodes/), so the outer-boundary contract (S-1 trust gate,
extract_input/merge_output field mapping) is proven separately by
tests/proof_of_boundary/test_pb_graphnode_boundary.py. A GraphNode's
__call__ intentionally skips the standard S-2/S-4/S-3 lifecycle
(framework/nodes/graph_node.py) - that gating is delegated to the inner
subgraph's entry node, which is required to declare its own trust level.
"""

from typing import Any, ClassVar

from framework.graph.agent_base_graph import AgentBaseGraph
from shared.services.events import emitter
from shared.services.events.types import EventType
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.post_process_node import OutputValidateNode
from src.nodes.pre_process_node import InputValidateSystemInventoryParseNode
from src.schemas.state import State


class APPIAuditReportGraphNode(GraphNode):
    """Wraps the inner APPI classification/gap-report/board-summary workflow (Cat 2 composition)."""

    # DPO/Legal team callers only - internal enterprise audit function
    # (matches agent.yaml required_trust_level and the outer pre/post_process nodes).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL
    # "propagate": re-raise inner errors as SubgraphError (fail fast - default).
    error_strategy: ClassVar[str] = "propagate"
    # No HITL in this template.
    propagate_hitl: ClassVar[bool] = False

    def __init__(self, appi_kb: Any | None = None, llm: Any | None = None) -> None:
        super().__init__()
        self._appi_kb = appi_kb or []
        self._llm = llm

    def get_subgraph(self) -> AgentBaseGraph:
        from src.graph.domain_workflow_graph import APPIAuditReportWorkflowGraph

        sg = APPIAuditReportWorkflowGraph(config={"appi_kb": self._appi_kb, "llm": self._llm})
        sg.compile()
        return sg

    def extract_input(self, state: AgentState) -> str:
        # system_inventory is already the complete payload the inner
        # graph needs - no multi-field envelope required.
        # Progress (non-terminal) event for the caller, emitted as the subgraph step
        # begins. Outside the Marketplace runtime this is a no-op emitter.
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Working on the request...",
            metadata={"step": "main"},
        )
        emit_trace_event(
            "ret_appi_audit_workflow_dispatched", {"correlation_id": state.get("correlation_id", "")}, state
        )
        value = state.get("system_inventory", state.get("user_input", ""))
        return value if isinstance(value, str) else str(value)

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event(
            "ret_appi_audit_workflow_completed",
            {"correlation_id": state.get("correlation_id", ""), "status": str(sub_result.get("status"))},
            state,
        )
        return {
            "classified_systems": sub_result.get("classified_systems"),
            "gap_report": sub_result.get("gap_report"),
            "board_summary": sub_result.get("board_summary"),
            "formatted_report": sub_result.get("output"),
            "result": sub_result.get("output"),
            "status": sub_result.get("status"),
        }


class RETAPPIDataFlowAuditReportAgent(AgentBaseGraph):
    """RET-C2-584 - Retail APPI 2026 Personal Data Flow Audit Report Generator (Cat 2)."""

    @property
    def name(self) -> str:
        return "ret-c2-584"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize

        appi_kb = self.config.get("appi_kb")
        llm = self.config.get("llm")

        self._nodes["pre_process"] = InputValidateSystemInventoryParseNode()
        self._nodes["main"] = APPIAuditReportGraphNode(appi_kb=appi_kb, llm=llm)
        self._nodes["post_process"] = OutputValidateNode()

    # add_edges() is NOT overridden - backbone wiring belongs to the framework.


# Stable alias for the standalone entry point import (src/api/server.py).
Graph = RETAPPIDataFlowAuditReportAgent
