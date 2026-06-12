import os
import shutil
import re
import random
import json
import httpx
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Form, UploadFile, File, BackgroundTasks, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
from pydantic import BaseModel
import markdown
from git import Repo, InvalidGitRepositoryError

app = FastAPI(title="Pi Wiki")

# --- PATH SETUP ---
BASE_DIR = Path(__file__).resolve().parent
ARTICLES_DIR = BASE_DIR / "articles"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"
DATA_FILE = BASE_DIR / "progress.json" # SM-2 State file

for d in [ARTICLES_DIR, STATIC_DIR, IMAGES_DIR]:
    d.mkdir(exist_ok=True)

if not DATA_FILE.exists():
    with open(DATA_FILE, "w") as f: json.dump({}, f)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# --- SECURITY ---
security = HTTPBasic()
ADMIN_USER = "admin"
ADMIN_PASS = "admin"

def verify_user(credentials: HTTPBasicCredentials = Depends(security)):
    is_user_ok = secrets.compare_digest(credentials.username, ADMIN_USER)
    is_pass_ok = secrets.compare_digest(credentials.password, ADMIN_PASS)
    if not (is_user_ok and is_pass_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect credentials", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

# --- GIT VERSIONING ---
def init_git():
    try: repo = Repo(ARTICLES_DIR)
    except InvalidGitRepositoryError:
        repo = Repo.init(ARTICLES_DIR)
        repo.git.add(A=True)
        if repo.is_dirty() or repo.untracked_files: repo.index.commit("Initial Wiki Commit")
    return repo

git_repo = init_git()
def commit_changes(message: str):
    git_repo.git.add(A=True)
    if git_repo.is_dirty() or git_repo.untracked_files: git_repo.index.commit(message)

# --- LOCAL AI & FLASHCARDS ---
async def process_with_local_ai(file_path: Path):
    try:
        with open(file_path, "r", encoding="utf-8") as f: content = f.read()
        if "> **AI TL;DR:**" in content: return 

        lm_studio_url = "http://10.5.0.2:1234/v1/chat/completions"
        payload = {
            "model": "local-model",
            "messages": [
                {"role": "system", "content": "You are a technical knowledge assistant. 1. Write a 1-sentence TL;DR summary. 2. Extract the 2 most important concepts and format them EXACTLY like this:\n:::Q\nQuestion\n:::A\nAnswer\n:::"},
                {"role": "user", "content": f"Process this text:\n\n{content}"}
            ],
            "temperature": 0.3, "max_tokens": 1000, "stream": False
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(lm_studio_url, json=payload, timeout=60.0)
            if response.status_code == 200:
                ai_response = response.json()["choices"][0]["message"]["content"].strip()
                if ":::Q" in ai_response:
                    parts = ai_response.split(":::Q", 1)
                    tldr, flashcards = parts[0].strip(), "\n\n:::Q" + parts[1].strip()
                else:
                    tldr, flashcards = ai_response, ""
                
                yaml_match = re.match(r'^---\n.*?\n---\n', content, flags=re.DOTALL)
                if yaml_match:
                    frontmatter, body = yaml_match.group(0), content[yaml_match.end():]
                    new_content = f"{frontmatter}\n> **AI TL;DR:** {tldr}\n\n{body}{flashcards}"
                else:
                    new_content = f"> **AI TL;DR:** {tldr}\n\n{content}{flashcards}"
                
                with open(file_path, "w", encoding="utf-8") as f: f.write(new_content)
                commit_changes(f"LM Studio generated summary for {file_path.stem}")
    except Exception as e:
        print(f"LM Studio processing failed: {e}")

# --- KNOWLEDGE GRAPH API (PHASE 6) ---
@app.get("/api/graph_data")
async def api_graph_data():
    nodes, edges = [], []
    for file_path in ARTICLES_DIR.glob("*.md"):
        node_id = file_path.stem
        # Extract first tag for color grouping
        _, tags, _ = render_markdown_file(file_path)
        group = tags[0] if tags else "article"
        nodes.append({"id": node_id, "label": node_id.replace("-", " ").title(), "group": group})
        
        # Build edges based on wikilinks
        content = file_path.read_text(encoding="utf-8")
        links = re.findall(r'\[\[(.*?)\]\]', content)
        for link in links:
            edges.append({"from": node_id, "to": link.lower().replace(" ", "-")})
            
    return {"nodes": nodes, "edges": edges}

@app.get("/graph", response_class=HTMLResponse)
async def view_graph(request: Request):
    return templates.TemplateResponse(request=request, name="graph.html", context={"title": "Knowledge Graph", "pages": get_available_pages()})

# --- CORE PARSER ---
def get_backlinks(target_page: str) -> list[str]:
    backlinks = []
    pattern = re.compile(r'\[\[' + re.escape(target_page).replace(r'\-', r'[\-\s]') + r'\]\]', re.IGNORECASE)
    for file_path in ARTICLES_DIR.glob("*.md"):
        if file_path.stem == target_page: continue
        if pattern.search(file_path.read_text(encoding="utf-8")): backlinks.append(file_path.stem)
    return backlinks

def render_markdown_file(file_path: Path):
    text = file_path.read_text(encoding="utf-8")
    text = re.sub(r'\[\[(.*?)\]\]', lambda m: f"[{m.group(1)}](/wiki/{m.group(1).lower().replace(' ', '-')})", text)
    text = re.sub(r':::Q\n(.*?)\n:::A\n(.*?)\n:::', r'> **Q:** \1  \n> **A:** \2', text, flags=re.DOTALL)
    
    md = markdown.Markdown(extensions=["extra", "codehilite", "toc", "meta"])
    html = md.convert(text)
    toc = md.toc # Extracts the Table of Contents!
    
    tags = []
    for tag_str in md.Meta.get("tags", []): tags.extend([t.strip().lower() for t in tag_str.split(",")])
    return html, tags, toc

# --- SM-2 MICRO-LEARNING ENGINE (PHASE 6) ---
class SM2Score(BaseModel):
    card_id: str
    quality: int # 0-5 scale

def load_progress():
    with open(DATA_FILE, "r") as f: return json.load(f)

def save_progress(data):
    with open(DATA_FILE, "w") as f: json.dump(data, f, indent=4)

@app.post("/api/score")
async def score_card(score: SM2Score):
    progress = load_progress()
    card_state = progress.get(score.card_id, {"repetitions": 0, "interval": 1, "easiness": 2.5, "next_review": "2000-01-01"})
    
    q = score.quality
    if q >= 3:
        if card_state["repetitions"] == 0: intvl = 1
        elif card_state["repetitions"] == 1: intvl = 6
        else: intvl = round(card_state["interval"] * card_state["easiness"])
        card_state["repetitions"] += 1
    else:
        card_state["repetitions"] = 0
        intvl = 1
        
    card_state["easiness"] = max(1.3, card_state["easiness"] + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
    card_state["interval"] = intvl
    card_state["next_review"] = (datetime.now() + timedelta(days=intvl)).strftime("%Y-%m-%d")
    
    progress[score.card_id] = card_state
    save_progress(progress)
    return {"status": "success"}

@app.get("/quiz", response_class=HTMLResponse)
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
            flashcards.append(card_data)
            # Filter by SM-2 due date
            if progress.get(card_id, {}).get("next_review", "2000-01-01") <= today:
                due_cards.append(card_data)

    cards_to_review = due_cards[:5] if due_cards else []
    return templates.TemplateResponse(request=request, name="quiz.html", context={"title": "Micro-Learning", "cards": cards_to_review, "pages": get_available_pages()})

# --- STATIC SITE COMPILER (PHASE 6) ---
@app.get("/export/{page_name}")
async def export_article(page_name: str):
    safe_name = "".join(c for c in page_name if c.isalnum() or c in ("-", "_")).strip()
    file_path = ARTICLES_DIR / f"{safe_name}.md"
    if not file_path.exists(): raise HTTPException(status_code=404)
    
    html_content, _, _ = render_markdown_file(file_path)
    # Generates a completely standalone HTML payload
    standalone_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{safe_name}</title><script src="https://cdn.tailwindcss.com?plugins=typography"></script></head>
<body class="bg-white text-gray-900 p-10 max-w-4xl mx-auto prose prose-blue"><article>{html_content}</article></body>
</html>"""
    
    export_path = STATIC_DIR / f"{safe_name}-export.html"
    with open(export_path, "w", encoding="utf-8") as f: f.write(standalone_html)
    return FileResponse(path=export_path, filename=f"{safe_name}.html", media_type="text/html")

# --- STANDARD UTILITIES & ROUTES ---
def get_available_pages() -> list[str]:
    if not ARTICLES_DIR.exists(): return []
    return sorted([f.stem for f in ARTICLES_DIR.glob("*.md")])

def get_all_tags() -> dict:
    tag_map = {}
    for file_path in ARTICLES_DIR.glob("*.md"):
        md = markdown.Markdown(extensions=["meta"])
        md.convert(file_path.read_text(encoding="utf-8"))
        for tag_str in md.Meta.get("tags", []):
            for tag in [t.strip().lower() for t in tag_str.split(",")]:
                if tag: tag_map.setdefault(tag, []).append(file_path.stem)
    return tag_map

@app.get("/tags", response_class=HTMLResponse)
async def view_tags(request: Request):
    return templates.TemplateResponse(request=request, name="tags.html", context={"title": "Tags", "tag_map": get_all_tags(), "pages": get_available_pages()})

@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    index_path = ARTICLES_DIR / "index.md"
    if not index_path.exists():
        with open(index_path, "w", encoding="utf-8") as f: f.write("---\ntags: [home, setup]\n---\n# Welcome\n\nEdit this file.")
        commit_changes("Initialize index.md")
    html_content, tags, toc = render_markdown_file(index_path)
    return templates.TemplateResponse(request=request, name="view.html", context={"title": "Home", "content": html_content, "toc": toc, "pages": get_available_pages(), "page_name": "index", "tags": tags, "backlinks": get_backlinks("index")})

@app.get("/wiki/{page_name}", response_class=HTMLResponse)
async def read_article(request: Request, page_name: str):
    safe_name = "".join(c for c in page_name if c.isalnum() or c in ("-", "_")).strip()
    file_path = ARTICLES_DIR / f"{safe_name}.md"
    if not file_path.exists(): return RedirectResponse(url=f"/edit/{safe_name}", status_code=303)
    html_content, tags, toc = render_markdown_file(file_path)
    return templates.TemplateResponse(request=request, name="view.html", context={"title": safe_name, "content": html_content, "toc": toc, "pages": get_available_pages(), "page_name": safe_name, "tags": tags, "backlinks": get_backlinks(safe_name)})

@app.get("/search", response_class=HTMLResponse)
async def search_articles(request: Request, q: str = ""):
    results = []
    if q:
        for f in ARTICLES_DIR.glob("*.md"):
            if q.lower() in f.read_text(encoding="utf-8").lower(): results.append(f.stem)
    return templates.TemplateResponse(request=request, name="search.html", context={"title": "Search", "q": q, "results": results, "pages": get_available_pages()})

@app.get("/edit/{page_name}", response_class=HTMLResponse)
async def edit_article_form(request: Request, page_name: str, username: str = Depends(verify_user)):
    safe_name = "".join(c for c in page_name if c.isalnum() or c in ("-", "_")).strip()
    file_path = ARTICLES_DIR / f"{safe_name}.md"
    content = file_path.read_text(encoding="utf-8") if file_path.exists() else "---\ntags: [draft]\n---\n\n"
    return templates.TemplateResponse(request=request, name="edit.html", context={"title": f"Edit {safe_name}", "content": content, "pages": get_available_pages(), "page_name": safe_name})

@app.post("/edit/{page_name}")
async def save_article(request: Request, page_name: str, bg_tasks: BackgroundTasks, content: str = Form(...), username: str = Depends(verify_user)):
    safe_name = "".join(c for c in page_name if c.isalnum() or c in ("-", "_")).strip()
    file_path = ARTICLES_DIR / f"{safe_name}.md"
    with open(file_path, "w", encoding="utf-8") as f: f.write(content)
    commit_changes(f"{username} updated {safe_name}.md")
    bg_tasks.add_task(process_with_local_ai, file_path)
    return RedirectResponse(url=f"/wiki/{safe_name}", status_code=303)

@app.delete("/wiki/{page_name}")
async def delete_article(page_name: str, username: str = Depends(verify_user)):
    safe_name = "".join(c for c in page_name if c.isalnum() or c in ("-", "_")).strip()
    file_path = ARTICLES_DIR / f"{safe_name}.md"
    if file_path.exists():
        file_path.unlink()
        commit_changes(f"{username} deleted {safe_name}.md")
        return JSONResponse(status_code=200, content={"status": "deleted"})
    raise HTTPException(status_code=404)

@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...), username: str = Depends(verify_user)):
    safe_name = "".join(c for c in file.filename if c.isalnum() or c in (".", "-", "_")).strip()
    with open(IMAGES_DIR / safe_name, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    return {"markdown": f"![{safe_name}](/static/images/{safe_name})"}