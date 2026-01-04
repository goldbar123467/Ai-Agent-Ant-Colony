# Quick Start Guide

Get Agent Ant Colony running in 5 minutes.

## Prerequisites

- Docker and Docker Compose
- Git
- OpenRouter API key ([get one here](https://openrouter.ai/keys))

## Installation

### 1. Clone the Repository

```bash
git clone --recursive https://github.com/YOUR_USERNAME/agent-ant-colony.git
cd agent-ant-colony
```

The `--recursive` flag is important - it pulls the Agent Mail and RAG Brain submodules.

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your OpenRouter API key:

```env
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

### 3. Start the Colony

```bash
make start
```

This starts:
- PostgreSQL with pgvector
- Agent Mail messaging service
- RAG Brain memory service
- All 30 swarm agents

### 4. Verify Everything is Running

```bash
make status
```

You should see all services running:
```
NAME                STATUS
postgres            running (healthy)
agent-mail          running (healthy)
rag-brain           running (healthy)
queen               running
scribe              running
orch-web            running
orch-ai             running
orch-quant          running
workers             running
warden-web          running
warden-ai           running
warden-quant        running
qa-reporter         running
```

## Your First Task

### Option 1: Use the Demo Script

```bash
make demo
```

### Option 2: Submit via curl

```bash
curl -X POST http://localhost:8765/send \
  -H "Content-Type: application/json" \
  -d '{
    "from_agent": "Human",
    "to_agent": "Queen",
    "project": "/app",
    "message_type": "TaskAssignment",
    "payload": {
      "body": "Create a Python function to validate email addresses"
    }
  }'
```

### Option 3: Submit via Python

```python
import httpx

response = httpx.post("http://localhost:8765/send", json={
    "from_agent": "Human",
    "to_agent": "Queen",
    "project": "/app",
    "message_type": "TaskAssignment",
    "payload": {
        "body": "Create a Python function to validate email addresses"
    }
})

print(response.json())
```

## Watching the Colony Work

### Follow All Logs

```bash
make logs
```

### Follow Specific Agents

```bash
# Queen's strategic decisions
docker compose logs -f queen

# Worker execution
docker compose logs -f workers

# Validation
docker compose logs -f warden-web warden-ai warden-quant
```

### Monitor Communication Violations

```bash
make violations
```

## Common Operations

### Stop the Colony

```bash
make stop
```

### Restart Agents (Keep Data)

```bash
make restart-agents
```

### Full Reset (Delete All Data)

```bash
make clean
```

### Rebuild After Code Changes

```bash
make build
make start
```

## Troubleshooting

### Agents Not Connecting

Check if infrastructure services are healthy:

```bash
docker compose ps postgres agent-mail rag-brain
```

If not healthy, check logs:

```bash
docker compose logs postgres agent-mail rag-brain
```

### "API Key Invalid" Errors

Verify your `.env` file has the correct key:

```bash
cat .env | grep OPENROUTER
```

### Workers Not Receiving Tasks

Check Orchestrator logs:

```bash
docker compose logs orch-web orch-ai orch-quant
```

### High Memory Usage

The default configuration runs 30 agents. For limited resources:

```bash
# Scale down workers
docker compose up -d --scale workers=0

# Run workers manually with fewer instances
docker compose run workers python -m src.worker.agent --id 1
```

## Next Steps

1. Read [ARCHITECTURE.md](ARCHITECTURE.md) to understand the system
2. Explore `src/` to see agent implementations
3. Modify communication laws in `src/shared/comm_laws.py`
4. Add new agent types by extending `SwarmAgent`

## Support

- Check logs: `make logs`
- View violations: `make violations`
- Agent status: `make survey`
