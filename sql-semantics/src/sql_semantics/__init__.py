"""Reference dbxcarta preset for the Finance Genie Lakehouse example.

Pass `sql_semantics:preset` to the dbxcarta CLI:

    uv run dbxcarta preset sql_semantics:preset --print-env
    uv run dbxcarta preset sql_semantics:preset --check-ready --strict-optional
    uv run dbxcarta preset sql_semantics:preset --upload-questions
"""

from sql_semantics.finance_genie import preset

__all__ = ["preset"]
