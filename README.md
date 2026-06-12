# 🥧 Pi Wiki

Pi Wiki is a self-hosted, Dockerized knowledge management system designed for local infrastructure (like a Raspberry Pi). It transforms standard Markdown documentation into a highly connected, automated learning environment using local AI inference, spaced-repetition testing, and real-time data visualization.

## 🕸️ Key Systems & Features

* **FastAPI Core Engine:** High-performance routing, file management, and native asynchronous execution.
* **Local AI Integration (LM Studio):** Automated background processing that appends a 1-sentence TL;DR summary and extracts technical flashcards seamlessly without leaking data to public clouds.
* **Spaced-Repetition Review (SM-2):** A lightweight micro-learning suite using the SuperMemo-2 algorithm to dynamically track concept mastery and calculate custom card review intervals.
* **Interactive Knowledge Graph:** Real-time data visualization using `Vis.js` to map internal wikilinks and display topic clusters across documentation tags.
* **Automated Git Versioning:** Background file monitoring that automatically commits document updates, creations, or deletions directly to a local Git directory for strict version control.
* **Static HTML Export:** A one-click compiler that renders any markdown document and its asset links into a single standalone HTML layout for quick sharing.
* **Tailwind UI with Dark Mode:** Clean, responsive, multi-column dashboard with a sticky, collapsible Table of Contents and an inline dark-mode theme controller.

---

## 🛠️ Infrastructure & Tech Stack

* **Language/Runtime:** Python 3.11+
* **Framework:** FastAPI, Jinja2 Templates
* **Parsing Engine:** Python-Markdown (Extensions: `meta`, `extra`, `codehilite`, `toc`)
* **Frontend Layer:** Tailwind CSS (with Typography Plugin), Vis.js Network Library
* **Storage Engine:** Flat-file Markdown (`/articles`) & JSON tracking state
* **Orchestration:** Docker & Docker Compose

---

## 🚀 Installation & Local Deployment

### 1. Prerequisites

Ensure you have **Docker** and **Docker Compose** installed on your hosting system (e.g., Raspberry Pi or local server).

### 2. Clone and Setup Environment

```bash
git clone <your-github-repository-url>
cd pi-wiki
cp .env.copy .env
Open the newly created .env file and configure your security credentials and local AI server endpoint.

3. Orchestrate with Docker
Bash
docker compose up --build -d
The application will compile and become available on your local network at http://localhost:8000 (or your host IP address).

📝 Syntax & Automation Guide
🔗 Bi-Directional Linking
Link files together dynamically by wrapping any page title in double brackets:

Markdown
Refer to the [[system-architecture]] page for hardware layouts.
The engine will parse this into an HTML anchor link and map a structural edge in your Knowledge Graph.

🧠 Spaced-Repetition Flashcards
To feed the SM-2 review deck, append or type your concepts inside any document using the following exact syntax:

Plaintext
:::Q
What layer of the OSI model handles cryptographic encryption and compression?
:::A
The Presentation Layer (Layer 6).
:::
The local AI processor can automatically generate these blocks for you during document edits.

🏷️ Topic Tagging (YAML Frontmatter)
Enforce structured indexing by starting your files at line 1, character 1 with standard YAML:

YAML
---
tags: software, security, draft
---
🔒 Security & RBAC
Read-only routes (/, /wiki/*, /graph, /tags) are open to devices inside your local network.

Write routes (/edit/*, /upload-image, HTTP DELETE endpoints) are strictly gated behind HTTP Basic Authentication.

📄 License
Distributed under the MIT License.
