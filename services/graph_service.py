import re
from core.config import ARTICLES_DIR
from services.markdown_service import render_markdown_file

def build_graph_data():
    nodes, edges = [], []
    for file_path in ARTICLES_DIR.glob("*.md"):
        node_id = file_path.stem
        _, tags, _ = render_markdown_file(file_path)
        group = tags[0] if tags else "article"
        nodes.append({"id": node_id, "label": node_id.replace("-", " ").title(), "group": group})
        
        content = file_path.read_text(encoding="utf-8")
        links = re.findall(r'\[\[(.*?)\]\]', content)
        for link in links:
            edges.append({"from": node_id, "to": link.lower().replace(" ", "-")})
            
    return {"nodes": nodes, "edges": edges}