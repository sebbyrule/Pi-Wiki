import shutil
import subprocess
import platform
import json
import os
import httpx
import base64
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Request
from fastapi.responses import JSONResponse, FileResponse
import core.config as config
from core.config import ARTICLES_DIR, IMAGES_DIR, STATIC_DIR, INBOX_DIR, update_config_env
from core.security import verify_user
from services.git_service import commit_changes
from services.sm2_service import SM2Score, update_card_score
from services.graph_service import build_graph_data
from services.markdown_service import render_markdown_file
from services.ai_service import process_inbox_files
from services.rag_service import embed_document, query_knowledge_base, retrieve_context
from services.plugin_service import load_plugins
from pydantic import BaseModel
# LOCAL_AI_URL = os.getenv("LOCAL_AI_URL", "http://host.docker.internal:1234/v1/chat/completions")
router = APIRouter()

class CommandRequest(BaseModel):
    command: str

class SaveOutputRequest(BaseModel):
    filename: str
    content: str
    
class ChatQuery(BaseModel):
    query: str

class LinkSuggestionRequest(BaseModel):
    text: str

class ApplyPageRequest(BaseModel):
    action: str
    path: str
    content: str

@router.post("/api/terminal")
def run_terminal_command(req: CommandRequest, username: str = Depends(verify_user)):
    # Arbitrary shell execution is high-risk (RCE). It stays disabled unless the
    # operator explicitly opts in via ALLOW_TERMINAL=true on a trusted host.
    if not config.ALLOW_TERMINAL:
        raise HTTPException(
            status_code=403,
            detail="Terminal execution is disabled. Set ALLOW_TERMINAL=true in .env to enable it.",
        )
    try:
        result = subprocess.run(req.command, shell=True, capture_output=True, text=True, timeout=60)
        output = result.stdout.strip() if result.stdout else result.stderr.strip()
        if not output and result.returncode == 0:
            output = "[Command executed successfully with no output]"
        return {"output": output}
    except Exception as e:
        return {"error": f"Execution Failed: {str(e)}"}

@router.post("/api/terminal/save")
async def save_terminal_output(req: SaveOutputRequest, username: str = Depends(verify_user)):
    safe_name = "".join(c for c in req.filename if c.isalnum() or c in ("-", "_")).strip()
    if not safe_name:
        return {"error": "Invalid filename provided."}
        
    file_path = ARTICLES_DIR / f"{safe_name}.md"
    content = f"---\ntags: [terminal-log, auto-generated]\n---\n\n# Terminal Output: {safe_name}\n\n```text\n{req.content}\n```\n"
    
    file_path.write_text(content, encoding="utf-8")
    embed_document(safe_name, content)
    commit_changes(f"{username} saved terminal output to {safe_name}.md")
    return {"status": "success", "url": f"/wiki/{safe_name}"}

@router.get("/api/graph_data")
async def api_graph_data():
    return build_graph_data()

@router.post("/api/score")
async def score_card(score: SM2Score, username: str = Depends(verify_user)):
    update_card_score(score)
    return {"status": "success"}

@router.post("/api/inbox/process")
def trigger_inbox_processing(username: str = Depends(verify_user)):
    import asyncio
    result = asyncio.run(process_inbox_files())
    return result

@router.delete("/wiki/{page_name}")
async def delete_article(page_name: str, username: str = Depends(verify_user)):
    safe_name = "".join(c for c in page_name if c.isalnum() or c in ("-", "_")).strip()
    file_path = ARTICLES_DIR / f"{safe_name}.md"
    if file_path.exists():
        file_path.unlink()
        commit_changes(f"{username} deleted {safe_name}.md")
        return JSONResponse(status_code=200, content={"status": "deleted"})
    raise HTTPException(status_code=404)

@router.get("/export/{page_name}")
async def export_article(page_name: str):
    safe_name = "".join(c for c in page_name if c.isalnum() or c in ("-", "_")).strip()
    file_path = ARTICLES_DIR / f"{safe_name}.md"
    if not file_path.exists(): raise HTTPException(status_code=404)
    
    html_content, _, _ = render_markdown_file(file_path)
    standalone_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{safe_name}</title><script src="https://cdn.tailwindcss.com?plugins=typography"></script></head>
