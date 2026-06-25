# Supervisor Stub

The repository is structured for a future Mosaic AI multi-agent supervisor that routes analytics questions to a Genie space and product/KG questions to the deployed retail KG agent endpoint. The implementation is currently a stub:

- `retail_agent/agent/supervisor.py` contains sub-agent specs, `build_supervisor_chat_agent()` that raises `NotImplementedError`, and the TODO list in the module docstring.
- `retail_agent/deployment/deploy_supervisor.py` prints a `STUB` banner and exits nonzero.
- `retail-agent-deploy-supervisor` is the wheel entry point for the current supervisor stub.
- `retail_agent/agent/config.py` includes `supervisor_model_name` and `genie_space_id`; `genie_space_id` is empty by default and must be set before any real deployment.

To make this real, provision the Genie space, replace the supervisor skeleton with a `databricks_ai_bridge.GenieAgent` plus multi-agent supervisor implementation, mirror `deploy_agent.py` in `deploy_supervisor.py`, and add a check script.
