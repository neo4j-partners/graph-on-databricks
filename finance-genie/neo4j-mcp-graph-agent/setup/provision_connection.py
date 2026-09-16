"""Create the Unity Catalog HTTP connection and enable MCP behavior."""

from __future__ import annotations

from databricks.sdk.service.catalog import ConnectionType

from _common import (
    base_parser,
    execute_sql,
    fail,
    get_connection,
    make_context,
    ok,
    validate_identifier,
)

EXPECTED_OPTIONS = {
    "base_path": "/mcp",
    "is_mcp_connection": "true",
}
REDACTED_SECRET_OPTIONS = {"client_secret"}


def _connection_type_name(connection) -> str | None:
    value = getattr(connection, "connection_type", None)
    return getattr(value, "value", value)


def _options(connection) -> dict[str, str]:
    return dict(getattr(connection, "options", None) or {})


def _has_mcp_flag(connection) -> bool:
    options = {k.lower(): str(v).lower() for k, v in _options(connection).items()}
    properties = {
        k.lower(): str(v).lower()
        for k, v in (getattr(connection, "properties", None) or {}).items()
    }
    return (
        options.get("is_mcp_connection") == "true"
        or properties.get("is_mcp_connection") == "true"
    )


def _drift(connection) -> list[str]:
    problems: list[str] = []
    if _connection_type_name(connection) != ConnectionType.HTTP.value:
        problems.append(
            f"connection type is {_connection_type_name(connection)!r}, expected HTTP"
        )
    options = {k.lower(): str(v) for k, v in _options(connection).items()}
    for key, expected in EXPECTED_OPTIONS.items():
        actual = options.get(key)
        if actual is not None and actual.lower() != expected:
            problems.append(f"option {key} is {actual!r}, expected {expected!r}")
    for required in (
        "host",
        "base_path",
        "client_id",
        "oauth_scope",
        "token_endpoint",
    ):
        if required not in options:
            problems.append(f"connection option {required!r} is not visible")
    for redacted in REDACTED_SECRET_OPTIONS:
        actual = options.get(redacted)
        if actual is not None and actual.strip() == "":
            problems.append(f"connection option {redacted!r} is empty")
    if not _has_mcp_flag(connection):
        problems.append("is_mcp_connection flag is not true")
    return problems


def _create_sql(connection_name: str, secret_scope: str) -> str:
    return f"""
CREATE CONNECTION IF NOT EXISTS {connection_name} TYPE HTTP
OPTIONS (
  host secret('{secret_scope}', 'gateway_host'),
  base_path '/mcp',
  client_id secret('{secret_scope}', 'client_id'),
  client_secret secret('{secret_scope}', 'client_secret'),
  oauth_scope secret('{secret_scope}', 'oauth_scope'),
  token_endpoint secret('{secret_scope}', 'token_endpoint'),
  is_mcp_connection 'true'
)
""".strip()


def main() -> None:
    parser = base_parser(__doc__ or "")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Drop and recreate the connection if it already exists or drifts.",
    )
    args = parser.parse_args()
    ctx = make_context(args.profile)
    settings = ctx.settings

    validate_identifier(settings.uc_connection_name, "UC_CONNECTION_NAME")

    existing = get_connection(ctx.ws, settings.uc_connection_name)
    if existing and args.replace:
        execute_sql(settings, ctx.ws, f"DROP CONNECTION IF EXISTS {settings.uc_connection_name}")
        ok(f"dropped existing connection: {settings.uc_connection_name}")
        existing = None

    if existing:
        drift = _drift(existing)
        if drift:
            fail(
                "existing connection drift detected; rerun with --replace:\n"
                + "\n".join(f"  - {item}" for item in drift)
            )
        ok(f"connection already correct: {settings.uc_connection_name}")
    else:
        execute_sql(
            settings,
            ctx.ws,
            _create_sql(settings.uc_connection_name, settings.mcp_secret_scope),
        )
        ok(f"created connection: {settings.uc_connection_name}")

    after = get_connection(ctx.ws, settings.uc_connection_name)
    if not after:
        fail(f"connection was not found after create: {settings.uc_connection_name}")
    drift = _drift(after)
    if drift:
        fail(
            "connection exists but did not validate:\n"
            + "\n".join(f"  - {item}" for item in drift)
        )
    ok("connection validated with MCP flag enabled")


if __name__ == "__main__":
    main()
