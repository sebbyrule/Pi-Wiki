import urllib.request
import re
from html.parser import HTMLParser

class TagStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_data = []
    def handle_data(self, data):
        text = data.strip()
        if text: self.text_data.append(text)

tool_schema = {
    "type": "function",
    "function": {
        "name": "scrape_url",
        "description": "Reads a webpage and returns its text. Use this when a user asks you to read, summarize, or extract information from a specific URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The full HTTP/HTTPS URL to scrape (e.g., https://example.com)"}
            },
            "required": ["url"]
        }
    }
}

def run(url: str, **kwargs):
    try:
        # Pretend to be a standard web browser to bypass basic blocks
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
            # Clean out massive script and style blocks before parsing
            html = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<style.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
            
            stripper = TagStripper()
            stripper.feed(html)
            
            # Truncate to ~6000 chars to avoid blowing up the local model's context window
            content = " ".join(stripper.text_data)[:6000]
            return {"status": "success", "content": content}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}