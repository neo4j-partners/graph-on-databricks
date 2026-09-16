"""Log, register, and deploy the Neo4j MCP graph agent."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from _job_bootstrap import inject_params, setting

inject_params()


def requirement(package: str) -> str:
    try:
        return f"{package}=={version(package)}"
    except PackageNotFoundError:
        return package


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
    from databricks.sdk import WorkspaceClient
    from mlflow.models.resources import DatabricksServingEndpoint

    catalog = setting("CATALOG")
    schema = setting("SCHEMA")
    model_name = setting("UC_MODEL_NAME", "neo4j_mcp_agent")
    uc_model_name = f"{catalog}.{schema}.{model_name}"
    endpoint_name = setting("MODEL_SERVING_ENDPOINT_NAME", "neo4j-mcp-agent")
    llm_endpoint_name = setting("LLM_ENDPOINT_NAME")
    connection_name = setting("UC_CONNECTION_NAME")
    workspace_dir = setting("DATABRICKS_WORKSPACE_DIR")
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

    deployment = agents.deploy(
        uc_model_name,
        int(registered.version),
        endpoint_name=endpoint_name,
        environment_vars={
            "LLM_ENDPOINT_NAME": llm_endpoint_name,
            "UC_CONNECTION_NAME": connection_name,
            "MCP_SECRET_SCOPE": setting("MCP_SECRET_SCOPE"),
        },
        tags={
            "endpointSource": "neo4j-mcp-agentcore",
            "connection": connection_name,
        },
        deploy_feedback_model=False,
    )
    print(f"OK    deployment submitted: {deployment}")


if __name__ == "__main__":
    main()
