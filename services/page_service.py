"""Shared helpers for reading and writing wiki pages.

Used by the chat write-tools (which only *propose* changes) and the
/api/pages/apply endpoint (which actually writes on user approval). Keeping the
path sanitization in one place means the tool preview and the real write can
never disagree, and traversal is blocked in a single audited spot.
"""
import re
from pathlib import Path
from core.config import ARTICLES_DIR
from services.git_service import commit_changes
from services.rag_service import embed_document

_ARTICLES_ROOT = ARTICLES_DIR.resolve()


def sanitize_page_path(raw: str) -> str:
    """Normalize a user/LLM-supplied page path to a safe relative slug.

    Lowercases, drops any .md extension, keeps only [a-z0-9-_/], collapses
    repeated slashes, and strips leading/trailing slashes. Because dots are
    removed, `..` segments cannot survive, so traversal is impossible.
    """
    raw = (raw or "").strip().lower()
    if raw.endswith(".md"):
        raw = raw[:-3]
    safe = "".join(c for c in raw if c.isalnum() or c in ("-", "_", "/"))
    safe = re.sub(r"/+", "/", safe).strip("/")
    return safe


def slugify_title(title: str) -> str:
    """Turn a human title into a page slug: lowercase, non-alphanumeric runs
    become single hyphens (unlike sanitize_page_path, which drops spaces)."""
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")


def page_file(path: str) -> Path:
    """Resolve a sanitized page path to its .md file, guaranteeing the result
    stays inside the articles directory (defense in depth)."""
    safe = sanitize_page_path(path)
    if not safe:
        raise ValueError("Empty or invalid page path.")
    fp = (ARTICLES_DIR / f"{safe}.md").resolve()
    if _ARTICLES_ROOT != fp.parent and _ARTICLES_ROOT not in fp.parents:
        raise ValueError("Resolved path escapes the articles directory.")
    return fp


def page_exists(path: str) -> bool:
    try:
        return page_file(path).exists()
    except ValueError:
        return False


def read_page(path: str):
    """Return the raw markdown of a page, or None if it does not exist."""
    try:
        fp = page_file(path)
    except ValueError:
        return None
    return fp.read_text(encoding="utf-8") if fp.exists() else None


def write_page(path: str, content: str, message: str) -> str:
    """Write a page, embed it into the vector store, and commit. Returns the
    sanitized slug that was written."""
    safe = sanitize_page_path(path)
    fp = page_file(safe)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    embed_document(safe, content)
    commit_changes(message)
    return safe
