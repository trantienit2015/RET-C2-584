"""AgentCore Platform v1.0 - RET-C2-584 inner domain workflow graph.

Cat 2 inner graph: deterministic APPI 2026 classification + legal-basis
mapping (Tool) -> deterministic gap computation + LLM-essential board
summary synthesis. Instantiated by
APPIAuditReportGraphNode.get_subgraph() in graph.py.

Pipeline (linear, fail-fast on ERROR):
    START -> appi_classify_legal_basis_check -> gap_report_board_summary_format -> END
"""

from typing import Any, cast

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from langgraph.graph import END, START

from src.nodes.appi_classify_legal_basis_check_node import APPIClassifyLegalBasisCheckNode
from src.nodes.gap_report_board_summary_format_node import GapReportBoardSummaryFormatNode
from src.schemas.state import State, from_json


class APPIAuditReportWorkflowGraph(BaseGraph):
    """Inner graph for the RET-C2-584 APPI 2026 audit report workflow."""

    @property
    def name(self) -> str:
        return "ret-appi-audit-report-workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        # No mandatory config: appi_kb/llm are optional.
        pass

    def register_nodes(self) -> None:
        # No super() - BaseGraph.register_nodes() is abstract.
        appi_kb = self.config.get("appi_kb")
        llm = self.config.get("llm")

        self._nodes["appi_classify_legal_basis_check"] = APPIClassifyLegalBasisCheckNode(appi_kb=appi_kb)
        self._nodes["gap_report_board_summary_format"] = GapReportBoardSummaryFormatNode(llm=llm)

    def add_edges(self) -> None:
        self._sg.add_edge(START, "appi_classify_legal_basis_check")
        self._sg.add_conditional_edges(
            "appi_classify_legal_basis_check",
            lambda s: END if self._is_error(s) else "gap_report_board_summary_format",
            {"gap_report_board_summary_format": "gap_report_board_summary_format", END: END},
        )
        self._sg.add_edge("gap_report_board_summary_format", END)

    @staticmethod
    def _is_error(state: AgentState) -> bool:
        return state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value)

    def route(self, state: AgentState) -> str:
        return END if self._is_error(state) else "gap_report_board_summary_format"

    def get_output(self, state: AgentState) -> dict[str, Any]:
        gap_report = from_json(cast("str | None", state.get("gap_report", "")), [])
        board_summary = state.get("board_summary", "")
        high_count = sum(1 for g in gap_report if g.get("severity") == "H")
        report_text = (
            f"APPI 2026 Personal Data Flow Audit Report\n\n"
            f"Systems audited: {len(gap_report)} | High-severity gaps: {high_count}\n\n"
            f"Board Summary: {board_summary}"
        )
        return {
            "classified_systems": state.get("classified_systems"),
            "gap_report": state.get("gap_report"),
            "board_summary": board_summary,
            "output": report_text,
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
