# Data Formats

This document describes all data formats used in Agent Ant Colony.

## Message Formats

### TaskAssignment (Queen → Orchestrator)

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "task": "Build an analytics dashboard with real-time charts",
  "domain": "web",
  "project": "/app",
  "priority": "normal",
  "context": {
    "project_profile": "React 18 app with Tailwind",
    "patterns": ["dashboard-pattern", "chart-pattern"],
    "failures_to_avoid": ["tailwind-purge-bug"]
  },
  "created_at": "2026-01-04T08:30:00.000Z"
}
```

### TaskSlice (Orchestrator → Worker)

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "slice_id": 3,
  "worker_id": 3,
  "task_type": "code",
  "description": "Create metric card component with label, value, and trend indicator",
  "assigned_file": "src/components/Dashboard/MetricCard.tsx",
  "constraints": {
    "can_do": [
      "Create card component",
      "Use shadcn Card",
      "Add trend arrow icons"
    ],
    "cannot_do": [
      "Calculate metrics",
      "Fetch data",
      "Add animations"
    ]
  },
  "context": {
    "patterns": ["..."],
    "failures": ["..."]
  },
  "created_at": "2026-01-04T08:30:28.112Z"
}
```

### WorkerOutput (Worker → Orchestrator)

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "worker_id": 3,
  "slice_id": 3,
  "task_type": "code",
  "deliverable": {
    "type": "file",
    "file_path": "src/components/Dashboard/MetricCard.tsx",
    "content": "export function MetricCard({ label, value }:..."
  },
  "metrics": {
    "tokens_used": 987,
    "duration_ms": 6543
  },
  "feedback": {
    "confidence": 0.93,
    "task_fit": 0.97,
    "clarity": 0.90,
    "context_quality": 0.85,
    "friction": null,
    "friction_detail": null,
    "suggestion": null,
    "blocked_by_rule": null,
    "would_change": null
  },
  "created_at": "2026-01-04T08:30:55.000Z"
}
```

### ValidationResult (Warden → QA Reporter)

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "worker_id": 3,
  "slice_id": 3,
  "status": "passed",
  "violations": [],
  "notes": "Clean implementation, follows patterns"
}
```

### MergedResult (Warden → QA Reporter)

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "domain": "web",
  "worker_outputs": ["... 7 WorkerOutput objects ..."],
  "validation_results": ["... 7 ValidationResult objects ..."],
  "conflicts": [],
  "merged_files": {
    "src/components/Dashboard/index.ts": "export * from './MetricCard';..."
  },
  "total_violations": 0,
  "created_at": "2026-01-04T08:31:22.889Z"
}
```

### QAReport (QA Reporter → Scribe)

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "domain": "web",
  "status": "passed",
  "test_results": {},
  "quality_score": 0.87,
  "issues": [
    "Sample data should be externalized"
  ],
  "recommendations": [
    "Add barrel export for Dashboard components"
  ],
  "duration_ms": 12334,
  "created_at": "2026-01-04T08:31:35.223Z"
}
```

## Constraint Envelope

Defines worker boundaries:

```json
{
  "can_do": [
    "Create assigned file",
    "Use Tailwind classes",
    "Import from designated modules",
    "Use shadcn components",
    "Add TypeScript types"
  ],
  "cannot_do": [
    "Modify files outside assignment",
    "Fetch data directly",
    "Install new packages",
    "Create database migrations",
    "Modify global styles"
  ]
}
```

## Feedback Block

**Mandatory** in every WorkerOutput:

```json
{
  "confidence": 0.85,
  "task_fit": 0.90,
  "clarity": 0.78,
  "context_quality": 0.82,
  "friction": "rule_too_strict",
  "friction_detail": "Cannot use external API even for development testing",
  "suggestion": "Allow internal API calls during development",
  "blocked_by_rule": "Cannot fetch data directly",
  "would_change": "Split this into smaller components"
}
```

