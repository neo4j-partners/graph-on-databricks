# Real Backend Integration Plan

## Goal

Make the demo client a real backend-backed Databricks App instead of a sample-data presentation shell.

The finished demo should send browser requests to the demo-client FastAPI backend, have that backend call the deployed Agentic Commerce agent endpoint, and render live agent results whenever the endpoint is available. Sample data should remain only as an explicit development or fallback mode.

This document is now the source of truth for the remaining work.

## Current State

- Status: In progress
- The Agentic Commerce agent has real Neo4j catalog search tools.
- The Agentic Commerce agent has GraphRAG knowledge tools for vector search, hybrid search, and product issue diagnosis.
- The Agentic Commerce agent has long-term preference tools and a personalized recommendation tool.
- The Agentic Commerce agent serving adapter has source code that can return structured demo trace metadata from real LangGraph tool calls.
- The demo-client backend has search and diagnosis routes that can call the `agents_retail_assistant-retail-retail_agent_v3` Databricks Model Serving endpoint.
- The generated frontend API client includes search and diagnosis calls.
- The visible React demo now submits through the generated backend API client.
- The deployed Databricks App can call the live Agentic Commerce agent endpoint and return live trace-backed search and diagnosis responses.
- The `2026-05-11` deployed 502 was traced to the serving model, not the browser or app routing. Model versions 10, 11, and 14 exposed incompatible runtime-injected tool schemas. Model version 15 fixed that path, and model version 16 is now the active endpoint route after the latest deployment.

## Assumptions

- The browser must never call Databricks Model Serving directly.
- The backend remains the boundary for Databricks authentication, response normalization, fallback behavior, and logging.
- The first production-worthy demo keeps the two existing tabs: Agentic Search and Issue Diagnosis.
- Sample data remains available for local development and explicitly enabled fallback, but live mode must be the normal path.
- The canonical deployed endpoint name is `agents_retail_assistant-retail-retail_agent_v3`.
- Reset remains browser-local unless a scoped server-side memory reset capability is deliberately added later.

## Risks

- The React app may look live while still using sample data unless the local sample helper is removed from the submit path.
- The serving endpoint may be running an older model version that does not include structured demo trace metadata.
- The agent may answer in prose without calling the tools needed for product cards, knowledge chunks, recommendations, or trace rows.
- The app service principal may not have permission to query the serving endpoint after deployment.
- Long-term preference and reasoning behavior may persist between sessions unless user ids are scoped deliberately for demos.
- The current serving adapter uses MLflow `ChatAgent`; MLflow 3 `ResponsesAgent` is the preferred newer pattern for future agent serving work, so a migration should be planned separately rather than mixed into the current stabilization.
- Local environment files may contain secrets. They must not be promoted into tracked docs, samples, logs, or build artifacts.

## Phase Checklist

### Phase 1: Make The Frontend Use The Backend

- Status: Complete
- Outcome: Submitting either demo tab calls the generated backend API client instead of local sample data.
- Checklist:
  - Complete: Replace the active submit path in the React route with the generated search and diagnosis API calls.
  - Complete: Keep the existing UI response shape by adding a frontend adapter from backend response fields to display fields.
  - Complete: Preserve preset buttons by passing preset ids to the backend instead of selecting local samples in the browser.
  - Complete: Preserve session id handling by sending the current session id to the backend and storing the returned effective session id.
  - Complete: Add user-visible warnings when the backend reports sample, fallback, inferred, or unavailable trace data.
  - Complete: Remove the local sample-only submit path from the active helper so it cannot be mistaken for the real production path.
- Validation:
  - Complete: A typed frontend check passes.
  - Pending: Browser submits reach `/api/demo/search` and `/api/demo/diagnose`.
  - Complete: The sample-data warning about local-only backend wiring no longer appears in live mode.
- Review:
  - The adapter registers placeholder product records for live products that were not present in the original demo catalog, so live product cards no longer disappear because of unknown ids.
  - Backend warnings are preserved and expanded with source and trace provenance when needed.
  - Errors are converted into visible low-confidence or empty-result demo responses instead of leaving the UI stuck in loading state.
  - Browser-level network verification is still pending and is included in final readiness validation.

### Phase 2: Confirm Endpoint Naming And Configuration

