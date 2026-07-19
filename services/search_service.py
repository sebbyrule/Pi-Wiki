import re
from core.config import ARTICLES_DIR

# Strip YAML frontmatter so it doesn't pollute snippets / matches.
_FRONTMATTER = re.compile(r'^\s*---\r?\n.*?\r?\n---\r?\n', re.DOTALL)

# Match-type ranking: title hits first, then body hits, then semantic-only.
_RANK = {"title": 0, "content": 1, "semantic": 2}


def _page_name(path):
    return path.relative_to(ARTICLES_DIR).with_suffix("").as_posix()


def _title(name):
    return name.split("/")[-1].replace("-", " ").replace("_", " ").strip().title()


def _snippet(body, query, width=160):
    """Return a short excerpt around the first case-insensitive match, or the
    document's opening line if the query isn't found literally."""
    low = body.lower()
    idx = low.find(query.lower())
    if idx == -1:
        return " ".join(body.split())[:width].strip()
    start = max(0, idx - width // 2)
    end = min(len(body), idx + len(query) + width // 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(body) else ""
    return prefix + " ".join(body[start:end].split()) + suffix


def keyword_search(query):
    """Scan every article for a literal (case-insensitive) match in its name or
    body. Returns {page_name: result_dict}."""
    q = query.lower()
    hits = {}
    for path in ARTICLES_DIR.rglob("*.md"):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        name = _page_name(path)
        body = _FRONTMATTER.sub("", raw)

        in_name = q in name.lower() or q in _title(name).lower()
        in_body = q in body.lower()
        if not (in_name or in_body):
            continue

        hits[name] = {
            "name": name,
            "title": _title(name),
            "snippet": _snippet(body, query),
            "match": "title" if in_name else "content",
        }
    return hits


def semantic_search(query, n_results=5):
    """Vector-similarity matches from Chroma. Imported lazily so a search that is
    purely keyword-based never pays the embedding-model startup cost, and so a
    Chroma hiccup can't take the whole search page down."""
    try:
        from services.rag_service import query_knowledge_base
        results = query_knowledge_base(query, n_results=n_results)
    except Exception as e:  # pragma: no cover - defensive
        print(f"[Search] Semantic search unavailable: {e}")
        return {}

    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]

    hits = {}
    for doc, meta in zip(documents, metadatas):
        name = (meta or {}).get("source")
        if not name or name in hits:
            continue
        hits[name] = {
            "name": name,
            "title": _title(name),
            "snippet": " ".join(doc.split())[:160].strip(),
            "match": "semantic",
        }
    return hits


def search_wiki(query, limit=50):
    """Hybrid search: literal keyword hits (title/content) merged with semantic
    neighbours, deduped by page and ranked title -> content -> semantic."""
    query = (query or "").strip()
    if not query:
        return []

    merged = keyword_search(query)
    for name, hit in semantic_search(query).items():
        merged.setdefault(name, hit)  # keyword hit for a page always wins

    ordered = sorted(merged.values(), key=lambda r: (_RANK[r["match"]], r["name"]))
    return ordered[:limit]
