import json
from pathlib import Path
from fastapi.templating import Jinja2Templates

# Path Setup
BASE_DIR = Path(__file__).resolve().parent.parent
ARTICLES_DIR = BASE_DIR / "articles"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"
DATA_FILE = BASE_DIR / "progress.json"

# Ensure directories exist
for d in [ARTICLES_DIR, STATIC_DIR, IMAGES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Ensure state file exists
if not DATA_FILE.exists():
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))