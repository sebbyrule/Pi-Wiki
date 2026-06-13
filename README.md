# 🥧 Pi Wiki: System Intelligence

Pi Wiki is a self-hosted, Dockerized knowledge management system and homelab dashboard designed for local infrastructure (like a Raspberry Pi). It transforms standard Markdown documentation into a highly connected, automated learning environment using local AI inference, spaced-repetition testing, real-time data visualization, and direct container shell access.

## 🕸️ Key Systems & Features

* **FastAPI Core Engine:** High-performance, modular routing, file management, and native asynchronous execution.
* **Interactive PiOS Terminal:** A browser-based, OS-aware interactive shell that allows unrestricted command execution inside the host container.
* **Terminal-to-Wiki Pipeline:** One-click ingestion that captures raw terminal output (like `nmap` scans or system logs) and automatically commits it as a tagged, formatted Markdown document.
* **Live Microservice Registry:** A centralized API dashboard utilizing embedded Swagger UI (`/docs`) to track the OpenAPI contracts of the Wiki and any other microservices running on the local network.
* **Local AI Integration (LM Studio):** Automated background processing that appends 1-sentence TL;DR summaries and extracts technical flashcards seamlessly without leaking data to public clouds.
* **Spaced-Repetition Review (SM-2):** A lightweight micro-learning suite using the SuperMemo-2 algorithm to dynamically track concept mastery and calculate custom card review intervals.
* **Interactive Knowledge Graph:** Real-time data visualization using `Vis.js` to map internal wikilinks and display topic clusters across documentation tags.
* **Automated Git Versioning:** Background file monitoring that automatically commits document updates, creations, or deletions directly to a local Git directory for strict version control.
* **Tailwind UI with Dark Mode:** Clean, responsive, multi-column dashboard with a sticky Table of Contents, inline copy-to-clipboard buttons for code blocks, and an adaptive dark-mode theme controller.

---

## 🛠️ Infrastructure & Tech Stack

* **Language/Runtime:** Python 3.11+
* **Framework:** FastAPI, Jinja2 Templates
* **Parsing Engine:** Python-Markdown (Extensions: `meta`, `extra`, `codehilite`, `toc`)
* **Frontend Layer:** Tailwind CSS (with Typography Plugin), Vis.js Network Library
* **Storage Engine:** Flat-file Markdown (`/articles`) & JSON tracking state
* **Orchestration:** Docker & Docker Compose (Base: `debian-slim` with `procps` for system monitoring)

---

## 🚀 Installation & Local Deployment

### 1. Prerequisites

Ensure you have **Docker** and **Docker Compose** installed on your hosting system. The application detects the host OS dynamically, allowing for seamless testing on Windows before deploying to a Linux/ARM64 environment like a Raspberry Pi.

### 2. Clone and Setup Environment

```bash
git clone <your-github-repository-url>
cd pi-wiki
cp .env.copy .env
Open the newly created .env file and configure your security credentials and local AI server endpoint.

3. Orchestrate with Docker
Bash
docker compose up --build -d
The application will compile, install necessary Linux system tools, and become available on your local network at http://localhost:8000 (or your host IP address).

📝 Syntax & Automation Guide
🔗 Bi-Directional Linking
Link files together dynamically by wrapping any page title in double brackets:

Markdown
Refer to the [[system-architecture]] page for hardware layouts.
🧠 Spaced-Repetition Flashcards
To feed the SM-2 review deck, append or type your concepts inside any document using the following exact syntax:

Plaintext
:::Q
What layer of the OSI model handles cryptographic encryption and compression?
:::A
The Presentation Layer (Layer 6).
:::
🏷️ Topic Tagging (YAML Frontmatter)
Enforce structured indexing by starting your files at line 1, character 1 with standard YAML:

YAML
---
tags: [software, security, draft]
---
🔒 Security & Access Controls
Read-only routes (/, /wiki/*, /graph, /tags) are open to devices inside your local network.

Write routes (/edit/*, /upload-image, /api/terminal, HTTP DELETE endpoints) are strictly gated behind HTTP Basic Authentication.

🗺️ Roadmap (Future Integrations)
Pi Wiki is actively evolving from a static knowledge base into an autonomous "Cognitive Workbench." Upcoming architectural phases include:

Phase 1: Security & Identity Overhaul
Replace hardcoded HTTP Basic Authentication with a local SQLite user database.

Implement JWT/HTTP-Only session cookies to support proper browser-based Login/Logout flows and multi-user administration UI.

Phase 2: Advanced EdTech & Cognitive Architecture
Semantic Search / RAG: Transition from basic string-matching search to a ChromaDB-backed vector search engine to query the context of the entire knowledge base.

Feynman Technique AI Agent: An automated critique tool that scans documentation and flags areas relying too heavily on jargon rather than core principles.

Phase 3: Agentic Infrastructure Automation
External Feed Integration (RSS): Background workers that poll designated tech feeds and auto-generate summary drafts into a news/ directory.

Automated Cloud Sync Pipeline: Implement an rclone background task to mirror the local Git repository to an off-site cloud provider for automated disaster recovery.

📄 License
Distributed under the MIT License.
