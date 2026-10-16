import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("GOV_DATA_DIR", ROOT / ".data-v3")).resolve()
LOCAL_AUTO_LOGIN = os.environ.get("LOCAL_AUTO_LOGIN", "true").lower() == "true"
PORT = int(os.environ.get("PORT", "4173"))
JOB_TIMEOUT = min(45, max(0.1, float(os.environ.get("JOB_TIMEOUT_SECONDS", "45"))))
