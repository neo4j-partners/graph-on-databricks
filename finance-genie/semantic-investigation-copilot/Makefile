.PHONY: \
	check \
	demo \
	ingest \
	install \
	lint \
	mcp \
	neo4j-down \
	neo4j-up \
	record-demo \
	record-demo-validation \
	record-graph \
	record-sources \
	test \
	validate \
	validate-demo \
	validate-embeddings \
	validate-graph \
	validate-mcp \
	validate-sources

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

validate:
	uv run finance-semantic-validate-store

validate-sources:
	uv run finance-semantic-validate-sources

record-sources:
	uv run finance-semantic-validate-sources --write-evidence

validate-graph:
	uv run finance-semantic-validate-graph

record-graph:
	uv run finance-semantic-validate-graph --write-evidence

validate-embeddings:
	uv run finance-semantic-validate-embeddings

validate-mcp:
	uv run finance-semantic-validate-mcp

demo:
	uv run finance-semantic-demo

record-demo:
	uv run finance-semantic-demo --write-evidence

validate-demo:
	uv run finance-semantic-validate-demo

record-demo-validation:
	uv run finance-semantic-validate-demo --write-evidence

mcp:
	uv run finance-semantic-mcp
