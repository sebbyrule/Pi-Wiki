import httpx
import re
from pathlib import Path
from services.git_service import commit_changes

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
                
                yaml_match = re.match(r'^---\n.*?\n---\n', content, flags=re.DOTALL)
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