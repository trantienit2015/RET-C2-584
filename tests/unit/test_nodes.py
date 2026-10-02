# RET-C2-584 - Unit tests: per-node success + error/edge paths.

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.nodes.appi_classify_legal_basis_check_node import APPIClassifyLegalBasisCheckNode
from src.nodes.gap_report_board_summary_format_node import GapReportBoardSummaryFormatNode
from src.nodes.post_process_node import OutputValidateNode
from src.nodes.pre_process_node import InputValidateSystemInventoryParseNode
from src.schemas.state import from_json, to_json

BIOMETRIC_SYSTEM = {"system_name": "FaceCheckout", "processing_type": "biometric_auth", "data_categories_claimed": ["biometric"]}
STANDARD_SYSTEM = {"system_name": "LoyaltyEngine", "processing_type": "loyalty_scoring", "data_categories_claimed": []}


class TestInputValidateSystemInventoryParseNode:
    def test_success(self):
        state = {"user_input": to_json([BIOMETRIC_SYSTEM, STANDARD_SYSTEM])}
        r = InputValidateSystemInventoryParseNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert len(from_json(r["system_inventory"], [])) == 2

    def test_empty_input_error(self):
        assert InputValidateSystemInventoryParseNode().execute({"user_input": ""})["status"] == AgentStatus.ERROR

    def test_biometric_marker_rejected(self):
        state = {"user_input": "System notes: face recognition data: raw scan bytes here"}
        assert InputValidateSystemInventoryParseNode().execute(state)["status"] == AgentStatus.ERROR

    def test_not_json_array_error(self):
        assert InputValidateSystemInventoryParseNode().execute({"user_input": "not json"})["status"] == AgentStatus.ERROR

    def test_no_valid_entries_error(self):
        state = {"user_input": to_json([{"processing_type": "x"}])}
        assert InputValidateSystemInventoryParseNode().execute(state)["status"] == AgentStatus.ERROR


class TestAPPIClassifyLegalBasisCheckNode:
    def test_success_biometric_classification(self):
        state = {"system_inventory": to_json([BIOMETRIC_SYSTEM])}
        r = APPIClassifyLegalBasisCheckNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        classified = from_json(r["classified_systems"], [])
        assert classified[0]["appi_category"] == "biometric"
        assert "Art.17 consent" in classified[0]["required_legal_basis"]

    def test_success_standard_classification(self):
        state = {"system_inventory": to_json([STANDARD_SYSTEM])}
        r = APPIClassifyLegalBasisCheckNode().execute(state)
        classified = from_json(r["classified_systems"], [])
        assert classified[0]["appi_category"] == "standard"

    def test_missing_inventory_error(self):
        assert APPIClassifyLegalBasisCheckNode().execute({"system_inventory": ""})["status"] == AgentStatus.ERROR


class TestGapReportBoardSummaryFormatNode:
    def test_success_high_severity_gap(self):
        classified = [{**BIOMETRIC_SYSTEM, "appi_category": "biometric", "required_legal_basis": "Art.17 consent (要配慮個人情報)", "implemented_controls": []}]
        state = {"classified_systems": to_json(classified)}
        r = GapReportBoardSummaryFormatNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        gap_report = from_json(r["gap_report"], [])
        assert gap_report[0]["severity"] == "H"

    def test_success_no_gap(self):
        classified = [
            {
                **STANDARD_SYSTEM,
                "appi_category": "standard",
                "required_legal_basis": "Art.17 standard consent",
                "implemented_controls": ["Art.17 standard consent"],
            }
        ]
        state = {"classified_systems": to_json(classified)}
        r = GapReportBoardSummaryFormatNode().execute(state)
        gap_report = from_json(r["gap_report"], [])
        assert gap_report[0]["gap"] is False

    def test_missing_classified_systems_error(self):
        assert GapReportBoardSummaryFormatNode().execute({"classified_systems": ""})["status"] == AgentStatus.ERROR

    def test_llm_failure_logs_warning_and_returns_error(self, caplog):
        class RaisingLLM:
            def complete(self, messages):
                raise RuntimeError("provider unavailable")

        classified = [
            {
                **BIOMETRIC_SYSTEM,
                "appi_category": "biometric",
                "required_legal_basis": "Art.17 consent (要配慮個人情報)",
                "implemented_controls": [],
            }
        ]
        state = {"classified_systems": to_json(classified), "correlation_id": "corr-123"}
        with caplog.at_level("WARNING"):
            r = GapReportBoardSummaryFormatNode(llm=RaisingLLM()).execute(state)
        # Configured-but-failing LLM must surface as ERROR, not a silent
        # deterministic-text SUCCESS (3m half-fix trap).
        assert r["status"] == AgentStatus.ERROR
        assert any("board summary synthesis failed" in msg for msg in r.get("error_log", []))
        assert any("corr-123" in rec.message and "llm.complete() failed" in rec.message for rec in caplog.records)

    def test_llm_configured_success_uses_complete_result(self):
        class EchoLLM:
            def complete(self, messages):
                assert isinstance(messages, list)
                return {"content": "Board summary: 1 high-severity APPI gap requires remediation."}

        classified = [
            {
                **BIOMETRIC_SYSTEM,
                "appi_category": "biometric",
                "required_legal_basis": "Art.17 consent (要配慮個人情報)",
                "implemented_controls": [],
            }
        ]
        state = {"classified_systems": to_json(classified)}
        r = GapReportBoardSummaryFormatNode(llm=EchoLLM()).execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["board_summary"] == "Board summary: 1 high-severity APPI gap requires remediation."


