import re
import markdown
from pathlib import Path
from core.config import ARTICLES_DIR

def get_available_pages() -> list[str]:
    if not ARTICLES_DIR.exists(): return []
    return sorted([f.stem for f in ARTICLES_DIR.glob("*.md")])

def get_backlinks(target_page: str) -> list[str]:
    backlinks = []
    pattern = re.compile(r'\[\[' + re.escape(target_page).replace(r'\-', r'[\-\s]') + r'\]\]', re.IGNORECASE)
    for file_path in ARTICLES_DIR.glob("*.md"):
        if file_path.stem == target_page: continue
        if pattern.search(file_path.read_text(encoding="utf-8")):
            backlinks.append(file_path.stem)
    return backlinks

def render_markdown_file(file_path: Path):
    text = file_path.read_text(encoding="utf-8")
    text = re.sub(r'\[\[(.*?)\]\]', lambda m: f"[{m.group(1)}](/wiki/{m.group(1).lower().replace(' ', '-')})", text)
    text = re.sub(r':::Q\n(.*?)\n:::A\n(.*?)\n:::', r'> **Q:** \1  \n> **A:** \2', text, flags=re.DOTALL)
    
    md = markdown.Markdown(extensions=["extra", "codehilite", "toc", "meta"])
    html = md.convert(text)
    toc = md.toc
    
    tags = []
    for tag_str in md.Meta.get("tags", []):
        tags.extend([t.strip().lower() for t in tag_str.split(",")])
    return html, tags, toc

def get_all_tags() -> dict:
    tag_map = {}
    for file_path in ARTICLES_DIR.glob("*.md"):
        md = markdown.Markdown(extensions=["meta"])
        md.convert(file_path.read_text(encoding="utf-8"))
        for tag_str in md.Meta.get("tags", []):
            for tag in [t.strip().lower() for t in tag_str.split(",")]:
                if tag: tag_map.setdefault(tag, []).append(file_path.stem)
    return tag_map