"""AgentCore Platform v1.0 - RET-C2-584 GapReportBoardSummaryFormatNode (inner subgraph).

Combines GapReport (deterministic gap computation) + BoardSummaryFormat
(LLM-essential board-level narrative synthesis) from the workflow
outline, since both operate on the same classified_systems input with
no branching between them. Runs after APPIClassifyLegalBasisCheckNode
within the SAME inner subgraph invocation - classified_systems is already
in state (no GraphNode boundary crossing between inner nodes).
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import BoardSummaryLLMError, compute_gap, synthesize_board_summary


class GapReportBoardSummaryFormatNode(FunctionNode):
    """Compute per-system compliance gaps and synthesize the board-level risk summary."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def __init__(self, llm: Any | None = None) -> None:
        super().__init__()
        self._llm = llm

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        classified_systems = from_json(state.get("classified_systems", ""), None)
        emit_trace_event(
            "gap_report_board_summary_format_started", {"correlation_id": state.get("correlation_id", "")}, state
        )

        if not isinstance(classified_systems, list):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["GapReportBoardSummaryFormatNode: classified_systems missing or invalid"],
            }

        gap_report = [compute_gap(system, system["required_legal_basis"]) for system in classified_systems]
        try:
            board_summary = synthesize_board_summary(
                gap_report, llm=self._llm, correlation_id=state.get("correlation_id", "")
            )
        except BoardSummaryLLMError as exc:
            # Configured-but-failing LLM must surface as ERROR, not a silent
            # deterministic-text SUCCESS (3m half-fix trap).
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"GapReportBoardSummaryFormatNode: board summary synthesis failed: {exc}"],
            }

        return {
            "gap_report": to_json(gap_report),
            "board_summary": board_summary,
            "status": AgentStatus.SUCCESS.value,
        }
