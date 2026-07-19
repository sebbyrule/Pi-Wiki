from services.page_service import sanitize_page_path, page_exists

tool_schema = {
    "type": "function",
    "function": {
        "name": "create_page",
        "description": "Draft a NEW wiki page. This does NOT save the page — it stages a proposal that the user reviews and approves. Provide the complete Markdown content (YAML frontmatter with tags, an H1 title, a TL;DR blockquote, body sections, and a ## Review section with flashcards). After calling this, briefly tell the user what you drafted.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The new page path/slug, e.g. 'linux/systemd' or 'stoicism'."},
                "content": {"type": "string", "description": "The complete Markdown document to write."}
            },
            "required": ["path", "content"]
        }
    }
}


def run(path: str, content: str, **kwargs):
    safe = sanitize_page_path(path)
    if not safe:
        return {"status": "error", "message": "Invalid page path."}
    if not (content or "").strip():
        return {"status": "error", "message": "No content provided."}
    exists = page_exists(safe)
    return {
        "status": "proposal",
        "action": "create",
        "path": safe,
        "content": content,
        "exists": exists,
        "summary": f"{'Overwrite' if exists else 'Create'} /wiki/{safe}",
    }
