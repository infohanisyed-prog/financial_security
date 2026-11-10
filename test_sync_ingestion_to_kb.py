import json
from pathlib import Path

from sync_ingestion_to_kb import sync_staging_to_kb, is_sync_eligible


def _eligible_record():
    return {
        "document_id": "faq-new",
        "title": "Approved FAQ",
        "category": "faq",
        "content": "Approved answer.",
        "query_aliases": ["How does it work?"],
        "source_url": "https://example.com/faq",
        "source_owner": "Product Documentation",
        "last_verified_date": "2026-11-01",
        "approval_status": "approved",
        "privacy_review": "approved",
        "content_status": "active",
        "verified": True,
    }


def test_pending_record_is_skipped_and_existing_kb_preserved(tmp_path: Path):
    staging = tmp_path / "staging.json"
    kb = tmp_path / "kb.json"
    staging.write_text(json.dumps({"records": [{
        "document_id": "faq-001", "title": "Pending", "category": "faq",
        "content": "Not approved", "approval_status": "pending",
        "privacy_review": "pending"
    }]}), encoding="utf-8")
    original = {"kb_version": "1", "documents": [
        {"id": "existing", "title": "Keep me", "content": "Existing"}
    ]}
    kb.write_text(json.dumps(original), encoding="utf-8")

    result = sync_staging_to_kb(staging, kb)
    saved = json.loads(kb.read_text(encoding="utf-8"))

    assert result["eligible_records_synced"] == 0
    assert saved["documents"] == original["documents"]


def test_eligible_record_maps_to_existing_kb_schema(tmp_path: Path):
    staging = tmp_path / "staging.json"
    kb = tmp_path / "kb.json"
    staging.write_text(json.dumps({"records": [_eligible_record()]}), encoding="utf-8")
    kb.write_text(json.dumps({"kb_version": "1", "documents": []}), encoding="utf-8")

    result = sync_staging_to_kb(staging, kb)
    saved = json.loads(kb.read_text(encoding="utf-8"))
    doc = saved["documents"][0]

    assert result["eligible_records_synced"] == 1
    assert doc["id"] == "faq-new"
    assert doc["type"] == "faq"
    assert doc["audit"]["last_verified_date"] == "2026-11-01"
    assert doc["audit"]["indexing_eligible"] is True


def test_last_updated_date_is_not_treated_as_last_verified_date():
    record = _eligible_record()
    record.pop("last_verified_date")
    record["last_updated_date"] = "2026-11-01"
    assert is_sync_eligible(record) is False


def test_pending_record_cannot_overwrite_existing_same_id(tmp_path: Path):
    staging = tmp_path / "staging.json"
    kb = tmp_path / "kb.json"
    staging.write_text(json.dumps({"records": [{
        "document_id": "faq-001", "title": "Pending replacement",
        "category": "faq", "content": "Pending content",
        "approval_status": "pending", "privacy_review": "pending"
    }]}), encoding="utf-8")
    original_doc = {"id": "faq-001", "title": "Original", "content": "Keep"}
    kb.write_text(json.dumps({"documents": [original_doc]}), encoding="utf-8")

    sync_staging_to_kb(staging, kb)
    saved = json.loads(kb.read_text(encoding="utf-8"))
    assert saved["documents"] == [original_doc]
