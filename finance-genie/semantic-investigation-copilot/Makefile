.PHONY: \
	app \
	check \
	embeddings \
	ingest \
	neo4j-schema-context \
	neo4j-schema-ingest \
	install \
	lint \
	mcp \
	mcp-stop \
	neo4j-down \
	neo4j-up \
	test \
	validate \
	validate-ask \
	validate-embeddings \
	validate-mcp \
	validate-neo4j-schema

MCP_PORT ?= 8000

install:
	uv sync

app:
	uv run streamlit run src/app.py

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

embeddings:
	uv run finance-semantic-embeddings

neo4j-schema-ingest:
	uv run finance-semantic-neo4j-schema-ingest

neo4j-schema-context:
	uv run finance-semantic-neo4j-schema-context

validate:
	uv run finance-semantic-validate-store

validate-ask:
	uv run finance-semantic-validate-ask

validate-embeddings:
	uv run finance-semantic-validate-embeddings

validate-mcp:
	uv run finance-semantic-validate-mcp

validate-neo4j-schema:
	uv run finance-semantic-validate-neo4j-schema

mcp:
	uv run finance-semantic-mcp --transport streamable-http --port $(MCP_PORT)

mcp-stop:
	@pids="$$(lsof -tiTCP:$(MCP_PORT) -sTCP:LISTEN)"; \
	if [ -z "$$pids" ]; then \
		echo "No MCP server is listening on port $(MCP_PORT)."; \
		exit 0; \
	fi; \
	for pid in $$pids; do \
		command="$$(ps -p "$$pid" -o command=)"; \
		case "$$command" in \
			*finance-semantic-mcp*streamable-http*) kill "$$pid" ;; \
			*) echo "Refusing to stop non-MCP process $$pid on port $(MCP_PORT)." >&2; exit 1 ;; \
		esac; \
	done; \
	echo "Stopped NeoCarta MCP server on port $(MCP_PORT)."
