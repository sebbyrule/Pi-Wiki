import importlib.util
from pathlib import Path
from core.config import PLUGINS_DIR

def load_plugins():
    """
    Dynamically scans the plugins folder and hot-loads Python scripts.
    Returns a dictionary of executable functions and a list of JSON schemas for the AI.
    """
    plugin_functions = {}
    tools_schema = []

    if not PLUGINS_DIR.exists():
        return plugin_functions, tools_schema

    for plugin_file in PLUGINS_DIR.glob("*.py"):
        if plugin_file.name == "__init__.py":
            continue

        try:
            # Dynamically import the python file without restarting the server
            module_name = plugin_file.stem
            spec = importlib.util.spec_from_file_location(module_name, plugin_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # A valid plugin must have a 'tool_schema' dict and a 'run' function
            if hasattr(module, "tool_schema") and hasattr(module, "run"):
                func_name = module.tool_schema["function"]["name"]
                plugin_functions[func_name] = module.run
                tools_schema.append(module.tool_schema)
                
        except Exception as e:
            print(f"[Plugin Engine] Failed to load plugin {plugin_file.name}: {e}")

    return plugin_functions, tools_schema