- Status: Complete
- Outcome: The app consistently targets the intended Agentic Commerce agent serving endpoint.
- Checklist:
  - Complete: Choose `agents_retail_assistant-retail-retail_agent_v3` as the canonical deployed serving endpoint.
  - Complete: Align the backend default, sample environment file, bundle variable, deployment docs, and demo script defaults to the same endpoint name.
  - Complete: Keep the endpoint configurable through environment or bundle variables.
  - Complete: Verify that sample mode and live mode are controlled only by explicit configuration.
  - Complete: Confirm fallback is disabled by default unless a demo environment intentionally enables it.
- Validation:
  - Complete: The Databricks serving endpoint list shows `agents_retail_assistant-retail-retail_agent_v3` is READY.
  - Complete: Local configuration defaults now report the expected endpoint.
  - Complete: The stale endpoint name appears only as a CLI command prefix, historical naming, or non-demo artifact text.
- Review:
  - The serving endpoint name is now consistent across the Agentic Commerce agent default config, demo-client backend default, demo-client environment sample, bundle variable, deploy helper default, and demo-client README.
  - Legacy command names were replaced with `retail-agent-*` entry points, and the unused package-level wrapper functions were removed.
  - The endpoint remains overrideable through `RETAIL_AGENT_ENDPOINT_NAME`, `AGENTIC_COMMERCE_RETAIL_AGENT_ENDPOINT_NAME`, and bundle variables.

### Phase 3: Validate Live Backend Invocation

- Status: Complete
- Outcome: The demo-client backend can call the live Agentic Commerce agent and return frontend-safe responses.
- Checklist:
  - Complete: Run one live agentic search request through the backend route.
  - Complete: Run one live issue diagnosis request through the backend route.
  - Complete: Confirm session id and user id are passed through to the Agentic Commerce agent.
  - Complete: Confirm upstream request ids and latency are captured when Databricks returns them.
  - Complete: Confirm safe structured errors for authentication failure, permission failure, timeout, malformed response, and endpoint unavailable cases.
  - Complete: Confirm sample fallback is used only when explicitly enabled.
- Validation:
  - Complete: Live backend search returned `source_type=live`, `trace_source=live`, a Databricks request id, 8 tool timeline rows, 10 product picks, 5 knowledge chunks, and no warnings.
  - Complete: Live backend diagnosis returned `source_type=live`, `trace_source=live`, a Databricks request id, 4 tool timeline rows, 10 knowledge chunks, and no warnings.
  - Complete: Unit tests cover serving payload shape, session and user id pass-through, socket timeout mapping, safe upstream status mapping, sample responses, and adapter degradation when trace metadata is missing.
  - Complete: A log-shape test verifies request id, mode, endpoint name, source type, latency, Databricks request id, and fallback reason are emitted.
  - Complete: `uv run python -m unittest discover tests` passes in `demo-client`.
  - Complete: `apx dev check` passes.
  - Complete: Error responses match the documented frontend error shape through `DemoError`.
- Review:
  - The backend now derives a session-scoped user id when the browser does not provide one, so the agent receives both session and user context without introducing cross-demo identity leakage.
  - Live route validation confirms the backend calls the canonical Databricks Model Serving endpoint and normalizes both search and diagnosis responses into frontend-safe contracts.
  - Fallback remains disabled by default and is only used when explicitly configured.
  - The live search prompt revealed catalog/domain mismatch for computer peripherals, but the backend path, trace capture, and product normalization are working. Prompt and demo data fit are handled in Phase 5.

### Phase 4: Make The Agent Trace Fully Useful

- Status: Complete
- Outcome: The intelligence panels use real tool calls and real tool outputs when the agent calls tools.
- Checklist:
  - Complete: Verify the deployed Agentic Commerce agent version returns `custom_outputs.demo_trace`.
  - Complete: Confirm product search tool outputs become product cards.
  - Complete: Confirm related product tool outputs become the frequently paired or graph traversal lane.
  - Complete: Confirm GraphRAG knowledge tool outputs become chunks, sources, and graph-hop candidates.
  - Complete: Confirm issue diagnosis tool outputs become diagnosis path, actions, alternatives, and citations.
  - Complete: Add normalization for personalized recommendation tool output so recommendation results can become product cards.
  - Complete: Add clear warnings for non-JSON tool outputs, malformed tool outputs, or no tool calls.
  - Complete: Keep the normal assistant prose unchanged for existing agent consumers.
