# Architecture

## Overview

Agent Ant Colony implements a hierarchical multi-agent system where specialized agents coordinate to complete complex tasks. The architecture enforces strict communication laws, domain specialization, and quality gates.

## Agent Hierarchy

```
Level 0: Human (External)
    │
Level 1: Queen (Strategic Command)
    │
Level 2: Orchestrators (Task Decomposition)
    ├── Orch-Web (Web domain)
    ├── Orch-AI (AI domain)
    └── Orch-Quant (Quantitative domain)
    │
Level 3: Workers (Task Execution)
    ├── Workers 1-7 (Web)
    ├── Workers 8-14 (AI)
    └── Workers 15-21 (Quant)
    │
Level 4: Wardens (Validation)
    ├── Warden-Web
    ├── Warden-AI
    └── Warden-Quant
    │
Level 5: QA Reporter (Quality Assessment)
    │
Level 6: Scribe (Memory Persistence)
```

## Agent Roles

### Queen

The Queen is the strategic commander:
- Receives tasks from humans
- Analyzes task requirements
- Assigns to appropriate domain Orchestrator
- Makes escalation decisions
- Evolves system rules based on feedback

### Orchestrator

Three Orchestrators handle domain-specific task decomposition:
- **Orch-Web**: Frontend, APIs, web services
- **Orch-AI**: Machine learning, LLM integration
- **Orch-Quant**: Data analysis, algorithms, trading

Each Orchestrator:
- Slices tasks into 7 parallel sub-tasks
- Assigns constraints (can-do/cannot-do)
- Coordinates worker execution
- Aggregates results

### Worker

21 Workers execute atomic tasks:
- 7 per domain (Web: 1-7, AI: 8-14, Quant: 15-21)
- Follow constraint envelopes strictly
- Report friction when constraints block progress
- Return structured deliverables

### Warden

Three Wardens validate domain outputs:
- Verify constraints were followed
- Check deliverable quality
- Flag violations
- Monitor for anomalies

### QA Reporter

Single QA Reporter assesses overall quality:
- Aggregates warden reports
- Calculates quality scores
- Identifies patterns
- Reports to Queen

### Scribe

Single Scribe manages memory:
- Records task outcomes
- Stores learnings in RAG Brain
- Maintains audit trail
- Enables system learning

## Communication Laws

### Allowed Communications

```
Queen → Orchestrators (any)
Queen → Scribe
Queen → QA Reporter

Orchestrator → Workers (same domain only)
Orchestrator → Warden (same domain)

Worker → Orchestrator (same domain only)

Warden → Orchestrator (same domain)
Warden → QA Reporter

QA Reporter → Queen
QA Reporter → Scribe

Scribe → (no outbound messages)
```

### Violation Handling

1. Attempted violations are blocked
2. Violations are logged to `violations.jsonl`
3. Repeat offenders can be revoked
4. Human alerts generated for critical violations

## Task Flow

### Standard Flow

```
1. Human → Queen: Submit task
2. Queen analyzes, determines domain
3. Queen → Orchestrator: Assign task with context
4. Orchestrator decomposes into 7 slices
5. Orchestrator → Workers: Distribute slices with constraints
6. Workers execute in parallel
7. Workers → Orchestrator: Return outputs
8. Orchestrator → Warden: Submit for validation
9. Warden validates, flags issues
10. Warden → QA Reporter: Send validation result
11. QA Reporter → Queen: Quality assessment
12. QA Reporter → Scribe: Record outcome
13. Scribe → RAG Brain: Persist memory
```

### Escalation Flow

When workers encounter friction:

```
1. Worker reports friction to Orchestrator
2. Orchestrator aggregates friction reports
3. If friction > threshold:
   - Orchestrator → Queen: Escalation request
4. Queen decides:
   - Adjust constraints
   - Reassign task
   - Request human input
```

## Services

### Agent Mail

REST API for inter-agent messaging:
- `POST /send` - Send message
- `GET /messages` - Fetch inbox
- `POST /register` - Register agent

### RAG Brain

Vector memory with semantic search:
- `POST /store` - Store memory
- `POST /query` - Semantic search
- `GET /health` - Health check

### Bridge

Lightweight real-time coordination:
- Pub/sub signals
- Heartbeat monitoring
- Status broadcasts

## Data Models

### TaskAssignment

```python
{
    "task_id": "uuid",
    "description": "string",
    "constraints": {
        "can_do": ["list of allowed actions"],
        "cannot_do": ["list of forbidden actions"]
    },
    "deadline": "iso8601",
    "priority": "high|normal|low"
}
```

### TaskSlice

```python
{
    "slice_id": "uuid",
    "parent_task_id": "uuid",
    "worker_id": "Worker-N",
    "description": "string",
    "constraints": {...},
    "context": "string"
}
```

### WorkerOutput

```python
{
    "slice_id": "uuid",
    "deliverables": [...],
    "metrics": {
        "confidence": 0.0-1.0,
        "tokens_used": int
    },
    "friction": [...],
    "status": "complete|blocked|failed"
}
```

### ValidationResult

```python
{
    "task_id": "uuid",
    "status": "approved|rejected|needs_revision",
    "violations": [...],
    "score": 0.0-1.0,
    "feedback": "string"
}
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENROUTER_API_KEY` | LLM API key | Required |
| `PROJECT_KEY` | Project identifier | `/app` |
| `AGENT_MAIL_URL` | Messaging service | `http://agent-mail:8765` |
| `RAG_BRAIN_URL` | Memory service | `http://rag-brain:8000` |

### LLM Models

| Agent | Model | Reason |
|-------|-------|--------|
| Queen | Claude/GPT-4 | Strategic reasoning |
| Orchestrator | Claude/GPT-4 | Task decomposition |
| Worker | DeepSeek | Cost-effective execution |
| Warden | DeepSeek | Validation checks |
| QA Reporter | DeepSeek | Quality scoring |
| Scribe | DeepSeek | Memory formatting |

## Scaling

### Horizontal Scaling

- Workers can be scaled per domain
- Multiple instances share workload via Agent Mail
- State managed in PostgreSQL

### Resource Requirements

| Service | CPU | Memory |
|---------|-----|--------|
| PostgreSQL | 1 core | 1GB |
| Agent Mail | 0.5 core | 256MB |
| RAG Brain | 0.5 core | 512MB |
| Each Agent | 0.25 core | 256MB |

Total: ~4 cores, 4GB RAM for full colony