### Friction Types

| Type | Description |
|------|-------------|
| `rule_too_strict` | Constraint blocks necessary work |
| `rule_unclear` | Constraint is ambiguous |
| `missing_context` | Need more information |
| `wrong_slice` | Task doesn't match specialization |
| `dependency_issue` | Blocked by another worker's output |
| `tooling_gap` | Missing required tool or library |
| `scope_too_big` | Slice is too large |
| `scope_too_small` | Slice is trivial |
| `ambiguous_request` | Instructions unclear |

## Violation Format

```json
{
  "timestamp": "2026-01-04T09:45:33.112Z",
  "sender_id": "Worker-12",
  "sender_role": "worker",
  "sender_domain": "ai",
  "recipient_id": "Queen",
  "recipient_role": "queen",
  "recipient_domain": null,
  "reason": "Workers cannot message Queen directly",
  "channel": "agent_mail",
  "message_preview": "[ESCALATION] Task too complex...",
  "violation_count": 1
}
```

## Memory Record

```json
{
  "id": "mem_001",
  "category": "pattern",
  "content": "Detailed pattern description...",
  "tags": ["web", "react", "authentication"],
  "project": "/app",
  "source": "scribe",
  "quality_score": 0.89,
  "tier": "active",
  "created_at": "2026-01-03T14:23:45Z",
  "usefulness_score": 0.92,
  "retrieval_count": 34
}
```

## Agent Status Report

Survey response format:

```json
{
  "agent_id": "Worker-7",
  "agent_role": "worker",
  "domain": "web_design",
  "survey_id": "survey_20260104_1400",
  "timestamp": "2026-01-04T14:03:15Z",
  "q1_tasks_clear": false,
  "q2_blockers_waiting": false,
  "q3_hardest_thing": "Types slice is always last but blocks others",
  "q4_suggestion": "Run types slice FIRST, not last",
  "q5_unexpected": "Nothing unexpected. Types work is predictable."
}
```

## Human Alert

Generated when agents are revoked:

```json
{
  "alert_type": "AGENT_REVOKED",
  "severity": "critical",
  "timestamp": "2026-01-04T10:33:45.445Z",
  "agent_id": "Worker-12",
  "agent_role": "worker",
  "agent_domain": "ai",
  "summary": "Worker-12 revoked after 3 violations",
  "violation_history": ["..."],
  "pattern_analysis": {
    "primary_issue": "Attempted hierarchy bypass",
    "possible_causes": ["..."]
  },
  "recommended_actions": ["..."],
  "impact": {
    "active_tasks_affected": 2,
    "domain_capacity_reduction": "14%"
  }
}
```

## Enums

### TaskType

```python
CODE = "code"
RESEARCH = "research"
PLANNING = "planning"
DESIGN = "design"
DEBUG = "debug"
DOCUMENTATION = "documentation"
CONVERSATION = "conversation"
ANALYSIS = "analysis"
```

### MemoryCategory

```python
DECISION = "decision"
PATTERN = "pattern"
BUG_FIX = "bug_fix"
OUTCOME = "outcome"
CODE_SNIPPET = "code_snippet"
INSIGHT = "insight"
DOCUMENTATION = "documentation"
```

### ValidationStatus

```python
PASSED = "passed"
FAILED = "failed"
VIOLATION = "violation"
```

### QAStatus

```python
PASSED = "passed"
FAILED = "failed"
PARTIAL = "partial"
BLOCKED = "blocked"
```

## File Locations

| File | Format | Description |
|------|--------|-------------|
| `violations.jsonl` | JSONL | Communication violations |
| `agent_surveys.jsonl` | JSONL | Status survey responses |
| `rag_brain_memories.jsonl` | JSONL | Memory records |
| `human_alerts/*.json` | JSON | Critical alerts |
| `revoked_agents.json` | JSON | Revoked agent registry |

See `/data/examples/` for sample files.
