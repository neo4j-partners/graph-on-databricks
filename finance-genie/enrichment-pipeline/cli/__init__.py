"""Neo4j ingest CLI — wires Runner to the shared Finance Genie environment."""

from pathlib import Path

from cli.secure_runner import SecureRunner

PIPELINE_DIR = Path(__file__).resolve().parent.parent
FINANCE_GENIE_DIR = PIPELINE_DIR.parent

JOB_PARAMETER_KEYS = frozenset(
    {
        "CATALOG",
        "GENIE_SPACE_ID_AFTER",
        "GENIE_SPACE_ID_BEFORE",
        "GENIE_TEST_RETRIES",
        "GENIE_TEST_TIMEOUT_SECONDS",
        "GOLD_CATALOG",
        "GROUND_TRUTH_PATH",
        "NEO4J_READ_PARTITIONS",
        "NEO4J_SECRET_SCOPE",
        "RESULTS_VOLUME_DIR",
        "SAMPLERS",
        "SCHEMA",
        "SILVER_CATALOG",
    }
)

runner = SecureRunner(
    run_name_prefix="neo4j_ingest",
    project_dir=FINANCE_GENIE_DIR,
    parameter_keys=JOB_PARAMETER_KEYS,
    scripts_dir="enrichment-pipeline/jobs",
    remote_scripts_dir="jobs",
    extra_files=["enrichment-pipeline/sql/gold_schema.sql"],
)
