# Agent Ant Colony

**A hierarchical multi-agent AI swarm with 30+ coordinated agents**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com/)

```
                                    +-----------+
                                    |   HUMAN   |
                                    +-----+-----+
                                          |
                                          v
                              +-----------+-----------+
                              |         QUEEN         |
                              |   Strategic Command   |
                              |   Task Assignment     |
                              +-----------+-----------+
                                          |
            +-----------------------------+-----------------------------+
            |                             |                             |
            v                             v                             v
    +-------+-------+             +-------+-------+             +-------+-------+
    |   ORCH-WEB    |             |   ORCH-AI     |             |  ORCH-QUANT   |
    | Task Slicing  |             | Task Slicing  |             | Task Slicing  |
    | React/TS/CSS  |             | ML/LLM/RAG    |             | Trading/Algo  |
    +-------+-------+             +-------+-------+             +-------+-------+
            |                             |                             |
    +-------+-------+             +-------+-------+             +-------+-------+
    | Workers 1-7   |             | Workers 8-14  |             | Workers 15-21 |
    | 7 Specialists |             | 7 Specialists |             | 7 Specialists |
    | Parallel Exec |             | Parallel Exec |             | Parallel Exec |
    +-------+-------+             +-------+-------+             +-------+-------+
            |                             |                             |
            v                             v                             v
    +-------+-------+             +-------+-------+             +-------+-------+
    |  WARDEN-WEB   |             |  WARDEN-AI    |             | WARDEN-QUANT  |
    |  Validation   |             |  Validation   |             |  Validation   |
    |  Merge Output |             |  Merge Output |             |  Merge Output |
    +-------+-------+             +-------+-------+             +-------+-------+
            |                             |                             |
            +-----------------------------+-----------------------------+
                                          |
                                          v
                              +-----------+-----------+
                              |      QA REPORTER      |
                              |  Quality Assessment   |
                              |  Score 0.0 - 1.0      |
                              +-----------+-----------+
                                          |
                                          v
                              +-----------+-----------+
                              |        SCRIBE         |
                              |    Memory Writer      |
                              |    RAG Persistence    |
                              +-----------------------+
```

---

## One-Shot Startup

```bash
# Clone with submodules
git clone --recursive https://github.com/goldbar123467/Ai-Agent-Ant-Colony.git
cd Ai-Agent-Ant-Colony

# Configure (add your OpenRouter API key)
cp .env.example .env && nano .env

# Start the colony (30+ agents)
make start

# Watch them work
make logs
```

**That's it.** The entire colony starts in Docker with a single command.

---

## What Is This?

Agent Ant Colony is a **hierarchical multi-agent system** where 30+ AI agents coordinate to complete complex tasks. Unlike flat multi-agent architectures, this system enforces:

- **Strict communication laws** - agents can only message specific roles
- **Agent mortality** - 3 rule violations = permanent death
- **Constraint envelopes** - explicit can-do/cannot-do rules per worker
- **Self-improving rules** - friction feedback evolves constraints over time

The result: predictable, observable, self-improving AI coordination.

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Hierarchical Control** | Queen directs Orchestrators, who manage Workers. Clear chain of command. |
| **Communication Laws** | Agents can only message allowed roles. Violations are blocked and logged. |
| **Agent Mortality** | 3 communication violations = agent is permanently revoked ("killed"). |
| **Constraint Envelopes** | Each worker gets explicit can-do/cannot-do lists. No ambiguity. |
| **Friction Feedback** | Workers report when constraints block necessary work. Rules adapt. |
| **Domain Specialization** | Web (React/Tailwind), AI (ML/LLM), Quant (Trading/Algo) |
| **Parallel Execution** | 7 workers per domain execute simultaneously |
| **Quality-Gated Memory** | RAG system rejects poor-quality memories. Learns what's useful. |
| **Dual Messaging** | Agent Mail (formal, persistent) + Bridge (ephemeral, fast) |

