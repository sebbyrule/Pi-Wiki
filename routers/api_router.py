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
from services.page_service import read_page, page_exists, sanitize_page_path, slugify_title
from services.ai_service import WRITER_SYSTEM_PROMPT
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

def _strip_code_fence(text: str) -> str:
    """Remove a ```lang ... ``` wrapper if the model fenced the whole document."""
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.split("\n")
        lines = lines[1:]  # drop opening ``` / ```markdown
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


# Bounded budget for interactive page drafting. A wiki page is ~1-1.5k tokens;
# reasoning models spend extra on thinking, so 3500 leaves headroom without
# letting generation run for many minutes. The timeout must comfortably exceed
# WRITE_MAX_TOKENS / (tokens-per-sec) on slow local hardware.
WRITE_MAX_TOKENS = 3500
WRITE_TIMEOUT = 360.0


async def _handle_write_intent(intent: dict, client: httpx.AsyncClient):
    """Structured-output write path — bypasses native tool-calling entirely.

    For /new, /edit, /summarize we ask the model for a single plain-text
    completion (the page markdown or a summary) and wrap it into a proposal
    ourselves. This works even when the runtime never emits tool_calls.
    """
    action = intent.get("action")

    if action == "create":
        title = (intent.get("title") or "").strip()
        if not title:
            return {"reply": "⚠️ I need a title to create a page.", "sources": [], "proposals": []}
        path = slugify_title(title)
        system = WRITER_SYSTEM_PROMPT
        user = f'Write a complete wiki page titled "{title}". Output ONLY the Markdown document.'
    elif action in ("edit", "summarize"):
        path = sanitize_page_path(intent.get("path") or "")
        current = read_page(path)
        if current is None:
            return {"reply": f"⚠️ The page `{path}` doesn't exist, so there's nothing to {action}.", "sources": [], "proposals": []}
        if action == "summarize":
            system = "You are a concise technical summarizer for a personal wiki."
            user = f'Summarize the key points of this wiki page in 2-4 sentences:\n\n{current[:8000]}'
        else:
            system = WRITER_SYSTEM_PROMPT
            user = (
                "Revise the existing wiki page below. Keep all facts correct; improve clarity and "
                "structure; ensure it has a `> **TL;DR:**` line and a `## Review` section of flashcards. "
                "Output ONLY the complete revised Markdown document.\n\n"
                f'CURRENT PAGE "{path}":\n\n{current}'
            )
    else:
        return {"reply": "⚠️ Unknown write action.", "sources": [], "proposals": []}

    payload = {
        "model": config.LOCAL_AI_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.3,
        "max_tokens": WRITE_MAX_TOKENS,
    }
    try:
        response = await client.post(config.LOCAL_AI_URL, json=payload)
        content = response.json()["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException:
        return {
            "reply": (
                "⚠️ The model took too long to draft the page and timed out. This usually means a "
                "large/slow local model. Try a smaller or faster model in LM Studio, or a shorter title."
            ),
            "sources": [], "proposals": [],
        }
    except Exception:
        return {"reply": "⚠️ The model returned an unexpected response. Check the LM Studio logs.", "sources": [], "proposals": []}

    if action == "summarize":
        return {"reply": content or "(no summary produced)", "sources": [path], "proposals": []}

    content = _strip_code_fence(content)
    if not content:
        return {"reply": "⚠️ The model produced no content for the page.", "sources": [], "proposals": []}

    proposal = {
        "status": "proposal",
        "action": "edit" if action == "edit" else "create",
        "path": path,
        "content": content,
        "exists": page_exists(path),
        "summary": f"{'Edit' if action == 'edit' else 'Create'} /wiki/{path}",
    }
    verb = "revised" if action == "edit" else "drafted"
    return {"reply": f"I've {verb} **/wiki/{path}** — review it below and click Apply to save.", "sources": [], "proposals": [proposal]}


@router.post("/api/chat")
async def chat_with_agent(request: Request, username: str = Depends(verify_user)):
    try:
        data = await request.json()

        # Structured write path (from /new, /edit, /summarize). Bypasses native
        # tool-calling so it works even when the model won't emit tool_calls.
        intent = data.get("intent")
        if isinstance(intent, dict) and intent.get("action"):
            async with httpx.AsyncClient(timeout=WRITE_TIMEOUT) as client:
                return await _handle_write_intent(intent, client)

        messages = data.get("messages", [])

        # Translate the frontend's 'query' into the LLM's 'messages' format
        if not messages and "query" in data:
            messages = [{"role": "user", "content": data["query"]}]

        if not messages:
            return {"reply": "⚠️ **Error:** No input was received by the backend."}

        # Staged document changes proposed by write-tools this turn (Preview+Apply).
        proposals = []

        # Tool-governance directive — ALWAYS present so the model knows the write
        # tools exist and, crucially, does not narrate a page creation it never
        # actually performed. Without this the model tends to say "I created the
        # page" without ever calling create_page (no proposal is produced).
        system_parts = [
            "You are the Pi Wiki assistant for the user's personal Markdown wiki. "
            "You have tools: read_page (read a page), create_page (draft a NEW page), and "
            "edit_page (revise an EXISTING page).\n"
            "CRITICAL RULES:\n"
            "- To create or modify a page you MUST call create_page or edit_page with the "
            "COMPLETE Markdown content. These stage a proposal the user approves; they do not "
            "save directly.\n"
            "- NEVER claim you created, drafted, saved, or edited a page unless you actually "
            "called the tool in this turn. If you did not call the tool, do not say a page exists.\n"
            "- Before editing, call read_page first to preserve existing content.\n"
            "- Good page content has YAML frontmatter tags, an H1 title, a `> **TL;DR:**` line, "
            "body sections, and a `## Review` section of flashcards."
        ]

        # --- RAG grounding ---
        # Retrieve the most relevant wiki chunks for the user's question and add
        # them to the system context so answers are grounded. Set use_rag=false to
        # skip retrieval (e.g. for generative/write requests where it's just noise).
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
                    system_parts.append(
                        "When ANSWERING A QUESTION, prefer the CONTEXT below (retrieved from the "
                        "wiki) over prior knowledge and cite the source page names. If it doesn't "
                        "contain the answer, say so before answering from general knowledge.\n\n"
                        f"CONTEXT:\n{context_block}"
                    )

        messages = [{"role": "system", "content": "\n\n".join(system_parts)}] + messages

        plugin_functions, tools_schema = load_plugins()
        max_iterations = 5

        # Some local models narrate tool use (writing "I created the page") instead
        # of emitting a real tool_call. For write commands the frontend sends a
        # force_sequence (e.g. ["create_page"] or ["read_page","edit_page"]); we set
        # tool_choice to compel that exact call until a proposal is actually staged.
        force_sequence = [t for t in (data.get("force_sequence") or []) if isinstance(t, str)]
        forced_idx = 0

        async with httpx.AsyncClient(timeout=300.0) as client:
            for iteration in range(max_iterations):
                payload = {
                    "model": config.LOCAL_AI_MODEL,
                    "messages": messages,
                    "temperature": 0.2
                }
                if tools_schema:
                    payload["tools"] = tools_schema
                    # Force the next required tool while the write flow hasn't
                    # produced a proposal yet; then fall back to auto so the model
                    # can write its final reply.
                    if force_sequence and forced_idx < len(force_sequence) and not proposals:
                        payload["tool_choice"] = {
                            "type": "function",
                            "function": {"name": force_sequence[forced_idx]},
                        }
                        forced_idx += 1

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
                    # If this was a write command but the model narrated instead of
                    # calling the tool (no proposal staged), be honest rather than
                    # showing its false "I created the page" claim.
                    if force_sequence and not proposals:
                        final_text = (
                            "⚠️ **The model didn't actually call the write tool**, so nothing was staged "
                            "and no page was created. It only described the change. This is a limitation of "
                            "the current model/runtime's function-calling — try a model with reliable tool "
                            "support, or enable tool use in LM Studio.\n\n---\n\n" + final_text
                        )
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