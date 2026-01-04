.PHONY: start stop logs status clean build demo survey violations help

# Default target
help:
	@echo "Agent Ant Colony - Multi-Agent AI Swarm"
	@echo ""
	@echo "Usage:"
	@echo "  make start      - Start all services"
	@echo "  make stop       - Stop all services"
	@echo "  make logs       - Follow all logs"
	@echo "  make logs-queen - Follow Queen agent logs"
	@echo "  make status     - Show running containers"
	@echo "  make demo       - Run demo task"
	@echo "  make survey     - Run agent status survey"
	@echo "  make violations - Show communication violations"
	@echo "  make clean      - Stop and remove volumes"
	@echo "  make build      - Rebuild containers"
	@echo ""

# Initialize submodules if needed
init:
	@if [ ! -f services/agent-mail/README.md ]; then \
		echo "Initializing submodules..."; \
		git submodule update --init --recursive; \
	fi

# Start all services
start: init
	@echo "Starting Agent Ant Colony..."
	docker compose up -d
	@echo ""
	@echo "Services starting. Run 'make logs' to follow output."
	@echo "Run 'make status' to check container health."

# Stop all services
stop:
	@echo "Stopping Agent Ant Colony..."
	docker compose down

# Follow logs
logs:
	docker compose logs -f

logs-queen:
	docker compose logs -f queen

logs-workers:
	docker compose logs -f workers

logs-wardens:
	docker compose logs -f warden-web warden-ai warden-quant

# Show status
status:
	@echo "=== Agent Ant Colony Status ==="
	@echo ""
	@docker compose ps
	@echo ""
	@echo "=== Agent Count ==="
	@docker compose ps --format json 2>/dev/null | grep -c "running" || echo "0 running"

# Run demo task
demo:
	@echo "Running demo task..."
	python examples/demo.py

# Run status survey
survey:
	python tools/survey_cli.py

# Show violations
violations:
	python tools/violations_cli.py --stats

# Clean up everything
clean:
	@echo "Stopping and removing all data..."
	docker compose down -v
	@echo "Clean complete."

# Rebuild containers
build:
	docker compose build --no-cache

# Development helpers
shell-queen:
	docker compose exec queen /bin/bash

shell-workers:
	docker compose exec workers /bin/bash

# Quick restart of agents only (keeps infra)
restart-agents:
	docker compose restart queen scribe orch-web orch-ai orch-quant workers warden-web warden-ai warden-quant qa-reporter
