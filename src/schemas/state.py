"""AgentCore Platform v1.0 - RET-C2-584 state schema.

Retail APPI 2026 Personal Data Flow Audit Report Generator
(DocGenerationAgent pattern). Flat TypedDict extension of AgentState
(ADR-005). Structured payloads (dict/list) are JSON-string-encoded before
being stored in state fields.
"""

import json
from typing import Any, NotRequired

from framework.schemas.agent_state import AgentState


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def from_json(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class State(AgentState):
    """Agent state for RET-C2-584.

    system_inventory: JSON list[dict] of {system_name, processing_type,
      data_categories_claimed} parsed from the input.
    classified_systems: JSON list[dict] - system_inventory annotated with
      appi_category and required_legal_basis.
    gap_report: JSON list[dict] - {system_name, gap, severity} per system.
    board_summary: str - LLM-synthesized board-level risk narrative.
    formatted_report: str - final audit report (excerpt/redacted, no raw
      customer PII or biometric data).
    formatted_output: str - S-3-cleared copy of formatted_report, set by  # type: ignore[misc]
      OutputValidateNode once the PII re-check passes.
    """

    system_inventory: NotRequired[str]
    classified_systems: NotRequired[str]
    gap_report: NotRequired[str]
    board_summary: NotRequired[str]
    formatted_report: NotRequired[str]
    formatted_output: NotRequired[str]  # type: ignore[misc]
