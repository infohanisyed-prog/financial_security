"""Focused tests for audit eligibility and data-integrity checks."""
import json
import sys
import types
import numpy as np
import pytest

# Keep policy tests independent of downloading/loading a real embedding model.
stub = types.ModuleType("sentence_transformers")
stub.SentenceTransformer = lambda _name: None
sys.modules.setdefault("sentence_transformers", stub)
import semantic_search as ss


class FakeModel:
    def encode(self, texts, normalize_embeddings=True, convert_to_numpy=True):
        # Deterministic, normalized vectors sufficient for policy tests.
        return np.array([[1.0, 0.0] for _ in texts], dtype=np.float32)


def make_doc(doc_id="doc-1", *, approved=True):
    return {
        "id": doc_id,
        "title": "Example source",
        "content": "Example content for a retrieval test.",
        "source": "Official documentation",
        "verified": approved,
        "type": "faq",
        "audit": {
            "approval_status": "approved" if approved else "pending",
            "indexing_eligible": approved,
            "source_owner": "Documentation Team" if approved else None,
            "source_url": "https://example.com/docs" if approved else None,
            "last_verified_date": "2026-10-27" if approved else None,
            "privacy_review": "approved" if approved else "pending",
        },
    }


def make_kb(tmp_path, monkeypatch, docs):
    monkeypatch.setattr(ss, "SentenceTransformer", lambda _name: FakeModel())
    path = tmp_path / "knowledge_base.json"
    path.write_text(json.dumps({"kb_version": "test-1", "documents": docs}), encoding="utf-8")
    return ss.SemanticKnowledgeBase(kb_path=path, model_name="fake", threshold=0.0)


def test_pending_document_is_not_indexed(tmp_path, monkeypatch):
    kb = make_kb(tmp_path, monkeypatch, [make_doc(approved=False)])
    assert kb.documents == []
    assert kb.embeddings is None
    assert kb.search("example") == []


def test_approved_document_with_complete_metadata_is_indexed(tmp_path, monkeypatch):
    kb = make_kb(tmp_path, monkeypatch, [make_doc()])
    results = kb.search("example")
    assert len(kb.documents) == 1
    assert len(results) == 1
    assert results[0].source_owner == "Documentation Team"
    assert results[0].source_url == "https://example.com/docs"
    assert results[0].last_verified_date == "2026-10-27"


def test_missing_required_metadata_blocks_indexing(tmp_path, monkeypatch):
    doc = make_doc()
    doc["audit"]["source_owner"] = None
    kb = make_kb(tmp_path, monkeypatch, [doc])
    assert kb.documents == []
    assert kb.embeddings is None


def test_invalid_url_or_date_blocks_indexing(tmp_path, monkeypatch):
    doc = make_doc()
    doc["audit"]["source_url"] = "not-a-url"
    doc["audit"]["last_verified_date"] = "27-10-2026"
    kb = make_kb(tmp_path, monkeypatch, [doc])
    assert kb.documents == []


def test_duplicate_document_ids_raise_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "SentenceTransformer", lambda _name: FakeModel())
    path = tmp_path / "knowledge_base.json"
    path.write_text(json.dumps({"documents": [make_doc("same"), make_doc("same", approved=False)]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate knowledge-base document IDs"):
        ss.SemanticKnowledgeBase(kb_path=path, model_name="fake")
