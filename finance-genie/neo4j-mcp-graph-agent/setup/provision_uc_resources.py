"""Create Unity Catalog resources for the Neo4j MCP agent model."""

from __future__ import annotations

from databricks.sdk.errors import NotFound, ResourceAlreadyExists

from _common import base_parser, make_context, ok, validate_identifier


def main() -> None:
    parser = base_parser(__doc__ or "")
    args = parser.parse_args()
    ctx = make_context(args.profile)
    settings = ctx.settings

    validate_identifier(settings.catalog, "CATALOG")
    validate_identifier(settings.schema_name, "SCHEMA")

    try:
        ctx.ws.catalogs.get(settings.catalog)
        ok(f"catalog already exists: {settings.catalog}")
    except NotFound:
        try:
            ctx.ws.catalogs.create(
                name=settings.catalog,
                comment="Neo4j MCP graph-agent assets.",
            )
            ok(f"created catalog: {settings.catalog}")
        except ResourceAlreadyExists:
            ok(f"catalog already exists: {settings.catalog}")

    full_schema = f"{settings.catalog}.{settings.schema_name}"
    try:
        ctx.ws.schemas.get(full_schema)
        ok(f"schema already exists: {full_schema}")
    except NotFound:
        try:
            ctx.ws.schemas.create(
                name=settings.schema_name,
                catalog_name=settings.catalog,
                comment="Neo4j MCP graph-agent models.",
            )
            ok(f"created schema: {full_schema}")
        except ResourceAlreadyExists:
            ok(f"schema already exists: {full_schema}")


if __name__ == "__main__":
    main()
