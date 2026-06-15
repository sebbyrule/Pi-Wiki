import datetime

# 1. The JSON Schema tells the AI exactly what this tool does and how to use it
tool_schema = {
    "type": "function",
    "function": {
        "name": "get_server_time",
        "description": "Fetches the live, real-time date and time from the host operating system. Use this whenever the user asks for the current time or date.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}

# 2. The executable function that runs when the AI requests it
def run(**kwargs):
    current_time = datetime.datetime.now().strftime("%A, %B %d, %Y at %I:%M:%S %p")
    return {"status": "success", "live_time": current_time}