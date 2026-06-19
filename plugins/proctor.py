import re
import random
from core.config import ARTICLES_DIR

tool_schema = {
    "type": "function",
    "function": {
        "name": "start_exam_mode",
        "description": "Fetches flashcards from the vector wiki to test the user. Use this when the user asks to be tested, quizzed, or requests an exam proctor.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "The specific topic to test (e.g., 'networking', 'hardware', 'general')"}
            },
            "required": ["topic"]
        }
    }
}

def run(topic: str, **kwargs):
    pattern = re.compile(r':::Q\r?\n(.*?)\r?\n:::A\r?\n(.*?)\r?\n:::', re.DOTALL)
    questions = []
    
    for file_path in ARTICLES_DIR.rglob("*.md"):
        content = file_path.read_text(encoding="utf-8")
        # Filter by topic if requested
        if topic.lower() != 'general' and topic.lower() not in content.lower() and topic.lower() not in file_path.name.lower():
            continue
            
        for idx, (q, a) in enumerate(pattern.findall(content)):
            questions.append({"Question": q.strip(), "Answer": a.strip()})

    if not questions:
        return {"status": "error", "message": f"No flashcards found for topic: {topic}"}

    # Grab 5 random questions for the AI to ask
    selected = random.sample(questions, min(5, len(questions)))
    return {
        "status": "success",
        "instructions": "Assume the persona of a strict but helpful exam proctor. Ask the user the FIRST question only. Wait for their response. Grade it, correct any misconceptions, and then ask the NEXT question.",
        "questions": selected
    }