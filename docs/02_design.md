# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: `RETAPPIDataFlowAuditReportAgent`
- **L1 Base**: AgentBaseGraph
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

## Architecture Overview

Cat 2: outer `AgentBaseGraph` (fixed 5-node backbone) + `GraphNode` in the
`main` slot wrapping an inner `BaseGraph` (2-step linear domain workflow).

### Node Configuration (outer)

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | schema_version/session_id/trust_level | - | - | InitializeNode (default) |
| pre_process | `InputValidateSystemInventoryParseNode` — S-1/S-2 gate (pre-LLM biometric/個人番号 rejection invariant) + typed-inventory parsing | `user_input` | `system_inventory` | FunctionNode |
| main | `APPIAuditReportGraphNode` — wraps inner workflow | `system_inventory` | `classified_systems`, `gap_report`, `board_summary`, `formatted_report` | GraphNode |
| post_process | `OutputValidateNode` — non-suppressible PII/biometric re-check | `formatted_report` | (validated) | FunctionNode |
| finalize | response_metadata, total_time_ms | - | - | FinalizeNode (default) |

### Node Configuration (inner, per the locked node flow)

| Node | Responsibility |
|------|-----------------|
| `APPIClassifyLegalBasisCheckNode` | Deterministic APPI 2026 category classification (KB rule lookup) + deterministic (category → required legal basis) rule table lookup; no LLM |
| `GapReportBoardSummaryFormatNode` | Deterministic gap computation (implemented controls vs required legal basis, severity by deadline proximity) + LLM-essential board-level risk narrative synthesis (with a deterministic fallback) |

### Data Flow

```
START → initialize → pre_process → main → {route} → post_process → finalize → END
                                            ↓ (retry)
                                          pre_process
```

Inner (wrapped by `main`):
```
START → appi_classify_legal_basis_check → gap_report_board_summary_format → END
```

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `system_inventory` | str (JSON list[dict]) | parsed `{system_name, processing_type, data_categories_claimed}` entries | Yes |
| `classified_systems` | str (JSON list[dict]) | `system_inventory` annotated with `appi_category`/`required_legal_basis` | Yes |
| `gap_report` | str (JSON list[dict]) | `{system_name, gap, severity}` per system | Yes |
| `board_summary` | str | LLM-synthesized board-level risk narrative | Yes |
| `formatted_report` | str | final audit report text (no raw PII/biometric data) | Yes |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `config["configurable"]` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, permissions, credential handle)
- [x] SecurityViolationError
- [x] S-1: `required_trust_level = INTERNAL` on every node — DPO/Legal
      team callers only.
- [x] S-2: pre-LLM rejection invariant in `InputValidateSystemInventoryParseNode`
      — as a design invariant, any biometric-data marker or
      個人番号 pattern in the system inventory input is rejected BEFORE
      the LLM call in `GapReportBoardSummaryFormatNode`, not just at
      output time.
- [x] S-3: `_extra_security_gate_output()` — non-suppressible re-check on
      `OutputValidateNode` that `formatted_report` contains no raw
      customer PII or biometric data. Own-dict field re-check only, per
      the S-3 hook self-consistency rule.
- [x] S-4: `emit_trace_event()` — domain events
      (`ret_appi_audit_workflow_dispatched`,
      `ret_appi_audit_workflow_completed`,
      `output_validate_s3_recheck_blocked`) inside each `execute()`. Audit
      logs system count + gap severity summary only, never raw system
      inventory payload.

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)

### Composition Pattern

- **Pattern**: GraphNode (subgraph) — `APPIAuditReportGraphNode` wraps
  `APPIAuditReportWorkflowGraph`.
- **Composition target**: inner `BaseGraph` (2-node linear domain workflow).
- **Error propagation strategy**: `propagate` (fail fast — re-raise inner
  errors as `SubgraphError`, default). No HITL in this template.

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: framework/ and shared/ only (no agents/base/ required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| Level 2 pattern | ChatAgent (initial outline) | DocGenerationAgent | DocGenerationAgent | Correction: this is a stateless report-generation pipeline, not a multi-turn conversation agent |
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | AgentBaseGraph | Cat 2 fixed multi-step workflow, no autonomous loop needed |
| Composition pattern | Standalone nodes | GraphNode (subgraph) | GraphNode | Domain complexity (APPI classification + legal basis mapping + gap computation + board summary) is encapsulated inside the inner workflow per the locked node flow |
| APPI classification / legal basis / gap computation | LLM-based | Deterministic (Tool, KB rule lookup) | Deterministic | Per the design decision: classification is a rule-based KB lookup, not LLM inference — the LLM-essential value is the board-level narrative synthesis, which a rule-based template-fill cannot produce for a CFO/General Counsel audience |
| S-2 timing | Output-time PII scan only | Pre-LLM rejection invariant (before the LLM call) | Pre-LLM rejection | Design invariant: biometric/個人番号 patterns must be rejected before reaching the LLM step, not caught only at output |
| Scope | Full EU AI Act conformity | APPI 2026-primary + EU AI Act Annex III cross-reference annotation only | APPI-primary | Per the locked scope — full EU AI Act conformity documentation is out of scope |
| Node flow mapping | 7 separate nodes matching the initial workflow outline exactly | Combine InputValidate+SystemInventoryParse (pre_process); APPIClassify+LegalBasisCheck, GapReport+BoardSummaryFormat (inner) | Combined pairs | Each combined pair operates on the same input with no branching/retry boundary between them |
| Extract_input envelope | Multi-field JSON envelope | Forward `system_inventory` directly | Forward directly | `system_inventory` is already the complete payload the inner graph needs — no independent outer-classified field is lost across the GraphNode boundary |

## 1. Deployment entry points

The agent is reachable through two entry points, and both resolve their runtime inputs the same way.

| Entry point | File | Used by |
|---|---|---|
| Standalone HTTP | `src/api/server.py` | staging rehearsal, direct invocation |
| Marketplace one-shot Pod | `cli.py` | the platform runner (container `CMD`) |

Both read runtime parameters from `config/config.yaml` — the manifest carries discovery metadata
only — and both scope secrets to the same location (`namespace=ret`, `agent_name=ret-c2-584`), so a
secret provisioned for one path resolves identically on the other.

**Deployment-provided LLM client.** The three Azure OpenAI connection values
(`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` — the bare resource endpoint — and
`AZURE_OPENAI_DEPLOYMENT`) are resolved through the agent's own secret provider, never from the
process environment. Both entry points build the client only when all three resolve and pass it in
as `config["llm"]`; when any is absent the key stays unset and the graph keeps its deterministic
path. The manifest declares the three secrets and the provider extra.

**Progress events.** Each pipeline stage emits a non-terminal progress event at its start, so a
caller sees the run advancing. Outside the Marketplace runtime the emitter resolves to a no-op, so
the same code is safe on every path. Terminal events belong to the platform runner and are never
emitted by this agent.

**Caller authentication at the standalone entry point.** A caller that no upstream middleware
vouched for stays anonymous unless it presents a deployment-level credential: the external bearer
token grants the verified-external level, and a separate staging-only runner credential is the only
way to reach the internal level. Trust established upstream is never changed.