- Validation:
  - Complete: A live search prompt produced trace source `live`, 8 tool timeline rows, 10 product picks, 5 knowledge chunks, and no warnings.
  - Complete: A live diagnosis prompt produced trace source `live`, 4 tool timeline rows, 10 knowledge chunks, and no warnings.
  - Complete: A live preference-write prompt called `track_preference` and returned structured memory writes.
  - Complete: A live returning-user recommendation prompt called `get_user_profile` and `recommend_for_user`, proving the deployed endpoint uses real profile and recommendation tools.
  - Complete: Local trace extraction tests prove `recommend_for_user` output now becomes product results and profile chips.
  - Complete: Local trace extraction tests cover non-JSON tool output and no-tool trace warnings.
  - Complete: The Agentic Commerce agent endpoint was refreshed and endpoint smoke tests passed against the updated active route.
- Review:
  - Product search, GraphRAG, diagnosis, memory write, profile read, and recommendation tool calls are real, not mocked.
  - The demo trace is real LangGraph tool-call metadata from `custom_outputs.demo_trace`.
  - The local source now normalizes recommendation tool output into the same product-card path as catalog search.
  - The deployed serving endpoint now routes traffic to the refreshed canonical `retail_agent_v3` model.

### Phase 5: Improve Tool Selection For Demo Prompts

- Status: Complete
- Outcome: Representative demo prompts reliably exercise the real tools the UI is meant to showcase.
- Checklist:
  - Complete: Review the demo-mode prompt hints for search and diagnosis.
  - Complete: Add small prompt guidance if the agent skips the expected tools for common demo prompts.
  - Complete: Keep tool choice agentic, but make the desired demo behavior reliable enough for stakeholder walkthroughs.
  - Complete: Add representative checks for search, diagnosis, profile read, preference write, recommendation, and trace capture.
  - Complete: Record known prompts that still return prose-only answers.
- Validation:
  - Complete: The primary search prompt now asks for waterproof trail running shoes under $150, matching the live outdoor and fitness catalog.
  - Complete: The primary support prompt now asks about running shoes that feel flat after 300 miles, matching the live GraphRAG support corpus.
  - Complete: Live search called `get_user_profile`, `search_products`, and `track_preference`, returned 14 product cards, and produced trace source `live`.
  - Complete: Live diagnosis called `knowledge_search`, returned 5 knowledge chunks, 5 cited sources, 8 recommended actions, and produced trace source `live`.
  - Complete: A returning-user recommendation prompt called `get_user_profile` and `recommend_for_user`.
  - Complete: Local tests and `apx dev check` pass after the prompt and sample-data changes.
  - Notes: No revised primary prompt returned prose-only output during validation. The recommendation prompt used the real recommendation tool, but structured recommendation cards still require the endpoint refresh recorded in Phase 6.
- Review:
  - The old electronics-oriented demo prompts were removed from the active frontend and backend sample paths.
  - The sample fallback data now mirrors the live catalog domain so fallback mode does not tell a different product story from live mode.
  - The prompt hints now include outdoor and fitness examples, which should take effect after the Agentic Commerce agent endpoint is refreshed.

### Phase 6: Validate Deployed App Permissions

- Status: Complete
- Outcome: The Databricks App can query the serving endpoint from its deployed runtime.
- Checklist:
  - Complete: Refresh the Agentic Commerce agent serving endpoint so the active model version includes the latest trace normalization.
  - Complete: Re-run the live recommendation/search prompt and confirm structured product cards are returned from the deployed app path.
  - Complete: Confirm the app resource grants query permission to the serving endpoint.
  - Complete: Deploy the app with live mode enabled.
  - Complete: Submit one search request from the deployed app.
  - Complete: Submit one diagnosis request from the deployed app.
  - Complete: Check deployed app logs for live API calls and fallback behavior.
  - Complete: Confirm no Databricks credentials, Neo4j credentials, authorization headers, or raw secrets appear in user-visible responses or logs.
