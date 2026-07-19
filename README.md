# 🥧 Pi Wiki: System Intelligence

Pi Wiki is a self-hosted, Dockerized knowledge management system and homelab dashboard designed for local infrastructure (like a Raspberry Pi). It turns plain Markdown notes into a connected, automated learning environment using **local** AI inference, spaced-repetition testing, semantic search, real-time graph visualization, and (optional) container shell access — with no data ever leaving your hardware.

## 🕸️ Key Systems & Features

* **FastAPI Core Engine:** High-performance, modular routing with native asynchronous execution and flat-file storage.
* **Semantic Chat (RAG):** Ask questions in natural language and get answers grounded in your own notes. Relevant chunks are retrieved from a local ChromaDB vector index, injected as context, and every answer cites the source pages it used. A per-message toggle switches between grounded and plain chat.
* **Hybrid Search:** The header search combines literal keyword matching (title + body, with excerpt snippets) and semantic vector search, ranked title → content → related, so you find pages by wording *or* by meaning.
* **The Omnivorous Inbox:** Drop text, Markdown, PDFs, or audio (`.mp3/.wav/.m4a`) into `inbox/` and process it in one click. Audio is transcribed locally with **Whisper**, PDFs are parsed with **PyMuPDF**, and a multi-agent "writer → evaluator → reviser" loop formats everything into clean, tagged Markdown before embedding it into the vector store.
* **Spaced-Repetition Review (SM-2):** A micro-learning deck using the SuperMemo-2 algorithm to track concept mastery and schedule card reviews, fed straight from flashcard syntax in your notes.
* **Interactive Knowledge Graph:** Real-time `Vis.js` visualization of your wikilinks and tag clusters — double-click a node to travel to that page.
* **Interactive PiOS Terminal:** An optional browser-based shell for the host container (**disabled by default** — see Security).
* **Terminal-to-Wiki Pipeline:** Capture raw terminal output and commit it as a tagged Markdown document in one click.
* **Settings Tab:** Update the local AI endpoint, model, and token budget from the UI; changes persist to `.env` and take effect immediately (no restart).
* **Automated Git Versioning:** Every create/update/delete is auto-committed to a local Git repo for strict version control.
* **Editorial UI (light + dark):** A distinctive "archive" aesthetic — warm paper/ink palette, **self-hosted** Fraunces / Newsreader / IBM Plex Mono typefaces (fully offline), hairline rules, a sticky table of contents, and inline copy-to-clipboard for code blocks.

---

## 🛠️ Infrastructure & Tech Stack

* **Language / Runtime:** Python 3.11+
* **Framework:** FastAPI, Jinja2 Templates
* **AI / Retrieval:** Local OpenAI-compatible server (e.g. LM Studio), ChromaDB (`all-MiniLM-L6-v2` embeddings), OpenAI Whisper
* **Parsing:** Python-Markdown (`meta`, `extra`, `codehilite`, `toc`), PyMuPDF
* **Frontend:** Tailwind CSS (Typography plugin) + self-hosted webfonts, Vis.js
* **Storage:** Flat-file Markdown (`/articles`), ChromaDB (`/chroma_db`), JSON review state (`progress.json`)
* **Orchestration:** Docker & Docker Compose (base: `python:3.11-slim-bookworm`, with `git`, `procps`, `ffmpeg`)

---

## 🚀 Installation & Local Deployment

### 1. Prerequisites

Install **Docker** and **Docker Compose**. A local OpenAI-compatible inference server (e.g. LM Studio) is needed for the AI features. The app detects the host OS dynamically, so you can test on Windows before deploying to a Linux/ARM64 Raspberry Pi.

### 2. Clone and configure

```bash
git clone <your-github-repository-url>
cd pi-wiki
cp .env.copy .env
```

Open `.env` and set your credentials, AI endpoint, and options (see below).

### 3. Run with Docker

```bash
docker compose up --build -d
```

