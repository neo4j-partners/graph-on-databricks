import os
import tempfile
from pathlib import Path

_TRACKING_DIR = Path(tempfile.mkdtemp(prefix="mlflow-tests-"))
os.environ.setdefault("MLFLOW_TRACKING_URI", f"sqlite:///{_TRACKING_DIR / 'mlflow.db'}")
