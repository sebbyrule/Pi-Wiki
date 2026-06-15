import os
import httpx
import re
from pathlib import Path
from core.config import ARTICLES_DIR, INBOX_DIR
from services.git_service import commit_changes
from services.rag_service import embed_document

async def process_inbox_files():
    """Scans the inbox, formats raw text via LLM, and moves it to articles/"""
    inbox_files = list(INBOX_DIR.glob("*.txt")) + list(INBOX_DIR.glob("*.md"))
    if not inbox_files:
        return {"status": "empty", "message": "No files in inbox."}

    # Fetch the URL from your .env file
    lm_studio_url = os.getenv("LOCAL_AI_URL", "http://10.5.0.2:1234/v1/chat/completions")
    processed_count = 0
    errors = []

    for file_path in inbox_files:
        raw_text = file_path.read_text(encoding="utf-8")
        
        system_prompt = (
            "You are an expert technical editor. Your job is to take raw, messy brain dumps "
            "and format them into clean, structured Markdown documentation.\n"
            "Rules:\n"
            "1. Start the document with YAML frontmatter containing relevant 'tags'.\n"
            "2. Create a concise, descriptive # H1 Title.\n"
            "3. Output ONLY the formatted markdown, no conversational filler.\n"
            "Example Output:\n"
            "---\n"
            "tags: example, markdown\n"
            "---\n"
            "\n"
            "# Example Title\n"
            "\n"
            "This is an example of formatted markdown."
        )

        payload = {
            "model": "local-model",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Format this raw text:\n\n{raw_text}"}
            ],
            "temperature": 0.2, "max_tokens": 2000, "stream": False
        }

        try:
            # We explicitly wait for LM Studio
            async with httpx.AsyncClient() as client:
                response = await client.post(lm_studio_url, json=payload, timeout=120.0)
                
            if response.status_code == 200:
                formatted_md = response.json()["choices"][0]["message"]["content"].strip()
                safe_name = file_path.stem.lower().replace(" ", "-")
                new_article_path = ARTICLES_DIR / f"{safe_name}.md"
                
                new_article_path.write_text(formatted_md, encoding="utf-8")
                if response.status_code == 200:
                    formatted_md = response.json()["choices"][0]["message"]["content"].strip()
                    safe_name = file_path.stem.lower().replace(" ", "-")
                    new_article_path = ARTICLES_DIR / f"{safe_name}.md"

                    # Save to disk
                    new_article_path.write_text(formatted_md, encoding="utf-8")

                    # --- NEW: Save to Vector Memory ---
                    embed_document(safe_name, formatted_md)
                
                file_path.unlink() 
                processed_count += 1
            else:
                errors.append(f"LM Studio returned status {response.status_code}")
                
        except Exception as e:
            # WE NOW RETURN THE ERROR DIRECTLY TO THE BROWSER
            return {"status": "error", "message": f"Connection Failed: {str(e)}"}

    if processed_count > 0:
        commit_changes(f"Auto-Synthesizer: Processed {processed_count} files from inbox.")
        
    if errors:
        return {"status": "error", "message": " | ".join(errors)}
        
    return {"status": "success", "processed": processed_count}

async def process_with_local_ai(file_path: Path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        if "> **AI TL;DR:**" in content:
            return 

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
                
                yaml_match = re.match(r'^\s*---\r?\n.*?\r?\n---\r?\n', content, flags=re.DOTALL)
                if yaml_match:
                    frontmatter, body = yaml_match.group(0), content[yaml_match.end():]
                    new_content = f"{frontmatter}\n> **AI TL;DR:** {tldr}\n\n{body}{flashcards}"
                else:
                    new_content = f"> **AI TL;DR:** {tldr}\n\n{content}{flashcards}"
                
                with open(file_path, "w", encoding="utf-8") as f: 
                    f.write(new_content)
                commit_changes(f"LM Studio generated summary for {file_path.stem}")
    except Exception as e:
        print(f"LM Studio processing failed: {e}")