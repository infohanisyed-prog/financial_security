import json
import numpy as np
from ingestion_pipeline import run_ingestion

class FakeModel:
    def encode(self, texts, normalize_embeddings=True, convert_to_numpy=True):
        return np.array([[1.0, 0.0] for _ in texts], dtype=np.float32)

def good_record(doc_id="faq-1", content="Record an expense from the expense entry screen."):
    return {
        "document_id": doc_id, "title": "Expense FAQ", "category": "faq",
        "section": "Expense entry", "product_module": "Expense entry",
        "source_url": "https://example.test/faq", "language": "en",
        "last_updated_date": "2026-10-01", "source_owner": "Product team",
        "approval_status": "approved", "privacy_review": "approved",
        "content_status": "active", "verified": True, "content": content,
        "query_aliases": []
    }

def test_pending_record_is_quarantined_and_not_embedded(tmp_path):
    rec = good_record()
    rec["approval_status"] = "pending"
    src = tmp_path/"in.json"; src.write_text(json.dumps({"records":[rec]}))
    report = run_ingestion(src, tmp_path/"out", embed=True, model=FakeModel())
    assert report["approved_records"] == 0
    assert report["chunks_created"] == 0
    assert not report["vectors_written"]
    assert report["quarantined_records"] == ["faq-1"]

def test_approved_record_chunks_and_embeds(tmp_path):
    src = tmp_path/"in.json"; src.write_text(json.dumps({"records":[good_record()]}))
    report = run_ingestion(src, tmp_path/"out", embed=True, model=FakeModel())
    assert report["approved_records"] == 1
    assert report["chunks_created"] == 1
    assert report["vectors_written"]
    assert report["actions"]["faq-1"] == "new"

def test_modified_and_deleted_sources_detected(tmp_path):
    src = tmp_path/"in.json"; out=tmp_path/"out"
    src.write_text(json.dumps({"records":[good_record()]}))
    run_ingestion(src, out, embed=False)
    src.write_text(json.dumps({"records":[good_record(content="Updated FAQ content.")]}))
    report = run_ingestion(src, out, embed=False)
    assert report["actions"]["faq-1"] == "modified"
    src.write_text(json.dumps({"records":[]}))
    report = run_ingestion(src, out, embed=False)
    assert report["deleted_sources"] == ["faq-1"]

def test_duplicate_ids_are_logged(tmp_path):
    rec = good_record()
    src=tmp_path/"in.json"; src.write_text(json.dumps({"records":[rec,rec]}))
    report=run_ingestion(src,tmp_path/"out",embed=False)
    assert any("duplicate document ID" in x["error"] for x in report["duplicate_or_parse_errors"])
