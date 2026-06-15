import re
import markdown
from pathlib import Path
from core.config import ARTICLES_DIR

def get_available_pages() -> list[str]:
    if not ARTICLES_DIR.exists(): return []
    # Upgraded to rglob to support the new nested folder system
    pages = []
    for f in ARTICLES_DIR.rglob("*.md"):
        pages.append(f.relative_to(ARTICLES_DIR).with_suffix("").as_posix())
    return sorted(pages)

def get_backlinks(target_page: str) -> list[str]:
    backlinks = []
    pattern = re.compile(r'\[\[' + re.escape(target_page).replace(r'\-', r'[\-\s]') + r'\]\]', re.IGNORECASE)
    
    # Upgraded to rglob to support nested folder linking
    for file_path in ARTICLES_DIR.rglob("*.md"):
        rel_path = file_path.relative_to(ARTICLES_DIR).with_suffix("").as_posix()
        if rel_path == target_page: continue
        if pattern.search(file_path.read_text(encoding="utf-8")):
            backlinks.append(rel_path)
    return backlinks

def render_markdown_file(file_path: Path):
    text = file_path.read_text(encoding="utf-8")
    text = re.sub(r'\[\[(.*?)\]\]', lambda m: f"[{m.group(1)}](/wiki/{m.group(1).lower().replace(' ', '-')})", text)
    text = re.sub(r':::Q\r?\n(.*?)\r?\n:::A\r?\n(.*?)\r?\n:::', r'> **Q:** \1  \n> **A:** \2', text, flags=re.DOTALL)
    
    md = markdown.Markdown(extensions=["extra", "codehilite", "toc", "meta"])
    html = md.convert(text)
    toc = md.toc
    
    tags = []
    for tag_str in md.Meta.get("tags", []):
        # THE FIX: strip(" []") deletes spaces AND square brackets from the edges!
        tags.extend([t.strip(" []").lower() for t in tag_str.split(",")])
    return html, tags, toc

def get_all_tags() -> dict:
    tag_map = {}
    for file_path in ARTICLES_DIR.rglob("*.md"): # Upgraded to rglob
        rel_path = file_path.relative_to(ARTICLES_DIR).with_suffix("").as_posix()
        md = markdown.Markdown(extensions=["meta"])
        md.convert(file_path.read_text(encoding="utf-8"))
        
        for tag_str in md.Meta.get("tags", []):
            # THE FIX: strip(" []") deletes spaces AND square brackets!
            for tag in [t.strip(" []").lower() for t in tag_str.split(",")]:
                if tag: tag_map.setdefault(tag, []).append(rel_path)
    return tag_map