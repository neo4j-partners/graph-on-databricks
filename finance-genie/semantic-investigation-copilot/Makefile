.PHONY: install test lint neo4j-up neo4j-down ingest validate validate-embeddings validate-mcp mcp

install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

neo4j-up:
	docker compose --env-file .env up -d --wait

neo4j-down:
	docker compose --env-file .env down

ingest:
	uv run finance-semantic-ingest

validate:
	uv run finance-semantic-validate-store

validate-embeddings:
	uv run finance-semantic-validate-embeddings

validate-mcp:
	uv run finance-semantic-validate-mcp

mcp:
	uv run finance-semantic-mcp