class TestOutputValidateNode:
    def test_success_compliant_report(self):
        state = {"formatted_report": "2 systems audited, 0 high-severity gaps."}
        r = OutputValidateNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS

    def test_unmasked_pii_error(self):
        state = {"formatted_report": "Contact reviewer@example.com for details."}
        assert OutputValidateNode().execute(state)["status"] == AgentStatus.ERROR

    def test_extra_gate_blocks_unmasked_pii(self):
        bad_state = {"formatted_report": "face recognition data: raw bytes"}
        out = OutputValidateNode()._extra_security_gate_output(bad_state)
        assert out["status"] == AgentStatus.ERROR

    def test_extra_gate_passthrough_compliant_report(self):
        good_state = {"formatted_report": "Clean audit summary."}
        assert OutputValidateNode()._extra_security_gate_output(good_state) is good_state


# S-1 trust-gate reject coverage — S-1 trust-gate reject coverage.
# InputValidateSystemInventoryParseNode, APPIClassifyLegalBasisCheckNode,
# GapReportBoardSummaryFormatNode, OutputValidateNode all declare required_trust_level=INTERNAL, but
# existing tests above call .execute(state) directly, bypassing BaseNode.__call__()'s S-1 trust gate.
class TestTrustGateReject:
    def test_input_validate_rejects_insufficient_trust(self):
        state = {"user_input": to_json([BIOMETRIC_SYSTEM, STANDARD_SYSTEM]), "caller_trust_level": TrustLevel.ANONYMOUS.value}
        result = InputValidateSystemInventoryParseNode()(state)
        assert str(result["status"]).lower().endswith("error")
        assert any("trust gate denied" in msg.lower() for msg in result.get("error_log", []))

    def test_input_validate_succeeds_with_sufficient_trust(self):
        state = {"user_input": to_json([BIOMETRIC_SYSTEM, STANDARD_SYSTEM]), "caller_trust_level": TrustLevel.INTERNAL.value}
        result = InputValidateSystemInventoryParseNode()(state)
        assert result["status"] == AgentStatus.SUCCESS.value

    def test_appi_classify_rejects_insufficient_trust(self):
        state = {"system_inventory": to_json([BIOMETRIC_SYSTEM]), "caller_trust_level": TrustLevel.ANONYMOUS.value}
        result = APPIClassifyLegalBasisCheckNode()(state)
        assert str(result["status"]).lower().endswith("error")
        assert any("trust gate denied" in msg.lower() for msg in result.get("error_log", []))

    def test_appi_classify_succeeds_with_sufficient_trust(self):
        state = {"system_inventory": to_json([BIOMETRIC_SYSTEM]), "caller_trust_level": TrustLevel.INTERNAL.value}
        result = APPIClassifyLegalBasisCheckNode()(state)
        assert result["status"] == AgentStatus.SUCCESS.value

    def test_gap_report_rejects_insufficient_trust(self):
        classified = [{**BIOMETRIC_SYSTEM, "appi_category": "biometric", "required_legal_basis": "Art.17 consent (要配慮個人情報)", "implemented_controls": []}]
        state = {"classified_systems": to_json(classified), "caller_trust_level": TrustLevel.ANONYMOUS.value}
        result = GapReportBoardSummaryFormatNode()(state)
        assert str(result["status"]).lower().endswith("error")
        assert any("trust gate denied" in msg.lower() for msg in result.get("error_log", []))

    def test_gap_report_succeeds_with_sufficient_trust(self):
        classified = [{**BIOMETRIC_SYSTEM, "appi_category": "biometric", "required_legal_basis": "Art.17 consent (要配慮個人情報)", "implemented_controls": []}]
        state = {"classified_systems": to_json(classified), "caller_trust_level": TrustLevel.INTERNAL.value}
        result = GapReportBoardSummaryFormatNode()(state)
        assert result["status"] == AgentStatus.SUCCESS.value

    def test_output_validate_rejects_insufficient_trust(self):
        state = {"formatted_report": "2 systems audited, 0 high-severity gaps.", "caller_trust_level": TrustLevel.ANONYMOUS.value}
        result = OutputValidateNode()(state)
        assert str(result["status"]).lower().endswith("error")
        assert any("trust gate denied" in msg.lower() for msg in result.get("error_log", []))

    def test_output_validate_succeeds_with_sufficient_trust(self):
        # S-1 clearance only — S-3 output re-check inspects the node's own result dict, not the
        # input state.
        state = {"formatted_report": "2 systems audited, 0 high-severity gaps.", "caller_trust_level": TrustLevel.INTERNAL.value}
        result = OutputValidateNode()(state)
        assert not any("trust gate denied" in msg.lower() for msg in result.get("error_log", []))
