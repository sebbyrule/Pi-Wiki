import json
import os
from pathlib import Path
from fastapi.templating import Jinja2Templates

# Path Setup
BASE_DIR = Path(__file__).resolve().parent.parent
ARTICLES_DIR = BASE_DIR / "articles"
INBOX_DIR = BASE_DIR / "inbox"
CHROMA_DIR = BASE_DIR / "chroma_db"
PLUGINS_DIR = BASE_DIR / "plugins"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"
DATA_FILE = BASE_DIR / "progress.json"

# Ensure directories exist
for d in [ARTICLES_DIR, INBOX_DIR, CHROMA_DIR, PLUGINS_DIR, STATIC_DIR, IMAGES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# --- NEW: Centralized Environment Variables ---
# We use os.getenv() with a safe default fallback just in case the .env is missing a line
LOCAL_AI_URL = os.getenv("LOCAL_AI_URL", "http://host.docker.internal:1234/v1/chat/completions")

# External UI Links
HOMELAB_DASHBOARD_URL = os.getenv("HOMELAB_DASHBOARD_URL", "/")
GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL", "https://github.com")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@localhost")

# Ensure state file exists
if not DATA_FILE.exists():
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

def update_config_env(key: str, value: str):
    """Updates the environment variables for the current session."""
    os.environ[key] = value