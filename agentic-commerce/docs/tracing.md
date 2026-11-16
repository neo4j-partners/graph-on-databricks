# Agentic Commerce Tracing

This project is deployed on Databricks with Mosaic AI Agent Framework through
`agents.deploy()`. Databricks MLflow Tracing is the production observability
source of truth. The demo client also has a smaller `custom_outputs.demo_trace`
contract so the browser can render product picks, tool results, graph hops, and
memory writes without querying MLflow.

## What Changed

The previous demo trace showed every tool as `0ms` because the browser rendered
`custom_outputs.demo_trace.tool_timeline[*].duration_ms`, and the served agent
was not populating that field. LangGraph messages include tool call and tool
result records, but they do not include elapsed time by default.

The serving adapter now collects per-tool latency during each LangGraph run:

- [retail_agent/agent/serving.py](../retail_agent/agent/serving.py) adds a
  `ToolTimingCallback` based on LangChain callbacks. It records `on_tool_start`,
  `on_tool_end`, and `on_tool_error` timestamps with `time.perf_counter()`.
- The same adapter passes those collected timings into
  `extract_demo_trace(...)` after `_agent.ainvoke(...)` completes.
- The adapter tags the current MLflow trace with the retail session ID, user ID,
  and demo mode when MLflow exposes an active trace.
- When available, the adapter also adds `mlflow_trace_id` to
  `custom_outputs.demo_trace`.
- [retail_agent/agent/demo_trace.py](../retail_agent/agent/demo_trace.py) now
  accepts optional tool timing records and merges `duration_ms` onto matching
  tool result timeline entries by `tool_call_id`, falling back to tool name order
  when no call ID is available.
- The demo UI now renders `n/a` rather than a fake `0ms` when an older endpoint
  or malformed trace does not include `duration_ms`.

## How It Should Work

The normal request path is:

1. The Databricks App backend invokes the Agent Framework serving endpoint.
2. The serving endpoint runs `RetailAgent.predict(...)`.
3. `RetailAgent._async_predict(...)` creates the retail context and calls the
   LangGraph agent with `ToolTimingCallback` in the LangChain config.
4. MLflow LangChain autologging records production spans for the agent, model
   calls, and tools.
5. The local callback records elapsed milliseconds for each tool execution.
6. `extract_demo_trace(...)` extracts structured tool calls and tool results from
   the LangGraph messages, then merges timing data into the timeline.
7. The endpoint returns normal assistant messages plus
   `custom_outputs.demo_trace`.
8. The demo-client backend adapts that payload into `tool_timeline`.
9. The browser renders non-zero tool durations in the Intelligence panel.

After deploying a model version that includes this change, a live response should
include timeline rows like:

```json
{
  "event": "tool_result",
  "tool_name": "search_products",
  "tool_call_id": "call_...",
  "status": "success",
  "content_type": "json",
  "duration_ms": 237,
  "summary": {
    "products": 6,
    "count": "int"
  }
}
```

The deploy command for this code-only serving change is:

```bash
uv run python -m cli pipeline --deploy
```

Use `--all` only when product data or GraphRAG data also needs to be rebuilt.
The [deployment runbook](runbook.md) describes each pipeline mode.

After deployment, run at least:

```bash
uv run python -m cli submit retail-agent-demo
```

For broader validation, run:

```bash
uv run python -m cli pipeline --verify
```

## What To Investigate If Durations Are Still Missing

Start with the version and payload path before debugging MLflow.

1. Confirm the serving endpoint is routing traffic to the new model version.
   The endpoint must be `READY`, have no pending config update, and route traffic
   to the version created by the latest `retail-agent-deploy` run.
2. Confirm the Databricks App backend is targeting the canonical endpoint:
   `agents_retail_assistant-retail-retail_agent_v3`.
3. Inspect the raw response from the backend or endpoint. If
   `custom_outputs.demo_trace.tool_timeline` has no `duration_ms`, the deployed
   model is likely stale or the callback did not run.
4. If `duration_ms` is present in `custom_outputs.demo_trace` but the UI still
   shows `n/a`, inspect the demo-client adapter path. The backend model
   `ToolTimelineItem.duration_ms` must preserve the value.
5. If the UI shows `n/a` only for tool call rows but not tool result rows, that is
   expected. Timing is attached to completed tool results, because only results
   have elapsed time.
6. If `mlflow_trace_id` is missing but `duration_ms` is present, the demo timing
   path is working. Investigate MLflow trace activation separately.
7. If MLflow traces are missing entirely, verify the agent is deployed with Agent
   Framework, the logged model includes the expected `mlflow` dependency, and the
   deployment used a non-Git-associated experiment when required.
8. If MLflow traces exist but are not queryable long-term, production monitoring
   or archival may not be configured. Real-time experiment traces and durable
   Delta trace storage are separate features.

Useful local checks before redeploying:

```bash
uv run python -m py_compile retail_agent/agent/serving.py retail_agent/agent/demo_trace.py
uv run pytest tests/test_demo_trace.py
cd demo-client && uv run pytest tests/test_demo_backend.py
cd demo-client && apx dev check
```

## Databricks Guidance

Databricks recommends Agent Framework for Databricks-hosted GenAI applications.
With Agent Framework, MLflow Tracing works automatically and traces are logged to
the agent's MLflow experiment. This project follows that path by logging the
agent model, registering it in Unity Catalog, and deploying it with
`agents.deploy()`.

For custom CPU Model Serving, Databricks documents additional environment
variables such as `ENABLE_MLFLOW_TRACING=true` and `MLFLOW_EXPERIMENT_ID`, but
that is the alternative path. Do not add those knobs unless this project stops
using Agent Framework.

Production Monitoring is optional and separate from the UI timing fix. Use it
when traces need durable Delta storage, sampled scorers, or continuous quality
monitoring. Recommended monitoring practices include:

- Use `sample_rate=1.0` for critical safety or security checks.
- Use lower sample rates for expensive LLM judges.
- Use filter strings so scorers run only on relevant traces.
- Use the same scorer definitions in development evaluation and production
  monitoring when possible.

## Reference Docs

- Databricks: [Trace agents deployed on Databricks](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/prod-tracing)
- Databricks: [MLflow Tracing - GenAI observability](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/)
- Databricks: [Monitor GenAI apps in production](https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/production-monitoring)
- MLflow: [Track users and sessions](https://mlflow.org/docs/latest/genai/tracing/track-users-sessions/)
