"""Store AgentCore OAuth credentials in a Databricks secret scope."""

from __future__ import annotations

from _common import (
    base_parser,
    create_secret_scope_if_needed,
    load_agentcore_credentials,
    make_context,
    ok,
)


def main() -> None:
    parser = base_parser(__doc__ or "")
    args = parser.parse_args()
    ctx = make_context(args.profile)
    settings = ctx.settings
    credentials = load_agentcore_credentials(settings.agentcore_credentials_path)

    create_secret_scope_if_needed(ctx.ws, settings.mcp_secret_scope)

    secret_values = {
        "gateway_host": credentials.gateway_host,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "token_endpoint": credentials.token_url,
        "oauth_scope": credentials.scope,
    }
    for key, value in secret_values.items():
        ctx.ws.secrets.put_secret(
            scope=settings.mcp_secret_scope,
            key=key,
            string_value=value,
        )
        if key == "client_secret":
            ok(f"stored secret {key}: [redacted, {len(value)} characters]")
        else:
            ok(f"stored secret {key}")

    ok(f"stored {len(secret_values)} secrets in scope {settings.mcp_secret_scope}")


if __name__ == "__main__":
    main()