<body class="bg-white text-gray-900 p-10 max-w-4xl mx-auto prose prose-blue"><article>{html_content}</article></body>
</html>"""
    
    export_path = STATIC_DIR / f"{safe_name}-export.html"
    export_path.write_text(standalone_html, encoding="utf-8")
    return FileResponse(path=export_path, filename=f"{safe_name}.html", media_type="text/html")

@router.post("/api/chat")
async def chat_with_agent(request: Request, username: str = Depends(verify_user)):
    try:
        data = await request.json()
        messages = data.get("messages", [])

        # Translate the frontend's 'query' into the LLM's 'messages' format
        if not messages and "query" in data:
            messages = [{"role": "user", "content": data["query"]}]

        if not messages:
            return {"reply": "⚠️ **Error:** No input was received by the backend."}

        # Staged document changes proposed by write-tools this turn (Preview+Apply).
        proposals = []

        # --- RAG grounding ---
        # Retrieve the most relevant wiki chunks for the user's question and inject
        # them as context so the assistant answers from the knowledge base. Set
        # use_rag=false in the request to fall back to a plain (ungrounded) chat.
        sources = []
        if data.get("use_rag", True):
            query_text = data.get("query")
            if not query_text:
                for m in reversed(messages):
                    if m.get("role") == "user" and isinstance(m.get("content"), str):
                        query_text = m["content"]
                        break
            if query_text:
                context_block, sources = retrieve_context(query_text)
                if context_block:
                    system_prompt = (
                        "You are the Pi Wiki assistant. Answer the user's question using the "
                        "CONTEXT below, which was retrieved from their personal wiki. Prefer the "
                        "context over prior knowledge and cite the source page names you rely on. "
                        "If the context does not contain the answer, say so plainly before "
                        "answering from general knowledge.\n\n"
                        f"CONTEXT:\n{context_block}"
                    )
                    messages = [{"role": "system", "content": system_prompt}] + messages

        plugin_functions, tools_schema = load_plugins()
        max_iterations = 5

        async with httpx.AsyncClient(timeout=120.0) as client:
            for iteration in range(max_iterations):
                payload = {
                    "model": config.LOCAL_AI_MODEL,
                    "messages": messages,
                    "temperature": 0.2
                }
                if tools_schema:
                    payload["tools"] = tools_schema

                response = await client.post(config.LOCAL_AI_URL, json=payload)
                
                try:
                    response_data = response.json()
                except Exception:
                    response_data = response.text
                
                if not isinstance(response_data, dict) or "choices" not in response_data:
                    if isinstance(response_data, dict):
                        error_msg = response_data.get("error", {}).get("message", str(response_data))
                    else:
                        error_msg = str(response_data)[:500]
                    if isinstance(error_msg, dict): 
                        error_msg = str(error_msg)
                    return {"reply": f"⚠️ **API Error:** {error_msg}"}
                
                ai_message = response_data["choices"][0]["message"]
                messages.append(ai_message)
                
                if "tool_calls" not in ai_message or not ai_message["tool_calls"]:
                    # Ensure we always safely return a string, even if content is None
                    final_text = ai_message.get("content") or ""
                    return {"reply": final_text, "sources": sources, "proposals": proposals}

                for tool_call in ai_message["tool_calls"]:
                    func_name = tool_call["function"]["name"]
                    try:
                        args = json.loads(tool_call["function"]["arguments"])
                    except json.JSONDecodeError:
                        args = {}

                    if func_name in plugin_functions:
                        try:
                            result = plugin_functions[func_name](**args)
                            # Write-tools return a "proposal": surface it to the user
                            # for Preview+Apply instead of writing to disk. Feed the
                            # model a benign acknowledgement so it finishes its turn.
                            if isinstance(result, dict) and result.get("status") == "proposal":
                                proposals.append(result)
                                tool_output = json.dumps({
                                    "status": "staged",
                                    "message": "Change staged for the user to review and apply. Briefly tell the user what you drafted.",
                                })
                            else:
                                tool_output = json.dumps(result)
                        except Exception as e:
                            tool_output = json.dumps({"error": str(e)})
                    else:
                        tool_output = json.dumps({"error": f"Tool '{func_name}' not found."})

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": func_name,
                        "content": tool_output
                    })

        return {"reply": "I reached my maximum thinking limit while trying to execute those tools.", "sources": sources, "proposals": proposals}
        
    except Exception as e:
        # Always log the full trace server-side; only leak details to the browser
        # when DEBUG_MODE is on.
        import traceback
        print(f"[FATAL BACKEND CRASH]\n{traceback.format_exc()}")
        if config.DEBUG_MODE:
            return {"reply": f"⚠️ **Python Backend Crash:** `{str(e)}`\n\nCheck your Docker terminal logs for the full stack trace!"}
        return {"reply": "⚠️ **Error:** The backend hit an unexpected problem. Check the server logs for details."}

@router.post("/api/rag/index-all")
def index_entire_wiki(username: str = Depends(verify_user)):
    all_files = list(ARTICLES_DIR.rglob("*.md"))
    count = 0
    for file_path in all_files:
        content = file_path.read_text(encoding="utf-8")
        safe_name = file_path.relative_to(ARTICLES_DIR).with_suffix("").as_posix()
        embed_document(safe_name, content)
        count += 1
    return {"status": "success", "message": f"Successfully vectorized {count} documents!"}

@router.post("/api/pages/apply")
async def apply_page_change(req: ApplyPageRequest, username: str = Depends(verify_user)):
    """Apply an AI-proposed page create/edit after the user approves it in the UI.
    Re-sanitizes server-side (never trusts the client) and writes + commits +
    re-embeds so every change is versioned and searchable."""
    from services.page_service import sanitize_page_path, write_page
    safe = sanitize_page_path(req.path)
    if not safe:
        return {"error": "Invalid page path."}
    if not (req.content or "").strip():
        return {"error": "No content to write."}
    action = "edited" if req.action == "edit" else "created"
    try:
        write_page(safe, req.content, f"{username} {action} {safe}.md via AI assistant")
    except ValueError as e:
        return {"error": str(e)}
    return {"status": "success", "url": f"/wiki/{safe}", "path": safe}

@router.post("/api/rag/suggest-link")
def suggest_semantic_link(req: LinkSuggestionRequest, username: str = Depends(verify_user)):
    if len(req.text) < 25:
        return {"suggestion": None}
    db_results = query_knowledge_base(req.text, n_results=1)
    sources = db_results.get("metadatas", [[]])[0]
    if sources:
        best_match = sources[0].get("source")
        return {"suggestion": best_match}
    return {"suggestion": None}

# MERGED SECURE IMAGE UPLOADER (Vision + Standard)
@router.post("/upload-image")
async def upload_image_secure(file: UploadFile = File(...), username: str = Depends(verify_user)):
    contents = await file.read()
    safe_name = "".join(c for c in file.filename if c.isalnum() or c in (".", "-", "_")).strip()
    file_path = IMAGES_DIR / safe_name
    file_path.write_bytes(contents)

    try:
        encoded = base64.b64encode(contents).decode('utf-8')
        payload = {
            "model": config.LOCAL_AI_MODEL,
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": "Briefly describe the key technical elements of this image in one sentence."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}
                ]}
            ],
            "max_tokens": 100
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(config.LOCAL_AI_URL, json=payload, timeout=30.0)
            ai_desc = response.json()["choices"][0]["message"]["content"].strip().replace('\n', ' ')
    except Exception:
        ai_desc = "Uploaded Image"

    return {"markdown": f"![{ai_desc}](/static/images/{safe_name})"}

@router.post("/api/inbox/upload")
async def dump_to_inbox(file: UploadFile = File(...), username: str = Depends(verify_user)):
    try:
        content = await file.read()
        # Sanitize to a bare filename so a crafted name (e.g. "../../evil") cannot
        # escape the inbox directory.
        raw_name = os.path.basename(file.filename or "")
        safe_name = "".join(c for c in raw_name if c.isalnum() or c in (".", "-", "_", " ")).strip()
        if not safe_name or safe_name in (".", ".."):
            return {"error": "Invalid filename provided."}
        file_path = INBOX_DIR / safe_name
        file_path.write_bytes(content)
        return {"status": "success", "filename": safe_name}
    except Exception as e:
        return {"error": str(e)}
    
@router.post("/api/settings/update")
async def update_settings(settings: dict, username: str = Depends(verify_user)):
    # update_config_env persists to .env, updates os.environ, and refreshes the
    # live core.config attribute so the change takes effect without a restart.
    allowed = {"LOCAL_AI_URL", "LOCAL_AI_MODEL", "HOMELAB_DASHBOARD_URL", "MAX_AI_TOKENS"}
    updated = []
    try:
        for key, value in settings.items():
            if key in allowed:
                update_config_env(key, value)
                updated.append(key)
        return {"status": "success", "updated": updated}
    except (ValueError, TypeError) as e:
        return {"error": f"Invalid setting value: {e}"}