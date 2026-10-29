"""Small FastAPI wrapper to test semantic retrieval independently."""
from pathlib import Path
import os
import secrets
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from semantic_search import SemanticKnowledgeBase, DEFAULT_THRESHOLD
from rag_service import RAGService

ROOT = Path(__file__).resolve().parent
KB_PATH = ROOT / "knowledge_base.json"

app = FastAPI(title="HisabDo Semantic KB API", version="1.0.0")
kb = SemanticKnowledgeBase(kb_path=KB_PATH, threshold=DEFAULT_THRESHOLD)
rag = RAGService(kb)


class SearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=10)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "semantic-kb",
        "kb_version": kb.metadata.get("kb_version", "unknown"),
        "documents_loaded": len(kb.documents),
        "threshold": kb.threshold,
    }


@app.post("/search")
def search(request: SearchRequest):
    return rag.retrieve(request.question, top_k=request.top_k)


@app.post("/reload-kb")
def reload_kb(x_kb_reload_token: str | None = Header(default=None)):
    """Reload JSON only when a deployment-specific admin token is configured."""
    expected = os.getenv("KB_RELOAD_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="KB reload is disabled: configure KB_RELOAD_TOKEN.")
    if not x_kb_reload_token or not secrets.compare_digest(x_kb_reload_token, expected):
        raise HTTPException(status_code=403, detail="Not authorized to reload the knowledge base.")
    kb.reload()
    return {
        "status": "reloaded",
        "kb_version": kb.metadata.get("kb_version", "unknown"),
        "documents_loaded": len(kb.documents),
    }
