import base64
import os
import sys
import time
import threading

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response

from neo4j_mcp_server_process import neo4j_mcp_server

URI            = os.getenv("NEO4J_URI",      "neo4j+s://26bf512b.databases.neo4j.io")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASS     = os.getenv("NEO4J_PASS",     "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

TARGET_URL  = "http://127.0.0.1:8001"
AUTH_HEADER = "Authorization"

# FIX: The original neo4j-labs sample used httpx.BasicAuth(user, pass)._auth_header which is a
# private attribute and does not reliably return the correct value, causing 401 Unauthorized
# from the Neo4j MCP server. We build the Basic Auth header manually using proper Base64 encoding.
_basic_auth_value = "Basic " + base64.b64encode(f"{NEO4J_USER}:{NEO4J_PASS}".encode()).decode()

# Startup log to confirm secrets were injected correctly from the Databricks secret scope.
# If NEO4J_PASS=EMPTY the secret resource mapping in the App config is missing or incorrect.
print(f"NEO4J_USER={NEO4J_USER} NEO4J_PASS={'set' if NEO4J_PASS else 'EMPTY'} URI={URI}", file=sys.stderr)

app         = FastAPI()
http_client = httpx.AsyncClient(timeout=60.0)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy(request: Request, path: str):
    url = f"{TARGET_URL}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"

    headers = dict(request.headers)
    headers.pop("host", None)
    headers[AUTH_HEADER] = _basic_auth_value

    body = await request.body()

    try:
        resp = await http_client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body,
            follow_redirects=False,
        )
        excluded = {"content-encoding", "content-length", "transfer-encoding", "connection", "keep-alive"}
        response_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded}
        return Response(content=resp.content, status_code=resp.status_code, headers=response_headers)
    except httpx.RequestError as exc:
        return Response(content=f"Error contacting target server: {exc}", status_code=503)


def run_neo4j_server():
    print("Starting Neo4j MCP Server...", file=sys.stderr)
    try:
        neo4j_mcp_server(args=[
            "--neo4j-uri",              URI,
            "--neo4j-database",         NEO4J_DATABASE,
            "--neo4j-transport-mode",   "http",
            "--neo4j-read-only",        "true",
            "--neo4j-telemetry",        "false",
            "--neo4j-http-host",        "0.0.0.0",
            "--neo4j-http-port",        "8001",
            "--neo4j-http-allowed-origins", "*",
        ])
    except Exception as e:
        print(f"Critical error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    t = threading.Thread(target=run_neo4j_server, daemon=True)
    t.start()

    print("Waiting for Neo4j MCP Server to start...", file=sys.stderr)
    time.sleep(3)

    print("Starting FastAPI proxy on http://0.0.0.0:8000", file=sys.stderr)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
