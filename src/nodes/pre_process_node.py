"""AgentCore Platform v1.0 - RET-C2-584 InputValidateSystemInventoryParseNode (outer pre_process).

Combines InputValidate (S-1/S-2: trust gate + pre-LLM biometric/個人番号
rejection invariant) + SystemInventoryParse
(deterministic typed-inventory parsing) from the workflow outline,
since both operate on the raw input with no branching between them.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from shared.services.events import emitter
from shared.services.events.types import EventType
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import has_pre_llm_rejection_pattern, parse_system_inventory


class InputValidateSystemInventoryParseNode(FunctionNode):
    """Validate the system inventory input and parse it into a typed model."""

    # DPO/Legal team callers only - internal enterprise audit function.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # Progress (non-terminal) event for the caller. Outside the Marketplace runtime
        # this resolves to a no-op emitter, so it is safe on every entry path.
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Checking the request...",
            metadata={"step": "pre_process"},
        )
        user_input = state.get("user_input", "")
        emit_trace_event("system_inventory_received", {"correlation_id": state.get("correlation_id", "")}, state)

        if not user_input or not user_input.strip():
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InputValidateSystemInventoryParseNode: user_input is empty or missing"],
            }

        if has_pre_llm_rejection_pattern(user_input):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [
                    "InputValidateSystemInventoryParseNode: input contains a biometric/個人番号 pattern - rejected before LLM call (S-2 pre-LLM invariant)"
                ],
            }

        raw_input = from_json(user_input, None)
        if not isinstance(raw_input, list):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [
                    "InputValidateSystemInventoryParseNode: user_input must be a JSON array of system entries"
                ],
            }

        system_inventory = parse_system_inventory(raw_input)
        if not system_inventory:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [
                    "InputValidateSystemInventoryParseNode: no valid system entries found (each needs system_name and processing_type)"
                ],
            }

        return {
            "system_inventory": to_json(system_inventory),
            "status": AgentStatus.SUCCESS.value,
        }
