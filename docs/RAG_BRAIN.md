# RAG Brain Memory System

The RAG Brain is the colony's persistent memory system. It stores learnings, patterns, failures, and insights that help agents improve over time.

## Overview

```
                    ┌─────────────────────┐
                    │     RAG Brain       │
                    │  (Memory Service)   │
                    └──────────┬──────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
  ┌───────────┐         ┌───────────┐         ┌───────────┐
  │  REMEMBER │         │  RECALL   │         │ FEEDBACK  │
  │  (Write)  │         │  (Read)   │         │ (Improve) │
  └───────────┘         └───────────┘         └───────────┘
        │                      │                      │
        ▼                      ▼                      ▼
  ┌───────────┐         ┌───────────┐         ┌───────────┐
  │ Gatekeeper│         │ Retrieval │         │ Feedback  │
  │  Quality  │         │  Ranking  │         │ Learning  │
  │   Check   │         │           │         │           │
  └───────────┘         └───────────┘         └───────────┘
```

## Memory Categories

| Category | Description | When Created |
|----------|-------------|--------------|
| `pattern` | Reusable approaches that worked well | High-confidence (>0.8) task completion |
| `bug_fix` | Problems encountered and solutions | Task failures or violations |
| `decision` | Strategic choices made by Queen/Orchestrators | Rule changes, escalations |
| `outcome` | Basic task completion records | Every completed task |
| `code_snippet` | Useful code patterns | Worker outputs with reusable code |
| `insight` | Cross-task observations | Scribe analysis of trends |
| `documentation` | Formatted reference material | Explicit documentation tasks |

## Quality Gating

Not all memories are stored. The Gatekeeper evaluates each memory:

### Feature Extraction

```python
features = {
    "content_length": len(content),
    "vocabulary_richness": unique_words / total_words,
    "has_code_blocks": bool(re.search(r'```', content)),
    "reasoning_words": count_of(['because', 'therefore', 'since'...]),
    "source_trust": trust_score_by_source,
}
```

### Quality Classification

- **XGBoost classifier** predicts quality 0.0-1.0
- Memories below **0.3 threshold** are rejected
- Rejection reasons provided for debugging

### Duplicate Detection

- Compute embedding of new memory
- Query existing memories with similarity > 0.95
- If match found: merge by appending, update metadata
- Prevents memory bloat (reduced 40% after implementation)

## Memory Structure

```json
{
  "id": "mem_001_pattern_react_auth",
  "category": "pattern",
  "content": "React Authentication Pattern: When implementing...",
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

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier |
| `category` | enum | Memory type (pattern, bug_fix, etc.) |
| `content` | string | The actual memory content |
| `tags` | list | Searchable tags for filtering |
| `project` | string | Project scope |
| `source` | string | Which agent created it |
| `quality_score` | float | Gatekeeper's quality assessment |
| `tier` | string | active, archived, or quarantined |
| `usefulness_score` | float | Computed from feedback |
| `retrieval_count` | int | How often recalled |

## API Endpoints

### Remember (Write)

```bash
POST /remember
{
  "content": "Pattern description...",
  "category": "pattern",
  "tags": ["web", "react"],
  "project": "/app",
  "source": "scribe",
  "metadata": {}
}

Response:
{
  "rejected": false,
  "memory_id": "mem_xxx",
  "quality_score": 0.87,
  "tier": "active"
}
```

### Recall (Read)

```bash
POST /recall
{
  "query": "React authentication patterns",
  "project": "/app",
  "tags": ["web"],
  "limit": 5
}

Response:
{
  "memories": [
    {
      "id": "mem_001",
      "content": "...",
      "similarity": 0.92,
      "usefulness_score": 0.88,
      "composite_score": 0.90
    }
  ]
}
```

### Feedback

```bash
POST /feedback
{
  "memory_id": "mem_001",
  "helpful": true,
  "context": "Used for auth implementation"
}
```

## Retrieval Scoring

When recalling memories, each result gets a composite score:

```
composite_score = (
    0.4 * similarity +
    0.3 * predicted_quality +
    0.3 * usefulness_score
)
```

- **similarity**: Semantic similarity to query (embedding cosine)
- **predicted_quality**: Gatekeeper's quality assessment
- **usefulness_score**: Accumulated from feedback

## Memory Lifecycle

```
┌─────────┐    Quality    ┌─────────┐    Feedback    ┌──────────┐
│  NEW    │──── Check ───▶│ ACTIVE  │───── Loop ────▶│ IMPROVED │
└─────────┘               └─────────┘                └──────────┘
     │                         │                          │
     │ Rejected                │ Low usage                │ High usage
     ▼                         ▼                          ▼
┌─────────┐               ┌──────────┐              ┌──────────┐
│ REJECTED│               │ ARCHIVED │              │ PROMOTED │
└─────────┘               └──────────┘              └──────────┘
```

### Tiers

- **active**: In rotation for retrieval
- **archived**: Older, rarely retrieved, still available
- **quarantined**: Poor quality, excluded from retrieval

## Retraining

Every 500 memories:

1. Collect memories with feedback
2. Split into helpful (positive) and not-helpful (negative)
3. Retrain XGBoost quality classifier
4. Update feature weights
5. Log training metrics

This makes the memory system **self-improving** - it learns what's actually useful.

## Agent Integration

### Scribe (Primary Writer)

```python
# After every QA report
memories = await extract_memories(task_record)
for memory in memories:
    result = await rag.remember(
        content=memory.content,
        category=memory.category,
        tags=memory.tags,
        project=task_record.project,
    )
```

### Orchestrator (Primary Reader)

```python
# Before slicing tasks
context = await rag.recall(
    query=f"{domain} patterns for {task_description}",
    tags=[domain, "pattern"],
    limit=5,
)

failures = await rag.get_failures(domain)
```

### All Agents

```python
# From SwarmAgent base class
await self.remember(content, category, tags)
memories = await self.recall(query, limit)
await self.feedback(memory_id, helpful=True)
```

## Example Memories

See `/data/examples/rag_brain_memories.jsonl` for 20 example memories including:

- React authentication pattern
- Tailwind CSS purge bug fix
- LLM model routing decision
- WebSocket connection pattern
- Async context loss bug fix
- And more...

## Monitoring

### Stats Endpoint

```bash
GET /stats?project=/app

{
  "total_memories": 1247,
  "by_category": {
    "pattern": 342,
    "bug_fix": 156,
    "outcome": 589,
    "decision": 78,
    "insight": 82
  },
  "by_tier": {
    "active": 1089,
    "archived": 134,
    "quarantined": 24
  },
  "average_quality": 0.76,
  "last_retraining": "2026-01-04T00:00:00Z"
}
```

## Best Practices

1. **Be Specific**: Vague memories get low quality scores
2. **Include Context**: Why something worked, not just what
3. **Tag Appropriately**: Domain + concept tags improve retrieval
4. **Provide Feedback**: Helps the system learn what's useful
5. **Check Before Writing**: Use recall to avoid duplicates
