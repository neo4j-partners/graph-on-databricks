# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "neo4j>=5.20",
#     "python-dotenv>=1.0",
# ]
# ///
"""Validate that .env contains working Neo4j Aura credentials.

Run from this directory:

    uv run validate_neo4j.py

Exits 0 on success, 1 on failure.
"""

from __future__ import annotations

import os

from _common import fail, load_env
from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable

REQUIRED_VARS = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")


def main() -> None:
    load_env(REQUIRED_VARS)

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]

    print("OK    .env loaded")
    print(f"OK    NEO4J_URI      = {uri}")
    print(f"OK    NEO4J_USERNAME = {user}")
    print(f"OK    NEO4J_PASSWORD = <{len(password)} chars>")

    try:
        with GraphDatabase.driver(uri, auth=(user, password)) as driver:
            driver.verify_connectivity()
            print("OK    verify_connectivity() succeeded")

            with driver.session() as session:
                record = session.run("RETURN 1 AS ok").single(strict=True)
                if not record or record["ok"] != 1:
                    fail("test query did not return 1")
                print("OK    test query RETURN 1 returned 1")

                components = session.run(
                    "CALL dbms.components() YIELD name, versions, edition "
                    "RETURN name, versions[0] AS version, edition"
                )
                info = next(iter(components), None)
                if info:
                    print(
                        f"OK    server: {info['name']} "
                        f"{info['version']} ({info['edition']})"
                    )
    except AuthError as e:
        fail(f"authentication failed — check NEO4J_USERNAME / NEO4J_PASSWORD: {e}")
    except ServiceUnavailable as e:
        fail(f"cannot reach server — check NEO4J_URI / network: {e}")
    except (Neo4jError, ValueError) as e:
        fail(f"Neo4j validation failed: {e}")

    print("\nPASS  Neo4j credentials in .env are valid and working.")


if __name__ == "__main__":
    main()
