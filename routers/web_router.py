import re
import markdown
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
import core.config as config
from core.config import ARTICLES_DIR
from core.security import verify_user
from core.config import TEMPLATES_DIR, HOMELAB_DASHBOARD_URL, GITHUB_REPO_URL, SUPPORT_EMAIL
from services.markdown_service import render_markdown_file, get_all_tags, get_backlinks
from services.git_service import commit_changes
from services.ai_service import process_with_local_ai
from services.sm2_service import load_progress

router = APIRouter()

# Initialize Jinja2 Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Inject Global UI Variables
templates.env.globals["HOMELAB_DASHBOARD_URL"] = HOMELAB_DASHBOARD_URL
templates.env.globals["GITHUB_REPO_URL"] = GITHUB_REPO_URL
templates.env.globals["SUPPORT_EMAIL"] = SUPPORT_EMAIL

def get_all_pages():
    """Returns a grouped dictionary of pages for the collapsible sidebar."""
    if not ARTICLES_DIR.exists():
        return {"Root": ["index"]}
    
    # We will separate root-level files and folder-level files
    tree = {"Root": []}
    
    for f in ARTICLES_DIR.rglob("*.md"):
        rel_path = f.relative_to(ARTICLES_DIR).with_suffix("").as_posix()
        if rel_path == "index":
            continue
            
        parts = rel_path.split("/")
        if len(parts) == 1:
            # It's a top-level file
            tree["Root"].append(rel_path)
        else:
            # It's inside a folder. Group it by the first folder name.
            folder_name = parts[0]
            if folder_name not in tree:
                tree[folder_name] = []
            tree[folder_name].append(rel_path)
    
    # Sort files alphabetically for a clean UI
    tree["Root"].sort()
    for folder in tree:
        if folder != "Root":
            tree[folder].sort()
            
    # Ensure 'index' (Home) is always the absolute first item
    tree["Root"].insert(0, "index")
    return tree

@router.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    index_path = ARTICLES_DIR / "index.md"
    if not index_path.exists():
        index_path.write_text("---\ntags: [home]\n---\n# Welcome\n\nEdit this file.", encoding="utf-8")
        commit_changes("Initialize index.md")
    html_content, tags, toc = render_markdown_file(index_path)
    return templates.TemplateResponse(request, "view.html", {"title": "Home", "content": html_content, "toc": toc, "pages": get_all_pages(), "page_name": "index", "tags": tags, "backlinks": get_backlinks("index")})

# NEW: :path tells FastAPI to accept slashes in the URL
@router.get("/wiki/{page_path:path}", response_class=HTMLResponse)
async def read_article(request: Request, page_path: str):
    # ALLOW slashes during sanitization
    safe_path = "".join(c for c in page_path if c.isalnum() or c in ("-", "_", "/")).strip("/")
    file_path = ARTICLES_DIR / f"{safe_path}.md"
    if not file_path.exists():
        return RedirectResponse(url=f"/edit/{safe_path}", status_code=303)
    html_content, tags, toc = render_markdown_file(file_path)
    return templates.TemplateResponse(request, "view.html", {"title": safe_path, "content": html_content, "toc": toc, "pages": get_all_pages(), "page_name": safe_path, "tags": tags, "backlinks": get_backlinks(safe_path)})

@router.get("/edit/{page_path:path}", response_class=HTMLResponse)
async def edit_article_form(request: Request, page_path: str, username: str = Depends(verify_user)):
    safe_path = "".join(c for c in page_path if c.isalnum() or c in ("-", "_", "/")).strip("/")
    file_path = ARTICLES_DIR / f"{safe_path}.md"
    content = file_path.read_text(encoding="utf-8") if file_path.exists() else "---\ntags: [draft]\n---\n\n"
    return templates.TemplateResponse(request, "edit.html", {"title": f"Edit {safe_path}", "content": content, "pages": get_all_pages(), "page_name": safe_path})

