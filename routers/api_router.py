import shutil
import subprocess
import platform
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import JSONResponse, FileResponse
from core.config import ARTICLES_DIR, IMAGES_DIR, STATIC_DIR
from core.security import verify_user
from services.git_service import commit_changes
from services.sm2_service import SM2Score, update_card_score
from services.graph_service import build_graph_data
from services.markdown_service import render_markdown_file
from pydantic import BaseModel

router = APIRouter()

class CommandRequest(BaseModel):
    command: str

@router.post("/api/terminal")
async def run_terminal_command(req: CommandRequest, username: str = Depends(verify_user)):
    # 1. Detect the Operating System
    is_windows = platform.system() == "Windows"
    
    # 2. Assign the correct OS commands
    if is_windows:
        allowed_commands = {
            "uptime": ["cmd", "/c", "net statistics workstation"],
            "disk": ["cmd", "/c", "wmic logicaldisk get caption,freespace,size"],
            "memory": ["cmd", "/c", "wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /Value"],
            "temp": ["cmd", "/c", "echo [Notice] CPU Temp requires third-party software on Windows."],
            "docker_ps": ["docker", "ps", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"]
        }
    else:
        # These will run when deployed to your Raspberry Pi
        allowed_commands = {
            "uptime": ["uptime", "-p"],
            "disk": ["df", "-h", "/"],
            "memory": ["free", "-m"],
            "temp": ["vcgencmd", "measure_temp"],
            "docker_ps": ["docker", "ps", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"]
        }
    
    # 3. Execute
    if req.command not in allowed_commands:
        return {"error": "Command not recognized or strictly forbidden."}
        
    try:
        result = subprocess.run(allowed_commands[req.command], capture_output=True, text=True, timeout=5)
        return {"output": result.stdout.strip() if result.stdout else result.stderr.strip()}
    except Exception as e:
        return {"error": str(e)}
    

@router.get("/api/graph_data")
async def api_graph_data():
    return build_graph_data()

@router.post("/api/score")
async def score_card(score: SM2Score):
    update_card_score(score)
    return {"status": "success"}

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