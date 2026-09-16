from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, AsyncGenerator, TypeAlias

from fastapi import FastAPI, Request
from neo4j import Driver, GraphDatabase

from ._base import LifespanDependency
from ._config import AppConfig, logger


class _Neo4jDriverDependency(LifespanDependency):
    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        config: AppConfig = app.state.config

        if not (config.neo4j_uri and config.neo4j_username and config.neo4j_password):
            logger.warning(
                "Neo4j config incomplete (NEO4J_URI/USERNAME/PASSWORD); "
                "the driver will not be created. Cypher-backed endpoints will 500."
            )
            app.state.neo4j_driver = None
            yield
            return

        driver = GraphDatabase.driver(
            config.neo4j_uri,
            auth=(config.neo4j_username, config.neo4j_password),
            max_connection_pool_size=20,
            connection_acquisition_timeout=30,
        )
        try:
            driver.verify_connectivity()
            logger.info(f"Connectivity verified to {config.neo4j_uri}")
        except Exception as e:
            logger.error(f"Neo4j connectivity check failed: {e}")
            driver.close()
            raise

        app.state.neo4j_driver = driver
        try:
            yield
        finally:
            driver.close()

    @staticmethod
    def __call__(request: Request) -> Driver:
        driver = request.app.state.neo4j_driver
        if driver is None:
            raise RuntimeError(
                "Neo4j driver is not configured. Set NEO4J_URI, NEO4J_USERNAME, "
                "and NEO4J_PASSWORD via the neo4j-graph-engineering secret scope."
            )
        return driver


Neo4jDriverDependency: TypeAlias = Annotated[
    Driver, _Neo4jDriverDependency.depends()
]
