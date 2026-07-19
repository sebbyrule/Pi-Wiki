import json
import httpx
from pathlib import Path
import core.config as config
from core.config import INBOX_DIR, ARTICLES_DIR
from services.git_service import commit_changes
from services.rag_service import embed_document

# Cap on characters pulled from a single PDF before it is sent to the LLM.
PDF_CHAR_LIMIT = 12000

# --- Generation prompts -----------------------------------------------------
# Kept as named module constants so they are easy to find and tune without
# touching the control flow. The inbox synthesizer turns each raw note into a
# structured wiki page: frontmatter -> title -> TL;DR -> body -> review cards.

WRITER_SYSTEM_PROMPT = """You are an expert technical editor building a personal wiki. Turn the raw input into ONE clean Markdown document with this EXACT structure, in this order:

1. YAML frontmatter with 2-5 lowercase topic tags. No square brackets.
2. A single `# Title` (concise, specific — name the actual subject).
3. A TL;DR line, written as: `> **TL;DR:** <one or two sentences>`.
4. The cleaned, well-structured body (use `##` headings, lists, and code fences where useful).
5. A final `## Review` section containing 3-6 spaced-repetition flashcards.

TL;DR rules:
- State the key takeaway as a direct factual claim. Lead with the substance.
- BANNED openers: "This text/document/note...", "In this...", "The following...", "This covers/introduces/discusses...". Never describe the document; state what it TEACHES.

Flashcard rules (one atomic fact per card):
- Each card tests exactly ONE idea. No compound "and"/"or" questions.
- Prefer "why/how/what-is" questions over yes/no or fill-in-the-blank.
- The question must be self-contained (answerable without seeing this page).
- Keep answers to 1-2 sentences. Skip trivia (exact dates/numbers) unless central.
- Use this EXACT syntax, each card separated by a blank line:

:::Q
What does X do?
:::A
X does Y.
:::

Output ONLY the raw Markdown — no code fences around the whole document, no conversational filler.

Example of the expected shape:
---
tags: networking, linux
---
# Reverse Proxy with Nginx

> **TL;DR:** Nginx forwards outside requests to internal services by hostname, letting one public port serve many backends over TLS.

## How it works
A `server` block matches the incoming host and `proxy_pass` sends the request to an upstream address.

## Review

:::Q
What directive forwards a request to an upstream service in Nginx?
:::A
`proxy_pass`, inside a `location` block.
:::

:::Q
Why use a reverse proxy in front of multiple services?
:::A
It lets a single public entry point route to many internal backends and centralizes TLS termination.
:::"""

EVALUATOR_SYSTEM_PROMPT = """You are a strict QA evaluator for wiki documents. Grade the draft against this rubric and fail it if ANY item is violated:
1. Frontmatter: valid YAML `tags:` with 2-5 lowercase tags, no square brackets.
2. Structure: has a single `# Title`, a `> **TL;DR:**` line, body content, and a `## Review` section.
3. TL;DR: states the takeaway directly; does NOT open with "This document/text...", "In this...", or similar meta-description.
4. Flashcards: 3-6 cards in the exact `:::Q / :::A / :::` syntax; each tests ONE atomic fact; no yes/no or compound questions.
5. Cleanliness: no conversational filler ("Here is...", "Sure!") and no code fence wrapping the whole document.

Respond with ONLY a JSON object: {"passed": true/false, "feedback": "specific, actionable fixes"}"""


