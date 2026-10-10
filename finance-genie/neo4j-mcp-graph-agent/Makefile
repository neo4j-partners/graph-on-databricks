# One-command wrappers around the commands in README.md and docs/traffic.md.
# Set DATABRICKS_CONFIG_PROFILE first. The README has no default profile.

DEPLOY_NAME ?= neo4j-graph-agent
APP_NAME ?= agent-bricks-$(DEPLOY_NAME)
QUESTION ?= What does the SIMILAR_TO relationship mean?
USERS ?= 6
SESSIONS ?= 2
TURNS ?= 2
EXPECT_TURNS ?= 24
TRANSCRIPTS ?= transcripts.json
LABEL ?=
OUT ?= $(LABEL).json
BEFORE ?= before-1.json
AFTER ?= after-1.json
ONTOLOGY_YAML = ontology/finance_genie.ontology.yaml

APP_URL_CMD = databricks apps get $(APP_NAME) -p "$(DATABRICKS_CONFIG_PROFILE)" -o json | jq -r .url

.PHONY: deploy smoke logs traffic check-profile
.PHONY: export replay snapshot apply-ontology compare

check-profile:
	@test -n "$(DATABRICKS_CONFIG_PROFILE)" || { echo "Set DATABRICKS_CONFIG_PROFILE first." >&2; exit 1; }

deploy: check-profile
	agentbricks --profile "$(DATABRICKS_CONFIG_PROFILE)" deploy $(DEPLOY_NAME)
	agentbricks --profile "$(DATABRICKS_CONFIG_PROFILE)" deployments get $(APP_NAME)
	@echo "APP_URL=$$($(APP_URL_CMD))"

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

# Ontology before and after run. See docs/ontology-experiment.md for the order and the manual MEMORY_API_KEY switch.
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
