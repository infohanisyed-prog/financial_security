"""Dense and hybrid retrieval for the HisabDo knowledge base.

Production search remains fail-closed: only verified, approved, privacy-reviewed
and audit-complete documents are searchable. Diagnostic search is explicitly
separate and may rank pending documents for offline evaluation only.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_THRESHOLD = 0.42
DEFAULT_TOP_K = 3
DEFAULT_ALPHA = 0.5  # hybrid = alpha * vector + (1-alpha) * BM25
DEFAULT_RERANK_CANDIDATES = 10


@dataclass
class SearchResult:
    """A knowledge-base search result with audit metadata."""
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
    vector_score: float = 0.0
    bm25_score: float = 0.0
    diagnostic_only: bool = False


class SemanticKnowledgeBase:
    """Load, validate, embed, and retrieve HisabDo knowledge-base documents."""

    def __init__(
        self,
        kb_path: str | Path = "knowledge_base.json",
        model_name: str = DEFAULT_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        hybrid_alpha: float = DEFAULT_ALPHA,
    ) -> None:
        self.kb_path = Path(kb_path)
        self.threshold = float(threshold)
        self.hybrid_alpha = float(hybrid_alpha)
        if not math.isfinite(self.threshold) or not -1.0 <= self.threshold <= 1.0:
            raise ValueError("Similarity threshold must be finite and between -1 and 1.")
        if not math.isfinite(self.hybrid_alpha) or not 0.0 <= self.hybrid_alpha <= 1.0:
            raise ValueError("hybrid_alpha must be between 0 and 1.")
        self.model = SentenceTransformer(model_name)
        self.metadata: dict[str, Any] = {}
        self.documents: list[dict[str, Any]] = []       # production-eligible only
        self.texts: list[str] = []
        self.embeddings: np.ndarray | None = None
        self.all_documents: list[dict[str, Any]] = []   # offline diagnostics only
        self.all_texts: list[str] = []
        self.all_embeddings: np.ndarray | None = None
        self.reload()

    @staticmethod
    def _clean_text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def normalize_query(query: str) -> str:
        """Conservative normalization: lowercase, normalize whitespace/punctuation."""
        query = query.strip().lower()
        query = re.sub(r"[\u2018\u2019]", "'", query)
        query = re.sub(r"[\u201c\u201d]", '"', query)
        query = re.sub(r"[^\w\s'-]", " ", query, flags=re.UNICODE)
        return re.sub(r"\s+", " ", query).strip()

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+|[\u0600-\u06ff]+", text.lower())

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
        return privacy_review == "approved"

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

    @staticmethod
    def _document_text(doc: dict[str, Any]) -> str:
        return (
            f"Title: {doc['title']}. Type: {SemanticKnowledgeBase._clean_text(doc.get('type')) or 'document'}. "
            f"Content: {doc['content']}. Alternative questions: {'; '.join(doc['aliases'])}"
        )

    def _encode_texts(self, texts: list[str]) -> np.ndarray | None:
        if not texts:
            return None
        vectors = self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        embeddings = np.asarray(vectors, dtype=np.float32)
        if embeddings.ndim != 2 or embeddings.shape[0] != len(texts) or embeddings.shape[1] == 0:
            raise ValueError("Embedding model returned an invalid matrix.")
        if not np.isfinite(embeddings).all():
            raise ValueError("Embedding model returned non-finite values.")
        return embeddings

    def reload(self) -> None:
        """Read and validate KB, then atomically replace production and diagnostic state."""
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

        all_docs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        duplicates: set[str] = set()
        for item in raw_documents:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_document(item)
            if normalized is None:
                continue
            if normalized["id"] in seen_ids:
                duplicates.add(normalized["id"])
            seen_ids.add(normalized["id"])
            all_docs.append(normalized)
        if duplicates:
            raise ValueError("Duplicate knowledge-base document IDs detected: " + ", ".join(sorted(duplicates)))

        eligible_docs = [d for d in all_docs if self._is_indexing_eligible(d)]
        all_texts = [self._document_text(d) for d in all_docs]
        eligible_texts = [self._document_text(d) for d in eligible_docs]
        # Offline diagnostics intentionally embed the full corpus separately.
        all_embeddings = self._encode_texts(all_texts)
        eligible_embeddings = self._encode_texts(eligible_texts)

        self.metadata = {
            "kb_version": data.get("kb_version", "unknown"),
            "updated_at": data.get("updated_at", ""),
            "document_count": len(all_docs),
            "eligible_document_count": len(eligible_docs),
        }
        self.all_documents, self.all_texts, self.all_embeddings = all_docs, all_texts, all_embeddings
        self.documents, self.texts, self.embeddings = eligible_docs, eligible_texts, eligible_embeddings

    @staticmethod
    def _bm25_scores(query: str, texts: list[str], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
        """Small dependency-free BM25 implementation; scores are min-max normalized."""
        q_tokens = set(SemanticKnowledgeBase._tokenize(query))
        if not texts or not q_tokens:
            return np.zeros(len(texts), dtype=np.float32)
        tokenized = [SemanticKnowledgeBase._tokenize(t) for t in texts]
        lengths = np.asarray([len(t) for t in tokenized], dtype=np.float32)
        avgdl = float(lengths.mean()) if len(lengths) else 0.0
        if avgdl <= 0:
            return np.zeros(len(texts), dtype=np.float32)
        df = Counter(token for tokens in tokenized for token in set(tokens))
        n = len(texts)
        scores = np.zeros(n, dtype=np.float32)
        for i, tokens in enumerate(tokenized):
            counts = Counter(tokens)
            dl = float(lengths[i])
            for term in q_tokens:
                freq = counts.get(term, 0)
                if not freq:
                    continue
                idf = math.log(1.0 + (n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
                denom = freq + k1 * (1.0 - b + b * dl / avgdl)
                scores[i] += idf * (freq * (k1 + 1.0)) / denom
        maximum = float(scores.max()) if len(scores) else 0.0
        if maximum > 0:
            scores /= maximum
        return scores

    @staticmethod
    def _metadata_match(doc: dict[str, Any], filters: dict[str, Any] | None) -> bool:
        if not filters:
            return True
        for key, expected in filters.items():
            if expected is None:
                continue
            actual = doc.get(key)
            if isinstance(expected, (list, tuple, set)):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    def _rank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        embeddings: np.ndarray | None,
        top_k: int,
        strategy: str,
        metadata_filters: dict[str, Any] | None,
        alpha: float | None,
        rerank: bool,
    ) -> list[SearchResult]:
        if not isinstance(top_k, int) or isinstance(top_k, bool):
            raise TypeError("top_k must be an integer.")
        if top_k <= 0 or not query or embeddings is None or not documents:
            return []
        if strategy not in {"dense", "hybrid"}:
            raise ValueError("strategy must be 'dense' or 'hybrid'.")
        normalized_query = self.normalize_query(query)
        query_vector = np.asarray(
            self.model.encode([normalized_query], normalize_embeddings=True, convert_to_numpy=True),
            dtype=np.float32,
        )
        if query_vector.ndim != 2 or query_vector.shape != (1, embeddings.shape[1]):
            raise ValueError("Query embedding dimensions do not match KB embeddings.")
        if not np.isfinite(query_vector).all():
            raise ValueError("Embedding model returned an invalid query vector.")

        vector_scores = embeddings @ query_vector[0]
        lexical_scores = self._bm25_scores(normalized_query, [self._document_text(d) for d in documents])
        mix = self.hybrid_alpha if alpha is None else float(alpha)
        if not math.isfinite(mix) or not 0 <= mix <= 1:
            raise ValueError("alpha must be between 0 and 1.")
        combined = vector_scores if strategy == "dense" else mix * vector_scores + (1.0 - mix) * lexical_scores

        candidates = [
            i for i, doc in enumerate(documents)
            if self._metadata_match(doc, metadata_filters)
        ]
        candidates.sort(key=lambda i: float(combined[i]), reverse=True)

        # Lightweight deterministic reranker: lexical overlap breaks near-score ties.
        # It does not claim model-based relevance or override metadata/eligibility.
        if rerank and strategy == "hybrid":
            q_terms = set(self._tokenize(normalized_query))
            candidates.sort(
                key=lambda i: (
                    float(combined[i]),
                    len(q_terms.intersection(set(self._tokenize(self._document_text(documents[i]))))),
                    float(vector_scores[i]),
                ),
                reverse=True,
            )

        results: list[SearchResult] = []
        for i in candidates:
            doc = documents[i]
            score = float(combined[i])
            if score < self.threshold:
                continue
            audit = doc.get("audit", {}) if isinstance(doc.get("audit"), dict) else {}
            results.append(SearchResult(
                id=doc["id"], title=doc["title"], content=doc["content"],
                source=self._clean_text(doc.get("source")) or "Knowledge Base",
                version=str(doc.get("version", self.metadata.get("kb_version", "unknown"))),
                verified=doc.get("verified") is True, score=score,
                doc_type=self._clean_text(doc.get("type")) or "document",
                source_owner=self._clean_text(audit.get("source_owner")),
                source_url=self._clean_text(audit.get("source_url")),
                last_verified_date=self._clean_text(audit.get("last_verified_date")),
                approval_status=self._clean_text(audit.get("approval_status")),
                privacy_review=self._clean_text(audit.get("privacy_review")),
                vector_score=float(vector_scores[i]), bm25_score=float(lexical_scores[i]),
                diagnostic_only=not self._is_indexing_eligible(doc),
            ))
            if len(results) >= top_k:
                break
        return results

    def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        strategy: str = "dense",
        metadata_filters: dict[str, Any] | None = None,
        alpha: float | None = None,
        rerank: bool = False,
    ) -> list[SearchResult]:
        """Production retrieval. Only approved/verified/audit-complete docs are searched."""
        return self._rank(
            self._clean_text(query), self.documents, self.embeddings, top_k,
            strategy, metadata_filters, alpha, rerank,
        )

    def diagnostic_search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        strategy: str = "dense",
        metadata_filters: dict[str, Any] | None = None,
        alpha: float | None = None,
        rerank: bool = False,
    ) -> list[SearchResult]:
        """Offline evaluation only. Results may include pending/unapproved docs.

        Never pass these results to RAG answer generation or production users.
        """
        return self._rank(
            self._clean_text(query), self.all_documents, self.all_embeddings, top_k,
            strategy, metadata_filters, alpha, rerank,
        )
