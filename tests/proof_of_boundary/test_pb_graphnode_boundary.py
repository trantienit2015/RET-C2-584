# GraphNode boundary test — outer `main` slot GraphNode is out of PB-6's discovery
# scope (PB-6 only walks src/nodes/), but it is the first security boundary that
# receives the caller's input for the Cat 2 domain workflow. This test proves the
# boundary is exercised: S-1 trust gate, explicit extract_input/merge_output field
# mapping (criterion #9), and the intentional delegation of S-2/S-3 gating to the
# inner subgraph's entry node (framework/nodes/graph_node.py GraphNode.__call__()).

from framework.schemas.trust_level import TrustLevel

from src.graph.graph import APPIAuditReportGraphNode
from src.nodes.appi_classify_legal_basis_check_node import APPIClassifyLegalBasisCheckNode
from src.schemas.state import to_json


class TestGraphNodeS1TrustGate:
    def test_rejects_insufficient_trust(self):
        node = APPIAuditReportGraphNode()
        state = {
            "system_inventory": to_json([{"system_name": "x", "processing_type": "y"}]),
            "caller_trust_level": TrustLevel.ANONYMOUS.value,
        }
        result = node(state)
        assert str(result["status"]).lower().endswith("error")
        assert any("trust gate denied" in msg.lower() for msg in result.get("error_log", []))

    def test_accepts_sufficient_trust(self):
        node = APPIAuditReportGraphNode()
        state = {
            "system_inventory": to_json(
                [{"system_name": "x", "processing_type": "y", "data_categories_claimed": []}]
            ),
            "caller_trust_level": TrustLevel.INTERNAL.value,
        }
        result = node(state)
        assert not any("trust gate denied" in msg.lower() for msg in result.get("error_log", []))


class TestGraphNodeBoundaryMapping:
    def test_extract_input_forwards_only_system_inventory(self):
        node = APPIAuditReportGraphNode()
        state = {
            "system_inventory": to_json([{"system_name": "x"}]),
            "user_input": "should not leak if system_inventory is present",
            "some_unrelated_field": "must not appear in extracted input",
        }
        extracted = node.extract_input(state)
        assert extracted == state["system_inventory"]
        assert "some_unrelated_field" not in extracted

    def test_merge_output_maps_fields_explicitly_no_raw_passthrough(self):
        node = APPIAuditReportGraphNode()
        sub_result = {
            "classified_systems": to_json([{"system_name": "x"}]),
            "gap_report": to_json([{"system_name": "x", "gap": False, "severity": "L"}]),
            "board_summary": "No high-severity gaps.",
            "output": "final report text",
            "status": "success",
            "internal_debug_field": "must not leak into parent state",
        }
        merged = node.merge_output({}, sub_result)
        assert merged["classified_systems"] == sub_result["classified_systems"]
        assert merged["gap_report"] == sub_result["gap_report"]
        assert merged["board_summary"] == sub_result["board_summary"]
        assert merged["formatted_report"] == sub_result["output"]
        assert merged["result"] == sub_result["output"]
        assert merged["status"] == sub_result["status"]
        assert "internal_debug_field" not in merged


class TestGraphNodeDelegatesGatingToInnerEntryNode:
    """GraphNode.__call__() intentionally skips S-2/S-4/S-3 (framework/nodes/graph_node.py) -
    gating is delegated to the inner subgraph's entry node. Prove the delegate exists and
    itself declares a trust level (it is not silently ungated)."""

    def test_inner_entry_node_declares_trust_level(self):
        assert hasattr(APPIClassifyLegalBasisCheckNode, "required_trust_level")