@router.post("/edit/{page_path:path}")
async def save_article(request: Request, page_path: str, bg_tasks: BackgroundTasks, content: str = Form(...), username: str = Depends(verify_user)):
    safe_path = "".join(c for c in page_path if c.isalnum() or c in ("-", "_", "/")).strip("/")
    file_path = ARTICLES_DIR / f"{safe_path}.md"
    
    # MAGIC FIX: Automatically create the folder on your PC if it doesn't exist yet!
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    file_path.write_text(content, encoding="utf-8")
    commit_changes(f"{username} updated {safe_path}.md")
    bg_tasks.add_task(process_with_local_ai, file_path)
    return RedirectResponse(url=f"/wiki/{safe_path}", status_code=303)

@router.get("/tags", response_class=HTMLResponse)
async def view_tags(request: Request):
    return templates.TemplateResponse(request, "tags.html", {"title": "Tags", "tag_map": get_all_tags(), "pages": get_all_pages()})

@router.get("/graph", response_class=HTMLResponse)
async def view_graph(request: Request):
    return templates.TemplateResponse(request, "graph.html", {"title": "Knowledge Graph", "pages": get_all_pages()})

@router.get("/chat")
async def chat_page(request: Request):
    return templates.TemplateResponse(request, "chat.html", {"pages": get_all_pages()})

@router.get("/quiz", response_class=HTMLResponse)
async def serve_quiz(request: Request):
    progress = load_progress()
    today = datetime.now().strftime("%Y-%m-%d")
    flashcards, due_cards = [], []
    
    # --- NEW: Stat Tracker ---
    total_cards = 0 
    
    pattern = re.compile(r':::Q\r?\n(.*?)\r?\n:::A\r?\n(.*?)\r?\n:::', re.DOTALL)
    
    for file_path in ARTICLES_DIR.rglob("*.md"):
        content = file_path.read_text(encoding="utf-8")
        for idx, (q, a) in enumerate(pattern.findall(content)):
            total_cards += 1 # Count every flashcard found in the system
            
            rel_stem = file_path.relative_to(ARTICLES_DIR).with_suffix("").as_posix()
            card_id = f"{rel_stem}-{idx}"
            card_data = {
                "id": card_id, 
                "question": markdown.markdown(q.strip()), 
                "answer": markdown.markdown(a.strip()), 
                "source": rel_stem
            }
            if progress.get(card_id, {}).get("next_review", "2000-01-01") <= today:
                due_cards.append(card_data)

    cards_to_review = due_cards[:5] if due_cards else []
    
    return templates.TemplateResponse(
        request=request,
        name="quiz.html", 
        context={
            "request": request, 
            "title": "Study Dashboard", 
            "cards": cards_to_review, 
            "pages": get_all_pages(),
            # --- NEW: Send the stats to the frontend UI ---
            "stats": {"total": total_cards, "due": len(due_cards)} 
        }
    )

@router.get("/journal/today")
async def create_daily_journal(request: Request, username: str = Depends(verify_user)):
    today = datetime.now().strftime("%Y-%m-%d")
    journal_path = ARTICLES_DIR / "journal" / f"{today}.md"
    
    # If today's journal doesn't exist, generate the folder and boilerplate automatically
    if not journal_path.exists():
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        template = f"---\ntags: [journal, daily]\ndate: {today}\n---\n# Journal: {today}\n\n## 🎯 Focus for Today\n- \n\n## 📝 Notes & Logs\n- \n"
        journal_path.write_text(template, encoding="utf-8")
        commit_changes(f"Created daily journal for {today}")
        
    # Instantly redirect the user to the edit page for today's file
    return RedirectResponse(url=f"/edit/journal/{today}", status_code=303)

@router.get("/settings")
async def settings_page(request: Request, username: str = Depends(verify_user)):
    # Read live values from the config module so edits made via /api/settings/update
    # are reflected here without a restart.
    return templates.TemplateResponse(request, "settings.html", {
        "pages": get_all_pages(),
        "LOCAL_AI_URL": config.LOCAL_AI_URL,
        "LOCAL_AI_MODEL": config.LOCAL_AI_MODEL,
        "MAX_AI_TOKENS": config.MAX_AI_TOKENS,
        "HOMELAB_DASHBOARD_URL": config.HOMELAB_DASHBOARD_URL
    })