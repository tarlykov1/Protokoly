from pathlib import Path
import os
BASE_DIR = Path(os.getenv("PROTOCOL_DASHBOARD_BASE_DIR", "/webapp/app"))
RUNTIME_DIR = Path(os.getenv("PROTOCOL_DASHBOARD_RUNTIME_DIR", str(BASE_DIR / "runtime" / "protocol_dashboard")))
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
REPORT_TTL_HOURS = int(os.getenv("PROTOCOL_DASHBOARD_TTL_HOURS", "6"))
API_TOKEN = os.getenv("PROTOCOL_DASHBOARD_TOKEN")
