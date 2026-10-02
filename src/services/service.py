"""AgentCore Platform v1.0 - RET-C2-584 domain services.

Deterministic APPI 2026 classification + legal-basis rule table + gap
computation (Tool layer, no LLM) + LLM-essential board-summary
synthesis (with a deterministic fallback). S-2
pre-LLM rejection: any biometric/個人番号 pattern in system inventory
input must be rejected before the LLM call (design
invariant). S-3 output gate is non-suppressible: no
raw customer PII or biometric data in the audit report.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_PII_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
    re.compile(r"(?<!\d)\d{12}(?!\d)"),  # My Number
]
_BIOMETRIC_MARKERS = ("face recognition data:", "fingerprint data:", "iris scan data:", "顔認証データ:", "指紋データ:")

# APPI 2026 legal-basis rule table: (appi_category) -> required_legal_basis.
_LEGAL_BASIS_BY_CATEGORY = {
    "biometric": "Art.17 consent (要配慮個人情報)",
    "third_party_transfer": "Art.26-2 third-party transfer disclosure",
    "algorithm_disclosure": "Art.17 algorithm disclosure (effective 2026-07-06)",
}
_DEFAULT_LEGAL_BASIS = "Art.17 standard consent"

_SEVERITY_DEADLINE_DAYS = {"biometric": 30, "algorithm_disclosure": 60, "third_party_transfer": 90}


def has_pre_llm_rejection_pattern(text: str) -> bool:
    """S-2 pre-LLM invariant: reject if biometric/個人番号 pattern is present."""
    if any(p.search(text) for p in _PII_PATTERNS):
        return True
    lower = text.lower()
    return any(marker.lower() in lower for marker in _BIOMETRIC_MARKERS)


def parse_system_inventory(raw_input: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic typed-inventory parsing (Tool layer, no LLM)."""
    parsed = []
    for entry in raw_input:
        if not entry.get("system_name") or not entry.get("processing_type"):
            continue
        parsed.append(
            {
                "system_name": entry["system_name"],
                "processing_type": entry["processing_type"],
                "data_categories_claimed": entry.get("data_categories_claimed", []),
            }
        )
    return parsed


def classify_appi_category(system: dict[str, Any], appi_kb: list[dict[str, Any]] | None = None) -> str:
    """Deterministic APPI 2026 category classification (KB rule lookup, no LLM)."""
    appi_kb = appi_kb or []
    for entry in appi_kb:
        if entry.get("processing_type") == system.get("processing_type"):
            return str(entry.get("appi_category", "standard"))
    if "biometric" in system.get("data_categories_claimed", []):
        return "biometric"
    return "standard"


def determine_legal_basis(appi_category: str) -> str:
    """Deterministic (category -> required legal basis) rule table lookup."""
    return _LEGAL_BASIS_BY_CATEGORY.get(appi_category, _DEFAULT_LEGAL_BASIS)


def compute_gap(system: dict[str, Any], required_legal_basis: str) -> dict[str, Any]:
    """Deterministic gap computation: implemented controls vs required legal basis."""
    implemented = set(system.get("implemented_controls", []))
    gap = required_legal_basis not in implemented
    category = classify_appi_category(system)
    severity = "H" if gap and _SEVERITY_DEADLINE_DAYS.get(category, 90) <= 30 else ("M" if gap else "L")
    return {"system_name": system.get("system_name"), "gap": gap, "severity": severity}


class BoardSummaryLLMError(Exception):
    """Raised when a configured LLM fails, times out, or returns unusable content.

    Deterministic fallback is only valid when NO llm is configured at all - a
    configured-but-failing LLM must surface as an error to the caller (node
    sets AgentStatus.ERROR.value), never a silent SUCCESS with substitute text.
    """


def _extract_board_summary_text(raw: Any) -> str:
    """Normalise BaseLLM.complete() response - canonical is dict {"content": str, ...}."""
    if isinstance(raw, dict):
        content = raw.get("content", "")
        return content if isinstance(content, str) else ""
    if isinstance(raw, str):
        return raw
    return ""


def synthesize_board_summary(gap_report: list[dict[str, Any]], llm: Any | None = None, correlation_id: str = "") -> str:
    """LLM-essential board-level risk summary synthesis.

    Deterministic fallback keeps the pipeline runnable when llm is None. Once
    an LLM is configured, this raises BoardSummaryLLMError on failure/empty
    output instead of silently degrading to the deterministic text - callers
    must translate that into AgentStatus.ERROR.value (see 3m half-fix trap).
    """
    high_severity = [g for g in gap_report if g.get("severity") == "H"]

    if llm is None:
        if not high_severity:
            return "No high-severity APPI 2026 compliance gaps identified across the audited system inventory."
        return f"{len(high_severity)} system(s) have high-severity APPI 2026 compliance gaps requiring immediate remediation before the July 6, 2026 deadline."

    messages = [
        {
            "role": "user",
            "content": f"Write a board-level APPI 2026 risk summary for CFO/General Counsel given gaps: {gap_report}",
        }
    ]
    try:
        raw = llm.complete([{"role": "user", "content": messages}])
    except Exception as exc:  # noqa: BLE001 - narrow to a typed error, do not silently succeed
        logger.warning("synthesize_board_summary: llm.complete() failed (correlation_id=%s): %s", correlation_id, exc)
        raise BoardSummaryLLMError(f"llm.complete() failed: {exc}") from exc

    text = _extract_board_summary_text(raw).strip()
    if not text:
        logger.warning(
            "synthesize_board_summary: llm.complete() returned empty content (correlation_id=%s)", correlation_id
        )
        raise BoardSummaryLLMError("llm.complete() returned empty content")
    return text


def has_unmasked_pii(text: str) -> bool:
    """Non-suppressible re-check: verify no PII/biometric marker remains in the output."""
    return has_pre_llm_rejection_pattern(text)
