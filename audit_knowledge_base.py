"""Pre-indexing quality gate for HisabDo knowledge_base.json."""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from collections import defaultdict

REQUIRED_AUDIT_FIELDS = ("source_owner", "source_url", "last_verified_date", "review_policy")
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")

def norm(value):
    return re.sub(r"\W+", " ", (value or "").lower()).strip()

def audit(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    docs = payload.get("documents")
    if not isinstance(docs, list):
        raise ValueError("'documents' must be a list")
    ids, contents, aliases = set(), defaultdict(list), defaultdict(list)
    findings = []
    for i, doc in enumerate(docs):
        did = doc.get("id", f"index-{i}")
        if did in ids: findings.append(("ERROR", did, "duplicate document id"))
        ids.add(did)
        if not doc.get("title") or not doc.get("content"):
            findings.append(("ERROR", did, "missing title/content"))
        contents[norm(doc.get("content", ""))].append(did)
        for alias in doc.get("aliases", []):
            aliases[norm(alias)].append(did)
        audit_meta = doc.get("audit", {})
        missing = [k for k in REQUIRED_AUDIT_FIELDS if not audit_meta.get(k)]
        if missing:
            findings.append(("BLOCK", did, "missing audit metadata: " + ", ".join(missing)))
        if doc.get("verified") is not True or audit_meta.get("approval_status") != "approved":
            findings.append(("BLOCK", did, "not explicitly approved and verified"))
        body = doc.get("content", "") + " " + " ".join(doc.get("aliases", []))
        if EMAIL.search(body) or PHONE.search(body):
            findings.append(("PRIVACY", did, "possible email/phone identifier; manual review required"))
    for text, group in contents.items():
        if text and len(group) > 1:
            findings.append(("DUPLICATE", ",".join(group), "identical normalized content"))
    for text, group in aliases.items():
        if text and len(group) > 1:
            findings.append(("DUPLICATE_ALIAS", ",".join(group), "duplicate normalized alias"))
    for level, did, message in findings:
        print(f"{level}\t{did}\t{message}")
    blocked = sum(1 for level, *_ in findings if level in {"ERROR", "BLOCK", "PRIVACY"})
    print(f"\nDocuments: {len(docs)} | Findings: {len(findings)} | Blocking findings: {blocked}")
    print("Policy: do not index blocked documents until reviewed and approved.")
    return 1 if blocked else 0

if __name__ == "__main__":
    sys.exit(audit(sys.argv[1] if len(sys.argv) > 1 else "knowledge_base.json"))
