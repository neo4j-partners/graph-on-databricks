.PHONY: install test lint neo4j-up neo4j-down ingest validate validate-mcp mcp

install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .

neo4j-up:
	docker compose --env-file .env up -d --wait

neo4j-down:
	docker compose --env-file .env down

ingest:
	uv run python ingest_databricks.py

validate:
	uv run python validate_store.py

validate-mcp:
	uv run python validate_mcp.py

mcp:
	uv run python serve_mcp.py