---

## Agent Roles

| Agent | Role | Count | Description |
|-------|------|-------|-------------|
| **Queen** | Strategic Command | 1 | Receives tasks, determines domain, assigns to Orchestrators |
| **Orchestrator** | Task Slicing | 3 | Decomposes tasks into 7 parallel slices with constraints |
| **Worker** | Task Execution | 21 | Executes slices respecting constraint envelopes |
| **Warden** | Validation | 3 | Validates outputs, detects violations, merges results |
| **QA Reporter** | Quality Assessment | 1 | Scores quality 0-1, identifies issues |
| **Scribe** | Memory Writer | 1 | Extracts learnings, persists to RAG Brain |

**Total: 30 agents** (+ infrastructure services)

---

## How It Works

```
1. HUMAN submits task
   └─> "Build a React dashboard with authentication"

2. QUEEN analyzes task
   └─> Determines domain: "web"
   └─> Assigns to: Orch-Web

3. ORCH-WEB slices into 7 parallel tasks
   └─> Worker 1: Layout shell and routing
   └─> Worker 2: Navigation and header
   └─> Worker 3: Dashboard components
   └─> Worker 4: Auth forms
   └─> Worker 5: Data visualization
   └─> Worker 6: Styles and theme
   └─> Worker 7: Types and utilities

4. WORKERS 1-7 execute in parallel
   └─> Each respects constraint envelope
   └─> Reports friction if blocked
   └─> Returns deliverable + feedback

5. WARDEN-WEB validates
   └─> Checks constraint compliance
   └─> Detects conflicts between outputs
   └─> Merges into unified result

6. QA REPORTER assesses
   └─> Scores: completeness, correctness, code quality
   └─> Returns quality_score: 0.87

7. SCRIBE records memories
   └─> High confidence (>0.8) → Pattern
   └─> Failures → Bug fix record
   └─> All tasks → Outcome record
```

---

## Q&A

### Getting Started

<details>
<summary><strong>What do I need to run this?</strong></summary>

