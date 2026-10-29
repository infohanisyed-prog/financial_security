import json
from pathlib import Path
import subprocess
import sys

def test_audit_blocks_unapproved_document(tmp_path):
    p = tmp_path / "kb.json"
    p.write_text(json.dumps({"documents":[{"id":"a","title":"A","content":"hello","verified":False}]}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(Path(__file__).with_name("audit_knowledge_base.py")), str(p)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "not explicitly approved and verified" in result.stdout

def test_audit_detects_duplicate_content(tmp_path):
    p = tmp_path / "kb.json"
    p.write_text(json.dumps({"documents":[
        {"id":"a","title":"A","content":"Same text","verified":True,"audit":{"source_owner":"x","source_url":"https://example.com","last_verified_date":"2026-10-27","review_policy":"monthly","approval_status":"approved","indexing_eligible":True}},
        {"id":"b","title":"B","content":"Same text","verified":True,"audit":{"source_owner":"x","source_url":"https://example.com","last_verified_date":"2026-10-27","review_policy":"monthly","approval_status":"approved","indexing_eligible":True}}
    ]}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(Path(__file__).with_name("audit_knowledge_base.py")), str(p)], capture_output=True, text=True)
    assert "DUPLICATE" in result.stdout
