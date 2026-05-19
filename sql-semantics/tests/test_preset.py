from __future__ import annotations

import pytest

import sql_semantics.finance_genie as preset_module
from dbxcarta.client.presets import (
    QuestionsUploadable,
    ReadinessCheckable,
    ReadinessReport,
)
from dbxcarta.spark import SparkIngestSettings
from dbxcarta.spark.loader import load_preset
from dbxcarta.spark.presets import Preset
from sql_semantics.finance_genie import (
    FinanceGeniePreset,
    _EXPECTED_TABLES,
    preset,
)


def test_preset_satisfies_required_protocol() -> None:
    assert isinstance(preset, Preset)


def test_preset_satisfies_optional_capabilities() -> None:
    assert isinstance(preset, ReadinessCheckable)
    assert isinstance(preset, QuestionsUploadable)


def test_minimal_preset_satisfies_required_protocol_alone() -> None:
    """A preset that only implements env() must still pass the Preset check."""

    class MinimalPreset:
        def env(self) -> dict[str, str]:
            return {"DBXCARTA_CATALOG": "c"}

    minimal = MinimalPreset()
    assert isinstance(minimal, Preset)
    assert not isinstance(minimal, ReadinessCheckable)
    assert not isinstance(minimal, QuestionsUploadable)


def test_preset_resolvable_via_import_path() -> None:
    resolved = load_preset("sql_semantics:preset")
    assert resolved is preset


def test_env_overlay_validates_against_settings() -> None:
    env = preset.env()
    settings = SparkIngestSettings(
        dbxcarta_catalog=env["DBXCARTA_CATALOG"],
        dbxcarta_schemas=env["DBXCARTA_SCHEMAS"],
        dbxcarta_summary_volume=env["DBXCARTA_SUMMARY_VOLUME"],
        dbxcarta_summary_table=env["DBXCARTA_SUMMARY_TABLE"],
        dbxcarta_include_values=env["DBXCARTA_INCLUDE_VALUES"] == "true",
        dbxcarta_include_embeddings_tables=True,
        dbxcarta_include_embeddings_columns=True,
        dbxcarta_include_embeddings_values=True,
        dbxcarta_include_embeddings_schemas=True,
        dbxcarta_include_embeddings_databases=True,
        dbxcarta_infer_semantic=True,
        dbxcarta_embedding_endpoint=env["DBXCARTA_EMBEDDING_ENDPOINT"],
        dbxcarta_embedding_dimension=int(env["DBXCARTA_EMBEDDING_DIMENSION"]),
        dbxcarta_embedding_failure_threshold=float(
            env["DBXCARTA_EMBEDDING_FAILURE_THRESHOLD"]
        ),
    )
    assert settings.dbxcarta_catalog == "graph-enriched-lakehouse"
    assert settings.dbxcarta_schemas == "graph-enriched-schema"


def test_env_overlay_pins_known_keys() -> None:
    env = preset.env()
    assert env["DBXCARTA_INJECT_CRITERIA"] == "false"
    assert env["DBXCARTA_CLIENT_ARMS"] == "no_context,schema_dump,graph_rag"
    assert env["DBXCARTA_INFER_SEMANTIC"] == "true"
    assert env["DBXCARTA_EMBEDDING_FAILURE_THRESHOLD"] == "0.10"
    assert env["DBXCARTA_CLIENT_QUESTIONS"].endswith("/dbxcarta/questions.json")


def test_volume_path_is_volumes_subpath() -> None:
    assert preset.volume_path.startswith("/Volumes/")
    assert preset.volume_path.count("/") == 4


def test_readiness_all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        preset_module, "_fetch_table_names",
        lambda ws, wh, c, s: list(_EXPECTED_TABLES),
    )
    report = preset.readiness(ws=None, warehouse_id="abc")  # type: ignore[arg-type]
    assert report.ok(strict_optional=True)
    assert report.missing_required == ()
    assert report.missing_optional == ()
    assert len(report.present) == len(_EXPECTED_TABLES)


def test_readiness_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        preset_module, "_fetch_table_names",
        lambda ws, wh, c, s: ["accounts", "merchants"],
    )
    report = preset.readiness(ws=None, warehouse_id="abc")  # type: ignore[arg-type]
    assert not report.ok()
    assert set(report.missing_required) == {"transactions", "account_links", "account_labels"}


def test_readiness_missing_optional_lenient_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preset_module, "_fetch_table_names",
        lambda ws, wh, c, s: [
            "accounts", "merchants", "transactions",
            "account_links", "account_labels",
        ],
    )
    report = preset.readiness(ws=None, warehouse_id="abc")  # type: ignore[arg-type]
    assert report.ok()
    assert not report.ok(strict_optional=True)
    assert set(report.missing_optional) == {
        "gold_accounts",
        "gold_account_similarity_pairs",
        "gold_fraud_ring_communities",
    }


def test_readiness_report_format_contains_expected_lines() -> None:
    report = ReadinessReport(
        catalog="c",
        schema="s",
        present=("a", "b"),
        missing_required=("x",),
        missing_optional=("y",),
    )
    formatted = report.format()
    assert "scope: c.s" in formatted
    assert "missing required: x" in formatted
    assert "status: not ready" in formatted


def test_preset_rejects_invalid_identifier() -> None:
    with pytest.raises(ValueError):
        FinanceGeniePreset(catalog="invalid catalog name with spaces")
