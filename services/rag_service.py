import re
import chromadb
from pathlib import Path
from core.config import CHROMA_DIR

# 1. Initialize the persistent local database
chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))

# ChromaDB defaults to 'all-MiniLM-L6-v2' (a highly optimized local embedding model).
# This creates a collection (like a SQL table) for our wiki data.
collection = chroma_client.get_or_create_collection(name="wiki_knowledge")

def chunk_text(text: str, chunk_size: int = 300, overlap: int = 50):
    """Splits markdown into manageable semantic chunks for the AI to read."""
    # Strip out the YAML frontmatter so it doesn't confuse the embedder
    text = re.sub(r'^\s*---\r?\n.*?\r?\n---\r?\n', '', text, flags=re.DOTALL)
    
    words = text.split()
    chunks = []
    
    # Sliding window approach to create overlapping text chunks
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks

def embed_document(file_name: str, content: str):
    """Embeds a single document into the vector database."""
    chunks = chunk_text(content)
    if not chunks:
        return
    
    # We need unique IDs for every chunk so we can overwrite them if the document changes
    ids = [f"{file_name}-chunk-{i}" for i in range(len(chunks))]
    metadatas = [{"source": file_name} for _ in chunks]
    
    # Upsert automatically inserts new chunks or overwrites existing ones
    collection.upsert(
        documents=chunks,
        metadatas=metadatas,
        ids=ids
    )
    print(f"[RAG] Successfully embedded {len(chunks)} chunks for {file_name}")

def query_knowledge_base(query: str, n_results: int = 4):
    """Searches the vector database for the most relevant context chunks."""
    results = collection.query(
        query_texts=[query],
        n_results=n_results
    )
    return results

def retrieve_context(query: str, n_results: int = 4):
    """Retrieve grounding context for a chat answer.

    Returns a tuple of (context_block, sources) where context_block is a
    formatted string of the most relevant chunks and sources is the list of
    unique source page names (in relevance order) for citation.
    """
    results = query_knowledge_base(query, n_results=n_results)
    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]

    if not documents:
        return "", []

    blocks = []
    sources = []
    for doc, meta in zip(documents, metadatas):
        source = (meta or {}).get("source", "unknown")
        if source not in sources:
            sources.append(source)
        blocks.append(f"[Source: {source}]\n{doc}")

    context_block = "\n\n---\n\n".join(blocks)
    return context_block, sources