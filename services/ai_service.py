import os
import json
import httpx
from pathlib import Path
from core.config import INBOX_DIR, ARTICLES_DIR
from services.git_service import commit_changes
from services.rag_service import embed_document

async def generate_with_reflection(raw_text: str, client: httpx.AsyncClient, lm_studio_url: str) -> str:
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
    
    payload = {"model": "local-model", "messages": messages, "temperature": 0.2, "max_tokens": 2000}
    response = await client.post(lm_studio_url, json=payload, timeout=120.0)
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
        "model": "local-model",
        "messages": [
            {"role": "system", "content": critic_prompt},
            {"role": "user", "content": f"Evaluate this draft:\n\n{draft}"}
        ],
        "temperature": 0.1
    }
    
    eval_response = await client.post(lm_studio_url, json=eval_payload, timeout=120.0)
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
        retry_response = await client.post(lm_studio_url, json=payload, timeout=120.0)
        final_draft = retry_response.json()["choices"][0]["message"]["content"].strip()
        print("[Self-Reflection] Document successfully revised.")
        return final_draft
        
    except json.JSONDecodeError:
        # Fallback if the local model failed to output valid JSON
        print("[Self-Reflection] Critic failed to output valid JSON. Proceeding with initial draft.")
        return draft

async def process_inbox_files():
    """Scans the inbox, transcribes audio, uses reflective formatting, and moves it to articles/"""
    audio_extensions = (".mp3", ".wav", ".m4a")
    doc_extensions = (".txt", ".md", ".pdf")
    
    inbox_files = [f for f in INBOX_DIR.glob("*.*") if f.suffix.lower() in list(doc_extensions) + list(audio_extensions)]
    
    if not inbox_files:
        return {"status": "empty", "message": "No files in inbox."}

    lm_studio_url = os.getenv("LOCAL_AI_URL", "http://host.docker.internal:1234/v1/chat/completions")
    processed_count = 0
    errors = []
    whisper_model = None

    for file_path in inbox_files:
        # Extract Text
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
            raw_text = raw_text[:12000] 
            
        else:
            raw_text = file_path.read_text(encoding="utf-8")
        
        # Format with the new Multi-Agent Reflection Loop
        try:
            async with httpx.AsyncClient() as client:
                formatted_md = await generate_with_reflection(raw_text, client, lm_studio_url)
                
            safe_name = file_path.stem.lower().replace(" ", "-")
            new_article_path = ARTICLES_DIR / f"{safe_name}.md"
            new_article_path.write_text(formatted_md, encoding="utf-8")
            
            embed_document(safe_name, formatted_md) 
            file_path.unlink() 
            processed_count += 1
                
        except Exception as e:
            errors.append(f"Processing failed for {file_path.name}: {str(e)}")

    if processed_count > 0:
        commit_changes(f"Auto-Synthesizer: Processed {processed_count} files using Reflection.")
        
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