async def generate_with_reflection(raw_text: str, client: httpx.AsyncClient) -> str:
    """Multi-Agent Reflection Loop: Writer -> Evaluator -> Reviser"""

    # 1. THE WRITER AGENT
    messages = [
        {"role": "system", "content": WRITER_SYSTEM_PROMPT},
        {"role": "user", "content": f"Turn this raw note/transcript into a wiki document:\n\n{raw_text}"}
    ]

    payload = {"model": config.LOCAL_AI_MODEL, "messages": messages, "temperature": 0.3, "max_tokens": config.MAX_AI_TOKENS}
    response = await client.post(config.LOCAL_AI_URL, json=payload, timeout=120.0)
    draft = response.json()["choices"][0]["message"]["content"].strip()

    # 2. THE EVALUATOR AGENT
    eval_payload = {
        "model": config.LOCAL_AI_MODEL,
        "messages": [
            {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
            {"role": "user", "content": f"Evaluate this draft:\n\n{draft}"}
        ],
        "temperature": 0.1
    }

    eval_response = await client.post(config.LOCAL_AI_URL, json=eval_payload, timeout=120.0)
    eval_result = eval_response.json()["choices"][0]["message"]["content"].strip()
    
    # Clean the JSON output (in case the local model wraps it in markdown blocks)
    eval_result = eval_result.replace("```json", "").replace("```", "").strip()
    
    try:
        evaluation = json.loads(eval_result)
        
        # If the Evaluator is happy, return the original draft
        if evaluation.get("passed") is True:
            print("[Self-Reflection] Document passed validation on the first attempt.")
            return draft
            
        print(f"[Self-Reflection] Document failed validation. Critic feedback: {evaluation.get('feedback')}")
        
        # 3. THE REVISER AGENT
        messages.extend([
            {"role": "assistant", "content": draft},
            {"role": "user", "content": f"The QA Evaluator rejected this draft with the following feedback: {evaluation.get('feedback')}\n\nPlease rewrite the draft, fixing all errors. Output ONLY the fixed markdown."}
        ])
        
        payload["messages"] = messages
        retry_response = await client.post(config.LOCAL_AI_URL, json=payload, timeout=120.0)
        final_draft = retry_response.json()["choices"][0]["message"]["content"].strip()
        print("[Self-Reflection] Document successfully revised.")
        return final_draft
        
    except json.JSONDecodeError:
        # Fallback if the local model failed to output valid JSON
        print("[Self-Reflection] Critic failed to output valid JSON. Proceeding with initial draft.")
        return draft

async def process_inbox_files():
    """
    Scans the inbox recursively, preserves directory sub-folders,
    normalizes filenames to perfectly match Web Router lookups, and moves to articles/
    """
    audio_extensions = (".mp3", ".wav", ".m4a")
    doc_extensions = (".txt", ".md", ".pdf")
    valid_extensions = list(doc_extensions) + list(audio_extensions)
    
    # 1. Use rglob to scan recursively for folders nested in the inbox
    inbox_files = [f for f in INBOX_DIR.rglob("*") if f.suffix.lower() in valid_extensions]
    
    if not inbox_files:
        return {"status": "empty", "message": "No files in inbox."}

    processed_count = 0
    errors = []
    whisper_model = None

    for file_path in inbox_files:
        try:
            # 2. Extract Text Content
            if file_path.suffix.lower() in audio_extensions:
                if whisper_model is None:
                    import whisper
                    whisper_model = whisper.load_model("base")
                result = whisper_model.transcribe(str(file_path))
                raw_text = result["text"]
                
            elif file_path.suffix.lower() == ".pdf":
                import fitz
                doc = fitz.open(str(file_path))
                raw_text = ""
                for page in doc:
                    raw_text += page.get_text("text") + "\n\n"
                if len(raw_text) > PDF_CHAR_LIMIT:
                    print(f"[INBOX] {file_path.name}: PDF text truncated from {len(raw_text)} to {PDF_CHAR_LIMIT} chars.")
                    raw_text = raw_text[:PDF_CHAR_LIMIT]

            else:
                raw_text = file_path.read_text(encoding="utf-8")

            # 3. Format with the Multi-Agent Reflection Loop
            async with httpx.AsyncClient() as client:
                formatted_md = await generate_with_reflection(raw_text, client)
            
            # 4. Map the path dynamically, preserving subfolder structure
            # e.g., inbox/comptia-a-plus/networking.pdf -> relative path: comptia-a-plus/networking.pdf
            relative_path = file_path.relative_to(INBOX_DIR)
            
            # Break down the path parts to clean them exactly like the web router
            cleaned_parts = []
            for part in relative_path.parent.parts:
                # Clean subfolder names
                cleaned_folder = "".join(c for c in part if c.isalnum() or c in ("-", "_")).lower().strip("-")
                cleaned_parts.append(cleaned_folder)
            
            # Clean the file stem name (removes extensions safely)
            cleaned_stem = "".join(c for c in file_path.stem if c.isalnum() or c in ("-", "_", " ")).lower()
            cleaned_stem = cleaned_stem.replace(" ", "-").strip("-")
            
            # Combine back together under the articles directory
            target_sub_dir = ARTICLES_DIR / Path(*cleaned_parts)
            target_sub_dir.mkdir(parents=True, exist_ok=True) # Create folders on disk if missing
            
            new_article_path = target_sub_dir / f"{cleaned_stem}.md"
            new_article_path.write_text(formatted_md, encoding="utf-8")
            
            # 5. Extract a safe posix path name for ChromaDB (e.g., 'comptia-a-plus/networking')
            vector_db_name = new_article_path.relative_to(ARTICLES_DIR).with_suffix("").as_posix()
            
            embed_document(vector_db_name, formatted_md) 
            file_path.unlink() # Safely remove original from inbox
            processed_count += 1
                
        except Exception as e:
            import traceback
            print(f"[INBOX ERROR TRACEBACK]\n{traceback.format_exc()}")
            errors.append(f"Processing failed for {file_path.name}: {str(e)}")

    if processed_count > 0:
        commit_changes(f"Auto-Synthesizer: Processed {processed_count} files using directory mirroring.")
        
    if errors:
        return {"status": "error", "message": " | ".join(errors)}
        
    return {"status": "success", "processed": processed_count}

async def process_with_local_ai(file_path: Path):
    """
    Background task for manually edited files from the Web UI.
    Automatically syncs your manual edits directly into the Vector Database.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        # Extract the correct relative path (e.g., 'linux/docker')
        safe_name = file_path.relative_to(ARTICLES_DIR).with_suffix("").as_posix()
        
        # Update ChromaDB so Semantic Chat instantly knows about your edits
        embed_document(safe_name, content)
        print(f"[Vector DB] Successfully updated memory for {safe_name}")
    except Exception as e:
        print(f"[Vector DB] Error updating memory for {file_path.name}: {str(e)}")