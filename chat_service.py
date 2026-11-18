"""Grounded chat orchestration with fail-closed source citation validation."""
from __future__ import annotations

import re
from typing import Any

from conversation_safety import inspect_support_request
SAFE_FALLBACK = (
    "I couldn't find a sufficiently relevant, approved and verified source for that question. "
    "Could you rephrase it or check the official HisabDo support documentation?"
)

_CITATION = re.compile(r"\[([A-Za-z0-9_-]+)\]")


class ChatService:
    def __init__(self, rag: Any, llm: Any) -> None:
        self.rag = rag
        self.llm = llm

    def answer(self, question: str, top_k: int = 3) -> dict[str, Any]:
        safety = inspect_support_request(question)
        if not safety.allowed:
            return {"status": "blocked", "reason": safety.reason, "answer": SAFE_FALLBACK, "citations": []}
        if safety.escalation_required:
            return {
                "status": "escalation_requested",
                "reason": safety.reason,
                "answer": "Your request has been identified for human support. A live support handoff is not configured in this service.",
                "citations": [],
            }

        retrieved = self.rag.retrieve(question, top_k=top_k)
        if not retrieved.get("found"):
            return {"status": "source_unavailable", "answer": SAFE_FALLBACK, "citations": [],
                    "kb_version": retrieved.get("kb_version", "unknown")}

        sources = retrieved.get("sources", [])
        allowed_ids = {str(source.get("id", "")) for source in sources if source.get("id")}
        if not allowed_ids:
            return {"status": "source_unavailable", "answer": SAFE_FALLBACK, "citations": []}
        try:
            answer = self.llm.generate(question, retrieved.get("answer_context", ""), sorted(allowed_ids))
        except Exception:
            return {"status": "generation_unavailable", "answer": SAFE_FALLBACK, "citations": [],
                    "kb_version": retrieved.get("kb_version", "unknown")}

        cited_ids = set(_CITATION.findall(answer))
        # Reject missing, malformed, or invented citations rather than returning an ungrounded answer.
        if not cited_ids or not cited_ids.issubset(allowed_ids):
            return {"status": "citation_validation_failed", "answer": SAFE_FALLBACK, "citations": [],
                    "kb_version": retrieved.get("kb_version", "unknown")}
        citations = [source for source in sources if source.get("id") in cited_ids]
        return {"status": "answered", "answer": answer, "citations": citations,
                "kb_version": retrieved.get("kb_version", "unknown")}
