.PHONY: \
	check \
	ingest \
	neo4j-schema-context \
	neo4j-schema-ingest \
	install \
	lint \
	mcp \
	neo4j-down \
	neo4j-up \
	test \
	validate \
	validate-embeddings \
	validate-mcp \
	validate-neo4j-schema

install:
	uv sync

check: lint test

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

neo4j-schema-ingest:
	uv run finance-semantic-neo4j-schema-ingest

neo4j-schema-context:
	uv run finance-semantic-neo4j-schema-context

validate:
	uv run finance-semantic-validate-store

validate-embeddings:
	uv run finance-semantic-validate-embeddings

validate-mcp:
	uv run finance-semantic-validate-mcp

validate-neo4j-schema:
	uv run finance-semantic-validate-neo4j-schema

mcp:
	uv run finance-semantic-mcp
