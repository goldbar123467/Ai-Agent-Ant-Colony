# Example Data Files

This directory contains example data files demonstrating the various data formats used in Agent Ant Colony.

## Files

### rag_brain_memories.jsonl

20 example memories from the RAG Brain system, including:
- Patterns (React auth, API error handling, WebSocket feeds)
- Bug fixes (Tailwind purge, async context loss, revocation race)
- Decisions (LLM routing, constraint relaxation, quant safety)
- Outcomes (dashboard task, ML pipeline, trading bot)
- Insights (parallelism limits, feedback quality correlation)
- Code snippets (retry decorator)

### violations.jsonl

10 example communication law violations showing:
- Worker → Scribe (blocked)
- Cross-domain messaging (blocked)
- Worker → Queen bypass attempts (blocked)
- Agent revocation event

### agent_surveys.jsonl

9 example survey responses from different agent types:
- Queen's domain routing challenges
- Orchestrator's slicing dilemmas
- Workers' friction with constraints
- Wardens' merge conflict handling
- QA Reporter's quality observations
- Scribe's memory extraction insights

### task_flow_complete.json

Complete lifecycle of a single task showing all 7 phases:
1. Human submission
2. Queen analysis and routing
3. Orchestrator slicing (7 slices)
4. Worker execution (7 parallel outputs)
5. Warden validation
6. QA assessment
7. Scribe memory extraction

### human_alerts/

Example human alert file generated when an agent is revoked:
- `alert_worker12_revoked.json` - Full revocation record with violation history, pattern analysis, and recommended actions

## Usage

These files serve as:
- Documentation of data formats
- Test fixtures for development
- Templates for understanding system behavior

## Format Notes

- `.jsonl` files have one JSON object per line
- `.json` files are formatted for readability
- All timestamps are ISO 8601 UTC
- UUIDs are version 4

See `/docs/DATA_FORMATS.md` for complete schema documentation.