- Validation:
  - Complete: Deployed search returned HTTP 200 with `source_type=live`, `trace_source=live`, product cards, memory writes, a Databricks request id, upstream latency, and no fallback warning.
  - Complete: Deployed diagnosis returned HTTP 200 with `source_type=live`, `trace_source=live`, a Databricks request id, upstream latency, and no fallback warning.
  - Complete: The app works from the deployed Databricks App runtime through the app service principal and serving endpoint resource binding. Local CLI auth was used only to authenticate the external smoke request into the protected app URL.
  - Complete: The serving endpoint is READY with no pending config and routes 100% traffic to `retail_assistant-retail-retail_agent_v3_16`.
  - Complete: The deployed Databricks App was refreshed from the current demo-client build on `2026-05-11T02:16:51Z` with `AGENTIC_COMMERCE_DEMO_DATA_MODE=live`, `AGENTIC_COMMERCE_DEMO_ALLOW_SAMPLE_FALLBACK=false`, and `AGENTIC_COMMERCE_RETAIL_AGENT_ENDPOINT_NAME=agents_retail_assistant-retail-retail_agent_v3`.
  - Complete: The Databricks App resource binding grants the app service principal `CAN_QUERY` on `agents_retail_assistant-retail-retail_agent_v3`.
  - Complete: Endpoint model version 15 was built from `retail_agent-0.1.22`, registered as Unity Catalog model version 15, deployed successfully, and smoke-tested through both the endpoint and app API path.
  - Complete: Endpoint model version 16 was built from `retail_agent-0.1.24`, registered as Unity Catalog model version 16, deployed successfully, and smoke-tested directly through the serving endpoint.
  - Notes: A stale deployed frontend showed old sample-only copy before the refresh. A later browser/app search returned 502 because the active serving model had an injected runtime schema failure. That failure was fixed in version 15 and remains fixed in version 16.
- Review:
  - The deployed app was already wired to the live backend. The 502 was caused by the live serving endpoint failing during agent tool execution.
  - The root issue was the interaction between LangGraph `ToolRuntime` injection and JSON/schema generation for Databricks serving. The fix keeps `runtime` injectable for LangGraph while making the internal args schema JSON-safe and keeping `runtime` hidden from the model-facing tool schema.
  - Search now exercises the real endpoint from the deployed app and returns live product cards. Diagnosis now exercises the real GraphRAG support path from the deployed app.
  - App logs show the earlier `POST /api/demo/search` 502 and the later `POST /api/demo/search` 200 after endpoint version 15 was deployed. The later version 16 endpoint smoke test returned live assistant messages, product results, and structured `custom_outputs.demo_trace`.

### Phase 7: Final Demo Readiness

- Status: In progress
- Outcome: The demo is repeatable, honest about provenance, and ready for stakeholder walkthroughs.
- Checklist:
  - Complete: Run backend unit tests.
  - Complete: Run Python compile checks.
  - Complete: Run frontend and backend type checks.
  - Complete: Build the app.
  - Pending: Verify desktop and mobile layouts in a browser.
  - Pending: Verify live, sample, fallback, inferred, and unavailable states render distinctly in the browser.
  - Complete: Add an MLflow GenAI evaluation gate using `mlflow.genai.evaluate()` with nested `inputs`, a keyword-argument `predict_fn`, optional safety/relevance judges, and deterministic checks for live trace structure.
  - In progress: Evaluate representative prompts before promoting a new serving model version. Current gate covers deployed search and diagnosis; preference-write, profile-read, and recommendation-specific prompts still need to be added.
  - Pending: Decide whether to migrate the serving adapter from `ChatAgent` to MLflow 3 `ResponsesAgent` after the current demo remains stable.
  - Pending: Decide whether production MLflow trace ingestion should be enabled for the Databricks App, the Model Serving endpoint, or both.
  - Update the demo script with exact prompts, expected panels, fallback notes, and reset steps.
  - Document any remaining limitations in this file.
