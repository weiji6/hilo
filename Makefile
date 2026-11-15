.PHONY: help config install dev docker-start docker-stop docker-logs index-knowledge test export
COMPOSE = docker compose -p hilo -f docker/compose.hilo.yaml
PYTHON ?= python3

help:
	@echo "Hilo: config | install | dev | docker-start | docker-stop | index-knowledge | test | export"

config:
	$(PYTHON) scripts/init_config.py --example technical-docs

install:
	cd backend && uv sync --group dev
	cd frontend && pnpm install --frozen-lockfile

# Docker is the supported full-stack quick start (including auth DB and Qdrant).
dev: docker-start

docker-start:
	$(COMPOSE) up --build -d

docker-stop:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs --tail=100 -f

index-knowledge:
	$(COMPOSE) exec gateway python -m src.community.knowledge_base.indexer

test:
	cd backend && uv run pytest tests -q

export:
	$(PYTHON) scripts/export_open_source.py --output release/hilo
