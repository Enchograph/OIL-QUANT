from pathlib import Path
import os
import sys


BASE_DIR = Path(__file__).resolve().parent
VENDOR_DIR = BASE_DIR / ".vendor"
ROOT_DIR = BASE_DIR.parent

if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from backend.api_service import create_app
from backend.logging_utils import configure_backend_logging


configure_backend_logging()
app = create_app()


if __name__ == "__main__":
    host = os.getenv("BACKEND_HOST", "127.0.0.1")
    port = int(os.getenv("BACKEND_PORT", "5001"))
    debug = os.getenv("BACKEND_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
