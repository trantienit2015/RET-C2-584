"""AgentCore Platform v1.0 - RET-C2-584 OutputValidateNode (outer post_process slot).

S-3 output gate: non-suppressible re-check that the audit report contains
no raw customer PII or biometric data. Own-dict field re-check only
(S-3 self-consistency rule - s3 hook cross state recheck fragile).
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from shared.services.events import emitter
from shared.services.events.types import EventType
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.service import has_unmasked_pii


class OutputValidateNode(FunctionNode):
    """Validate the audit report contains no raw PII or biometric data."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # Progress (non-terminal) event for the caller. Outside the Marketplace runtime
        # this resolves to a no-op emitter, so it is safe on every entry path.
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Preparing the result...",
            metadata={"step": "post_process"},
        )
        formatted_report = state.get("formatted_report", "")

        if has_unmasked_pii(formatted_report):
            emit_trace_event("output_validate_rejected_pii", {"correlation_id": state.get("correlation_id", "")}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["OutputValidateNode: audit report contains raw customer PII or biometric data"],
            }

        emit_trace_event("output_validate_passed", {"correlation_id": state.get("correlation_id", "")}, state)
        return {
            "formatted_output": formatted_report,
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """Non-suppressible re-check on the output dict's own field."""
        formatted_report = state.get("formatted_report", "")
        if has_unmasked_pii(formatted_report):
            emit_trace_event("output_validate_s3_recheck_blocked", {}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["OutputValidateNode: S-3 re-check blocked a report containing raw PII or biometric data"],
            }
        return state
