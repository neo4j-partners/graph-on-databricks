"""dbxcarta preset for the Finance Genie Lakehouse consumer.

Per-integration dbxcarta config lives in the committed dbxcarta-overlay.env beside
this package, and the bundled questions.json is the only per-integration data. The
shared StandardPreset provides the readiness check and the question upload, so this
preset is just StandardPreset bound to this project's questions.json.

Resolvable via:
    uv run dbxcarta preset finance_genie_dbxcarta:preset --check-ready
    uv run dbxcarta preset finance_genie_dbxcarta:preset --upload-questions
"""

from __future__ import annotations

from pathlib import Path

from dbxcarta.core.presets import StandardPreset

preset = StandardPreset(questions_file=Path(__file__).resolve().parents[2] / "questions.json")

__all__ = ["preset"]
