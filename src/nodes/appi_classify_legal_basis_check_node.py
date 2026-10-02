"""AgentCore Platform v1.0 - RET-C2-584 APPIClassifyLegalBasisCheckNode (inner subgraph).

Combines APPIClassify (KB retrieval + deterministic rule) + LegalBasisCheck
(deterministic rule table) from the workflow outline, since both
are deterministic lookups on the same system_inventory input with no
branching between them.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import classify_appi_category, determine_legal_basis


class APPIClassifyLegalBasisCheckNode(FunctionNode):
    """Classify each system's APPI 2026 category and required legal basis."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def __init__(self, appi_kb: list[dict[str, Any]] | None = None) -> None:
        super().__init__()
        self._appi_kb = appi_kb or []

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # GraphNode subgraph boundary: extract_input() forwards
        # system_inventory as the inner graph's user_input; system_inventory
        # itself is not seeded in the fresh inner state (see
        # graphnode subgraph boundary field loss).
        system_inventory = from_json(state.get("system_inventory") or state.get("user_input", ""), None)
        emit_trace_event(
            "appi_classify_legal_basis_check_started", {"correlation_id": state.get("correlation_id", "")}, state
        )

        if not isinstance(system_inventory, list) or not system_inventory:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["APPIClassifyLegalBasisCheckNode: system_inventory missing or empty"],
            }

        classified = []
        for system in system_inventory:
            appi_category = classify_appi_category(system, appi_kb=self._appi_kb)
            required_legal_basis = determine_legal_basis(appi_category)
            classified.append({**system, "appi_category": appi_category, "required_legal_basis": required_legal_basis})

        return {
            "classified_systems": to_json(classified),
            "status": AgentStatus.SUCCESS.value,
        }
