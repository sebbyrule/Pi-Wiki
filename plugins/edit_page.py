from services.page_service import sanitize_page_path, page_exists

tool_schema = {
    "type": "function",
    "function": {
        "name": "edit_page",
        "description": "Propose an edit to an EXISTING wiki page. This does NOT save — it stages a proposal for the user to review and approve. First call read_page to get the current content, then provide the COMPLETE new Markdown (not a diff). After calling this, briefly tell the user what you changed.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The page path/slug to edit, e.g. 'linux/docker'."},
                "content": {"type": "string", "description": "The complete revised Markdown document (full replacement)."}
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
        "action": "edit",
        "path": safe,
        "content": content,
        "exists": exists,
        "summary": f"{'Edit' if exists else 'Create'} /wiki/{safe}",
    }
