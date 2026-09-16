from pathlib import Path

app_name = "graph-fraud-analyst"
app_entrypoint = "graph_fraud_analyst.backend.app:app"
app_slug = "graph_fraud_analyst"
api_prefix = "/api"
dist_dir = Path(__file__).parent / "__dist__"