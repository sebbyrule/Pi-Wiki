import platform

# Look here! We are using Anthropic's exact "input_schema" structure
anthropic_skill = {
    "name": "get_system_info",
    "description": "Retrieves the host operating system information and architecture. Use this when asked about the server hardware.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verbose": {
                "type": "boolean",
                "description": "If true, returns detailed architecture info."
            }
        },
        "required": []
    }
}

def run(verbose: bool = False, **kwargs):
    system = platform.system()
    release = platform.release()
    
    if verbose:
        arch = platform.machine()
        return {"status": "success", "data": f"{system} {release} (Architecture: {arch})"}
        
    return {"status": "success", "data": f"{system} {release}"}