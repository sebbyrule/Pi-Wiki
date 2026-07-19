from services.page_service import read_page, sanitize_page_path

tool_schema = {
    "type": "function",
    "function": {
        "name": "read_page",
        "description": "Read the full Markdown content of an existing wiki page. Use this before proposing edits so you can preserve the existing content, or to answer questions about a specific page.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The page path/slug, e.g. 'linux/docker' or 'index'."}
            },
            "required": ["path"]
        }
    }
}


def run(path: str, **kwargs):
    content = read_page(path)
    if content is None:
        return {"status": "error", "message": f"Page '{path}' does not exist."}
    # Cap to keep the tool result from blowing the context window.
    return {"status": "success", "path": sanitize_page_path(path), "content": content[:8000]}
