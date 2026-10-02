# RET-C2-584 — Test Specification

## Test Strategy

Deterministic-core: no LLM required, full suite runs offline. Board
summary synthesis accepts an optional `llm` client and falls back to
deterministic reasoning when absent.

## Unit Tests (`tests/unit/test_nodes.py`)

| Node | Cases |
|---|---|
| InputValidateSystemInventoryParseNode | success (valid inventory parsed); empty user_input→ERROR; biometric marker present→ERROR (S-2 pre-LLM invariant); not a JSON array→ERROR; no valid entries→ERROR |
| APPIClassifyLegalBasisCheckNode | success (biometric system classified + Art.17 consent basis); success (standard system, default legal basis); missing system_inventory→ERROR |
| GapReportBoardSummaryFormatNode | success (high-severity gap flagged for missing legal basis); success (no gap when control implemented); missing classified_systems→ERROR |
| OutputValidateNode | success (compliant report); raw PII/biometric data present→ERROR (non-suppressible hook) |

## Integration Tests (`tests/integration/test_graph.py`)

| ID | Test | Expected |
|---|---|---|
| I-1 | system inventory with a biometric system lacking consent | pipeline completes (≥4 nodes); report flags a high-severity gap |
| I-2 | system inventory with all controls implemented | pipeline completes; report shows no high-severity gaps |
| I-3 | empty user_input | ERROR |
| I-4 | input containing a biometric-data marker | ERROR (S-2 pre-LLM rejection) |

> Per the S-2 gate's effect on the success path, integration tests
> assert pipeline-completion invariants rather than an exact terminal status
> for success cases — unit tests already pin the success-path logic
> deterministically.

## Proof-of-Boundary Tests (`tests/proof_of_boundary/`)

| PB-ID | Boundary | Test | Expected Result |
|-------|----------|------|----------------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations |
| PB-5 | Checkpoint safety | No JWT/Pydantic in checkpoint | Inspection pass |
| PB-6 | Invoke execution order | S-1 → node_start → S-2 → execute → S-3 → node_complete | Order verified |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result |
|-------|------|-------|----------------|
| BL-01 | S-2 pre-LLM biometric rejection | input contains "face recognition data:" marker | rejected before reaching the board-summary LLM step |
| BL-02 | biometric APPI category | system claims biometric data category | appi_category=biometric, required_legal_basis=Art.17 consent |
| BL-03 | high-severity gap on missing legal basis | biometric system with no implemented_controls | severity=H |
| BL-04 | no gap when control implemented | system with required legal basis in implemented_controls | gap=False |

## Non-suppressible output tests (critical)

- `formatted_report` must never contain raw customer PII or biometric
  data (unit + I-1/I-2 + BL-01).
- The post_process S-3 hook re-checks `formatted_report`'s own field only
  (S-3 hook self-consistency rule) — never cross-references separate
  state fields read independently.

## Test Execution Summary
- Execution date: 2026-07-08
- Total tests: see CI `run-tests` job output
- Coverage: deterministic-core, no LLM dependency

## 1. Deployment path tests

### TC-DEP-01 Marketplace entry point identity — `tests/unit/test_cli_entry_point.py`

| Case | Expected |
|---|---|
| Identity is concrete | `agent_name` / `namespace` are non-empty and not the runner default |
| Identity matches the HTTP entry point | the values equal what `src/api/server.py` passes to `secrets_factory`; where that entry point provisions no secrets, they equal the manifest `namespace` and the lower-cased template id |
| The runner call uses the constants | `run_agent_marketplace` is called with the module constants, not inline literals |

### TC-DEP-02 Standalone entry point boundary — `tests/proof_of_boundary/test_server_llm_injection.py`

| Case | Expected |
|---|---|
| Boots with no credential provisioned | the module imports and the app/agent objects are constructed |
| External bearer never reaches the internal level | resolves to the verified-external level |
| Staging runner credential reaches the internal level | resolves to the internal level |
| Wrong or missing bearer while auth is enabled | rejected with 401 |
