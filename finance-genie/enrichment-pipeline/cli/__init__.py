"""Neo4j ingest CLI — wires Runner to the shared Finance Genie environment."""

from pathlib import Path

from databricks_job_runner import Runner

PIPELINE_DIR = Path(__file__).resolve().parent.parent
FINANCE_GENIE_DIR = PIPELINE_DIR.parent

runner = Runner(
    run_name_prefix="neo4j_ingest",
    project_dir=FINANCE_GENIE_DIR,
    scripts_dir="enrichment-pipeline/jobs",
    remote_scripts_dir="jobs",
    extra_files=["enrichment-pipeline/sql/gold_schema.sql"],
)
