"""Log, register, and deploy the Neo4j MCP graph agent."""

import os
import time
from importlib.metadata import PackageNotFoundError, version

from databricks.sdk import WorkspaceClient

from _job_bootstrap import inject_params, setting

inject_params()


def requirement(package: str) -> str:
    try:
        return f"{package}=={version(package)}"
    except PackageNotFoundError:
        return package


OPTIONAL_AGENT_ENV_VARS = ("MAX_AGENT_STEPS", "TOOL_RESULT_MAX_CHARS")
POLL_INTERVAL_SECONDS = 30


def enum_text(value) -> str:
    """Return the plain enum value whether the SDK gives an Enum or a string."""
    return str(getattr(value, "value", value))


def wait_for_endpoint_ready(
    ws: WorkspaceClient, endpoint_name: str, timeout_seconds: float
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        state = ws.serving_endpoints.get(endpoint_name).state
        ready = enum_text(state.ready) if state and state.ready else "UNKNOWN"
        config_update = "UNKNOWN"
        if state and state.config_update:
            config_update = enum_text(state.config_update)
        if config_update == "UPDATE_FAILED":
            raise RuntimeError(
                f"endpoint {endpoint_name} update failed "
                f"(ready={ready}, config_update={config_update})"
            )
        if ready == "READY" and config_update == "NOT_UPDATING":
            print(f"OK    endpoint {endpoint_name} is READY")
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"timed out after {timeout_seconds:.0f}s waiting for endpoint "
                f"{endpoint_name} (ready={ready}, config_update={config_update})"
            )
        print(f"OK    waiting: ready={ready} config_update={config_update}")
        time.sleep(POLL_INTERVAL_SECONDS)


def get_mcp_resources(ws: WorkspaceClient, connection_name: str):
    from databricks_mcp import DatabricksMCPClient

    host = ws.config.host.rstrip("/")
    server_url = f"{host}/api/2.0/mcp/external/{connection_name}"
    client = DatabricksMCPClient(server_url=server_url, workspace_client=ws)
    resources = client.get_databricks_resources()
    if not resources:
        raise RuntimeError(
            "DatabricksMCPClient did not return resources for "
            f"{server_url}. Check that the URL is an external Databricks MCP "
            "proxy URL and that the installed databricks-mcp package supports "
            "external MCP resource detection."
        )
    return resources


def main() -> None:
    import mlflow
    import databricks.agents as agents
    from mlflow import MlflowClient
    from mlflow.models.resources import DatabricksServingEndpoint

    catalog = setting("CATALOG")
    schema = setting("SCHEMA")
    model_name = setting("UC_MODEL_NAME", "neo4j_mcp_agent")
    uc_model_name = f"{catalog}.{schema}.{model_name}"
    endpoint_name = setting("MODEL_SERVING_ENDPOINT_NAME", "neo4j-mcp-agent")
    llm_endpoint_name = setting("LLM_ENDPOINT_NAME")
    connection_name = setting("UC_CONNECTION_NAME")
    workspace_dir = setting("DATABRICKS_WORKSPACE_DIR")
    model_alias = setting("MODEL_ALIAS", "champion")
    ready_timeout_seconds = float(setting("ENDPOINT_READY_TIMEOUT_SECONDS", "1500"))
    ws = WorkspaceClient()

    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment(f"{workspace_dir}/neo4j-mcp-agent")

    resources = [
        DatabricksServingEndpoint(endpoint_name=llm_endpoint_name),
        *get_mcp_resources(ws, connection_name),
    ]
    pip_requirements = [
        requirement("databricks-agents"),
        requirement("databricks-langchain"),
        requirement("databricks-mcp"),
        requirement("langchain"),
        requirement("langchain-core"),
        requirement("langgraph"),
        requirement("langgraph-prebuilt"),
        requirement("mcp"),
        requirement("mlflow"),
        requirement("nest-asyncio"),
    ]

    with mlflow.start_run():
        logged_agent_info = mlflow.pyfunc.log_model(
            name="neo4j-mcp-agent",
            python_model="neo4j_mcp_graph_agent.py",
            resources=resources,
            pip_requirements=pip_requirements,
        )
    print(f"OK    logged model: {logged_agent_info.model_uri}")

    registered = mlflow.register_model(
        model_uri=logged_agent_info.model_uri,
        name=uc_model_name,
    )
    print(f"OK    registered UC model: {registered.name} v{registered.version}")

    version_number = int(registered.version)
    MlflowClient(registry_uri="databricks-uc").set_registered_model_alias(
        uc_model_name, model_alias, version_number
    )
    print(f"OK    set alias '{model_alias}' on {uc_model_name} v{version_number}")

    environment_vars = {
        "LLM_ENDPOINT_NAME": llm_endpoint_name,
        "UC_CONNECTION_NAME": connection_name,
        "MCP_SECRET_SCOPE": setting("MCP_SECRET_SCOPE"),
    }
    environment_vars.update(
        {
            name: os.environ[name]
            for name in OPTIONAL_AGENT_ENV_VARS
            if os.environ.get(name)
        }
    )

    deployment = agents.deploy(
        uc_model_name,
        version_number,
        endpoint_name=endpoint_name,
        environment_vars=environment_vars,
        tags={
            "endpointSource": "neo4j-mcp-agentcore",
            "connection": connection_name,
        },
        deploy_feedback_model=False,
    )
    print(f"OK    deployment submitted: {deployment}")

    wait_for_endpoint_ready(ws, endpoint_name, ready_timeout_seconds)


if __name__ == "__main__":
    main()