- Docker and Docker Compose
- Git
- An OpenRouter API key ([get one here](https://openrouter.ai/keys))

That's it. Everything else runs in containers.
</details>

<details>
<summary><strong>How do I submit a task to the colony?</strong></summary>

Via Agent Mail REST API:

```python
import httpx

response = httpx.post("http://localhost:8765/send", json={
    "from_agent": "Human",
    "to_agent": "Queen",
    "project": "/app",
    "message_type": "TaskAssignment",
    "payload": {
        "body": "Build a REST API with user authentication"
    }
})
```

Or use the demo script: `make demo`
</details>

<details>
<summary><strong>How do I monitor the colony?</strong></summary>

```bash
make logs          # All agent logs
make logs-queen    # Queen's decisions
make logs-workers  # Worker execution
make status        # Container health
make violations    # Communication law violations
make survey        # Agent status survey
```
</details>

### Architecture

<details>
<summary><strong>Why 30+ agents? Isn't that overkill?</strong></summary>

It's not about scale - it's about **specialization**.

- 21 workers = 7 per domain × 3 domains
- Each worker has a specific role (layout specialist, navigation specialist, etc.)
- All 7 execute in **parallel** without dependencies
- Warden per domain = validation without bottleneck

The architecture prevents:
- Single-point-of-failure
- Context window exhaustion
- Cross-domain confusion
</details>

<details>
<summary><strong>What are the three domains?</strong></summary>

| Domain | Focus | Workers | Constraints Example |
|--------|-------|---------|---------------------|
| **Web** | React, TypeScript, Tailwind, CSS | 1-7 | Can use shadcn; Cannot fetch data directly |
| **AI** | ML, LLMs, RAG, Embeddings | 8-14 | Can call LLM clients; Cannot hardcode API keys |
| **Quant** | Trading, Algorithms, Data | 15-21 | Can use websockets; Cannot execute real trades |

Domain is determined by the Queen based on task content.
</details>

<details>
<summary><strong>How do communication laws work?</strong></summary>

Each role has explicit `allowed_send_to` and `allowed_receive_from` rules:

```
Queen     → Orchestrators, Scribe, QA Reporter
Orchestr  → Workers (same domain), Warden (same domain)
Worker    → Orchestrator (same domain only)
Warden    → Orchestrator, QA Reporter
QA Report → Queen, Scribe
Scribe    → (no outbound)
```

Messages violating these rules are **blocked at send time** and logged to `violations.jsonl`.
</details>

<details>
<summary><strong>What happens if an agent breaks the rules?</strong></summary>

1. **First violation**: Blocked and logged
2. **Second violation**: Warning injected into agent's system prompt
3. **Third violation**: Agent is **permanently revoked** (killed)

Revoked agents:
- Cannot process messages
- Receive "YOU ARE DEAD" in their prompt
- Generate human alert files for review
- Death is announced publicly to all agents

This creates genuine behavioral incentive for rule compliance.
</details>

### Technical

<details>
<summary><strong>What LLM models are used?</strong></summary>

Configurable via OpenRouter:

| Agent Type | Recommended Model | Why |
|------------|-------------------|-----|
| Queen | Claude/GPT-4 | Strategic reasoning |
| Orchestrator | Claude/GPT-4 | Task decomposition |
| Workers | DeepSeek | Cost-effective execution |
| Wardens | DeepSeek | Validation checks |
| QA Reporter | DeepSeek | Quality scoring |
| Scribe | DeepSeek | Memory formatting |

Configure in `.env` or `src/shared/config.py`.
</details>

<details>
<summary><strong>How does the constraint system work?</strong></summary>

Each worker receives a **ConstraintEnvelope**:

```python
{
    "can_do": [
        "Create assigned file",
        "Use Tailwind classes",
        "Import from designated modules"
    ],
    "cannot_do": [
        "Modify files outside assignment",
        "Fetch data directly",
        "Install new packages"
    ]
}
```

Workers must respect these constraints. If blocked:
1. Worker reports **friction** with type (RULE_TOO_STRICT, MISSING_CONTEXT, etc.)
2. Orchestrator accumulates friction reports
3. After 25+ reports, proposes **rule adjustment**
4. Minor relaxations auto-apply; major changes escalate to Queen
</details>

<details>
<summary><strong>How does the memory system learn?</strong></summary>

The RAG Brain doesn't just store everything:

1. **Gatekeeper** extracts features: vocabulary richness, code blocks, reasoning words
2. **XGBoost classifier** predicts quality score 0-1
3. Memories below threshold (0.3) are **rejected**
4. Duplicate detection merges similar memories
5. Every 500 memories, system **retrains** based on what was actually helpful

Result: Memory system becomes smarter over time.
</details>

<details>
<summary><strong>Can I add my own agents?</strong></summary>

Yes:

1. Create module in `src/your_agent/`
2. Inherit from `SwarmAgent` base class
3. Implement `process_message()` handler
4. Add to `docker-compose.yml`
5. Update communication laws in `src/shared/comm_laws.py`

See `src/shared/base_agent.py` for the interface.
</details>

### Comparison

<details>
<summary><strong>How is this different from AutoGPT/CrewAI/LangGraph?</strong></summary>

| Aspect | Other Systems | Agent Ant Colony |
|--------|---------------|------------------|
| Communication | Free-form, any agent can message any other | Strict hierarchical laws, violations blocked |
| Agent Lifecycle | Persistent until stopped | Agents can **die** after 3 violations |
| Constraints | Suggestions or prompts | Explicit can-do/cannot-do, validated by Warden |
| Learning | Static or external | Self-improving via friction feedback |
| Parallelism | Often pipelined | True parallel (7 workers execute simultaneously) |
| Memory | Store everything | Quality-gated, rejects poor memories |

**Key differentiator**: Agent Ant Colony makes consequences **real**. Violations have teeth. Rules evolve. Agents can die.
</details>

<details>
<summary><strong>Why hierarchical instead of flat?</strong></summary>

Flat multi-agent systems suffer from:
- **Decision paralysis**: Who decides when agents disagree?
- **Context explosion**: Every agent needs to know about every other
- **Unpredictable messaging**: Hard to debug, hard to observe

Hierarchy provides:
- **Clear escalation path**: Worker → Orchestrator → Queen
- **Bounded context**: Workers only know their domain
- **Predictable flow**: Messages follow defined paths
- **Observability**: You know exactly where to look
</details>

### Troubleshooting

<details>
<summary><strong>Why are agents failing to start?</strong></summary>

1. **Check infrastructure health**:
   ```bash
   docker compose ps postgres agent-mail rag-brain
   ```

2. **Verify API key**:
   ```bash
   grep OPENROUTER .env
   ```

3. **Check logs**:
   ```bash
   docker compose logs agent-mail rag-brain
   ```

4. **Restart with rebuild**:
   ```bash
   make clean && make build && make start
   ```
</details>

<details>
<summary><strong>How do I debug communication issues?</strong></summary>

1. **Check violations**:
   ```bash
   make violations
   ```

2. **Watch specific agent**:
   ```bash
   docker compose logs -f queen
   ```

3. **Check Agent Mail directly**:
   ```bash
   curl http://localhost:8765/messages?agent_name=Queen&project=/app
   ```

4. **Review communication laws**: `src/shared/comm_laws.py`
</details>

<details>
<summary><strong>Why is memory not being saved?</strong></summary>

1. **Check Scribe logs**:
   ```bash
   docker compose logs scribe
   ```

2. **Verify RAG Brain health**:
   ```bash
   curl http://localhost:8000/health
   ```

3. **Quality too low**: Gatekeeper rejects memories below 0.3 quality score. Check if outputs lack substance.
</details>

---

## Make Commands

```bash
make start          # Start all services
make stop           # Stop all services
make logs           # Follow all logs
make logs-queen     # Follow Queen logs
make logs-workers   # Follow worker logs
make status         # Show container status
make demo           # Run example task
make survey         # Agent status survey
make violations     # Communication violations
make clean          # Stop and remove volumes
make build          # Rebuild containers
make restart-agents # Restart agents (keep data)
```

---

## Project Structure

```
agent-ant-colony/
├── src/
│   ├── queen/              # Strategic commander
│   ├── orchestrator/       # Task slicing (3 domains)
│   ├── worker/             # Task execution (21 workers)
│   │   ├── agent.py        # Worker implementation
│   │   └── manager.py      # Runs all 21 workers
│   ├── warden/             # Validation (3 domains)
│   ├── scribe/             # Memory writer
│   ├── qa_reporter/        # Quality assessment
│   └── shared/             # Core utilities
│       ├── config.py       # Configuration
│       ├── comm_laws.py    # Communication rules
│       ├── agent_mail.py   # Messaging client
│       ├── rag_client.py   # Memory client
│       ├── bridge.py       # Real-time signals
│       ├── base_agent.py   # Agent base class
│       └── schemas.py      # Data models
├── services/
│   ├── agent-mail/         # Messaging (submodule)
│   └── rag-brain/          # Memory (submodule)
├── tools/
│   ├── survey_cli.py       # Status surveys
│   └── violations_cli.py   # Compliance monitor
├── examples/
│   └── demo.py             # Example task
└── docs/
    ├── ARCHITECTURE.md     # Detailed architecture
    └── QUICKSTART.md       # Setup guide
```

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

MIT License - see [LICENSE](LICENSE)

---

<p align="center">
  <strong>Built with AI agents coordinating AI agents.</strong>
</p>
