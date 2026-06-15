import re
import markdown
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from core.config import templates, ARTICLES_DIR
from core.security import verify_user
from services.markdown_service import render_markdown_file, get_all_tags, get_available_pages, get_backlinks
from services.git_service import commit_changes
from services.ai_service import process_with_local_ai
from services.sm2_service import load_progress

router = APIRouter()

def get_all_pages():
    """Returns a list of all markdown file stems to populate the sidebar."""
    if not ARTICLES_DIR.exists():
        return ["index"]
    
    pages = [f.stem for f in ARTICLES_DIR.glob("*.md")]
    
    # Ensure 'index' (Home) is always at the very top of the list
    if "index" in pages:
        pages.remove("index")
        pages.insert(0, "index")
        
    return pages

@router.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    index_path = ARTICLES_DIR / "index.md"
    if not index_path.exists():
        index_path.write_text("---\ntags: [home]\n---\n# Welcome\n\nEdit this file.", encoding="utf-8")
        commit_changes("Initialize index.md")
    html_content, tags, toc = render_markdown_file(index_path)
    return templates.TemplateResponse(request, "view.html", {"title": "Home", "content": html_content, "toc": toc, "pages": get_available_pages(), "page_name": "index", "tags": tags, "backlinks": get_backlinks("index")})

@router.get("/wiki/{page_name}", response_class=HTMLResponse)
async def read_article(request: Request, page_name: str):
    safe_name = "".join(c for c in page_name if c.isalnum() or c in ("-", "_")).strip()
    file_path = ARTICLES_DIR / f"{safe_name}.md"
    if not file_path.exists():
        return RedirectResponse(url=f"/edit/{safe_name}", status_code=303)
    html_content, tags, toc = render_markdown_file(file_path)
    return templates.TemplateResponse(request, "view.html", {"title": safe_name, "content": html_content, "toc": toc, "pages": get_available_pages(), "page_name": safe_name, "tags": tags, "backlinks": get_backlinks(safe_name)})

@router.get("/edit/{page_name}", response_class=HTMLResponse)
async def edit_article_form(request: Request, page_name: str, username: str = Depends(verify_user)):
    safe_name = "".join(c for c in page_name if c.isalnum() or c in ("-", "_")).strip()
    file_path = ARTICLES_DIR / f"{safe_name}.md"
    content = file_path.read_text(encoding="utf-8") if file_path.exists() else "---\ntags: [draft]\n---\n\n"
    return templates.TemplateResponse(request, "edit.html", {"title": f"Edit {safe_name}", "content": content, "pages": get_available_pages(), "page_name": safe_name})

@router.post("/edit/{page_name}")
async def save_article(request: Request, page_name: str, bg_tasks: BackgroundTasks, content: str = Form(...), username: str = Depends(verify_user)):
    safe_name = "".join(c for c in page_name if c.isalnum() or c in ("-", "_")).strip()
    file_path = ARTICLES_DIR / f"{safe_name}.md"
    file_path.write_text(content, encoding="utf-8")
    commit_changes(f"{username} updated {safe_name}.md")
    bg_tasks.add_task(process_with_local_ai, file_path)
    return RedirectResponse(url=f"/wiki/{safe_name}", status_code=303)

@router.get("/tags", response_class=HTMLResponse)
async def view_tags(request: Request):
    return templates.TemplateResponse(request, "tags.html", {"title": "Tags", "tag_map": get_all_tags(), "pages": get_available_pages()})

@router.get("/graph", response_class=HTMLResponse)
async def view_graph(request: Request):
    return templates.TemplateResponse(request, "graph.html", {"title": "Knowledge Graph", "pages": get_available_pages()})

@router.get("/chat")
async def chat_page(request: Request):
    """Renders the semantic chat interface."""
    pages = get_all_pages()
    return templates.TemplateResponse(
        request=request, 
        name="chat.html", 
        context={"pages": pages}
    )

@router.get("/quiz", response_class=HTMLResponse)
async def serve_quiz(request: Request):
    progress = load_progress()
    today = datetime.now().strftime("%Y-%m-%d")
    flashcards, due_cards = [], []
    pattern = re.compile(r':::Q\n(.*?)\n:::A\n(.*?)\n:::', re.DOTALL)
    
    for file_path in ARTICLES_DIR.glob("*.md"):
        content = file_path.read_text(encoding="utf-8")
        for idx, (q, a) in enumerate(pattern.findall(content)):
            card_id = f"{file_path.stem}-{idx}"
            card_data = {"id": card_id, "question": markdown.markdown(q.strip()), "answer": markdown.markdown(a.strip()), "source": file_path.stem}
            if progress.get(card_id, {}).get("next_review", "2000-01-01") <= today:
                due_cards.append(card_data)

    cards_to_review = due_cards[:5] if due_cards else []
    return templates.TemplateResponse(request, "quiz.html", {"title": "Micro-Learning", "cards": cards_to_review, "pages": get_available_pages()})