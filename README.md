# Agent Ant Colony

A hierarchical multi-agent AI swarm with 30+ coordinated agents for complex task execution.

```
                              QUEEN
                        Strategic Command
                              |
          +-------------------+-------------------+
          |                   |                   |
      ORCH-WEB            ORCH-AI           ORCH-QUANT
    Task Slicing        Task Slicing        Task Slicing
          |                   |                   |
    +-----+-----+       +-----+-----+       +-----+-----+
    | Workers   |       | Workers   |       | Workers   |
    | 1-7       |       | 8-14      |       | 15-21     |
    +-----+-----+       +-----+-----+       +-----+-----+
          |                   |                   |
     WARDEN-WEB          WARDEN-AI         WARDEN-QUANT
     Validation          Validation          Validation
          |                   |                   |
          +-------------------+-------------------+
                              |
                        QA REPORTER
                    Quality Assessment
                              |
                          SCRIBE
                      Memory Writer
```

## Quick Start

```bash
# Clone with submodules
git clone --recursive https://github.com/YOUR_USERNAME/agent-ant-colony.git
cd agent-ant-colony

# Configure
cp .env.example .env
# Edit .env and add your OPENROUTER_API_KEY

# Start everything
make start

# Watch the colony work
make logs
```

## Features

- **Hierarchical Control** - Queen directs strategy, Orchestrators slice tasks, Workers execute
- **Domain Specialization** - Web, AI, and Quant domains with dedicated pipelines
- **Parallel Execution** - 7 workers per domain process tasks concurrently
- **Constraint Enforcement** - Can-do/cannot-do rules prevent scope creep
- **Self-Improving** - Friction feedback evolves rules over time
- **Memory System** - RAG-based learning from task outcomes
- **Communication Laws** - Hierarchical messaging enforcement

## Architecture

### Agent Roles

| Agent | Role | Count |
|-------|------|-------|
| Queen | Strategic command, task assignment | 1 |
| Orchestrator | Task slicing by domain | 3 |
| Worker | Task execution | 21 |
| Warden | Validation and quality gates | 3 |
| QA Reporter | Quality assessment and reporting | 1 |
| Scribe | Memory persistence | 1 |

### Communication Flow

1. **Human** submits task to **Queen**
2. **Queen** analyzes and assigns to domain **Orchestrator**
3. **Orchestrator** slices into 7 parallel sub-tasks
4. **Workers** execute with constraints
5. **Warden** validates outputs
6. **QA Reporter** assesses quality
7. **Scribe** records learnings to memory

### Services

- **Agent Mail** - Inter-agent messaging system
- **RAG Brain** - Vector memory with semantic search
- **Bridge** - Real-time coordination signals

## Configuration

### Required

```env
OPENROUTER_API_KEY=your_key_here
```

### Optional

```env
PROJECT_KEY=/app              # Project identifier
POSTGRES_USER=postgres        # Database user
POSTGRES_PASSWORD=postgres    # Database password
```

## Usage

### Make Commands

```bash
make start      # Start all services
make stop       # Stop all services
make logs       # Follow all logs
make status     # Show running containers
make demo       # Run example task
make survey     # Agent status survey
make violations # Communication violations
make clean      # Remove all data
```

### Submit a Task

```python
import httpx

# Send task to Queen via Agent Mail
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

### Monitor Progress

```bash
# Watch Queen's decisions
make logs-queen

# Watch worker execution
make logs-workers

# Check for rule violations
make violations
```

## Project Structure

```
agent-ant-colony/
├── src/
│   ├── shared/           # Core utilities
│   │   ├── config.py     # Configuration
│   │   ├── llm_client.py # LLM interface
│   │   ├── agent_mail.py # Messaging client
│   │   ├── bridge.py     # Real-time signals
│   │   ├── rag_client.py # Memory client
│   │   ├── base_agent.py # Agent base class
│   │   ├── schemas.py    # Data models
│   │   └── comm_laws.py  # Communication rules
│   │
│   ├── queen/            # Strategic commander
│   ├── orchestrator/     # Task slicing
│   ├── worker/           # Task execution
│   ├── warden/           # Validation
│   ├── scribe/           # Memory writer
│   └── qa_reporter/      # Quality assessment
│
├── services/
│   ├── agent-mail/       # Messaging (submodule)
│   └── rag-brain/        # Memory (submodule)
│
├── tools/                # CLI utilities
├── examples/             # Demo scripts
└── docs/                 # Documentation
```

## Communication Laws

Agents follow strict hierarchical communication rules:

| From | Can Message |
|------|-------------|
| Queen | Orchestrators, Scribe, QA Reporter |
| Orchestrator | Workers in same domain, Warden |
| Worker | Orchestrator (same domain only) |
| Warden | Orchestrator, QA Reporter |
| QA Reporter | Queen, Scribe |

Violations are logged and can trigger agent revocation.

## Development

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest

# Run single agent
python -m src.queen.agent
```

### Adding a New Agent

1. Create agent module in `src/`
2. Inherit from `SwarmAgent` base class
3. Implement `process_message()` handler
4. Add to `docker-compose.yml`
5. Update communication laws if needed

## License

MIT License - see [LICENSE](LICENSE)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Submit a pull request

---

Built with AI agents coordinating AI agents.
