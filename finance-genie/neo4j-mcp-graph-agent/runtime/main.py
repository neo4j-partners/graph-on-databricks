"""Serve the graph agent through Agent Bricks Runtime."""

import logging
import os
from pathlib import Path

# Importing the agent is side-effect-free (no env is read until configure()), so it sits up top.
import uvicorn
from agent.agent import configure
from dotenv import load_dotenv

from databricks_agentkit import DurableAgentServer
from runtime.adapter import invoke, recover
from runtime.identity import MemoryIdentityMiddleware

# override=False so injected DATABRICKS_* (from `agentbricks dev -p` or the deploy platform) win over a
# checked-in .env.
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=False)
configure()

# Uvicorn configures only its own loggers. This surfaces the per-request bound identity in the
# app log without raising the level of any other library.
_identity_log = logging.getLogger("runtime.identity")
_identity_log.setLevel(logging.INFO)
_identity_log.addHandler(logging.StreamHandler())
_identity_log.propagate = False

app = DurableAgentServer()
app.add_middleware(MemoryIdentityMiddleware)
app.invoke(invoke)
app.recover(recover)


def main() -> None:
    uvicorn.run("runtime.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
