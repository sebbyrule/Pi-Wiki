import re
import subprocess
import importlib.util
from pathlib import Path
from core.config import PLUGINS_DIR

# --- 1. CORE AI BASH TOOL ---
def execute_bash(command: str, **kwargs):
    """
    Executes a shell script inside the sandboxed Docker container.
    Used by the AI to run procedures defined in SKILL.md playbooks.
    """
    try:
        # Timeout set to 30s to prevent the AI from hanging the server with infinite loops
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return {"status": "success", "output": result.stdout[:3000]} # Truncate massive outputs
        else:
            return {"status": "error", "output": result.stderr[:3000]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# The schema for the core Bash tool
base_tools = [{
    "type": "function",
    "function": {
        "name": "execute_bash",
        "description": "Executes a bash command or script inside the sandboxed Debian container. Use this to run scripts provided in skill playbooks.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The exact bash command or script path to execute."}
            },
            "required": ["command"]
        }
    }
}]

def load_plugins():
    """
    Sweeps the plugins directory for both legacy .py tools and 
    new Anthropic-style Progressive Disclosure SKILL.md folders.
    """
    plugin_functions = {"execute_bash": execute_bash}
    tools_schema = list(base_tools)

    if not PLUGINS_DIR.exists():
        return plugin_functions, tools_schema

    # --- 2. LEGACY PYTHON SCRIPTS (Backwards Compatibility) ---
    for plugin_file in PLUGINS_DIR.glob("*.py"):
        if plugin_file.name == "__init__.py": continue
        try:
            module_name = plugin_file.stem
            spec = importlib.util.spec_from_file_location(module_name, plugin_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Standard OpenAI Format
            if hasattr(module, "tool_schema") and hasattr(module, "run"):
                func_name = module.tool_schema["function"]["name"]
                plugin_functions[func_name] = module.run
                tools_schema.append(module.tool_schema)
            # Anthropic Format Bridge
            elif hasattr(module, "anthropic_skill") and hasattr(module, "run"):
                skill = module.anthropic_skill
                func_name = skill["name"]
                plugin_functions[func_name] = module.run
                tools_schema.append({
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "description": skill.get("description", ""),
                        "parameters": skill.get("input_schema", {"type": "object", "properties": {}})
                    }
                })
        except Exception as e:
            print(f"[Plugin Engine] Failed to load legacy plugin {plugin_file.name}: {e}")

    # --- 3. ANTHROPIC PROGRESSIVE DISCLOSURE SKILLS ---
    for skill_dir in PLUGINS_DIR.iterdir():
        if not skill_dir.is_dir(): continue
        
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists(): continue
        
        try:
            content = skill_md.read_text(encoding="utf-8")
            
            # Extract YAML frontmatter
            match = re.match(r'^---\n(.*?)\n---\n(.*)', content, re.DOTALL)
            if not match: continue
            
            frontmatter, body = match.groups()
            
            # Parse the metadata without importing heavy YAML libraries
            name_match = re.search(r'name:\s*(.+)', frontmatter)
            desc_match = re.search(r'description:\s*(.+)', frontmatter)
            
            if not name_match or not desc_match: continue
            
            skill_name = name_match.group(1).strip()
            skill_desc = desc_match.group(1).strip()
            
            # Create a dynamic closure that returns the playbook body when the AI calls this skill
            def create_playbook_reader(playbook_text):
                def read_playbook(**kwargs):
                    return {
                        "status": "success", 
                        "instructions": "You have unlocked the playbook. Read it carefully and immediately use the 'execute_bash' tool to perform the required actions.", 
                        "playbook": playbook_text
                    }
                return read_playbook
                
            plugin_functions[skill_name] = create_playbook_reader(body.strip())
            
            # Expose ONLY the lightweight description to the LLM's context window
            tools_schema.append({
                "type": "function",
                "function": {
                    "name": skill_name,
                    "description": skill_desc + " (Call this tool to read the workflow playbook)",
                    "parameters": {"type": "object", "properties": {}}
                }
            })
        except Exception as e:
            print(f"[Plugin Engine] Failed to load folder skill {skill_dir.name}: {e}")

    return plugin_functions, tools_schema