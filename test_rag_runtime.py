
from types import SimpleNamespace

from rag_service import RAGService, SAFE_FALLBACK


class FakeKnowledgeBase:
    def __init__(self, eligible=True):
        self.metadata = {"kb_version": "test"}
       
        self.documents = [
            {
                "id": "test-001",
                "title": "Test document",
                "content": "Example content for an isolated test.",
                "source": "test fixture",
                "version": "1.0",
                "verified": eligible,
                "audit": {
                    "approval_status": "approved" if eligible else "pending",
                    "indexing_eligible": eligible,
                    "source_owner": "Test Fixture",
                    "source_url": "https://example.com/test",
                    "last_verified_date": "2026-10-29",
                    "privacy_review": "approved",
                },
            }
        ]

        

    def search(self, question, top_k=3):
        return [
            SimpleNamespace(
                id="test-001",
                title="Test document",
                source="test fixture",
                version="1.0",
                content="Example content for an isolated test.",
                score=0.95,
            )
        ]


def test_unapproved_document_is_blocked():
    service = RAGService(FakeKnowledgeBase(eligible=False))

    result = service.retrieve("test question")

    assert result["found"] is False
    assert result["sources"] == []
    assert result["answer_context"] == SAFE_FALLBACK


def test_approved_verified_document_can_be_returned():
    service = RAGService(FakeKnowledgeBase(eligible=True))

    result = service.retrieve("test question")

    assert result["found"] is True
    assert len(result["sources"]) == 1
    assert result["sources"][0]["id"] == "test-001"
    assert "Example content" in result["answer_context"]
