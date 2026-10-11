# One-command wrappers. docs/reference.md lists the raw command behind each target.
# Set DATABRICKS_CONFIG_PROFILE in .env or in your shell. A shell value wins.

ifndef DATABRICKS_CONFIG_PROFILE
DATABRICKS_CONFIG_PROFILE := $(shell sed -nE 's/^[[:space:]]*DATABRICKS_CONFIG_PROFILE=[[:space:]]*"?([^"\#[:space:]]*).*/\1/p' .env 2>/dev/null | tail -n 1)
endif

DEPLOY_NAME ?= neo4j-graph-agent
APP_NAME ?= agent-bricks-$(DEPLOY_NAME)
QUESTION ?= What does the SIMILAR_TO relationship mean?
USERS ?= 6
SESSIONS ?= 2
TURNS ?= 2
EXPECT_TURNS ?= 24
TRANSCRIPTS ?= ontology/out/transcripts.json
LABEL ?=
OUT ?= ontology/out/$(LABEL).json
BEFORE ?= ontology/out/before-1.json
AFTER ?= ontology/out/after-1.json
ONTOLOGY_YAML = ontology/finance_genie.ontology.yaml
LOCAL_URL ?= http://localhost:8000

APP_URL_CMD = databricks apps get $(APP_NAME) -p "$(DATABRICKS_CONFIG_PROFILE)" -o json | jq -r .url

.PHONY: secrets deploy grant-genie smoke logs traffic check-profile dev smoke-local
.PHONY: export replay snapshot apply-ontology compare

# Loads .env so the server sees MEMORY_API_KEY; agentbricks dev reads the key only
# from the environment, not from .env on its own.
dev:
	@test -f .env || { echo "Copy .env.example to .env and fill it in first." >&2; exit 1; }
	@set -a && . ./.env && set +a && \
	  test -n "$$MEMORY_API_KEY" || { echo "Set MEMORY_API_KEY in .env." >&2; exit 1; }; \
	  agentbricks dev

# Asks the local server one question in a new session. LOCAL_URL= and QUESTION= override.
smoke-local:
	agentbricks endpoint invoke --url $(LOCAL_URL) --path /api/invocations \
	  --json '{"id":"'$$(uuidgen)'","session_id":"make-smoke-local","input":[{"role":"user","content":"$(QUESTION)"}]}'

check-profile:
	@test -n "$(DATABRICKS_CONFIG_PROFILE)" || { echo "Set DATABRICKS_CONFIG_PROFILE in .env." >&2; exit 1; }

secrets: check-profile
	./setup_secrets.sh --profile "$(DATABRICKS_CONFIG_PROFILE)"

# Attaches the NAMS key resource when the app lacks it (exit 3), then deploys again to pick it up.
deploy: check-profile
	agentbricks --profile "$(DATABRICKS_CONFIG_PROFILE)" deploy $(DEPLOY_NAME); deployed=$$?; \
	uv run python scripts/attach_nams_key.py --profile "$(DATABRICKS_CONFIG_PROFILE)" --app $(APP_NAME); \
	attached=$$?; \
	if [ $$attached -eq 3 ]; then agentbricks --profile "$(DATABRICKS_CONFIG_PROFILE)" deploy $(DEPLOY_NAME); \
	elif [ $$attached -ne 0 ]; then exit $$attached; \
	else exit $$deployed; fi
	agentbricks --profile "$(DATABRICKS_CONFIG_PROFILE)" deployments get $(APP_NAME)
	@echo "APP_URL=$$($(APP_URL_CMD))"

grant-genie: check-profile
	uv run python scripts/grant_genie.py --profile "$(DATABRICKS_CONFIG_PROFILE)" --app $(APP_NAME) $(if $(DRY_RUN),--dry-run)

smoke: check-profile
	SESSION_ID=$$(uuidgen); \
	agentbricks --profile "$(DATABRICKS_CONFIG_PROFILE)" endpoint invoke $(APP_NAME) \
	  --path /api/invocations --routing-key "$$SESSION_ID" \
	  --json '{"id":"'$$(uuidgen)'","session_id":"'$$SESSION_ID'","input":[{"role":"user","content":"$(QUESTION)"}]}'

logs: check-profile
	agentbricks --profile "$(DATABRICKS_CONFIG_PROFILE)" deployments logs $(APP_NAME)

traffic: check-profile
	cd traffic && uv sync && \
	uv run agent-traffic --profile "$(DATABRICKS_CONFIG_PROFILE)" \
	  --app-url "$${APP_URL:-$$($(APP_URL_CMD))}" \
	  --users $(USERS) --sessions-per-user $(SESSIONS) --turns-per-session $(TURNS)

# Ontology before and after run. See docs/ontology-experiment.md for the order and where to reset the NAMS database.
export:
	uv run ontology/replay_transcripts.py export --out $(TRANSCRIPTS) --expect-turns $(EXPECT_TURNS)

replay:
	uv run ontology/replay_transcripts.py replay $(TRANSCRIPTS) --execute --wait

snapshot:
	@test -n "$(LABEL)" || { echo "Set LABEL, for example LABEL=before-1." >&2; exit 1; }
	uv run ontology/measure_ingestion.py snapshot --label $(LABEL) --out $(OUT) \
	  --ontology-yaml $(ONTOLOGY_YAML) --expect-turns $(EXPECT_TURNS)

apply-ontology:
	uv run ontology/apply_ontology.py --create --activate

compare:
	uv run ontology/measure_ingestion.py compare $(BEFORE) $(AFTER) \
	  --users $(USERS) --sessions $(SESSIONS) --turns $(TURNS)
