# Agentic Commerce Demo Client

Databricks App demo client for the Agentic Commerce agent. The app is built with
[`apx`](https://github.com/databricks-solutions/apx) and includes:

- Frontend: React, Vite, TanStack Router, shadcn-style components.
- Backend: FastAPI served under `/api`.
- API client: generated from the FastAPI OpenAPI schema by apx.
- Deployment: Databricks Asset Bundle from `databricks.yml`.

Current state:

- The two-tab frontend demo is implemented.
- Backend demo routes are implemented:
  - `POST /api/demo/search`
  - `POST /api/demo/diagnose`
- Backend live Model Serving invocation and `custom_outputs.demo_trace`
  response adaptation are implemented.
- The visible UI submits through the generated backend API client.
- The target Agentic Commerce agent serving endpoint is
  `agents_retail_assistant-retail-retail_agent_v3`.
- The live Agentic Commerce agent endpoint is validated on model version 16 with
  `custom_outputs.demo_trace`.

The [Real Backend Integration Plan](../docs/real-backend.md) records the
integration phases, the validation results, and the remaining work.

## Local Run And Test

Prerequisites:

- apx installed.
- `uv` available for Python package management.
- Run commands from `demo-client`.

Start all development servers in detached mode:

```bash
apx dev start
```

Open the app:

```text
http://localhost:9000
```

View local logs:

```bash
apx dev logs
```

Follow local logs:

```bash
apx dev logs -f
```

Check server status:

```bash
apx dev status
```

Run local checks:

```bash
apx dev check
```

Build the production artifact:

```bash
apx build
```

Smoke-check the running app:

```bash
curl -I http://localhost:9000
```

Stop local servers:

```bash
apx dev stop
```

Expected local results:

- `apx dev status` reports frontend and backend as healthy.
- `apx dev check` succeeds.
- `apx build` succeeds.
- `curl -I http://localhost:9000` returns `200 OK`.

Backend route smoke checks:

```bash
curl -sS http://localhost:9000/api/demo/search \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Find running shoes under $150","demo_mode":"agentic_search"}'
```

```bash
curl -sS http://localhost:9000/api/demo/diagnose \
  -H "Content-Type: application/json" \
  -d '{"prompt":"My running shoes feel flat after 300 miles. What should I do?","demo_mode":"issue_diagnosis"}'
```

Expected backend route results:

- In live mode, responses include `source_type: "live"` when the backend can
  reach Model Serving.
- In sample mode, responses include `source_type: "sample"` and
  `trace_source: "sample"`.
- Search responses include `mode: "agentic_search"` and may include product
  picks from live `demo_trace.product_results`.
- Diagnosis responses include `mode: "issue_diagnosis"` and may include cited
  chunks from live `demo_trace.knowledge_chunks`.

Manual UI checks:

- Agentic search loads as the first usable screen.
- "waterproof trail shoes under $150" preset renders top picks, related
  products, profile chips, and intelligence surge rows.
- "packable rain shell for day hikes" preset renders top picks, related
  products, profile chips, and intelligence surge rows.
- Typed search query submits on Enter and with the Ask button.
- Issue diagnosis tab switches without a full page reload.
- "running shoes feel flat" preset renders diagnosis path, actions,
  alternatives, and cited sources.
- "outsole peeling after 3 months" preset renders diagnosis path, actions, and
  cited sources.
- Reset session clears the active response, profile chips, query, progress
  state, and local session id.
- Narrow viewport stacks the right rail below the main content without overlap.
- Text stays inside cards and buttons at mobile and desktop widths.

apx MCP and browser automation notes:

- The apx CLI includes an MCP server entrypoint: `apx mcp`.
- If your agent environment exposes apx MCP tools, prefer them for start, stop,
  logs, checks, OpenAPI refresh, and component lookup.
- This project does not currently include Playwright dependencies.
- If your agent environment exposes Playwright MCP, use it for browser smoke
  tests and viewport checks.
- If Playwright MCP is not available, use manual browser checks or add
  project-level Playwright tests later through apx package management.

## Runtime Configuration

Copy the sample environment file and edit values for your workspace:

```bash
cp .env.sample .env
```

Runtime variables consumed by the backend:

- `AGENTIC_COMMERCE_RETAIL_AGENT_ENDPOINT_NAME`: target serving endpoint.
  Defaults to `agents_retail_assistant-retail-retail_agent_v3`.
- `AGENTIC_COMMERCE_RETAIL_AGENT_TIMEOUT_SECONDS`: upstream invocation timeout.
  Defaults to `120`.
- `AGENTIC_COMMERCE_DEMO_DATA_MODE`: `live` or `sample`. Defaults to `live`.
- `AGENTIC_COMMERCE_DEMO_ALLOW_SAMPLE_FALLBACK`: when true, live failures can
  return sample responses with `source_type: "fallback"`.
- `AGENTIC_COMMERCE_DEMO_INCLUDE_RAW_ENDPOINT_METADATA`: development-only raw
  endpoint payload inclusion. Keep false for normal deployment.

Deploy helper variables:

- `DATABRICKS_PROFILE`: Databricks CLI profile. Leave empty to use default CLI
  authentication.
- `DATABRICKS_BUNDLE_TARGET`: bundle target, usually `dev`.
- `DATABRICKS_APP_RESOURCE_KEY`: bundle app resource key from `databricks.yml`,
  currently `agentic-commerce-app`.
- `DATABRICKS_APP_NAME`: Databricks App name from `databricks.yml`, currently
  `agentic-commerce`.
- `DATABRICKS_DEPLOY_STRICT_VALIDATE`: when true, also runs strict bundle
  validation.

Databricks Apps receive additional runtime variables from the app config
`env` section. `scripts/deploy_from_env.py` loads `.env`, temporarily stages
only `AGENTIC_COMMERCE_*` values into `app.yml` for the build/deploy window,
then restores the source file. Databricks CLI values such as
`DATABRICKS_PROFILE` are used only by the deploy process.

The bundle also binds the configured Agentic Commerce agent serving endpoint as a
Databricks App resource with `CAN_QUERY`, so the deployed app service principal
gets the serving permission it needs during deployment.

## Remote Deploy And Monitor

Prerequisites:

- Databricks CLI installed and authenticated.
- A Databricks profile with access to the target workspace.
- The target workspace supports Databricks Apps.
- Run commands from `demo-client`.

Deploy everything from `.env`:

```bash
uv run python scripts/deploy_from_env.py
```

Preview the deploy commands and staged runtime config:

```bash
uv run python scripts/deploy_from_env.py --dry-run
```

The helper runs:

1. `apx build`
2. `databricks bundle validate`
3. Optional `databricks bundle validate --strict`
4. `databricks bundle deploy`
5. `databricks bundle run <app-resource-key>`
6. `databricks bundle summary`
7. `databricks apps get <app-name>`

This path uses Databricks Declarative Automation Bundles. In the current CLI
configuration this is the Terraform-backed bundle deploy path; there are no
separate checked-in `.tf` files to run manually.

The helper removes `DATABRICKS_CLUSTER_ID` from the deploy process environment
because Databricks Apps do not need a cluster override. It also prints app URL,
app state, compute state, and deployment state from `databricks apps get`,
which is the authoritative status source when `bundle summary` does not show an
app URL.

Manual bundle commands:

```bash
databricks bundle validate --target <target> --profile <profile>
```

```bash
databricks bundle validate --target <target> --profile <profile> --strict
```

```bash
databricks bundle plan --target <target> --profile <profile>
```

```bash
databricks bundle deploy --target <target> --profile <profile>
```

```bash
databricks bundle run <app-resource-key> --target <target> --profile <profile>
```

```bash
databricks bundle summary --target <target> --profile <profile>
```

```bash
databricks bundle open <app-resource-key> --target <target> --profile <profile>
```

Inspect the app directly:

```bash
databricks apps get <app-name> --profile <profile>
```

View deployed logs:

```bash
databricks apps logs --target <target> --profile <profile>
```

Follow deployed logs:

```bash
databricks apps logs --target <target> --profile <profile> --follow
```

Show only app logs:

```bash
databricks apps logs --target <target> --profile <profile> --source APP
```

Show only system logs:

```bash
databricks apps logs --target <target> --profile <profile> --source SYSTEM
```

Search logs:

```bash
databricks apps logs --target <target> --profile <profile> --search "Error"
```

Check app permissions:

```bash
databricks apps get-permissions <app-name> --profile <profile>
```

Verify the target serving endpoint:

```bash
databricks serving-endpoints get agents_retail_assistant-retail-retail_agent_v3 --profile <profile>
```

Expected serving endpoint state:

- `state.ready` is `READY`.
- `state.config_update` is `NOT_UPDATING`.
- Active traffic is routed to the latest validated model version.
- The current validated upstream model version is `16`.

Validate live trace output through the backend routes after deployment:

```bash
curl -sS <app-url>/api/demo/search \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Find running shoes under $150","demo_mode":"agentic_search"}'
```

```bash
curl -sS <app-url>/api/demo/diagnose \
  -H "Content-Type: application/json" \
  -d '{"prompt":"My running shoes feel flat and unresponsive after 300 miles. What should I do?","demo_mode":"issue_diagnosis"}'
```

Expected live backend results:

- Search returns `source_type: "live"`, `trace_source: "live"`, and product
  picks when live tool output includes product results.
- Diagnosis returns `source_type: "live"`, `trace_source: "live"`, and cited
  sources or knowledge chunks when live tool output includes knowledge results.
- If the endpoint returns prose without trace metadata, the backend keeps the
  answer and marks trace data unavailable.

Direct endpoint validation note:

- Prefer backend route checks for the demo client contract.
- If validating the raw Model Serving endpoint directly, use direct REST so the
  request can include ChatAgent `custom_inputs`.
- `databricks serving-endpoints query` may ignore or reject `custom_inputs`, so
  it is not a reliable check for `demo_mode` or `custom_outputs.demo_trace`.

Check serving endpoint permissions:

```bash
databricks serving-endpoints get-permissions agents_retail_assistant-retail-retail_agent_v3 --profile <profile>
```

Remote validation checklist:

- Bundle validation succeeds.
- Bundle deployment succeeds.
- App starts successfully.
- App URL opens in the browser.
- App logs do not show startup errors.
- System logs do not show dependency or resource injection failures.
- App service principal can query the target serving endpoint.
- Backend search route returns a live response with product picks when live mode
  is configured and permissions are correct.
- Backend diagnosis route returns a live response with cited sources or
  knowledge chunks when live mode is configured and permissions are correct.
- The UI submits through the backend API routes in live mode.

Troubleshooting:

- If deployment fails, run bundle validation again and inspect system logs.
- If the app does not start, inspect app and system logs.
- If the deployed app cannot call Model Serving, confirm endpoint state,
  endpoint permissions, and backend configuration.
- If backend routes return sample data or the UI only shows sample data, check
  `AGENTIC_COMMERCE_DEMO_DATA_MODE` and fallback settings.
