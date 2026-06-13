import json
from datetime import datetime, timedelta
from pydantic import BaseModel
from core.config import DATA_FILE

class SM2Score(BaseModel):
    card_id: str
    quality: int

def load_progress():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_progress(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def update_card_score(score: SM2Score):
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