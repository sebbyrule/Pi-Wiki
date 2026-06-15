import shutil
import subprocess
import platform
import json
import os
import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends # pyright: ignore[reportMissingImports]
from fastapi.responses import JSONResponse, FileResponse
from core.config import ARTICLES_DIR, IMAGES_DIR, STATIC_DIR
from core.security import verify_user
from core.config import LOCAL_AI_URL
from services.git_service import commit_changes
from services.sm2_service import SM2Score, update_card_score
from services.graph_service import build_graph_data
from services.markdown_service import render_markdown_file
from services.ai_service import process_inbox_files
from services.rag_service import embed_document, query_knowledge_base
from services.plugin_service import load_plugins
from pydantic import BaseModel

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

@router.post("/api/terminal")
def run_terminal_command(req: CommandRequest, username: str = Depends(verify_user)):
    # SECURITY NOTE: Removing the allow-list grants full execution access to the container. 
    # Because this is gated by Depends(verify_user), it remains secure for personal use.
    try:
        # shell=True allows for pipes, redirects, and arbitrary script execution
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
    
    # Wrap the raw output in an automated markdown template
    content = f"---\ntags: [terminal-log, auto-generated]\n---\n\n# Terminal Output: {safe_name}\n\n```text\n{req.content}\n```\n"
    
    file_path.write_text(content, encoding="utf-8")
    embed_document(safe_name, content)
    commit_changes(f"{username} saved terminal output to {safe_name}.md")
    
    return {"status": "success", "url": f"/wiki/{safe_name}"}
    

@router.get("/api/graph_data")
async def api_graph_data():
    return build_graph_data()

@router.post("/api/score")
async def score_card(score: SM2Score):
    update_card_score(score)
    return {"status": "success"}

from services.ai_service import process_inbox_files

# ... (paste this at the very bottom of api_router.py) ...
@router.post("/api/inbox/process")
def trigger_inbox_processing(username: str = Depends(verify_user)):
    """Triggers the AI to sweep the inbox directory."""
    import asyncio
    # We use asyncio.run because api_router is currently running synchronously 
    # so we don't freeze the terminal!
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

@router.post("/upload-image")
async def upload_image(file: UploadFile = File(...), username: str = Depends(verify_user)):
    safe_name = "".join(c for c in file.filename if c.isalnum() or c in (".", "-", "_")).strip()
    with open(IMAGES_DIR / safe_name, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"markdown": f"![{safe_name}](/static/images/{safe_name})"}

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
async def rag_semantic_chat(req: ChatQuery, username: str = Depends(verify_user)):
    """Agentic Chat: Searches vector DB and executes dynamic plugins if needed."""
    
    # 1. Gather RAG Context
    db_results = query_knowledge_base(req.query, n_results=3)
    chunks = db_results.get("documents", [[]])[0]
    sources = list(set([s.get("source", "Unknown") for s in db_results.get("metadatas", [[]])[0]]))
    context_text = "\n\n---\n\n".join(chunks) if chunks else "No local wiki context found."

    # 2. Hot-load Plugins
    available_functions, tools_schema = load_plugins()

    system_prompt = (
        "You are the Pi Wiki Autonomous Agent. "
        "You have access to local documents (provided below) and local system tools. "
        "Use tools if the user asks for real-time data or actions outside the documents.\n\n"
        f"WIKI CONTEXT:\n{context_text}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": req.query}
    ]

    lm_studio_url = LOCAL_AI_URL
    payload = {
        "model": "local-model",
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 10000
    }
    
    # Only attach tools if we actually have scripts in the plugins folder
    if tools_schema:
        payload["tools"] = tools_schema

    try:
        async with httpx.AsyncClient() as client:
            # FIRST PASS: Ask the AI how it wants to answer
            response = await client.post(lm_studio_url, json=payload, timeout=60.0)
            if response.status_code != 200:
                return {"error": f"LM Studio Error: {response.status_code}"}
                
            response_data = response.json()["choices"][0]["message"]

            # IF THE AI WANTS TO USE A TOOL:
            if response_data.get("tool_calls"):
                messages.append(response_data) # Append the AI's request to history
                
                # Execute every tool the AI asked for
                for tool_call in response_data["tool_calls"]:
                    func_name = tool_call["function"]["name"]
                    func_args = json.loads(tool_call["function"]["arguments"])
                    
                    if func_name in available_functions:
                        # Run the dynamic python script!
                        tool_result = available_functions[func_name](**func_args)
                        
                        # Feed the result back into the chat history
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": json.dumps(tool_result)
                        })
                
                # SECOND PASS: Ask the AI to read the tool results and give a final answer
                payload["messages"] = messages
                final_response = await client.post(lm_studio_url, json=payload, timeout=60.0)
                final_answer = final_response.json()["choices"][0]["message"]["content"]
                return {"answer": final_answer, "sources": sources + ["Live System Plugin"]}

            # If no tools were needed, just return the standard text answer
            return {"answer": response_data["content"], "sources": sources}

    except Exception as e:
        return {"error": f"Failed to connect to AI Agent: {str(e)}"}
    
@router.post("/api/rag/index-all")
def index_entire_wiki(username: str = Depends(verify_user)):
    """Sweeps the articles folder (and all subfolders) into ChromaDB."""
    all_files = list(ARTICLES_DIR.rglob("*.md")) # Changed to rglob!
    count = 0
    for file_path in all_files:
        content = file_path.read_text(encoding="utf-8")
        
        # Save the nested path (e.g. 'homelab/docker') so the AI links back correctly
        safe_name = file_path.relative_to(ARTICLES_DIR).with_suffix("").as_posix()
        
        embed_document(safe_name, content)
        count += 1
    return {"status": "success", "message": f"Successfully vectorized {count} documents!"}

@router.post("/api/rag/suggest-link")
def suggest_semantic_link(req: LinkSuggestionRequest):
    """Takes a fragment of text and searches the vector DB for a related page."""
    # Only search if they've typed enough context
    if len(req.text) < 25: 
        return {"suggestion": None}
        
    # Search the vector database
    db_results = query_knowledge_base(req.text, n_results=1)
    sources = db_results.get("metadatas", [[]])[0]
    
    if sources:
        # Return the highest matching document
        best_match = sources[0].get("source")
        return {"suggestion": best_match}
        
    return {"suggestion": None}