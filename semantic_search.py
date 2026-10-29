"""Embedding-based semantic retrieval for the HisabDo knowledge base."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_THRESHOLD = 0.42


@dataclass
class SearchResult:
    """A verified and approved knowledge-base search result with audit metadata."""
    id: str
    title: str
    content: str
    source: str
    version: str
    verified: bool
    score: float
    doc_type: str
    source_owner: str
    source_url: str
    last_verified_date: str
    approval_status: str
    privacy_review: str


class SemanticKnowledgeBase:
    """Load, validate, embed, and search approved knowledge-base documents."""

    def __init__(
        self,
        kb_path: str | Path = "knowledge_base.json",
        model_name: str = DEFAULT_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self.kb_path = Path(kb_path)
        self.threshold = float(threshold)
        if not math.isfinite(self.threshold) or not -1.0 <= self.threshold <= 1.0:
            raise ValueError("Similarity threshold must be finite and between -1 and 1.")
        self.model = SentenceTransformer(model_name)
        self.metadata: dict[str, Any] = {}
        self.documents: list[dict[str, Any]] = []
        self.texts: list[str] = []
        self.embeddings: np.ndarray | None = None
        self.reload()

    @staticmethod
    def _clean_text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    @classmethod
    def _normalize_document(cls, document: dict[str, Any]) -> dict[str, Any] | None:
        doc_id = cls._clean_text(document.get("id"))
        title = cls._clean_text(document.get("title"))
        content = cls._clean_text(document.get("content"))
        if not doc_id or not title or not content:
            return None

        raw_aliases = document.get("aliases", [])
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        elif not isinstance(raw_aliases, list):
            raw_aliases = []
        aliases = [a.strip() for a in raw_aliases if isinstance(a, str) and a.strip()]

        normalized = dict(document)
        normalized.update(id=doc_id, title=title, content=content, aliases=aliases)
        return normalized

    @classmethod
    def _has_complete_audit_metadata(cls, document: dict[str, Any]) -> bool:
        """Only allow indexing when required source and review metadata is valid."""
        audit = document.get("audit")
        if not isinstance(audit, dict):
            return False

        source_owner = cls._clean_text(audit.get("source_owner"))
        source_url = cls._clean_text(audit.get("source_url"))
        verified_date = cls._clean_text(audit.get("last_verified_date"))
        privacy_review = cls._clean_text(audit.get("privacy_review")).lower()

        if not source_owner or not source_url or not verified_date:
            return False
        parsed_url = urlparse(source_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            return False
        try:
            date.fromisoformat(verified_date)
        except ValueError:
            return False
        # Privacy review must be explicitly approved, not merely present/pending.
        if privacy_review != "approved":
            return False
        return True

    @classmethod
    def _is_indexing_eligible(cls, document: dict[str, Any]) -> bool:
        audit = document.get("audit")
        if not isinstance(audit, dict):
            return False
        return (
            document.get("verified") is True
            and audit.get("approval_status") == "approved"
            and audit.get("indexing_eligible") is True
            and cls._has_complete_audit_metadata(document)
        )

    def reload(self) -> None:
        """Read and validate the KB, then atomically replace the indexed state."""
        try:
            raw_data = self.kb_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Knowledge base file not found: {self.kb_path}") from exc
        except OSError as exc:
            raise OSError(f"Unable to read knowledge base: {self.kb_path}") from exc
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in knowledge base file {self.kb_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Knowledge base JSON must contain a top-level object.")
        raw_documents = data.get("documents", [])
        if not isinstance(raw_documents, list):
            raise ValueError("Knowledge base 'documents' must be a list.")

        normalized_docs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        duplicate_ids: set[str] = set()
        for item in raw_documents:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_document(item)
            if normalized is None:
                continue
            doc_id = normalized["id"]
            if doc_id in seen_ids:
                duplicate_ids.add(doc_id)
            seen_ids.add(doc_id)
            normalized_docs.append(normalized)
        if duplicate_ids:
            duplicate_list = ", ".join(sorted(duplicate_ids))
            raise ValueError(f"Duplicate knowledge-base document IDs detected: {duplicate_list}")

        # Fail closed: only verified, approved, privacy-reviewed documents with
        # complete source-owner, source-URL, and ISO last-verified-date metadata are indexed.
        documents = [doc for doc in normalized_docs if self._is_indexing_eligible(doc)]
        texts = [
            f"Title: {doc['title']}. Type: {self._clean_text(doc.get('type')) or 'document'}. "
            f"Content: {doc['content']}. Alternative questions: {'; '.join(doc['aliases'])}"
            for doc in documents
        ]

        embeddings: np.ndarray | None = None
        if texts:
            vectors = self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
            embeddings = np.asarray(vectors, dtype=np.float32)
            if embeddings.ndim != 2:
                raise ValueError("Embedding model returned an invalid matrix.")
            if embeddings.shape[0] != len(documents):
                raise ValueError("Embedding count does not match document count.")
            if embeddings.shape[1] == 0:
                raise ValueError("Embedding vectors cannot be empty.")
            if not np.isfinite(embeddings).all():
                raise ValueError("Embedding model returned non-finite values.")

        self.metadata = {
            "kb_version": data.get("kb_version", "unknown"),
            "updated_at": data.get("updated_at", ""),
        }
        self.documents = documents
        self.texts = texts
        self.embeddings = embeddings

    def search(self, query: str, top_k: int = 3) -> list[SearchResult]:
        """Return relevant, verified, approved, and audit-complete documents."""
        query = self._clean_text(query)
        if not query or self.embeddings is None:
            return []
        if not isinstance(top_k, int) or isinstance(top_k, bool):
            raise TypeError("top_k must be an integer.")
        if top_k <= 0:
            return []

        query_vectors = self.model.encode([query], normalize_embeddings=True, convert_to_numpy=True)
        query_vector = np.asarray(query_vectors, dtype=np.float32)
        if (query_vector.ndim != 2 or query_vector.shape[0] != 1
                or query_vector.shape[1] != self.embeddings.shape[1]):
            raise ValueError("Query embedding dimensions do not match KB embeddings.")
        query_vector = query_vector[0]
        if not np.isfinite(query_vector).all():
            raise ValueError("Embedding model returned an invalid query vector.")

        scores = self.embeddings @ query_vector
        ranked_indices = np.argsort(scores)[::-1]
        results: list[SearchResult] = []
        for index in ranked_indices:
            idx = int(index)
            score = float(scores[idx])
            document = self.documents[idx]
            if score < self.threshold or not self._is_indexing_eligible(document):
                continue
            audit = document["audit"]
            results.append(SearchResult(
                id=document["id"], title=document["title"], content=document["content"],
                source=self._clean_text(document.get("source")) or "Knowledge Base",
                version=str(document.get("version", self.metadata["kb_version"])),
                verified=True, score=score,
                doc_type=self._clean_text(document.get("type")) or "document",
                source_owner=self._clean_text(audit.get("source_owner")),
                source_url=self._clean_text(audit.get("source_url")),
                last_verified_date=self._clean_text(audit.get("last_verified_date")),
                approval_status=self._clean_text(audit.get("approval_status")),
                privacy_review=self._clean_text(audit.get("privacy_review")),
            ))
            if len(results) >= top_k:
                break
        return results
