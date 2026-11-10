"""Safely sync approved staging records into the existing HisabDo KB format.

Pending/incomplete staging records never overwrite or delete existing KB documents.
A staging record must have an explicit verified=True and last_verified_date.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def is_sync_eligible(record: dict[str, Any]) -> bool:
    if not (
        record.get("verified") is True
        and record.get("approval_status") == "approved"
        and record.get("privacy_review") == "approved"
        and record.get("content_status", "active") == "active"
        and _text(record.get("source_owner"))
        and _text(record.get("last_verified_date"))
    ):
        return False

    url = _text(record.get("source_url"))
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    try:
        date.fromisoformat(record["last_verified_date"])
    except (TypeError, ValueError):
        return False

    return bool(_text(record.get("document_id")) and
                _text(record.get("title")) and
                _text(record.get("content")))


def convert_record(record: dict[str, Any]) -> dict[str, Any]:
    """Convert one eligible flat staging record to the legacy KB schema."""
    doc_id = _text(record["document_id"])
    aliases = record.get("query_aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    if not isinstance(aliases, list):
        aliases = []

    return {
        "id": doc_id,
        "title": _text(record["title"]),
        "type": _text(record.get("category")) or "document",
        "version": _text(record.get("source_version")) or "1",
        "verified": True,
        "source": _text(record.get("source_url")),
        "aliases": [x.strip() for x in aliases if isinstance(x, str) and x.strip()],
        "content": _text(record["content"]),
        "audit": {
            "approval_status": "approved",
            "source_owner": _text(record["source_owner"]),
            "source_url": _text(record["source_url"]),
            "last_verified_date": _text(record["last_verified_date"]),
            "review_policy": _text(record.get("review_policy")) or "manual_review",
            "privacy_review": "approved",
            "indexing_eligible": True,
            "audit_notes": "Synced from approved staging record by integration adapter.",
        },
    }


def sync_staging_to_kb(staging_path: Path, kb_path: Path) -> dict[str, Any]:
    staging = json.loads(staging_path.read_text(encoding="utf-8"))
    existing = json.loads(kb_path.read_text(encoding="utf-8"))

    if not isinstance(staging, dict) or not isinstance(existing, dict):
        raise ValueError("Both JSON files must contain top-level objects.")

    records = staging.get("records", staging.get("documents", []))
    documents = existing.get("documents", [])
    if not isinstance(records, list) or not isinstance(documents, list):
        raise ValueError("Staging records and KB documents must be lists.")

    eligible_records = [r for r in records
                        if isinstance(r, dict) and is_sync_eligible(r)]
    updates = {doc["id"]: doc for doc in
               (convert_record(r) for r in eligible_records)}

    # Update eligible IDs only. Preserve all existing documents not explicitly
    # replaced by a fully eligible staging record; never delete on absence.
    merged = []
    seen = set()
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get("id")
        if doc_id in updates:
            merged.append(updates[doc_id])
            seen.add(doc_id)
        else:
            merged.append(doc)
            if doc_id:
                seen.add(doc_id)

    for doc_id, doc in updates.items():
        if doc_id not in seen:
            merged.append(doc)

    output = dict(existing)
    output["documents"] = merged
    output["updated_at"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()

    # Atomic replacement prevents a partial/corrupt KB if writing is interrupted.
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=kb_path.name + ".", suffix=".tmp", dir=str(kb_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(output, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, kb_path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise

    return {
        "staging_records": len(records),
        "eligible_records_synced": len(eligible_records),
        "existing_documents_preserved_or_updated": len(merged),
        "pending_or_incomplete_records_skipped": len(records) - len(eligible_records),
        "kb_path": str(kb_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", default="HisabDo_Cleaned_Staging_Knowledge_Set.json")
    parser.add_argument("--kb", default="knowledge_base.json")
    args = parser.parse_args()
    result = sync_staging_to_kb(Path(args.staging), Path(args.kb))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
