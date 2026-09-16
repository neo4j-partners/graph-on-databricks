"""Validate the configured Databricks embedding endpoint without storing data."""

from __future__ import annotations

import json

from config import load_demo_env, require_env


def main() -> None:
    """Create one probe embedding and report only non-sensitive metadata."""
    load_demo_env()
    model = require_env("EMBEDDING_MODEL")
    if not model.startswith("databricks/"):
        raise RuntimeError("EMBEDDING_MODEL must use the databricks/ provider prefix")

    import litellm

    response = litellm.embedding(
        model=model,
        input=["shared identity investigation"],
    )
    vector = response.data[0]["embedding"]
    if not vector:
        raise RuntimeError("Databricks embedding endpoint returned an empty vector")

    print(
        json.dumps(
            {
                "status": "passed",
                "provider": "databricks",
                "model": model.removeprefix("databricks/"),
                "vectors": len(response.data),
                "dimensions": len(vector),
                "data_stored": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