- Validation:
  - Complete: Root tests passed with `uv run python -m pytest tests`.
  - Complete: Demo-client tests passed with `uv run python -m pytest tests` from `demo-client`.
  - Complete: Python compile checks passed with `uv run python -m compileall retail_agent`.
  - Complete: `apx dev check` passed TypeScript compilation and Python type checking.
  - Complete: `apx build` passed, producing the frontend build and Python wheel.
  - Complete: The demo-client was redeployed after logging hardening as deployment `01f14cdf78c518a5a42bdadd7fe362d6`.
  - Complete: Package command metadata was cleaned up in `retail_agent-0.1.23`; public wheel entry points now use `retail-agent-*`, and package-level wrapper functions were removed.
  - Complete: Deployed smoke search returned HTTP 200 with `source_type=live`, `trace_source=live`, 6 product cards, no warnings, and a Databricks request id.
  - Complete: Deployed smoke diagnosis returned HTTP 200 with `source_type=live`, `trace_source=live`, 5 knowledge chunks, 14 recommended actions, no warnings, and a Databricks request id.
  - Complete: MLflow GenAI evaluation passed against the deployed app with local file tracking. Run `433964d628ea401f90fe317b5ad2f0c6` reported `live_backend_contract/mean=1.0` and `no_secret_leak/mean=1.0`.
  - Complete: Deployed app logs now include structured `demo_request` entries with mode, request id, session id, endpoint, source type, latency, Databricks request id, and fallback reason.
  - Complete: `uv run python -m cli validate retail-agent-demo` passed and listed only the new `retail-agent-*` wheel entry points.
  - Complete: `retail_agent-0.1.24` was uploaded, `retail-agent-deploy` registered UC model version 16, and the serving endpoint now routes 100% traffic to `retail_assistant-retail-retail_agent_v3_16`.
  - Complete: Direct endpoint smoke testing returned live assistant messages, product results, memory writes, and structured demo trace output from version 16.
  - Complete: `retail-agent-demo` run `714990109566429` passed 9 of 9 deployed-agent checks covering product search, product lookup, graph traversal, short-term memory, long-term preferences, profile retrieval, and preference-based recommendation.
  - Complete: `retail-agent-check-knowledge` run `30013564659849` passed 4 of 4 deployed GraphRAG checks covering knowledge search, hybrid knowledge search, product diagnosis, and cross-product knowledge comparison.
  - Complete: Deployed app smoke search after the version 16 endpoint promotion returned `source_type=live`, `trace_source=live`, 6 product cards, no warnings, and request id `74240380-1fec-42af-9dad-d79c03c4677c`.
  - Pending: Browser desktop and mobile visual verification is still needed before marking this phase complete.
- Review:
  - The quality gate now checks the actual demo contract rather than only answer text. It fails if live mode silently falls back to sample/static data or if obvious credential markers appear in returned output.
  - The current production path still uses MLflow `ChatAgent`. That is valid for the deployed endpoint today, but new GenAI serving work should prefer `ResponsesAgent`; migration should be a separate stabilization phase because it changes the request and response contract.
  - The current MLflow evaluation run uses local file tracking for deterministic contract validation. Production trace ingestion into Unity Catalog should be planned separately so permissions, storage location, and retention are explicit.
  - The deployed app's structured logs are now visible in Databricks App logs, which closes the earlier observability gap where only Uvicorn access logs were available.

## Completion Criteria

- Status: In progress
- Complete: The React client submits through the backend API routes for both demo tabs.
- Complete: The backend invokes the configured Databricks Model Serving endpoint in live mode.
- Complete: The frontend never needs Databricks credentials or raw Model Serving URLs.
- Complete: Search can render live product or recommendation results when the agent returns them.
- Complete: Issue diagnosis can render live GraphRAG chunks, citations, actions, and diagnosis details when the agent returns them.
- Complete: The intelligence panel uses real LangGraph tool-call trace data when available.
- Complete: Sample data is used only in sample mode or explicitly enabled fallback mode.
- Complete: Fallback and inferred data are visibly labeled by the response contract.
- Complete: Endpoint naming is consistent across configuration, deployment, and docs.
- Complete: Deployed app permission to query the serving endpoint is validated.
- In progress: Tests, checks, and build have passed. Browser desktop and mobile verification remains.

## Deferred Work

- Server-side memory reset for a demo user or demo session.
- Full operator console or behind-the-glass trace replay.
- Bundle builder and comparison pages beyond the two current tabs.
- Persistent session replay, saved carts, feedback capture, or Lakebase-backed history.
- Exact token accounting and exact per-tool timing.
