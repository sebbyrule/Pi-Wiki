import json
import os
import sys
from pathlib import Path
from fastapi.templating import Jinja2Templates

# Path Setup
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
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


def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).strip().lower() in ("1", "true", "yes", "on")


# --- Centralized Environment Variables ---
# We use os.getenv() with a safe default fallback in case .env is missing a line.
# IMPORTANT: consumers should read these as `core.config.LOCAL_AI_URL` (module
# attribute) rather than `from core.config import LOCAL_AI_URL` so that runtime
# updates via update_config_env() are actually picked up (see #settings-update).
LOCAL_AI_URL = os.getenv("LOCAL_AI_URL", "http://host.docker.internal:1234/v1/chat/completions")
LOCAL_AI_MODEL = os.getenv("LOCAL_AI_MODEL", "local-model")
MAX_AI_TOKENS = int(os.getenv("MAX_AI_TOKENS", "20000"))

# External UI Links
HOMELAB_DASHBOARD_URL = os.getenv("HOMELAB_DASHBOARD_URL", "/")
GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL", "https://github.com")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@localhost")

# --- Access / Security ---
# Credentials come from the environment (.env). Defaults stay as admin/admin only
# for first-run convenience; a warning is printed so it is never silently shipped.
ADMIN_USER = os.getenv("WIKI_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("WIKI_ADMIN_PASSWORD", "admin")

# The arbitrary-shell terminal endpoint is dangerous (RCE) and OFF by default.
# Set ALLOW_TERMINAL=true in .env to opt in on a trusted, network-isolated host.
ALLOW_TERMINAL = _env_bool("ALLOW_TERMINAL", False)

# When true, raw exception details are surfaced to the browser UI. Off in prod.
DEBUG_MODE = _env_bool("DEBUG_MODE", False)

if ADMIN_USER == "admin" and ADMIN_PASS == "admin":
    print(
        "[SECURITY WARNING] Pi Wiki is running with the default admin/admin "
        "credentials. Set WIKI_ADMIN_USER and WIKI_ADMIN_PASSWORD in .env.",
        file=sys.stderr,
    )

# Ensure state file exists
if not DATA_FILE.exists():
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Keys that update_config_env is allowed to touch, mapped to a coercion function
# used when refreshing the in-process module attribute of the same name.
_UPDATABLE_KEYS = {
    "LOCAL_AI_URL": str,
    "LOCAL_AI_MODEL": str,
    "HOMELAB_DASHBOARD_URL": str,
    "MAX_AI_TOKENS": int,
}


def _persist_to_env_file(key: str, value: str) -> None:
    """Upsert KEY=value in the .env file so the change survives a restart."""
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    except OSError:
        lines = []

    replaced = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_config_env(key: str, value: str):
    """Persist a setting to .env, update the process environment, and refresh the
    live module attribute so the running app uses the new value immediately."""
    if key not in _UPDATABLE_KEYS:
        raise ValueError(f"Refusing to update unknown config key: {key!r}")

    value = str(value)
    coerce = _UPDATABLE_KEYS[key]
    coerced = coerce(value)  # validate before persisting (e.g. MAX_AI_TOKENS must be int)

    os.environ[key] = value
    _persist_to_env_file(key, value)
    # Refresh this module's attribute so `core.config.<KEY>` reflects the change.
    globals()[key] = coerced
    return coerced
