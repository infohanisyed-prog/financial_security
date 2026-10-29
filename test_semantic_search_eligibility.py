
from pathlib import Path


def test_reload_requires_explicit_audit_approval_before_indexing():
    source = Path(__file__).with_name("semantic_search.py").read_text(
        encoding="utf-8"
    )

    assert "_is_indexing_eligible" in source
    assert 'audit.get("approval_status") == "approved"' in source
    assert 'audit.get("indexing_eligible") is True' in source
    assert 'document.get("verified") is True' in source


def test_rag_also_filters_search_results_against_eligible_documents():
    source = Path(__file__).with_name("rag_service.py").read_text(
        encoding="utf-8"
    )

    assert "_eligible_document_map" in source
    assert 'audit.get("approval_status") == "approved"' in source
    assert 'audit.get("indexing_eligible") is True' in source