The app becomes available at `http://localhost:8000` (or your host IP). The `core/`, `routers/`, `services/`, `templates/`, and `static/` directories are bind-mounted, so most code and UI changes only need a container recreate (`docker compose up -d`) — not a full rebuild.

### ⚙️ Environment Variables (`.env`)

| Variable | Purpose | Default |
| --- | --- | --- |
| `WIKI_ADMIN_USER` / `WIKI_ADMIN_PASSWORD` | Credentials for all write/admin routes. **Change these** — leaving `admin`/`admin` prints a startup warning. | `admin` / `admin` |
| `ALLOW_TERMINAL` | Enables the shell terminal and the AI's `execute_bash` tool. High risk (RCE) — leave `false` unless on a trusted, isolated host. | `false` |
| `DEBUG_MODE` | When `true`, surfaces raw backend error details in the UI. Keep `false` in production. | `False` |
| `LOCAL_AI_URL` | Endpoint of your local OpenAI-compatible chat completions server. | — |
| `LOCAL_AI_MODEL` | Model name passed to that server. | `local-model` |
| `MAX_AI_TOKENS` | Max tokens the inbox synthesizer requests. | `20000` |
| `HOMELAB_DASHBOARD_URL` / `GITHUB_REPO_URL` / `SUPPORT_EMAIL` | Links shown in the sidebar. | — |

---

## 📝 Syntax & Automation Guide

### 🔗 Bi-Directional Linking

Link pages by wrapping a page title in double brackets:

```markdown
Refer to the [[system-architecture]] page for hardware layouts.
```

### 🧠 Spaced-Repetition Flashcards

Feed the SM-2 review deck by writing concepts in any document using this exact syntax:

```text
:::Q
What layer of the OSI model handles cryptographic encryption and compression?
:::A
The Presentation Layer (Layer 6).
:::
```

### 🏷️ Topic Tagging (YAML Frontmatter)

Start a file at line 1 with YAML frontmatter to index it:

```yaml
---
tags: [software, security, draft]
---
```

---

## 🔒 Security & Access Controls

* **Credentials** come from `WIKI_ADMIN_USER` / `WIKI_ADMIN_PASSWORD` in `.env`. The default `admin`/`admin` prints a startup warning until changed.
* **Public (read) routes** — open to devices on your local network: `/`, `/wiki/*`, `/search`, `/graph`, `/tags`, `/quiz`, and the chat page.
* **Authenticated routes** — gated behind HTTP Basic Auth: `/edit/*`, `/upload-image`, `/settings`, `/journal/today`, HTTP `DELETE`, and the `/api/chat`, `/api/score`, `/api/inbox/*`, `/api/rag/*`, and `/api/terminal` endpoints.
* **Terminal execution is disabled by default.** The shell terminal and the AI's `execute_bash` tool only run when `ALLOW_TERMINAL=true`, and even then require authentication. Bind the app to a trusted, network-isolated host before enabling it.
* Uploaded filenames are sanitized to prevent path traversal, and backend error detail is hidden unless `DEBUG_MODE=true`.

> This is homelab-grade single-admin auth. Do not expose Pi Wiki directly to the public internet.

---

## 🗺️ Roadmap (Future Integrations)

**Recently shipped:** semantic RAG chat with citations, hybrid keyword+vector search, a UI settings tab, security hardening (opt-in terminal, env credentials, path-traversal fixes), and a self-hosted editorial redesign.

Next up:

**Phase 1 — Identity & Sessions**
Replace single-admin Basic Auth with a local user store, JWT / HTTP-only session cookies, and proper login/logout with a multi-user admin UI.

**Phase 2 — Cognitive Tooling**
A "Feynman Technique" critique agent that flags documentation leaning on jargon over core principles, and richer graph analytics.

**Phase 3 — Agentic Automation**
Background RSS workers that draft summaries into a `news/` directory, and an `rclone` pipeline to mirror the local Git repo off-site for disaster recovery.

---

## 📄 License

Distributed under the MIT License.
