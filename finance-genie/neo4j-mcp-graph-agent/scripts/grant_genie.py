"""Grant the app's service principal what its Genie tool needs. Idempotent; changes permissions.

`agentbricks deploy` gives the app CAN_RUN on the Genie space, but Genie runs its SQL as the app, so
the app also needs these grants:

- CAN_USE on the space's SQL warehouse
- USE_CATALOG on each catalog that holds the space's tables
- USE_SCHEMA and SELECT on each schema that holds the space's tables

The space ids come from the genie_agent tools in agent.toml. Each grant is printed before it runs,
and a grant the service principal already has is skipped.

    uv run python scripts/grant_genie.py --profile PROFILE --app APP [--dry-run]
"""

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.catalog import PermissionsChange, Privilege
from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel

ROOT = Path(__file__).resolve().parents[1]
AGENT_TOML = ROOT / "agent.toml"
# Warehouse levels that include CAN_USE.
WAREHOUSE_USE_LEVELS = {
    PermissionLevel.CAN_USE, PermissionLevel.CAN_MANAGE, PermissionLevel.IS_OWNER
}


@dataclass(frozen=True)
class Grant:
    securable_type: str  # "warehouse", "catalog", or "schema"
    name: str
    privilege: str

    def __str__(self) -> str:
        return f"{self.privilege} on {self.securable_type} {self.name}"


def genie_space_ids(agent_toml: str) -> list[str]:
    """The space ids of the genie_agent tools in agent.toml."""
    tools = tomllib.loads(agent_toml).get("tools", [])
    return [
        tool["source"]["space_id"]
        for tool in tools
        if tool.get("source", {}).get("kind") == "genie_agent"
    ]


def space_schemas(serialized_space: str) -> list[str]:
    """The `catalog.schema` names that hold the space's tables, in sorted order."""
    tables = json.loads(serialized_space).get("data_sources", {}).get("tables", [])
    return sorted({table["identifier"].rsplit(".", 1)[0] for table in tables})


def planned_grants(warehouse_ids: list[str], schemas: list[str]) -> list[Grant]:
    grants = [Grant("warehouse", warehouse_id, "CAN_USE") for warehouse_id in warehouse_ids]
    catalogs = sorted({schema.split(".", 1)[0] for schema in schemas})
    grants += [Grant("catalog", catalog, "USE_CATALOG") for catalog in catalogs]
    for schema in schemas:
        grants += [Grant("schema", schema, "USE_SCHEMA"), Grant("schema", schema, "SELECT")]
    return grants


def has_grant(w: WorkspaceClient, principal: str, grant: Grant) -> bool:
    if grant.securable_type == "warehouse":
        acl = w.permissions.get("warehouses", grant.name).access_control_list or []
        return any(
            entry.service_principal_name == principal
            and any(p.permission_level in WAREHOUSE_USE_LEVELS for p in entry.all_permissions or [])
            for entry in acl
        )
    current = w.grants.get(grant.securable_type, grant.name, principal=principal)
    privileges = {
        str(getattr(p, "value", p))
        for assignment in current.privilege_assignments or []
        for p in assignment.privileges or []
    }
    return grant.privilege in privileges or "ALL_PRIVILEGES" in privileges


def apply_grant(w: WorkspaceClient, principal: str, grant: Grant) -> None:
    if grant.securable_type == "warehouse":
        w.permissions.update(
            "warehouses",
            grant.name,
            access_control_list=[
                AccessControlRequest(
                    service_principal_name=principal, permission_level=PermissionLevel.CAN_USE
                )
            ],
        )
        return
    w.grants.update(
        grant.securable_type,
        grant.name,
        changes=[PermissionsChange(principal=principal, add=[Privilege(grant.privilege)])],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--dry-run", action="store_true", help="print the grants, change nothing")
    args = parser.parse_args(argv)

    space_ids = genie_space_ids(AGENT_TOML.read_text())
    if not space_ids:
        print("agent.toml has no genie_agent tool. Nothing to grant.")
        return 0

    w = WorkspaceClient(profile=args.profile)
    warehouse_ids: list[str] = []
    schemas: list[str] = []
    for space_id in space_ids:
        space = w.genie.get_space(space_id, include_serialized_space=True)
        print(f"Genie space {space_id} ({space.title}): warehouse {space.warehouse_id}")
        warehouse_ids.append(space.warehouse_id)
        schemas += space_schemas(space.serialized_space or "{}")
    grants = planned_grants(sorted(set(warehouse_ids)), sorted(set(schemas)))

    try:
        principal = w.apps.get(args.app).service_principal_client_id
    except NotFound:
        if not args.dry_run:
            print(f"App {args.app} not found. Run make deploy first.", file=sys.stderr)
            return 1
        print(f"App {args.app} not found, so this dry run cannot check existing grants.")
        for grant in grants:
            print(f"Would grant {grant} to the app's service principal")
        return 0

    print(f"App {args.app} service principal: {principal}")
    for grant in grants:
        if has_grant(w, principal, grant):
            print(f"Already granted: {grant}")
        elif args.dry_run:
            print(f"Would grant: {grant}")
        else:
            print(f"Granting: {grant}")
            apply_grant(w, principal, grant)
    return 0


if __name__ == "__main__":
    sys.exit(main())
