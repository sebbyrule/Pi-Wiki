import json
import httpx
from pathlib import Path
import core.config as config
from core.config import INBOX_DIR, ARTICLES_DIR
from services.git_service import commit_changes
from services.rag_service import embed_document

# Cap on characters pulled from a single PDF before it is sent to the LLM.
PDF_CHAR_LIMIT = 12000


async def generate_with_reflection(raw_text: str, client: httpx.AsyncClient) -> str:
    """Multi-Agent Reflection Loop: Writer -> Evaluator -> Reviser"""
    
    # 1. THE WRITER AGENT
    writer_prompt = (
        "You are an expert technical editor. Format this raw text into clean, structured Markdown.\n"
        "Rules:\n"
        "1. Start with YAML frontmatter containing 'tags' (e.g. tags: hardware, networking).\n"
        "2. Do NOT use square brackets in the tags.\n"
        "3. Create a concise # H1 Title.\n"
        "4. Output ONLY the raw markdown, no conversational filler."
    )
    
    messages = [
        {"role": "system", "content": writer_prompt},
        {"role": "user", "content": f"Format this raw text/transcript:\n\n{raw_text}"}
    ]
    
    payload = {"model": config.LOCAL_AI_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": config.MAX_AI_TOKENS}
    response = await client.post(config.LOCAL_AI_URL, json=payload, timeout=120.0)
    draft = response.json()["choices"][0]["message"]["content"].strip()
    
    # 2. THE EVALUATOR AGENT
    critic_prompt = (
        "You are an AI Quality Assurance Evaluator. Inspect the following Markdown draft.\n"
        "Grade it against this strict rubric:\n"
        "1. Frontmatter: Must have valid YAML tags WITHOUT square brackets.\n"
        "2. Formatting: Must have clear headers and no conversational filler (like 'Here is the formatted text').\n"
        "3. Depth: If the document covers hardware, networking, or infrastructure topics, ensure it is detailed enough for a certification exam candidate.\n"
        "Respond strictly with a JSON object: {\"passed\": true/false, \"feedback\": \"Specific instructions on what to fix\"}"
    )
    
    eval_payload = {
        "model": config.LOCAL_AI_MODEL,
        "messages": [
            {"role": "system", "content": critic_prompt},
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